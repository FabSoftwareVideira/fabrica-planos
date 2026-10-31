import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    planos_dir: str
    resultados_dir: str
    ollama_url: str
    modelo: str
    num_ctx: int
    hora_agendada: int
    agendar: bool
    pdf_max_mb: int = 10
    # Login feito pelo proxy (Caddy + oauth2-proxy), que repassa o e-mail no cabeçalho X-Usuario-Email.
    # Sem exigir login (uso local, testes), todo acesso conta como administrador.
    exigir_login: bool = False
    admins: frozenset = frozenset()
    # Só em desenvolvimento: login simulado em /dev/login no lugar do Google (rotas/login_simulado.py)
    login_simulado: bool = False
    email_dominio: str = 'ifc.edu.br'

    @property
    def historico_dir(self):
        return os.path.join(self.resultados_dir, 'historico')

    @property
    def usuarios_path(self):
        """Cadastro de quem já entrou (nome, ativo, acessos)."""
        return os.path.join(self.resultados_dir, 'usuarios.sqlite3')

    @property
    def revisoes_path(self):
        """Revisões manuais (coordenação, NDE, NDB) da avaliação da IA."""
        return os.path.join(self.resultados_dir, 'revisoes.sqlite3')

    @property
    def csv_path(self):
        """Cópia do CSV da última validação, no caminho de sempre, para quem lê o arquivo direto."""
        return os.path.join(self.resultados_dir, 'validacao_planos.csv')


def carregar():
    return Config(
        planos_dir=os.environ.get('PLANOS_DIR', '/data/planos'),
        resultados_dir=os.environ.get('RESULTADOS_DIR', '/data/resultados'),
        ollama_url=os.environ.get('OLLAMA_URL', 'http://ollama:11434').rstrip('/'),
        modelo=os.environ.get('OLLAMA_MODEL', 'qwen2.5:7b'),
        num_ctx=int(os.environ.get('OLLAMA_NUM_CTX', '8192')),
        hora_agendada=int(os.environ.get('AGENDAMENTO_HORA', '5')),
        agendar=os.environ.get('AGENDAR', '1') == '1',
        pdf_max_mb=int(os.environ.get('PDF_MAX_MB') or '10'),
        exigir_login=os.environ.get('EXIGIR_LOGIN', '1') == '1',
        admins=frozenset(e.strip().lower() for e in os.environ.get('ADMIN_EMAILS', '').split(',') if e.strip()),
        login_simulado=os.environ.get('LOGIN_SIMULADO', '0') == '1',
        email_dominio=(os.environ.get('EMAIL_DOMINIO') or 'ifc.edu.br').strip().lower(),
    )
