from app.extrator import _texto_pagina
from app.secoes import analisar_texto


def _palavra(texto, x0, top):
    return {'text': texto, 'x0': x0, 'x1': x0 + 6 * len(texto), 'top': top, 'bottom': top + 8}


class PaginaFalsa:
    def __init__(self, palavras, palavras_justas=None):
        self.palavras = palavras
        self.palavras_justas = palavras_justas  # resultado com a tolerância menor, se diferente

    def extract_words(self, x_tolerance=3):
        if x_tolerance < 3 and self.palavras_justas is not None:
            return self.palavras_justas
        return self.palavras

    def find_tables(self):
        return []


def _linha(texto, x0, top):
    palavras, x = [], x0
    for parte in texto.split():
        palavras.append(_palavra(parte, x, top))
        x += 6 * len(parte) + 4
    return palavras


def test_rotulo_centralizado_vai_para_o_inicio_do_valor():
    # Layout do SIGAA: o rótulo "Objetivos:" fica na altura do meio do valor.
    pagina = PaginaFalsa(
        _linha('Programa', 52, 400)
        + _linha('GERAL:', 166, 417)
        + _linha('Desenvolver um projeto completo.', 166, 425)
        + _linha('Objetivos:', 52, 445)
        + _linha('ESPECÍFICOS:', 166, 445)
        + _linha('- Conhecer SQL avançado.', 166, 455)
        + _linha('- Praticar tecnologias.', 166, 465)
        + _linha('- Comparar SGBDs.', 166, 473)
        + _linha('Conteúdo Programático:', 52, 501)
        + _linha('- Indexação', 166, 501)
    )
    texto = _texto_pagina(pagina)
    assert texto.splitlines()[:3] == ['Programa', 'Objetivos: GERAL:', 'Desenvolver um projeto completo.']

    sec = analisar_texto(texto)
    assert sec['objetivos_geral'] == 'Desenvolver um projeto completo.'
    assert sec['objetivos_especificos'].splitlines() == [
        '- Conhecer SQL avançado.', '- Praticar tecnologias.', '- Comparar SGBDs.',
    ]
    assert sec['conteudo_programatico'] == '- Indexação'


def test_rotulo_em_duas_linhas():
    pagina = PaginaFalsa(
        _linha('Metodologia de Ensino', 52, 20)
        + _linha('A média final', 166, 237)
        + _linha('Procedimentos de Avaliação', 52, 247)
        + _linha('T1 e T2', 166, 247)
        + _linha('da Aprendizagem:', 52, 257)
        + _linha('P1 projeto', 166, 257)
        + _linha('M média', 166, 267)
    )
    linhas = _texto_pagina(pagina).splitlines()
    assert linhas[1] == 'Procedimentos de Avaliação da Aprendizagem: A média final'
    assert linhas[2:] == ['T1 e T2', 'P1 projeto', 'M média']


def test_pagina_com_palavras_grudadas_usa_tolerancia_menor():
    grudada = PaginaFalsa(
        _linha('MetodologiadeEnsinoeAvaliação', 52, 20)
        + _linha('Metodologia: Odesenvolvimentodosconteúdos seráabordadoaosdiscentes', 52, 40),
        palavras_justas=_linha('Metodologia de Ensino e Avaliação', 52, 20)
        + _linha('Metodologia:', 52, 40) + _linha('O desenvolvimento dos conteúdos', 166, 40),
    )
    assert _texto_pagina(grudada).splitlines() == [
        'Metodologia de Ensino e Avaliação', 'Metodologia: O desenvolvimento dos conteúdos',
    ]


def test_pagina_normal_mantem_tolerancia_padrao():
    # Interdisciplinaridade é uma palavra longa legítima e não conta como grudada.
    normal = PaginaFalsa(
        _linha('INTERDISCIPLINARIDADE: Spring Security', 166, 20),
        palavras_justas=_linha('S p r i n g', 166, 20),
    )
    assert _texto_pagina(normal) == 'INTERDISCIPLINARIDADE: Spring Security'


def test_extrair_texto_de_pdf_real_e_recusa_digitalizado(tmp_path):
    import pytest

    from app.extrator import PdfIlegivel, extrair_texto
    from conftest import PDF_COM_TEXTO, PDF_SEM_TEXTO

    bom = tmp_path / 'bom.pdf'
    bom.write_bytes(PDF_COM_TEXTO)
    assert 'Linha de texto numero 0' in extrair_texto(str(bom))

    scan = tmp_path / 'scan.pdf'
    scan.write_bytes(PDF_SEM_TEXTO)
    with pytest.raises(PdfIlegivel, match='OCR'):
        extrair_texto(str(scan))
