import os
import sqlite3
import threading
from datetime import datetime

# Revisões manuais da avaliação da IA, em resultados/revisoes.sqlite3: uma por plano (a mais recente),
# feita por quem é da coordenação, do NDE ou do NDB do curso do plano. A assinatura (tamanho e data do
# PDF revisado) diz se a revisão ainda vale: um PDF novo com o mesmo nome a invalida (ver servicos/revisao.py).

ESQUEMA = """
CREATE TABLE IF NOT EXISTS revisoes (
    arquivo TEXT PRIMARY KEY,
    assinatura TEXT NOT NULL,
    status TEXT NOT NULL,
    status_ia TEXT NOT NULL DEFAULT '',
    comentario TEXT NOT NULL DEFAULT '',
    curso TEXT NOT NULL DEFAULT '',
    revisor_email TEXT NOT NULL,
    revisor_nome TEXT NOT NULL DEFAULT '',
    papel TEXT NOT NULL DEFAULT '',
    revisado_em TEXT NOT NULL
)
"""


class Revisoes:
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

    def salvar(self, arquivo, assinatura, status, status_ia, comentario, curso, revisor_email, revisor_nome, papel):
        """Grava a revisão do plano, substituindo a anterior. Devolve a revisão gravada."""
        revisao = {
            'arquivo': arquivo, 'assinatura': assinatura, 'status': status, 'status_ia': status_ia,
            'comentario': comentario, 'curso': curso, 'revisor_email': revisor_email, 'revisor_nome': revisor_nome,
            'papel': papel, 'revisado_em': datetime.now().isoformat(timespec='seconds'),
        }
        with self._trava, self._conexao() as con:
            con.execute(f'INSERT OR REPLACE INTO revisoes ({", ".join(revisao)}) '
                        f'VALUES ({", ".join("?" * len(revisao))})', list(revisao.values()))
        return revisao

    def obter(self, arquivo):
        with self._conexao() as con:
            linha = con.execute('SELECT * FROM revisoes WHERE arquivo = ?', (arquivo,)).fetchone()
        return dict(linha) if linha else None

    def todas(self):
        """{arquivo: revisão} de todas as revisões gravadas (vigentes ou não)."""
        with self._conexao() as con:
            return {l['arquivo']: dict(l) for l in con.execute('SELECT * FROM revisoes')}

    def remover(self, arquivo):
        with self._trava, self._conexao() as con:
            return con.execute('DELETE FROM revisoes WHERE arquivo = ?', (arquivo,)).rowcount > 0
