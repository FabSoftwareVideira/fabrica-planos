"""Testes unitários da configuração lida das variáveis de ambiente (app/config.py)."""
import os

import pytest

from app import config
from app.config import ASSINATURA_URLS, GOVBR_HOMOLOGACAO, GOVBR_PRODUCAO, Config, carregar

VARIAVEIS = [
    'PLANOS_DIR', 'RESULTADOS_DIR', 'OLLAMA_URL', 'OLLAMA_MODEL', 'OLLAMA_NUM_CTX', 'AGENDAMENTO_HORA', 'AGENDAR',
    'PDF_MAX_MB', 'BACKUPS_DIR', 'BACKUP_HORA', 'BACKUP_MANTER', 'BACKUP_AGENDAR', 'EXIGIR_LOGIN', 'ADMIN_EMAILS',
    'LOGIN_SIMULADO', 'EMAIL_DOMINIO', 'CERTIFICADOS_DIR', 'GOVBR_CLIENT_ID', 'GOVBR_CLIENT_SECRET',
    'GOVBR_AMBIENTE', 'GOVBR_REDIRECT_URI', 'SEGREDO_SESSAO', 'LOGIN_GOOGLE', 'OAUTH2_PROXY_URL', 'COOKIE_SECURE',
    'GOVBR_ASSINATURA_AMBIENTE', 'GOVBR_ASSINATURA_CLIENT_ID', 'GOVBR_ASSINATURA_CLIENT_SECRET',
    'GOVBR_ASSINATURA_OAUTH_URL', 'GOVBR_ASSINATURA_API_URL', 'GOVBR_ASSINATURA_REDIRECT_URI',
]


@pytest.fixture
def ambiente(monkeypatch):
    """Ambiente limpo: só valem as variáveis que o teste definir."""
    for nome in VARIAVEIS:
        monkeypatch.delenv(nome, raising=False)

    def definir(**valores):
        for nome, valor in valores.items():
            monkeypatch.setenv(nome, valor)
        return carregar()
    return definir


def _cfg(**opcoes):
    base = dict(planos_dir='/p', resultados_dir='/r', ollama_url='', modelo='', num_ctx=1, hora_agendada=5,
                agendar=False)
    return Config(**{**base, **opcoes})


def test_padroes_de_producao(ambiente):
    cfg = ambiente()
    assert (cfg.planos_dir, cfg.resultados_dir) == ('/data/planos', '/data/resultados')
    assert cfg.ollama_url == 'http://ollama:11434' and cfg.modelo == 'qwen2.5:7b' and cfg.num_ctx == 8192
    assert cfg.agendar and cfg.exigir_login and cfg.login_google and cfg.cookie_seguro and cfg.backup_agendar
    assert not cfg.login_simulado and cfg.admins == frozenset()
    assert cfg.pdf_max_mb == 10 and cfg.backup_hora == 3 and cfg.backup_manter == 7
    assert cfg.email_dominio == 'ifc.edu.br' and cfg.govbr_url == GOVBR_PRODUCAO
    assert cfg.oauth2_proxy_url == 'http://oauth2-proxy:4180'
    assert not cfg.govbr_ativo and not cfg.assinatura_api_ativa
    assert cfg.assinatura_ambiente == 'producao'
    assert (cfg.assinatura_oauth_url, cfg.assinatura_api_url) == ASSINATURA_URLS['producao']


def test_variaveis_definidas(ambiente):
    cfg = ambiente(OLLAMA_URL='http://gpu:11434/', OLLAMA_NUM_CTX='4096', AGENDAR='0', EXIGIR_LOGIN='0',
                   ADMIN_EMAILS=' Admin@IFC.edu.br, ,outro@ifc.edu.br ', EMAIL_DOMINIO=' IFC.EDU.BR ',
                   LOGIN_GOOGLE='0', COOKIE_SECURE='False', OAUTH2_PROXY_URL='http://proxy:4180/', PDF_MAX_MB='',
                   BACKUPS_DIR=' /backups ')
    assert cfg.ollama_url == 'http://gpu:11434' and cfg.num_ctx == 4096
    assert not cfg.agendar and not cfg.exigir_login and not cfg.login_google and not cfg.cookie_seguro
    assert cfg.admins == frozenset({'admin@ifc.edu.br', 'outro@ifc.edu.br'})
    assert cfg.email_dominio == 'ifc.edu.br' and cfg.oauth2_proxy_url == 'http://proxy:4180'
    assert cfg.pdf_max_mb == 10  # vazio vale o padrão
    assert cfg.pasta_backups == '/backups'


@pytest.mark.parametrize('hora, esperado', [('-3', 0), ('30', 23), ('12', 12), ('', 3)])
def test_hora_do_backup_fica_entre_0_e_23(ambiente, hora, esperado):
    assert ambiente(BACKUP_HORA=hora).backup_hora == esperado


def test_backup_mantem_pelo_menos_um(ambiente):
    assert ambiente(BACKUP_MANTER='0').backup_manter == 1


def test_login_govbr_liga_com_cliente_segredo_e_chave(ambiente):
    assert not ambiente(GOVBR_CLIENT_ID='c', GOVBR_CLIENT_SECRET='s').govbr_ativo  # falta SEGREDO_SESSAO
    cfg = ambiente(GOVBR_CLIENT_ID=' c ', GOVBR_CLIENT_SECRET='s', SEGREDO_SESSAO='k', GOVBR_AMBIENTE='Homologacao')
    assert cfg.govbr_ativo and cfg.govbr_client_id == 'c' and cfg.govbr_url == GOVBR_HOMOLOGACAO


def test_assinatura_segue_o_ambiente_do_login(ambiente):
    cfg = ambiente(GOVBR_AMBIENTE='homologacao')
    assert cfg.assinatura_ambiente == 'homologacao'
    assert (cfg.assinatura_oauth_url, cfg.assinatura_api_url) == ASSINATURA_URLS['homologacao']


def test_assinatura_com_ambiente_proprio_e_urls_trocadas(ambiente):
    cfg = ambiente(GOVBR_AMBIENTE='homologacao', GOVBR_ASSINATURA_AMBIENTE='producao',
                   GOVBR_ASSINATURA_OAUTH_URL='https://oauth.exemplo/', GOVBR_ASSINATURA_API_URL=' https://api.exemplo/v2/ ',
                   GOVBR_ASSINATURA_CLIENT_ID='c', GOVBR_ASSINATURA_CLIENT_SECRET='s', SEGREDO_SESSAO='k')
    assert cfg.assinatura_ambiente == 'producao' and cfg.assinatura_api_ativa
    assert cfg.assinatura_oauth_url == 'https://oauth.exemplo' and cfg.assinatura_api_url == 'https://api.exemplo/v2'


def test_urls_da_assinatura_so_com_o_host(ambiente):
    cfg = ambiente(GOVBR_ASSINATURA_AMBIENTE='homologacao', GOVBR_ASSINATURA_OAUTH_URL='cas.staging.iti.br',
                   GOVBR_ASSINATURA_API_URL='https://assinatura-api.staging.iti.br/')
    assert (cfg.assinatura_oauth_url, cfg.assinatura_api_url) == ASSINATURA_URLS['homologacao']
    # Em produção, o host de produção do ITI ganha o caminho dele
    cfg = ambiente(GOVBR_ASSINATURA_AMBIENTE='homologacao', GOVBR_ASSINATURA_OAUTH_URL='cas.iti.br')
    assert cfg.assinatura_oauth_url == ASSINATURA_URLS['producao'][0]


def test_ambiente_com_acento(ambiente):
    cfg = ambiente(GOVBR_AMBIENTE='Homologação', GOVBR_ASSINATURA_AMBIENTE=' homologação ')
    assert cfg.assinatura_ambiente == 'homologacao' and cfg.govbr_url == 'https://sso.staging.acesso.gov.br'


def test_ambiente_de_assinatura_desconhecido_vira_producao(ambiente):
    assert ambiente(GOVBR_ASSINATURA_AMBIENTE='qualquer').assinatura_ambiente == 'producao'


def test_assinatura_simulada_so_com_login_simulado():
    assert not _cfg(assinatura_ambiente='simulada').assinatura_api_ativa
    assert _cfg(assinatura_ambiente='simulada', login_simulado=True).assinatura_api_ativa


def test_caminhos_derivados():
    cfg = _cfg(resultados_dir=os.path.join('x', 'res'))
    assert cfg.pasta_backups == os.path.join('x', 'res', 'backups')
    assert cfg.historico_dir == os.path.join('x', 'res', 'historico')
    assert cfg.csv_path == os.path.join('x', 'res', 'validacao_planos.csv')


def test_certificados_padrao_e_trocado(ambiente):
    assert ambiente().certificados_dir == config.CERTIFICADOS_PADRAO
    assert ambiente(CERTIFICADOS_DIR='/certs').certificados_dir == '/certs'
