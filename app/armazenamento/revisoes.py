import threading
from datetime import datetime

# Revisões manuais da avaliação da IA, no PostgreSQL (tabela revisoes): uma por plano (a mais recente),
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
    def __init__(self, banco):
        self.banco = banco
        self._trava = threading.Lock()
        with self._conexao() as con:
            con.execute(ESQUEMA)

    def _conexao(self):
        return self.banco.conexao()

    def salvar(self, arquivo, assinatura, status, status_ia, comentario, curso, revisor_email, revisor_nome, papel):
        """Grava a revisão do plano, substituindo a anterior. Devolve a revisão gravada."""
        revisao = {
            'arquivo': arquivo, 'assinatura': assinatura, 'status': status, 'status_ia': status_ia,
            'comentario': comentario, 'curso': curso, 'revisor_email': revisor_email, 'revisor_nome': revisor_nome,
            'papel': papel, 'revisado_em': datetime.now().isoformat(timespec='seconds'),
        }
        with self._trava, self._conexao() as con:
            atualizar = ', '.join(f'{c} = EXCLUDED.{c}' for c in revisao if c != 'arquivo')
            con.execute(f'INSERT INTO revisoes ({", ".join(revisao)}) VALUES ({", ".join(["%s"] * len(revisao))}) '
                        f'ON CONFLICT (arquivo) DO UPDATE SET {atualizar}', list(revisao.values()))
        return revisao

    def obter(self, arquivo):
        with self._conexao() as con:
            linha = con.execute('SELECT * FROM revisoes WHERE arquivo = %s', (arquivo,)).fetchone()
        return dict(linha) if linha else None

    def todas(self):
        """{arquivo: revisão} de todas as revisões gravadas (vigentes ou não)."""
        with self._conexao() as con:
            return {l['arquivo']: dict(l) for l in con.execute('SELECT * FROM revisoes')}

    def remover(self, arquivo):
        with self._trava, self._conexao() as con:
            return con.execute('DELETE FROM revisoes WHERE arquivo = %s', (arquivo,)).rowcount > 0
