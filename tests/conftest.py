def gerar_pdf(linhas=()):
    """PDF mínimo válido de uma página; sem linhas, a página não tem texto (como um digitalizado)."""
    conteudo = 'BT /F1 10 Tf 40 800 Td 12 TL\n' + ''.join(
        '(' + l.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)') + ") '\n" for l in linhas
    ) + 'ET'
    objetos = [
        '<< /Type /Catalog /Pages 2 0 R >>',
        '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R '
        '/Resources << /Font << /F1 5 0 R >> >> >>',
        f'<< /Length {len(conteudo)} >>\nstream\n{conteudo}\nendstream',
        '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    ]
    saida = b'%PDF-1.4\n'
    posicoes = []
    for i, obj in enumerate(objetos, start=1):
        posicoes.append(len(saida))
        saida += f'{i} 0 obj\n{obj}\nendobj\n'.encode('latin-1')
    inicio_xref = len(saida)
    saida += f'xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n'.encode()
    saida += ''.join(f'{p:010d} 00000 n \n' for p in posicoes).encode()
    saida += f'trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{inicio_xref}\n%%EOF\n'.encode()
    return saida


PDF_COM_TEXTO = gerar_pdf(['Linha de texto numero {} do plano de ensino de teste.'.format(i) for i in range(8)])
PDF_SEM_TEXTO = gerar_pdf()
