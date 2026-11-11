"""Mostra a cadeia de certificados embutida nas assinaturas de um PDF e, com --salvar, grava os
certificados raiz (autoassinados) em app/certificados, para o app aceitar assinaturas dessa autoridade.

    python scripts/extrair_certificados.py plano-assinado.pdf
    python scripts/extrair_certificados.py plano-assinado.pdf --salvar

Antes de salvar, confira a impressão digital SHA-256 da raiz com uma fonte oficial (ITI/gov.br):
a raiz que vem dentro do PDF não prova nada sozinha.
"""
import hashlib
import os
import re
import sys

from pyhanko.pdf_utils.reader import PdfFileReader

PASTA = os.path.join(os.path.dirname(__file__), '..', 'app', 'certificados')


def _emissor_urls(cert):
    aia = cert.authority_information_access_value
    return [d['access_location'] for d in (aia.native if aia else []) if d['access_method'] == 'ca_issuers']


def main(caminho, salvar=False):
    with open(caminho, 'rb') as arq:
        assinaturas = PdfFileReader(arq, strict=False).embedded_regular_signatures
        if not assinaturas:
            sys.exit('O PDF não tem assinatura digital.')
        certificados = {}
        for assinatura in assinaturas:
            for cert in [assinatura.signer_cert, *assinatura.other_embedded_certs]:
                certificados[cert.sha256] = cert
    raizes = []
    for cert in certificados.values():
        raiz = cert.self_signed in ('maybe', 'yes')
        print(('RAIZ  ' if raiz else '      ') + cert.subject.human_friendly)
        print('      emitido por:', cert.issuer.human_friendly)
        print('      válido de', cert['tbs_certificate']['validity']['not_before'].native,
              'a', cert['tbs_certificate']['validity']['not_after'].native)
        for url in _emissor_urls(cert):  # onde a autoridade publica o certificado dela (AIA)
            print('      certificado do emissor em:', url)
        for url in cert.crl_distribution_points_value.native if cert.crl_distribution_points_value else []:
            for nome in url.get('distribution_point') or []:
                print('      lista de revogação:', nome)
        print('      SHA-256:', ':'.join(f'{b:02X}' for b in hashlib.sha256(cert.dump()).digest()), '\n')
        if raiz:
            raizes.append(cert)
    if not raizes:
        print('Nenhum certificado raiz veio embutido no PDF: obtenha o da autoridade emissora acima.')
    if salvar:
        for cert in raizes:
            nome = re.sub(r'[^A-Za-z0-9]+', '-', cert.subject.native.get('common_name', 'raiz')).strip('-')
            destino = os.path.join(PASTA, nome + '.crt')
            with open(destino, 'wb') as arq:
                arq.write(cert.dump())
            print('Salvo:', os.path.normpath(destino))


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], '--salvar' in sys.argv[2:])
