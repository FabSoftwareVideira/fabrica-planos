import logging
import os
import re
import time

import psycopg
from psycopg.rows import dict_row

# Acesso ao PostgreSQL (usuários e revisões). Cada operação abre e fecha a própria conexão
# (`with banco.conexao() as con:` confirma a transação e fecha ao sair), sem pool: o app tem
# um único worker e poucas escritas.

log = logging.getLogger(__name__)

TABELAS = ('usuarios', 'papeis_curso', 'revisoes')
_NOME_ESQUEMA = re.compile(r'^[a-z_][a-z0-9_]*$')


class Banco:
    def __init__(self, url, esquema=None, espera=30):
        if not url:
            raise RuntimeError('DATABASE_URL não definida (ex.: postgresql://usuario:senha@postgres:5432/planos)')
        # DB_ESQUEMA existe para isolar os testes; em produção fica o esquema padrão (public)
        self.url = url
        self.esquema = esquema or os.environ.get('DB_ESQUEMA') or 'public'
        if not _NOME_ESQUEMA.match(self.esquema):
            raise ValueError(f'Nome de esquema inválido: {self.esquema}')
        self._aguardar(espera)

    def _aguardar(self, espera):
        """Espera o PostgreSQL aceitar conexões (no docker compose ele pode subir depois do app)."""
        limite = time.monotonic() + espera
        while True:
            try:
                with psycopg.connect(self.url, connect_timeout=5) as con:
                    con.execute(f'CREATE SCHEMA IF NOT EXISTS {self.esquema}')
                return
            except psycopg.OperationalError:
                if time.monotonic() >= limite:
                    raise
                log.info('Aguardando o PostgreSQL...')
                time.sleep(1)

    def conexao(self):
        return psycopg.connect(self.url, row_factory=dict_row, connect_timeout=10,
                               options=f'-c search_path={self.esquema}')
