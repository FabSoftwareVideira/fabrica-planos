"""Importa os dados dos antigos SQLite (usuários e revisões) para o PostgreSQL.

    docker compose exec app python -m app.migrar_sqlite

Lê resultados/usuarios.sqlite3 e resultados/revisoes.sqlite3 (da RESULTADOS_DIR) e grava no banco de
DATABASE_URL. Pode ser repetido: o que já existe no PostgreSQL é mantido (ON CONFLICT DO NOTHING).
"""
import os
import sqlite3
import sys

from .armazenamento.revisoes import Revisoes
from .armazenamento.usuarios import Usuarios
from .banco import Banco

COLUNAS = {
    'usuarios': ('email', 'nome', 'ativo', 'primeiro_acesso', 'ultimo_acesso'),
    'papeis_curso': ('email', 'curso', 'papel'),
    'revisoes': ('arquivo', 'assinatura', 'status', 'status_ia', 'comentario', 'curso', 'revisor_email',
                 'revisor_nome', 'papel', 'revisado_em'),
}
ARQUIVOS = {'usuarios.sqlite3': ('usuarios', 'papeis_curso'), 'revisoes.sqlite3': ('revisoes',)}


def migrar(resultados_dir, banco):
    """Copia as tabelas dos arquivos que existirem e devolve {tabela: linhas lidas}."""
    Usuarios(banco), Revisoes(banco)  # cria as tabelas
    total = {}
    for arquivo, tabelas in ARQUIVOS.items():
        caminho = os.path.join(resultados_dir, arquivo)
        if not os.path.isfile(caminho):
            continue
        origem = sqlite3.connect(caminho)
        try:
            for tabela in tabelas:
                colunas = COLUNAS[tabela]
                try:
                    linhas = origem.execute(f'SELECT {", ".join(colunas)} FROM {tabela}').fetchall()
                except sqlite3.OperationalError:  # arquivo sem essa tabela
                    continue
                with banco.conexao() as con:
                    for linha in linhas:
                        con.execute(f'INSERT INTO {tabela} ({", ".join(colunas)}) '
                                    f'VALUES ({", ".join(["%s"] * len(colunas))}) ON CONFLICT DO NOTHING', linha)
                total[tabela] = len(linhas)
        finally:
            origem.close()
    return total


def main():
    resultados = os.environ.get('RESULTADOS_DIR', '/data/resultados')
    banco = Banco(os.environ.get('DATABASE_URL', ''))
    total = migrar(resultados, banco)
    if not total:
        print(f'Nenhum SQLite encontrado em {resultados}.')
        return 1
    for tabela, n in total.items():
        print(f'{tabela}: {n} linha(s) lida(s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
