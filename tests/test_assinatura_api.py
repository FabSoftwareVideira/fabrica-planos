"""Testes unitários das falhas da assinatura: cliente da API de Assinatura Eletrônica do gov.br
(app/servicos/assinatura_api.py) e conferência do PDF assinado (app/servicos/assinatura.py). A rede é
trocada por respostas falsas; nada vai ao gov.br."""
from unittest import mock

import pytest
import requests

from app.config import Config
from app.servicos import assinatura, assinatura_api
from app.servicos.assinatura_api import ApiGovbr, ApiSimulada, FalhaApi
from conftest import PDF_COM_TEXTO, assinar, gerar_ac, salvar_ac


def _cfg(**opcoes):
    base = dict(planos_dir='', resultados_dir='', ollama_url='', modelo='', num_ctx=1, hora_agendada=5,
                agendar=False, assinatura_client_id='cli', assinatura_client_secret='seg', segredo_sessao='k',
                assinatura_oauth_url='https://cas.exemplo/oauth2.0', assinatura_api_url='https://api.exemplo/v2')
    return Config(**{**base, **opcoes})


def _resposta(status=200, corpo=None, conteudo=b'', texto=''):
    r = mock.Mock(status_code=status, ok=status < 400, content=conteudo, text=texto)
    r.json = mock.Mock(return_value=corpo) if corpo is not None else mock.Mock(side_effect=ValueError)

    def levantar():
        if status >= 400:
            raise requests.HTTPError(f'HTTP {status}')
    r.raise_for_status = levantar
    return r


# Cliente da API -----------------------------------------------------------------------------------------

def test_url_de_autorizacao(monkeypatch):
    url = ApiGovbr(_cfg()).url_autorizacao('https://planos/volta', 'st', 'no')
    assert url.startswith('https://cas.exemplo/oauth2.0/authorize?')
    assert 'scope=sign+govbr' in url and 'state=st' in url and 'client_id=cli' in url


def test_token(monkeypatch):
    pedidos = []

    def post(url, **kw):
        pedidos.append((url, kw))
        return _resposta(corpo={'access_token': 'tok'})
    monkeypatch.setattr(requests, 'post', post)
    assert ApiGovbr(_cfg()).token('codigo', 'https://planos/volta') == 'tok'
    url, kw = pedidos[0]
    assert url == 'https://cas.exemplo/oauth2.0/token' and kw['data']['grant_type'] == 'authorization_code'


@pytest.mark.parametrize('resposta', [_resposta(400), _resposta(corpo={'sem': 'token'}), _resposta(corpo=None)])
def test_falha_ao_obter_o_token(monkeypatch, resposta):
    monkeypatch.setattr(requests, 'post', lambda url, **kw: resposta)
    with pytest.raises(FalhaApi, match='autorização'):
        ApiGovbr(_cfg()).token('codigo', 'https://planos/volta')


def test_token_com_gov_br_fora_do_ar(monkeypatch):
    def fora(url, **kw):
        raise requests.ConnectTimeout('timed out')
    monkeypatch.setattr(requests, 'post', fora)
    with pytest.raises(FalhaApi):
        ApiGovbr(_cfg()).token('codigo', 'x')


@pytest.mark.parametrize('resposta, mensagem', [
    (_resposta(403, texto='Cidadão não possui a identidade'), 'prata ou ouro'),
    (_resposta(500, texto='erro interno'), 'recusou o pedido'),
])
def test_api_recusa_a_assinatura(monkeypatch, resposta, mensagem):
    monkeypatch.setattr(requests, 'post', lambda url, **kw: resposta)
    with pytest.raises(FalhaApi, match=mensagem):
        ApiGovbr(_cfg()).assinar_hash('tok', b'0' * 32)


def test_api_de_assinatura_fora_do_ar(monkeypatch):
    def fora(url, **kw):
        raise requests.ConnectionError('recusada')
    monkeypatch.setattr(requests, 'post', fora)
    with pytest.raises(FalhaApi, match='não respondeu'):
        ApiGovbr(_cfg()).assinar_hash('tok', b'0' * 32)


def test_assinar_hash_envia_o_resumo_em_base64(monkeypatch):
    cms = ApiSimulada(None).assinar_hash('t', b'1' * 32, 'Fulano')
    pedidos = []

    def post(url, **kw):
        pedidos.append((url, kw))
        return _resposta(conteudo=cms)
    monkeypatch.setattr(requests, 'post', post)
    assert ApiGovbr(_cfg()).assinar_hash('tok', b'1' * 32) == cms
    url, kw = pedidos[0]
    assert url == 'https://api.exemplo/v2/assinarPKCS7' and kw['headers']['Authorization'] == 'Bearer tok'
    assert kw['json'] == {'hashBase64': 'MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE='}


@pytest.mark.parametrize('conteudo', [b'', b'nao e cms', b'\x30\x03\x02\x01\x01'])
def test_acs_de_cms_ilegivel(conteudo):
    assert assinatura_api.acs_do_cms(conteudo) == []


def test_assinatura_maior_que_o_espaco_reservado():
    with pytest.raises(FalhaApi, match='maior que o espaço'):
        assinatura_api.assinar_pdf(PDF_COM_TEXTO, lambda digest: b'0' * (assinatura_api.RESERVA_CMS + 1))


def test_cliente_conforme_o_ambiente(caplog):
    assert isinstance(assinatura_api.cliente(_cfg(assinatura_ambiente='homologacao')), ApiGovbr)
    assert assinatura_api.cliente(_cfg(assinatura_client_id='')) is None
    assert isinstance(assinatura_api.cliente(_cfg(assinatura_ambiente='simulada', login_simulado=True)), ApiSimulada)
    assert assinatura_api.cliente(_cfg(assinatura_ambiente='simulada')) is None
    assert 'simulada ignorado' in caplog.text


# Conferência do PDF assinado ------------------------------------------------------------------------------

def test_carregar_raizes_ignora_outros_arquivos_e_certificados_ilegiveis(tmp_path, caplog):
    pasta = salvar_ac(gerar_ac(), tmp_path / 'certs')
    (tmp_path / 'certs' / 'LEIA-ME.md').write_text('não é certificado')
    (tmp_path / 'certs' / 'quebrado.crt').write_bytes(b'-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n')
    raizes = assinatura.carregar_raizes(pasta)
    assert len(raizes) == 1 and 'Certificado ilegível ignorado' in caplog.text
    assert assinatura.carregar_raizes(str(tmp_path / 'nao-existe')) == []


def test_pdf_ilegivel_nao_e_o_mesmo_conteudo():
    assert not assinatura.mesmo_conteudo(b'%PDF-1.4 quebrado', PDF_COM_TEXTO)
    assert assinatura._palavras_por_pagina(b'nao e pdf') is None


def test_assinatura_que_nao_pode_ser_lida(tmp_path, monkeypatch):
    ac = gerar_ac()
    raizes = assinatura.carregar_raizes(salvar_ac(ac, tmp_path / 'c'))

    def quebra(*a, **k):
        raise ValueError('estrutura desconhecida')
    monkeypatch.setattr(assinatura, 'validate_pdf_signature', quebra)
    with pytest.raises(assinatura.AssinaturaInvalida, match='não pôde ser lida'):
        assinatura.verificar(assinar(PDF_COM_TEXTO, ac), PDF_COM_TEXTO, raizes)


def test_signatario_com_nome_comum_repetido():
    certificado = mock.Mock()
    certificado.subject.native = {'common_name': ['FULANO DE TAL:12345678900', 'outro']}
    assert assinatura.signatario(certificado)[0] == 'FULANO DE TAL'
