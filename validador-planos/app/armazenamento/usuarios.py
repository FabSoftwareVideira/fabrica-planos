import os
import sqlite3
import threading
from datetime import datetime, timedelta

# Usuários que já entraram no sistema, em resultados/usuarios.sqlite3: e-mail, nome (lido no login),
# se está ativo, primeiro e último acesso. Quem é administrador continua vindo de ADMIN_EMAILS.

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

ORDENS = {
    'acesso': 'ultimo_acesso DESC, email',
    'nome': "CASE WHEN nome = '' THEN 1 ELSE 0 END, nome COLLATE NOCASE, email",
    'email': 'email',
    'cadastro': 'primeiro_acesso DESC, email',
}


def _agora():
    return datetime.now().isoformat(timespec='seconds')


def _como_texto(texto):
    return ''.join(c for c in texto.lower() if c not in '%_')


class Usuarios:
    def __init__(self, caminho):
        self.caminho = caminho
        self._trava = threading.Lock()
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        with self._conexao() as con:
            con.execute(ESQUEMA)

    def _conexao(self):
        con = sqlite3.connect(self.caminho, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    def registrar_acesso(self, email, nome=''):
        """Cadastra no primeiro acesso; depois atualiza o nome (quando vem um) e o último acesso, no máximo
        a cada INTERVALO_ACESSO. Devolve o usuário (dict)."""
        agora = datetime.now()
        with self._trava, self._conexao() as con:
            atual = con.execute('SELECT * FROM usuarios WHERE email = ?', (email,)).fetchone()
            if atual is None:
                con.execute('INSERT INTO usuarios (email, nome, primeiro_acesso, ultimo_acesso) VALUES (?, ?, ?, ?)',
                            (email, nome, agora.isoformat(timespec='seconds'), agora.isoformat(timespec='seconds')))
                return dict(con.execute('SELECT * FROM usuarios WHERE email = ?', (email,)).fetchone())
            nome_novo = nome or atual['nome']
            antigo = datetime.fromisoformat(atual['ultimo_acesso'])
            if nome_novo != atual['nome'] or agora - antigo >= INTERVALO_ACESSO:
                con.execute('UPDATE usuarios SET nome = ?, ultimo_acesso = ? WHERE email = ?',
                            (nome_novo, agora.isoformat(timespec='seconds'), email))
                atual = con.execute('SELECT * FROM usuarios WHERE email = ?', (email,)).fetchone()
            return dict(atual)

    def obter(self, email):
        with self._conexao() as con:
            linha = con.execute('SELECT * FROM usuarios WHERE email = ?', (email,)).fetchone()
        return dict(linha) if linha else None

    def definir_ativo(self, email, ativo):
        """Ativa ou desativa; devolve False se o usuário não existir."""
        with self._trava, self._conexao() as con:
            return con.execute('UPDATE usuarios SET ativo = ? WHERE email = ?', (1 if ativo else 0, email)).rowcount > 0

    def listar(self, busca='', situacao='', papel='', admins=(), ordem='acesso', pagina=1, por_pagina=20):
        """Página de usuários filtrada. situacao: 'ativos', 'inativos' ou '' (todos); papel: 'admin',
        'consulta' ou '' (todos), conforme a lista de administradores. Devolve (usuários, total)."""
        condicoes, valores = [], []
        if busca:
            condicoes.append("(lower(nome) LIKE ? OR lower(email) LIKE ?)")
            valores += ['%' + _como_texto(busca) + '%'] * 2
        if situacao in ('ativos', 'inativos'):
            condicoes.append('ativo = ?')
            valores.append(1 if situacao == 'ativos' else 0)
        if papel in ('admin', 'consulta'):
            marcas = ','.join('?' * len(admins)) or "''"
            condicoes.append(f"email {'IN' if papel == 'admin' else 'NOT IN'} ({marcas})")
            valores += list(admins)
        onde = ('WHERE ' + ' AND '.join(condicoes)) if condicoes else ''
        with self._conexao() as con:
            total = con.execute(f'SELECT count(*) FROM usuarios {onde}', valores).fetchone()[0]
            linhas = con.execute(f'SELECT * FROM usuarios {onde} ORDER BY {ORDENS.get(ordem, ORDENS["acesso"])} '
                                 'LIMIT ? OFFSET ?', valores + [por_pagina, (pagina - 1) * por_pagina]).fetchall()
        return [dict(l) for l in linhas], total

    def contar(self):
        with self._conexao() as con:
            total, ativos = con.execute('SELECT count(*), coalesce(sum(ativo), 0) FROM usuarios').fetchone()
        return {'total': total, 'ativos': ativos, 'inativos': total - ativos}
