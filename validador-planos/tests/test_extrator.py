from app.extrator import _texto_pagina
from app.secoes import analisar_texto


def _palavra(texto, x0, top):
    return {'text': texto, 'x0': x0, 'x1': x0 + 6 * len(texto), 'top': top, 'bottom': top + 8}


class PaginaFalsa:
    def __init__(self, palavras):
        self.palavras = palavras

    def extract_words(self):
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
