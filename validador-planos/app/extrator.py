import pdfplumber


def extrair_texto(caminho):
    partes = []
    with pdfplumber.open(caminho) as pdf:
        for pagina in pdf.pages:
            partes.append(pagina.extract_text() or '')
    return '\n'.join(partes)
