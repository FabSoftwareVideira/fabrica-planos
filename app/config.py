import os
from dataclasses import dataclass

GOVBR_PRODUCAO = 'https://sso.acesso.gov.br'
GOVBR_HOMOLOGACAO = 'https://sso.staging.acesso.gov.br'
CERTIFICADOS_PADRAO = os.path.join(os.path.dirname(__file__), 'certificados')
# API de Assinatura Eletrônica do gov.br (ITI): servidor OAuth e API. Homologação conforme o manual de
# integração; produção a confirmar no documento das credenciais (dá para trocar pelas variáveis).
ASSINATURA_URLS = {
    'homologacao': ('https://cas.staging.iti.br/oauth2.0', 'https://assinatura-api.staging.iti.br/externo/v2'),
    'producao': ('https://cas.iti.br/oauth2.0', 'https://assinatura-api.iti.br/externo/v2'),
}


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
    # Backup diário de tudo o que o app grava: os PDFs de planos_dir e o conteúdo de resultados_dir.
    # `backups_dir` vazio guarda em resultados_dir/backups (bom para testes e uso local); em produção o
    # docker-compose.yml aponta para /data/backups, num volume próprio.
    backups_dir: str = ''
    backup_hora: int = 3
    backup_manter: int = 7
    backup_agendar: bool = False
    # Login feito pelo proxy (Caddy + oauth2-proxy), que repassa o e-mail no cabeçalho X-Usuario-Email.
    # Sem exigir login (uso local, testes), todo acesso conta como administrador.
    exigir_login: bool = False
    admins: frozenset = frozenset()
    # Só em desenvolvimento: login simulado em /dev/login no lugar do Google (rotas/login_simulado.py)
    login_simulado: bool = False
    email_dominio: str = 'ifc.edu.br'
    # Certificados raiz aceitos nas assinaturas dos planos (servicos/assinatura.py): por padrão os do
    # repositório, em app/certificados (a AC Raiz do Governo Federal do Brasil, do gov.br)
    certificados_dir: str = CERTIFICADOS_PADRAO
    # Login com gov.br (rotas/govbr.py), ao lado do Google (oauth2-proxy) ou no lugar dele (login_google=False).
    # Ligado quando há cliente, segredo e a chave da sessão (segredo_sessao).
    govbr_client_id: str = ''
    govbr_client_secret: str = ''
    govbr_url: str = GOVBR_PRODUCAO
    govbr_redirect_uri: str = ''
    govbr_logout_uri: str = ''
    segredo_sessao: str = ''
    login_google: bool = True
    oauth2_proxy_url: str = 'http://oauth2-proxy:4180'
    cookie_seguro: bool = True
    # Assinatura do plano pela API do gov.br (servicos/assinatura_api.py): credenciais próprias, separadas
    # das do login. 'simulada' (só desenvolvimento) assina com uma AC de teste local, sem o gov.br.
    assinatura_client_id: str = ''
    assinatura_client_secret: str = ''
    assinatura_ambiente: str = 'producao'
    assinatura_oauth_url: str = ASSINATURA_URLS['producao'][0]
    assinatura_api_url: str = ASSINATURA_URLS['producao'][1]
    assinatura_redirect_uri: str = ''

    @property
    def assinatura_api_ativa(self):
        if self.assinatura_ambiente == 'simulada':  # só junto do login simulado, que só existe em desenvolvimento
            return self.login_simulado
        return bool(self.assinatura_client_id and self.assinatura_client_secret and self.segredo_sessao)

    @property
    def govbr_ativo(self):
        return bool(self.govbr_client_id and self.govbr_client_secret and self.segredo_sessao)

    @property
    def pasta_backups(self):
        """Pasta dos arquivos de backup; por padrão, dentro de resultados_dir."""
        return self.backups_dir or os.path.join(self.resultados_dir, 'backups')

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
        backups_dir=(os.environ.get('BACKUPS_DIR') or '').strip(),
        backup_hora=max(0, min(23, int(os.environ.get('BACKUP_HORA') or '3'))),
        backup_manter=max(1, int(os.environ.get('BACKUP_MANTER') or '7')),
        backup_agendar=os.environ.get('BACKUP_AGENDAR', '1') == '1',
        exigir_login=os.environ.get('EXIGIR_LOGIN', '1') == '1',
        admins=frozenset(e.strip().lower() for e in os.environ.get('ADMIN_EMAILS', '').split(',') if e.strip()),
        login_simulado=os.environ.get('LOGIN_SIMULADO', '0') == '1',
        email_dominio=(os.environ.get('EMAIL_DOMINIO') or 'ifc.edu.br').strip().lower(),
        certificados_dir=os.environ.get('CERTIFICADOS_DIR') or CERTIFICADOS_PADRAO,
        govbr_client_id=os.environ.get('GOVBR_CLIENT_ID', '').strip(),
        govbr_client_secret=os.environ.get('GOVBR_CLIENT_SECRET', '').strip(),
        # GOVBR_AMBIENTE=homologacao usa o ambiente de testes do gov.br (credenciais de homologação)
        govbr_url=GOVBR_HOMOLOGACAO if os.environ.get('GOVBR_AMBIENTE', '').strip().lower() == 'homologacao'
        else GOVBR_PRODUCAO,
        govbr_redirect_uri=os.environ.get('GOVBR_REDIRECT_URI', '').strip(),
        govbr_logout_uri=os.environ.get('GOVBR_LOGOUT_URI', '').strip(),
        segredo_sessao=os.environ.get('SEGREDO_SESSAO', '').strip(),
        login_google=os.environ.get('LOGIN_GOOGLE', '1') == '1',
        oauth2_proxy_url=(os.environ.get('OAUTH2_PROXY_URL') or 'http://oauth2-proxy:4180').rstrip('/'),
        cookie_seguro=os.environ.get('COOKIE_SECURE', 'true').lower() != 'false',
        **_assinatura(),
    )


def _assinatura():
    """Configuração da API de assinatura. O ambiente segue o do login (GOVBR_AMBIENTE) se
    GOVBR_ASSINATURA_AMBIENTE não for dado; as URLs têm padrão por ambiente."""
    ambiente = (os.environ.get('GOVBR_ASSINATURA_AMBIENTE') or os.environ.get('GOVBR_AMBIENTE') or 'producao')
    ambiente = ambiente.strip().lower()
    if ambiente not in ('homologacao', 'producao', 'simulada'):
        ambiente = 'producao'
    oauth, api = ASSINATURA_URLS.get(ambiente, ASSINATURA_URLS['producao'])
    return {
        'assinatura_client_id': os.environ.get('GOVBR_ASSINATURA_CLIENT_ID', '').strip(),
        'assinatura_client_secret': os.environ.get('GOVBR_ASSINATURA_CLIENT_SECRET', '').strip(),
        'assinatura_ambiente': ambiente,
        'assinatura_oauth_url': (os.environ.get('GOVBR_ASSINATURA_OAUTH_URL') or oauth).strip().rstrip('/'),
        'assinatura_api_url': (os.environ.get('GOVBR_ASSINATURA_API_URL') or api).strip().rstrip('/'),
        'assinatura_redirect_uri': os.environ.get('GOVBR_ASSINATURA_REDIRECT_URI', '').strip(),
    }
