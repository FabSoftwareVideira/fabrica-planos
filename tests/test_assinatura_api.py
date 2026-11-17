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
    (_resposta(403, texto='Cidadão não possui a identidade (Prata ou Ouro) necessária'), 'nível bronze'),
    (_resposta(403, texto='CPF com situação cancelada, nula ou falecido na Receita Federal'), 'Receita Federal'),
    (_resposta(403, texto=''), 'CPF regular'),
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


def test_homologacao_sem_a_cadeia_no_cms_confia_no_certificado_do_professor(caplog):
    """A API de homologação pode devolver só o certificado do professor, sem a AC de teste do ITI."""
    import asyncio
    import logging
    from asn1crypto import keys, x509 as asn1_x509
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
    from pyhanko.sign import signers
    from pyhanko_certvalidator.registry import SimpleCertificateStore
    cert, chave = assinatura_api._certificado('FULANO DE TAL:12345678901', emissor=ApiSimulada.ac())
    folha = asn1_x509.Certificate.load(cert.public_bytes(Encoding.DER))
    signer = signers.SimpleSigner(signing_cert=folha, cert_registry=SimpleCertificateStore.from_certs([]),
                                  signing_key=keys.PrivateKeyInfo.load(
                                      chave.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())))
    cmss = []

    def assinar_hash(digest):
        cmss.append(asyncio.run(signer.async_sign(digest, 'sha256')).dump())
        return cmss[-1]
    pdf = assinatura_api.assinar_pdf(PDF_COM_TEXTO, assinar_hash)
    assert assinatura_api.acs_do_cms(cmss[0]) == []
    with caplog.at_level(logging.INFO):
        acs = ApiGovbr(_cfg(assinatura_ambiente='homologacao')).acs_confiaveis(cmss[0])
    assert [c.subject for c in acs] == [folha.subject] and 'FULANO DE TAL' in caplog.text
    assert assinatura.verificar(pdf, PDF_COM_TEXTO, acs)['cpf'] == '12345678901'
    assert ApiGovbr(_cfg(assinatura_ambiente='producao')).acs_confiaveis(cmss[0]) == []


def _cert_com_aia(url):
    """Certificado de professor (emitido pela AC simulada) com o endereço da cadeia (AIA)."""
    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import AuthorityInformationAccessOID, NameOID
    from datetime import datetime, timedelta, timezone
    ac, ac_chave = ApiSimulada.ac()
    chave = ec.generate_private_key(ec.SECP256R1())
    agora = datetime.now(timezone.utc)
    return (cx509.CertificateBuilder()
            .subject_name(cx509.Name([cx509.NameAttribute(NameOID.COMMON_NAME, 'MARIA DA SILVA:12345678901')]))
            .issuer_name(ac.subject).public_key(chave.public_key()).serial_number(cx509.random_serial_number())
            .not_valid_before(agora - timedelta(hours=1)).not_valid_after(agora + timedelta(days=1))
            .add_extension(cx509.AuthorityInformationAccess([cx509.AccessDescription(
                AuthorityInformationAccessOID.CA_ISSUERS, cx509.UniformResourceIdentifier(url))]), critical=False)
            .sign(ac_chave, hashes.SHA256()))


def test_cadeia_baixada_do_aia_vai_junto_da_assinatura(monkeypatch):
    from asn1crypto import x509 as asn1_x509
    from cryptography.hazmat.primitives.serialization import Encoding, pkcs7
    url = 'http://repo.exemplo/cadeia-teste.p7b'
    folha = asn1_x509.Certificate.load(_cert_com_aia(url).public_bytes(Encoding.DER))
    p7b = pkcs7.serialize_certificates([ApiSimulada.ac()[0]], Encoding.DER)
    pedidos = []
    monkeypatch.setattr(requests, 'get', lambda u, **kw: (pedidos.append(u), _resposta(conteudo=p7b))[1])
    cms_so_folha = assinatura_api.com_cadeia(ApiSimulada(_cfg()).assinar_hash('t', b'0' * 32), [])
    from asn1crypto import cms
    info = cms.ContentInfo.load(cms_so_folha)
    info['content']['certificates'] = cms.CertificateSet([cms.CertificateChoices(name='certificate', value=folha)])
    cms_der = info.dump(force=True)
    api = ApiGovbr(_cfg())
    cadeia = api.cadeia(cms_der)
    assert [c.subject for c in cadeia] == [ApiSimulada.ac_asn1().subject] and pedidos == [url]
    api.cadeia(cms_der)
    assert pedidos == [url]  # baixada uma vez só
    completo = assinatura_api.com_cadeia(cms_der, cadeia)
    assert len(assinatura_api.certificados_do_cms(completo)) == 2
    assert assinatura_api.com_cadeia(completo, cadeia) == completo  # nada repetido


def test_cadeia_sem_aia_ou_fora_do_ar(monkeypatch):
    def fora(u, **kw):
        raise requests.ConnectionError('fora')
    monkeypatch.setattr(requests, 'get', fora)
    from asn1crypto import x509 as asn1_x509
    from cryptography.hazmat.primitives.serialization import Encoding
    folha = asn1_x509.Certificate.load(_cert_com_aia('http://repo.exemplo/outra.p7b').public_bytes(Encoding.DER))
    from asn1crypto import cms
    info = cms.ContentInfo.load(ApiSimulada(_cfg()).assinar_hash('t', b'0' * 32))
    info['content']['certificates'] = cms.CertificateSet([cms.CertificateChoices(name='certificate', value=folha)])
    assert ApiGovbr(_cfg()).cadeia(info.dump(force=True)) == []
    assert ApiGovbr(_cfg()).cadeia(b'nao e cms') == []


def test_certificado_do_professor(monkeypatch):
    from cryptography.hazmat.primitives.serialization import Encoding
    pem = _cert_com_aia('http://x').public_bytes(Encoding.PEM)
    pedidos = []
    monkeypatch.setattr(requests, 'get', lambda u, **kw: (pedidos.append((u, kw)), _resposta(conteudo=pem))[1])
    cert = ApiGovbr(_cfg()).certificado('tok')
    assert assinatura.signatario(cert) == ('MARIA DA SILVA', '12345678901')
    assert pedidos[0][0] == 'https://api.exemplo/v2/certificadoPublico'
    assert pedidos[0][1]['headers']['Authorization'] == 'Bearer tok'
    monkeypatch.setattr(requests, 'get', lambda u, **kw: _resposta(status=401))
    assert ApiGovbr(_cfg()).certificado('tok') is None
    assert assinatura_api.certificados_de(b'lixo') == []


def test_pdf_assinado_como_recomenda_o_manual():
    """Primeira assinatura: /Reference com DocMDP P=2, sem /Perms nem /M; carimbo visível na última página."""
    import io
    import re
    from pyhanko.pdf_utils.reader import PdfFileReader
    api = ApiSimulada(_cfg())
    pdf = assinatura_api.assinar_pdf(PDF_COM_TEXTO, lambda d: api.assinar_hash('t', d), 'MARIA DA SILVA')
    novo = pdf[len(PDF_COM_TEXTO):]
    assert pdf.startswith(PDF_COM_TEXTO) and b'/Perms' not in novo and b'/DocMDP' in novo
    assert re.search(rb'/P\s+2', novo)
    assert not re.search(rb'/M\s*\(', novo)
    leitor = PdfFileReader(io.BytesIO(pdf), strict=False)
    [sig] = leitor.embedded_signatures
    campo = sig.sig_field
    assert [float(x) for x in campo['/Rect']] == list(map(float, assinatura_api.CAIXA_CARIMBO))
    assert '/AP' in campo
    assert assinatura.verificar(pdf, PDF_COM_TEXTO, [ApiSimulada.ac_asn1()])['signatario']
