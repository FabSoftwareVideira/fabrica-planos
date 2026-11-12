import asyncio
import base64
import io
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests
from asn1crypto import cms
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import fields
from pyhanko.sign.signers.cms_embedder import PdfCMSEmbedder, SigIOSetup, SigMDPSetup, SigObjSetup
from pyhanko.sign.signers.pdf_byterange import SignatureObject

log = logging.getLogger(__name__)

# Assinatura do plano pela API de Assinatura Eletrônica do gov.br (ITI), no lugar do assinador.iti.br.
# Fluxo (manual de integração da assinatura eletrônica gov.br):
#   1. o professor vai ao servidor OAuth do ITI (/authorize, escopo "sign govbr") e confirma com o gov.br;
#   2. o código que volta é trocado por um token (/token), que vale 10 minutos e uma assinatura;
#   3. o app reserva no PDF o espaço da assinatura e calcula o hash SHA-256 dos trechos cobertos (ByteRange);
#   4. POST /assinarPKCS7 com {"hashBase64": ...} devolve o PKCS#7 (CMS) com o certificado do professor;
#   5. o CMS é gravado no espaço reservado, e o PDF segue para a conferência de sempre (assinatura.py).

ESCOPO = 'sign govbr'  # uma assinatura, com o certificado do gov.br
RESERVA_CMS = 16384  # bytes reservados no PDF para o CMS (certificado e cadeia cabem com folga)
CAMPO = 'AssinaturaGovBr'


class FalhaApi(Exception):
    """A API do gov.br não assinou; a mensagem diz por quê, para o professor."""


def assinar_pdf(pdf, assinar_hash):
    """Devolve o PDF (bytes) com a assinatura embutida. `assinar_hash(digest)` recebe o SHA-256 dos trechos
    cobertos pela assinatura e devolve o CMS (DER) que o assinador remoto produziu sobre ele.

    A assinatura é acrescentada ao final do arquivo (atualização incremental), então o original fica
    intacto antes dela. Sendo a primeira do documento, ela certifica o PDF (DocMDP P=2: só preencher
    formulários e assinar), como recomenda o manual do gov.br."""
    ja_assinado = bool(PdfFileReader(io.BytesIO(pdf), strict=False).embedded_signatures)
    buffer = io.BytesIO(pdf)
    escritor = IncrementalPdfFileWriter(buffer, strict=False)
    etapas = PdfCMSEmbedder().write_cms(field_name=CAMPO, writer=escritor)
    next(etapas)
    mdp = SigMDPSetup(md_algorithm='sha256', certify=not ja_assinado,
                      docmdp_perms=None if ja_assinado else fields.MDPPerm.FILL_FORMS)
    etapas.send(SigObjSetup(sig_placeholder=SignatureObject(bytes_reserved=RESERVA_CMS), mdp_setup=mdp))
    digest, saida = etapas.send(SigIOSetup(md_algorithm='sha256', in_place=True))
    cms_der = assinar_hash(digest.document_digest)
    if len(cms_der) > RESERVA_CMS:
        raise FalhaApi('A assinatura devolvida pelo gov.br é maior que o espaço reservado no PDF; avise a administração.')
    etapas.send(cms_der)
    return saida.getvalue()


def ler_cms(conteudo):
    """CMS (DER) da resposta da API: binário, como diz o manual, ou em Base64/PEM, por garantia."""
    for candidato in (conteudo, _base64(conteudo)):
        if candidato:
            try:
                info = cms.ContentInfo.load(candidato)
                info['content']['signer_infos']  # confere a estrutura
                return candidato
            except (ValueError, TypeError, KeyError):
                continue
    raise FalhaApi('O gov.br devolveu uma assinatura em formato inesperado. Tente de novo.')


def _base64(conteudo):
    texto = conteudo.decode('ascii', 'ignore')
    texto = ''.join(l for l in texto.splitlines() if not l.startswith('-----'))
    try:
        return base64.b64decode(texto, validate=False)
    except ValueError:
        return b''


def acs_do_cms(cms_der):
    """Certificados de AC que vieram dentro do CMS (a cadeia do certificado do professor)."""
    try:
        certificados = cms.ContentInfo.load(cms_der)['content']['certificates'] or []
    except (ValueError, KeyError):
        return []
    return [c.chosen for c in certificados if c.name == 'certificate' and c.chosen.ca]


class ApiGovbr:
    """Cliente da API de Assinatura Eletrônica do gov.br (homologação ou produção)."""

    def __init__(self, cfg):
        self.cfg = cfg

    def url_autorizacao(self, redirect_uri, state, nonce):
        return self.cfg.assinatura_oauth_url + '/authorize?' + urlencode({
            'response_type': 'code', 'client_id': self.cfg.assinatura_client_id, 'scope': ESCOPO,
            'redirect_uri': redirect_uri, 'state': state, 'nonce': nonce})

    def token(self, codigo, redirect_uri):
        try:
            r = requests.post(self.cfg.assinatura_oauth_url + '/token', timeout=15, data={
                'code': codigo, 'client_id': self.cfg.assinatura_client_id, 'grant_type': 'authorization_code',
                'client_secret': self.cfg.assinatura_client_secret, 'redirect_uri': redirect_uri})
            r.raise_for_status()
            return r.json()['access_token']
        except (requests.RequestException, ValueError, KeyError) as erro:
            log.warning('Assinatura gov.br: falha ao obter o token: %s', erro)
            raise FalhaApi('Não foi possível concluir a autorização no gov.br. Tente assinar de novo.') from erro

    def assinar_hash(self, token, digest, titular=''):
        try:
            r = requests.post(self.cfg.assinatura_api_url + '/assinarPKCS7', timeout=30,
                              headers={'Authorization': 'Bearer ' + token},
                              json={'hashBase64': base64.b64encode(digest).decode()})
        except requests.RequestException as erro:
            log.warning('Assinatura gov.br: API indisponível: %s', erro)
            raise FalhaApi('A API de assinatura do gov.br não respondeu. Tente de novo em instantes.') from erro
        if r.status_code == 403:
            log.info('Assinatura gov.br recusada (403): %s', r.text[:200])
            raise FalhaApi('O gov.br não liberou a assinatura: ela exige conta gov.br nível prata ou ouro '
                           '(eleve o nível em confiabilidades.acesso.gov.br) e CPF regular.')
        if not r.ok:
            log.warning('Assinatura gov.br: API respondeu %s: %s', r.status_code, r.text[:200])
            raise FalhaApi('A API de assinatura do gov.br recusou o pedido. Tente assinar de novo.')
        return ler_cms(r.content)

    def acs_confiaveis(self, cms_der):
        """Em homologação, as ACs de teste do ITI não estão em app/certificados: confia nas que vieram no
        CMS, que chegou direto da API do ITI por HTTPS. Em produção, só valem as de app/certificados."""
        return acs_do_cms(cms_der) if self.cfg.assinatura_ambiente == 'homologacao' else []


class ApiSimulada:
    """Só para desenvolvimento (GOVBR_ASSINATURA_AMBIENTE=simulada): sem ir ao gov.br, assina com um
    certificado 'NOME:00000000000' emitido por uma AC de teste criada na memória do processo."""

    _ac = None

    def __init__(self, cfg):
        self.cfg = cfg

    def url_autorizacao(self, redirect_uri, state, nonce):
        return redirect_uri + '?' + urlencode({'code': 'simulado', 'state': state})

    def token(self, codigo, redirect_uri):
        return 'simulado'

    @classmethod
    def ac(cls):
        if cls._ac is None:
            cls._ac = _certificado('AC Simulada de Desenvolvimento', ac=True)
        return cls._ac

    def assinar_hash(self, token, digest, titular=''):
        from asn1crypto import keys, x509 as asn1_x509
        from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
        from pyhanko.sign import signers
        from pyhanko_certvalidator.registry import SimpleCertificateStore
        ac_cert, _ = self.ac()
        cert, chave = _certificado(f'{(titular or "PROFESSOR SIMULADO").upper()}:00000000000', emissor=self.ac())
        signer = signers.SimpleSigner(
            signing_cert=asn1_x509.Certificate.load(cert.public_bytes(Encoding.DER)),
            signing_key=keys.PrivateKeyInfo.load(chave.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())),
            cert_registry=SimpleCertificateStore.from_certs([asn1_x509.Certificate.load(ac_cert.public_bytes(Encoding.DER))]))
        return asyncio.run(signer.async_sign(digest, 'sha256')).dump()

    def acs_confiaveis(self, cms_der):
        return acs_do_cms(cms_der)


def _certificado(nome, ac=False, emissor=None):
    """(certificado, chave) de teste: uma AC autoassinada ou um certificado de assinatura emitido por ela."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    chave = ec.generate_private_key(ec.SECP256R1())
    sujeito = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, nome)])
    emissor_cert, emissor_chave = emissor or (None, chave)
    agora = datetime.now(timezone.utc)
    construtor = (x509.CertificateBuilder().subject_name(sujeito)
                  .issuer_name(emissor_cert.subject if emissor_cert else sujeito).public_key(chave.public_key())
                  .serial_number(x509.random_serial_number()).not_valid_before(agora - timedelta(hours=1))
                  .not_valid_after(agora + timedelta(days=365 if ac else 1))
                  .add_extension(x509.BasicConstraints(ca=ac, path_length=None), critical=True)
                  .add_extension(x509.KeyUsage(digital_signature=not ac, content_commitment=not ac,
                                               key_encipherment=False, data_encipherment=False, key_agreement=False,
                                               key_cert_sign=ac, crl_sign=ac, encipher_only=False,
                                               decipher_only=False), critical=True))
    return construtor.sign(emissor_chave, hashes.SHA256()), chave


def cliente(cfg):
    """O cliente da API conforme o ambiente (None se a assinatura pela API não estiver configurada)."""
    if not cfg.assinatura_api_ativa:
        if cfg.assinatura_ambiente == 'simulada':
            log.error('GOVBR_ASSINATURA_AMBIENTE=simulada ignorado: só vale com LOGIN_SIMULADO=1 (desenvolvimento)')
        return None
    return ApiSimulada(cfg) if cfg.assinatura_ambiente == 'simulada' else ApiGovbr(cfg)
