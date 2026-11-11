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
