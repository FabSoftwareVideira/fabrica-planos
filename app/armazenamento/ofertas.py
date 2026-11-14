import re
import threading
from datetime import datetime

from . import ppc

# Disciplinas de cada curso e semestre, no PostgreSQL:
#   componentes      a matriz curricular do PPC de cada curso (preenchida com armazenamento/ppc.py);
#   ofertas          as disciplinas que a coordenação abriu num semestre (período '2026.2'), cada uma com o
#                    seu plano de ensino: o PDF fica na pasta de planos com o nome guardado em `arquivo`;
#   oferta_docentes  os professores de cada oferta, pelo e-mail institucional (cadastrados ou não: quem
#                    ainda não entrou no sistema vê as disciplinas no primeiro acesso).
# Uma oferta guarda código, nome e carga da disciplina (copiados da matriz e editáveis só nela: renomear uma
# optativa não muda a matriz). Duas turmas da mesma disciplina são duas ofertas (um plano para cada turma).

ESQUEMA_COMPONENTES = """
CREATE TABLE IF NOT EXISTS componentes (
    id SERIAL PRIMARY KEY,
    curso TEXT NOT NULL,
    fase INTEGER NOT NULL,
    codigo TEXT NOT NULL DEFAULT '',
    nome TEXT NOT NULL,
    carga_horaria INTEGER NOT NULL DEFAULT 0
)
"""

ESQUEMA_OFERTAS = """
CREATE TABLE IF NOT EXISTS ofertas (
    id SERIAL PRIMARY KEY,
    curso TEXT NOT NULL,
    periodo TEXT NOT NULL,
    componente_id INTEGER REFERENCES componentes (id) ON DELETE SET NULL,
    fase INTEGER,
    codigo TEXT NOT NULL DEFAULT '',
    nome TEXT NOT NULL,
    carga_horaria INTEGER NOT NULL DEFAULT 0,
    turma TEXT NOT NULL DEFAULT '01',
    arquivo TEXT UNIQUE,
    criado_em TEXT NOT NULL,
    criado_por TEXT NOT NULL DEFAULT '',
    enviado_em TEXT,
    enviado_por TEXT,
    aviso TEXT NOT NULL DEFAULT ''
)
"""

ESQUEMA_DOCENTES = """
CREATE TABLE IF NOT EXISTS oferta_docentes (
    oferta_id INTEGER NOT NULL REFERENCES ofertas (id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    PRIMARY KEY (oferta_id, email)
)
"""

# '2026.2' (semestral) ou '2026' (anual)
PERIODO = re.compile(r'^(19|20)\d{2}(\.[12])?$')


def _agora():
    return datetime.now().isoformat(timespec='seconds')


def nome_do_arquivo(oferta):
    """Nome do PDF do plano na pasta de planos, fixado quando a oferta é criada (renomear a disciplina não
    muda o arquivo): '2026.2-CCC0723-T01-12.pdf'."""
    codigo = re.sub(r'[^A-Za-z0-9]', '', oferta['codigo']) or 'OPT'
    turma = re.sub(r'[^A-Za-z0-9]', '', oferta['turma']) or '01'
    return f"{oferta['periodo']}-{codigo}-T{turma}-{oferta['id']}.pdf"


class Ofertas:
    def __init__(self, banco):
        self.banco = banco
        self._trava = threading.Lock()
        with self._conexao() as con:
            con.execute(ESQUEMA_COMPONENTES)
            con.execute(ESQUEMA_OFERTAS)
            con.execute(ESQUEMA_DOCENTES)
            for curso, disciplinas in ppc.MATRIZES.items():  # matriz do PPC, na primeira vez
                if con.execute('SELECT 1 FROM componentes WHERE curso = %s LIMIT 1', (curso,)).fetchone() is None:
                    for fase, codigo, nome, carga in disciplinas:
                        con.execute('INSERT INTO componentes (curso, fase, codigo, nome, carga_horaria) '
                                    'VALUES (%s, %s, %s, %s, %s)', (curso, fase, codigo, nome, carga))

    def _conexao(self):
        return self.banco.conexao()

    # Matriz -----------------------------------------------------------------------------------------

    def matriz(self, curso):
        """Disciplinas da matriz do curso, por fase e nome."""
        with self._conexao() as con:
            return [dict(l) for l in con.execute(
                'SELECT * FROM componentes WHERE curso = %s ORDER BY fase, nome', (curso,))]

    def componente(self, id_):
        with self._conexao() as con:
            linha = con.execute('SELECT * FROM componentes WHERE id = %s', (id_,)).fetchone()
        return dict(linha) if linha else None

    def cursos(self):
        """Siglas dos cursos com matriz ou ofertas."""
        with self._conexao() as con:
            return [l['curso'] for l in con.execute(
                'SELECT curso FROM componentes UNION SELECT curso FROM ofertas ORDER BY curso')]

    # Ofertas ----------------------------------------------------------------------------------------

    def _com_docentes(self, con, linhas):
        ofertas = [dict(l) for l in linhas]
        if ofertas:
            ids = [o['id'] for o in ofertas]
            docentes = {}
            for l in con.execute('SELECT oferta_id, email FROM oferta_docentes WHERE oferta_id = ANY(%s) '
                                 'ORDER BY email', (ids,)):
                docentes.setdefault(l['oferta_id'], []).append(l['email'])
            for o in ofertas:
                o['docentes'] = docentes.get(o['id'], [])
        return ofertas

    def listar(self, curso=None, periodo=None, docente=None):
        """Ofertas (com a lista `docentes`), filtradas por curso, período e e-mail de docente, na ordem de
        período (mais recente primeiro), fase, nome e turma."""
        condicoes, valores = [], []
        if curso:
            condicoes.append('curso = %s')
            valores.append(curso)
        if periodo:
            condicoes.append('periodo = %s')
            valores.append(periodo)
        if docente:
            condicoes.append('id IN (SELECT oferta_id FROM oferta_docentes WHERE email = %s)')
            valores.append(docente)
        onde = ('WHERE ' + ' AND '.join(condicoes)) if condicoes else ''
        with self._conexao() as con:
            linhas = con.execute(f'SELECT * FROM ofertas {onde} ORDER BY periodo DESC, curso, fase NULLS LAST, '
                                 'lower(nome), turma, id', valores).fetchall()
            return self._com_docentes(con, linhas)

    def obter(self, id_):
        with self._conexao() as con:
            ofertas = self._com_docentes(con, con.execute('SELECT * FROM ofertas WHERE id = %s', (id_,)).fetchall())
        return ofertas[0] if ofertas else None

    def do_arquivo(self, arquivo):
        """A oferta dona do PDF da pasta de planos, ou None."""
        with self._conexao() as con:
            ofertas = self._com_docentes(con, con.execute('SELECT * FROM ofertas WHERE arquivo = %s',
                                                          (arquivo,)).fetchall())
        return ofertas[0] if ofertas else None

    def por_arquivo(self):
        """{arquivo: oferta} de todas as ofertas (para o painel montar curso, período e docentes)."""
        with self._conexao() as con:
            return {o['arquivo']: o for o in self._com_docentes(con, con.execute('SELECT * FROM ofertas').fetchall())}

    def periodos(self, curso):
        """Períodos com ofertas do curso, do mais recente para o mais antigo."""
        with self._conexao() as con:
            return [l['periodo'] for l in con.execute(
                'SELECT DISTINCT periodo FROM ofertas WHERE curso = %s ORDER BY periodo DESC', (curso,))]

    def criar(self, curso, periodo, nome, codigo='', carga_horaria=0, fase=None, turma='01', componente_id=None,
              criado_por=''):
        with self._trava, self._conexao() as con:
            linha = con.execute(
                'INSERT INTO ofertas (curso, periodo, componente_id, fase, codigo, nome, carga_horaria, turma, '
                'criado_em, criado_por) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *',
                (curso, periodo, componente_id, fase, codigo, nome, carga_horaria, turma, _agora(), criado_por)
            ).fetchone()
            arquivo = nome_do_arquivo(linha)
            con.execute('UPDATE ofertas SET arquivo = %s WHERE id = %s', (arquivo, linha['id']))
        return self.obter(linha['id'])

    def alterar(self, id_, **campos):
        """Muda nome, código, carga, fase ou turma da oferta (o arquivo do plano continua o mesmo)."""
        permitidos = {k: v for k, v in campos.items() if k in ('nome', 'codigo', 'carga_horaria', 'fase', 'turma')}
        if not permitidos:
            return False
        sets = ', '.join(f'{k} = %s' for k in permitidos)
        with self._trava, self._conexao() as con:
            return con.execute(f'UPDATE ofertas SET {sets} WHERE id = %s',
                               list(permitidos.values()) + [id_]).rowcount > 0

    def remover(self, id_):
        with self._trava, self._conexao() as con:
            return con.execute('DELETE FROM ofertas WHERE id = %s', (id_,)).rowcount > 0

    def definir_docentes(self, id_, emails):
        with self._trava, self._conexao() as con:
            con.execute('DELETE FROM oferta_docentes WHERE oferta_id = %s', (id_,))
            for e in dict.fromkeys(emails):
                con.execute('INSERT INTO oferta_docentes (oferta_id, email) VALUES (%s, %s)', (id_, e))

    # Plano enviado --------------------------------------------------------------------------------

    def registrar_envio(self, arquivo, email, aviso=''):
        with self._trava, self._conexao() as con:
            con.execute('UPDATE ofertas SET enviado_em = %s, enviado_por = %s, aviso = %s WHERE arquivo = %s',
                        (_agora(), email, aviso, arquivo))

    def limpar_envio(self, arquivo):
        with self._trava, self._conexao() as con:
            con.execute("UPDATE ofertas SET enviado_em = NULL, enviado_por = NULL, aviso = '' WHERE arquivo = %s",
                        (arquivo,))
