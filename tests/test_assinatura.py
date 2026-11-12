import pytest

from app.servicos import assinatura
from app.servicos.assinatura import AssinaturaInvalida, mesma_pessoa, verificar
from conftest import PDF_COM_TEXTO, assinar, gerar_ac, gerar_pdf

AC = gerar_ac()


@pytest.fixture
def raizes(tmp_path):
    from conftest import salvar_ac
    return assinatura.carregar_raizes(salvar_ac(AC, tmp_path / 'certificados'))


def test_aceita_pdf_assinado_por_ac_confiavel(raizes):
    dados = verificar(assinar(PDF_COM_TEXTO, AC), PDF_COM_TEXTO, raizes)
    assert dados['signatario'] == 'FULANO DE TAL' and dados['cpf'] == '12345678900'
    assert dados['assinado_em']


def test_recusa_sem_assinatura_ac_desconhecida_e_sem_configuracao(raizes):
    with pytest.raises(AssinaturaInvalida, match='não tem assinatura'):
        verificar(PDF_COM_TEXTO, PDF_COM_TEXTO, raizes)
    with pytest.raises(AssinaturaInvalida, match='não é do gov.br'):
        verificar(assinar(PDF_COM_TEXTO, gerar_ac('AC Falsa do Governo Federal')), PDF_COM_TEXTO, raizes)
    with pytest.raises(AssinaturaInvalida, match='não foi configurada'):
        verificar(assinar(PDF_COM_TEXTO, AC), PDF_COM_TEXTO, [])
    with pytest.raises(AssinaturaInvalida, match='não pôde ser aberto'):
        verificar(b'%PDF-1.4 lixo', PDF_COM_TEXTO, raizes)


def test_recusa_outro_plano_e_pdf_alterado_depois_de_assinar(raizes):
    outro = gerar_pdf(['Outro plano de ensino, de outra disciplina.'])
    with pytest.raises(AssinaturaInvalida, match='não é o plano aprovado'):
        verificar(assinar(outro, AC), PDF_COM_TEXTO, raizes)
    assinado = assinar(PDF_COM_TEXTO, AC)
    adulterado = assinado.replace(b'numero 3', b'numero 9')
    with pytest.raises(AssinaturaInvalida, match='alterado depois de assinado'):
        verificar(adulterado, PDF_COM_TEXTO, raizes)


def test_mesmo_texto_regravado_conta_como_o_mesmo_plano():
    linhas = ['Linha de texto numero {} do plano de ensino de teste.'.format(i) for i in range(8)]
    regravado = gerar_pdf(linhas + ['Documento assinado digitalmente FULANO DE TAL Data: 11/11/2026'])
    assert assinatura.mesmo_conteudo(regravado, PDF_COM_TEXTO)
    assert not assinatura.mesmo_conteudo(gerar_pdf(linhas[:-1]), PDF_COM_TEXTO)  # faltou uma linha
    assert not assinatura.mesmo_conteudo(gerar_pdf(linhas + ['extra ' * 70]), PDF_COM_TEXTO)


def test_nomes():
    assert mesma_pessoa('FABRÍCIO BIZOTTO DA SILVA', 'Fabricio Bizotto')
    assert mesma_pessoa('MARIA DE SOUZA', 'Maria Souza')
    assert not mesma_pessoa('MARIA DE SOUZA', 'Maria Oliveira')
    assert not mesma_pessoa('MARIA SOUZA', 'Maria')


def test_le_a_cadeia_em_pacote_p7b(tmp_path):
    from asn1crypto import cms, x509
    from cryptography.hazmat.primitives.serialization import Encoding
    raiz = x509.Certificate.load(AC[0].public_bytes(Encoding.DER))
    pacote = cms.ContentInfo({'content_type': 'signed_data', 'content': cms.SignedData({
        'version': 'v1', 'digest_algorithms': [], 'encap_content_info': {'content_type': 'data'},
        'certificates': [raiz], 'signer_infos': []})})
    (tmp_path / 'Cadeia.p7b').write_bytes(pacote.dump())
    raizes = assinatura.carregar_raizes(str(tmp_path))
    assert [r.sha256 for r in raizes] == [raiz.sha256]
    assert verificar(assinar(PDF_COM_TEXTO, AC), PDF_COM_TEXTO, raizes)['signatario'] == 'FULANO DE TAL'


# Assinatura pela API do gov.br: o PDF montado com o CMS devolvido pela API ---------------------------------

def test_pdf_assinado_pela_api_passa_na_conferencia():
    from app.servicos import assinatura_api
    api = assinatura_api.ApiSimulada(None)
    acs = []

    def assinar_hash(digest):
        cms_der = api.assinar_hash('token', digest, 'Fulano de Tal')
        acs.extend(api.acs_confiaveis(cms_der))
        return cms_der

    assinado = assinatura_api.assinar_pdf(PDF_COM_TEXTO, assinar_hash)
    assert assinado.startswith(PDF_COM_TEXTO)  # acrescentada ao final: o original fica intacto
    dados = verificar(assinado, PDF_COM_TEXTO, acs)
    assert dados['signatario'] == 'FULANO DE TAL' and dados['cpf'] == '00000000000'
    from asn1crypto import x509
    from cryptography.hazmat.primitives.serialization import Encoding
    outra_ac = [x509.Certificate.load(gerar_ac()[0].public_bytes(Encoding.DER))]
    with pytest.raises(AssinaturaInvalida, match='não é do gov.br'):  # sem a AC de teste, não vale
        verificar(assinado, PDF_COM_TEXTO, outra_ac)


def test_le_o_cms_em_binario_ou_base64():
    import base64
    from app.servicos import assinatura_api
    cms_der = assinatura_api.ApiSimulada(None).assinar_hash('t', b'\x00' * 32, 'X')
    assert assinatura_api.ler_cms(cms_der) == cms_der
    assert assinatura_api.ler_cms(base64.b64encode(cms_der)) == cms_der
    with pytest.raises(assinatura_api.FalhaApi):
        assinatura_api.ler_cms(b'<html>erro</html>')
