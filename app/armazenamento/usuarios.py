import threading
from datetime import datetime, timedelta

# Usuários que já entraram no sistema, no PostgreSQL (tabelas usuarios e papeis_curso): e-mail, nome (lido no login),
# se está ativo, primeiro e último acesso, e os papéis em cursos (coordenação, NDE ou NDB), que dão
# direito a revisar os planos daquele curso. Quem é administrador continua vindo de ADMIN_EMAILS.

# Intervalo mínimo entre duas gravações do último acesso de um mesmo usuário (evita uma escrita por requisição)
INTERVALO_ACESSO = timedelta(minutes=5)

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    email TEXT PRIMARY KEY,
    nome TEXT NOT NULL DEFAULT '',
    ativo INTEGER NOT NULL DEFAULT 1,
    primeiro_acesso TEXT NOT NULL,
    ultimo_acesso TEXT NOT NULL
)
"""

# Papel de um usuário num curso (sigla das 2 primeiras letras do código do componente, ex.: CC)
ESQUEMA_PAPEIS = """
CREATE TABLE IF NOT EXISTS papeis_curso (
    email TEXT NOT NULL,
    curso TEXT NOT NULL,
    papel TEXT NOT NULL,
    PRIMARY KEY (email, curso, papel)
)
"""

PAPEIS_CURSO = {'coordenador': 'Coordenação', 'nde': 'NDE', 'ndb': 'NDB'}

ORDENS = {
    'acesso': 'ultimo_acesso DESC, email',
    'nome': "CASE WHEN nome = '' THEN 1 ELSE 0 END, lower(nome), email",
    'email': 'email',
    'cadastro': 'primeiro_acesso DESC, email',
}


def _agora():
    return datetime.now().isoformat(timespec='seconds')


def _como_texto(texto):
    return ''.join(c for c in texto.lower() if c not in '%_')


class Usuarios:
    def __init__(self, banco):
        self.banco = banco
        self._trava = threading.Lock()
        with self._conexao() as con:
            con.execute(ESQUEMA)
            con.execute(ESQUEMA_PAPEIS)

    def _conexao(self):
        return self.banco.conexao()

    def registrar_acesso(self, email, nome=''):
        """Cadastra no primeiro acesso; depois atualiza o nome (quando vem um) e o último acesso, no máximo
        a cada INTERVALO_ACESSO. Devolve o usuário (dict)."""
        agora = datetime.now()
        with self._trava, self._conexao() as con:
            atual = con.execute('SELECT * FROM usuarios WHERE email = %s', (email,)).fetchone()
            if atual is None:
                con.execute('INSERT INTO usuarios (email, nome, primeiro_acesso, ultimo_acesso) '
                            'VALUES (%s, %s, %s, %s)',
                            (email, nome, agora.isoformat(timespec='seconds'), agora.isoformat(timespec='seconds')))
                return dict(con.execute('SELECT * FROM usuarios WHERE email = %s', (email,)).fetchone())
            nome_novo = nome or atual['nome']
            antigo = datetime.fromisoformat(atual['ultimo_acesso'])
            if nome_novo != atual['nome'] or agora - antigo >= INTERVALO_ACESSO:
                con.execute('UPDATE usuarios SET nome = %s, ultimo_acesso = %s WHERE email = %s',
                            (nome_novo, agora.isoformat(timespec='seconds'), email))
                atual = con.execute('SELECT * FROM usuarios WHERE email = %s', (email,)).fetchone()
            return dict(atual)

    def obter(self, email):
        with self._conexao() as con:
            linha = con.execute('SELECT * FROM usuarios WHERE email = %s', (email,)).fetchone()
        return dict(linha) if linha else None

    def definir_ativo(self, email, ativo):
        """Ativa ou desativa; devolve False se o usuário não existir."""
        with self._trava, self._conexao() as con:
            return con.execute('UPDATE usuarios SET ativo = %s WHERE email = %s',
                               (1 if ativo else 0, email)).rowcount > 0

    def listar(self, busca='', situacao='', papel='', admins=(), ordem='acesso', pagina=1, por_pagina=20):
        """Página de usuários filtrada. situacao: 'ativos', 'inativos' ou '' (todos); papel: 'admin',
        'consulta' ou '' (todos), conforme a lista de administradores. Devolve (usuários, total)."""
        condicoes, valores = [], []
        if busca:
            condicoes.append("(lower(nome) LIKE %s OR lower(email) LIKE %s)")
            valores += ['%' + _como_texto(busca) + '%'] * 2
        if situacao in ('ativos', 'inativos'):
            condicoes.append('ativo = %s')
            valores.append(1 if situacao == 'ativos' else 0)
        if papel == 'revisor':
            condicoes.append('email IN (SELECT email FROM papeis_curso)')
        elif papel in ('admin', 'consulta'):
            marcas = ','.join(['%s'] * len(admins)) or "''"
            condicoes.append(f"email {'IN' if papel == 'admin' else 'NOT IN'} ({marcas})")
            valores += list(admins)
        onde = ('WHERE ' + ' AND '.join(condicoes)) if condicoes else ''
        with self._conexao() as con:
            total = con.execute(f'SELECT count(*) AS n FROM usuarios {onde}', valores).fetchone()['n']
            linhas = con.execute(f'SELECT * FROM usuarios {onde} ORDER BY {ORDENS.get(ordem, ORDENS["acesso"])} '
                                 'LIMIT %s OFFSET %s', valores + [por_pagina, (pagina - 1) * por_pagina]).fetchall()
        return [dict(l) for l in linhas], total

    # Papéis em cursos ------------------------------------------------------------------------------

    def papeis(self, email):
        """[(curso, papel)] do usuário, em ordem de curso."""
        with self._conexao() as con:
            linhas = con.execute('SELECT curso, papel FROM papeis_curso WHERE email = %s ORDER BY curso, papel',
                                 (email,)).fetchall()
        return [(l['curso'], l['papel']) for l in linhas]

    def papeis_de(self, emails):
        """{email: [(curso, papel)]} de vários usuários de uma vez (para a tabela da administração)."""
        emails = list(emails)
        if not emails:
            return {}
        marcas = ','.join(['%s'] * len(emails))
        with self._conexao() as con:
            linhas = con.execute(f'SELECT email, curso, papel FROM papeis_curso WHERE email IN ({marcas}) '
                                 'ORDER BY curso, papel', emails).fetchall()
        saida = {e: [] for e in emails}
        for l in linhas:
            saida[l['email']].append((l['curso'], l['papel']))
        return saida

    def adicionar_papel(self, email, curso, papel):
        """Dá ao usuário (já cadastrado) o papel no curso; devolve False se o usuário não existir."""
        with self._trava, self._conexao() as con:
            if con.execute('SELECT 1 FROM usuarios WHERE email = %s', (email,)).fetchone() is None:
                return False
            con.execute('INSERT INTO papeis_curso (email, curso, papel) VALUES (%s, %s, %s) '
                        'ON CONFLICT DO NOTHING', (email, curso, papel))
            return True

    def remover_papel(self, email, curso, papel):
        with self._trava, self._conexao() as con:
            return con.execute('DELETE FROM papeis_curso WHERE email = %s AND curso = %s AND papel = %s',
                               (email, curso, papel)).rowcount > 0

    def cursos_com_papel(self):
        """Siglas dos cursos que já têm alguém com papel (para a lista de cursos da administração)."""
        with self._conexao() as con:
            return [l['curso'] for l in con.execute('SELECT DISTINCT curso FROM papeis_curso ORDER BY curso')]

    def contar(self):
        with self._conexao() as con:
            linha = con.execute('SELECT count(*) AS total, coalesce(sum(ativo), 0)::int AS ativos '
                                'FROM usuarios').fetchone()
        total, ativos = linha['total'], linha['ativos']
        return {'total': total, 'ativos': ativos, 'inativos': total - ativos}
