import os
import re
import shutil
import threading
from datetime import datetime

# Histórico de versões dos planos: quando o professor envia uma versão nova de um plano que já tinha PDF
# (mesmo assinado), a anterior é arquivada aqui, com o que se sabia dela. O PDF (e o assinado, se houver)
# fica em resultados/versoes/<plano>/v<número>.pdf e v<número>-assinado.pdf; os dados, na tabela
# versoes_planos do PostgreSQL. A versão atual é a do PDF na pasta de planos (número = arquivadas + 1).

ESQUEMA = """
CREATE TABLE IF NOT EXISTS versoes_planos (
    arquivo TEXT NOT NULL,
    numero INTEGER NOT NULL,
    enviado_em TEXT,
    enviado_por TEXT,
    aviso TEXT NOT NULL DEFAULT '',
    arquivado_em TEXT NOT NULL,
    bytes INTEGER NOT NULL DEFAULT 0,
    status_ia TEXT NOT NULL DEFAULT '',
    revisao_status TEXT NOT NULL DEFAULT '',
    revisor TEXT NOT NULL DEFAULT '',
    revisado_em TEXT,
    signatario TEXT NOT NULL DEFAULT '',
    assinado_em TEXT,
    tem_assinado BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (arquivo, numero)
)
"""

CAMPOS = ('enviado_em', 'enviado_por', 'aviso', 'bytes', 'status_ia', 'revisao_status', 'revisor', 'revisado_em',
          'signatario', 'assinado_em', 'tem_assinado')


def _agora():
    return datetime.now().isoformat(timespec='seconds')


class Versoes:
    def __init__(self, banco, resultados_dir):
        self.banco = banco
        self.dir = os.path.join(resultados_dir, 'versoes')
        self._trava = threading.Lock()
        with self.banco.conexao() as con:
            con.execute(ESQUEMA)

    def _pasta(self, arquivo):
        return os.path.join(self.dir, re.sub(r'[^\w.\-]', '_', arquivo))

    def caminho(self, arquivo, numero, assinado=False):
        return os.path.join(self._pasta(arquivo), f"v{int(numero)}{'-assinado' if assinado else ''}.pdf")

    def arquivar(self, arquivo, pdf, pdf_assinado=None, **dados):
        """Guarda a versão atual do plano (o PDF e, se houver, o assinado) e devolve o número dela."""
        dados = {k: v for k, v in dados.items() if k in CAMPOS}
        with self._trava, self.banco.conexao() as con:
            numero = con.execute('SELECT coalesce(max(numero), 0) + 1 AS n FROM versoes_planos WHERE arquivo = %s',
                                 (arquivo,)).fetchone()['n']
            os.makedirs(self._pasta(arquivo), exist_ok=True)
            shutil.copy2(pdf, self.caminho(arquivo, numero))
            dados['bytes'] = os.path.getsize(pdf)
            dados['tem_assinado'] = bool(pdf_assinado and os.path.isfile(pdf_assinado))
            if dados['tem_assinado']:
                shutil.copy2(pdf_assinado, self.caminho(arquivo, numero, assinado=True))
            colunas = ['arquivo', 'numero', 'arquivado_em'] + list(dados)
            con.execute(f'INSERT INTO versoes_planos ({", ".join(colunas)}) VALUES ({", ".join(["%s"] * len(colunas))})',
                        [arquivo, numero, _agora()] + list(dados.values()))
        return numero

    def listar(self, arquivo):
        """Versões arquivadas do plano, da mais recente para a mais antiga."""
        with self.banco.conexao() as con:
            return [dict(l) for l in con.execute(
                'SELECT * FROM versoes_planos WHERE arquivo = %s ORDER BY numero DESC', (arquivo,))]

    def de_varios(self, arquivos):
        """{arquivo: [versões]} de vários planos de uma vez."""
        arquivos = list(arquivos)
        saida = {a: [] for a in arquivos}
        if arquivos:
            with self.banco.conexao() as con:
                for l in con.execute('SELECT * FROM versoes_planos WHERE arquivo = ANY(%s) ORDER BY numero DESC',
                                     (arquivos,)):
                    saida[l['arquivo']].append(dict(l))
        return saida

    def obter(self, arquivo, numero):
        with self.banco.conexao() as con:
            linha = con.execute('SELECT * FROM versoes_planos WHERE arquivo = %s AND numero = %s',
                                (arquivo, numero)).fetchone()
        return dict(linha) if linha else None
