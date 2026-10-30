import re

import pdfplumber

# O SIGAA monta o plano como tabela de duas colunas (rótulo | valor) e centraliza o rótulo
# na vertical. Lido linha a linha, o rótulo cai no meio do valor ("GERAL: ... Objetivos:
# ESPECÍFICOS: ..."), e a separação por tópicos corta a seção no lugar errado. Por isso o
# texto é remontado a partir das palavras, levando cada rótulo para o início do seu valor.

COLUNA_VALOR_X = 160  # palavras com x0 a partir daqui estão na coluna de valores
TOLERANCIA_LINHA = 3  # diferença máxima de "top" (pt) entre palavras da mesma linha

# Distância horizontal (pt) entre letras abaixo da qual elas formam uma só palavra. Alguns PDFs
# justificam o texto só pela posição, sem caracteres de espaço e com vãos estreitos: com o padrão (3)
# saem palavras grudadas ("ConteúdoProgramático:"). Nessas páginas usa-se a tolerância menor; nas
# demais não, porque ela parte palavras de linhas com letras espaçadas ("S p r i n g").
X_TOLERANCIA = 3
X_TOLERANCIA_JUSTA = 1.5
LETRAS_GRUDADAS = re.compile(r'[^\W\d_]{20,}')
MIN_GRUDADAS = 3  # palavras com 20+ letras seguidas na página para trocar de tolerância


def _grudada(texto):
    trecho = LETRAS_GRUDADAS.search(texto)
    return bool(trecho) and trecho.group(0).lower() != 'interdisciplinaridade'


def _palavras(pagina):
    palavras = pagina.extract_words(x_tolerance=X_TOLERANCIA)
    grudadas = sum(1 for p in palavras if _grudada(p['text']))
    if grudadas >= MIN_GRUDADAS:
        return pagina.extract_words(x_tolerance=X_TOLERANCIA_JUSTA)
    return palavras

ROTULO = re.compile(
    r'^(Ementa|Metodologia|Procedimentos\s+de\s+Avalia[çc][ãa]o(\s+da\s+Aprendizagem)?|'
    r'Hor[áa]rio\s+de\s+Atendimento|Objetivos?(\s+Gerais?)?|Conte[úu]do\s+Program[áa]tico)\s*:$',
    re.IGNORECASE,
)


def _agrupar_linhas(palavras):
    linhas = []
    for palavra in sorted(palavras, key=lambda p: (p['top'], p['x0'])):
        if linhas and abs(palavra['top'] - linhas[-1]['top']) <= TOLERANCIA_LINHA:
            linhas[-1]['palavras'].append(palavra)
        else:
            linhas.append({'top': palavra['top'], 'bottom': palavra['bottom'], 'palavras': [palavra]})
    for linha in linhas:
        linha['palavras'].sort(key=lambda p: p['x0'])
        linha['bottom'] = max(p['bottom'] for p in linha['palavras'])
        linha['rotulo'] = ' '.join(p['text'] for p in linha['palavras'] if p['x0'] < COLUNA_VALOR_X)
        linha['valor'] = ' '.join(p['text'] for p in linha['palavras'] if p['x0'] >= COLUNA_VALOR_X)
    return linhas


def _linha_da_tabela(linha, faixas):
    centro = (linha['top'] + linha['bottom']) / 2
    for i, (topo, base) in enumerate(faixas):
        if topo <= centro <= base:
            return i
    return None


def _rotulos(linhas):
    """Índices (início, fim) de rótulos conhecidos na coluna esquerda; um rótulo pode ocupar duas linhas."""
    encontrados = []
    i = 0
    while i < len(linhas):
        texto = linhas[i]['rotulo']
        if texto and not ROTULO.match(texto) and i + 1 < len(linhas) and linhas[i + 1]['rotulo']:
            junto = texto + ' ' + linhas[i + 1]['rotulo']
            if ROTULO.match(junto):
                encontrados.append((i, i + 1, junto))
                i += 2
                continue
        if texto and ROTULO.match(texto):
            encontrados.append((i, i, texto))
        i += 1
    return encontrados


def _texto_pagina(pagina):
    linhas = _agrupar_linhas(_palavras(pagina))
    faixas = [(r.bbox[1], r.bbox[3]) for t in pagina.find_tables() for r in t.rows]
    for linha in linhas:
        linha['faixa'] = _linha_da_tabela(linha, faixas)

    originais = [linha['rotulo'] for linha in linhas]

    def so_valor(k, faixa):
        return not originais[k] and linhas[k]['valor'] and linhas[k]['faixa'] == faixa

    for inicio, fim, texto in _rotulos(linhas):
        faixa = linhas[inicio]['faixa']
        limite = float('-inf')
        if faixa is None:
            # Sem bordas de tabela, o bloco é estimado pela simetria: o rótulo fica no meio do valor.
            ultima = fim
            while ultima + 1 < len(linhas) and so_valor(ultima + 1, faixa):
                ultima += 1
            centro = (linhas[inicio]['top'] + linhas[fim]['bottom']) / 2
            limite = 2 * centro - linhas[ultima]['bottom'] - 2 * TOLERANCIA_LINHA
        # Sobe pelas linhas que só têm valor e pertencem à mesma linha da tabela.
        primeira = inicio
        while primeira > 0 and so_valor(primeira - 1, faixa) and linhas[primeira - 1]['top'] >= limite:
            primeira -= 1
        for k in range(inicio, fim + 1):
            linhas[k]['rotulo'] = ''
        linhas[primeira]['rotulo'] = texto

    saida = []
    for linha in linhas:
        texto = ' '.join(parte for parte in (linha['rotulo'], linha['valor']) if parte)
        if texto:
            saida.append(texto)
    return '\n'.join(saida)


MIN_CARACTERES = 200  # abaixo disso o PDF é tratado como digitalizado (só imagem)


class PdfIlegivel(Exception):
    """O PDF não abre ou não tem camada de texto (digitalizado, precisa de OCR)."""


def extrair_texto(caminho):
    try:
        with pdfplumber.open(caminho) as pdf:
            texto = '\n'.join(_texto_pagina(pagina) for pagina in pdf.pages)
    except Exception as erro:
        raise PdfIlegivel(f'O PDF não pôde ser aberto (corrompido ou protegido por senha): {erro}') from erro
    if len(''.join(texto.split())) < MIN_CARACTERES:
        raise PdfIlegivel(
            'O PDF não tem texto selecionável: é uma imagem digitalizada e precisa passar por OCR antes da validação.'
        )
    return texto
