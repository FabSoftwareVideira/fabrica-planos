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


# Assinaturas digitais de teste: uma AC raiz própria (no lugar da do gov.br) e PDFs assinados por ela.

def gerar_ac(nome='AC Raiz de Teste'):
    """(certificado, chave) de uma AC raiz autoassinada."""
    from datetime import datetime, timedelta, timezone

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    chave = ec.generate_private_key(ec.SECP256R1())
    sujeito = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, nome)])
    agora = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(sujeito).issuer_name(sujeito).public_key(chave.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(agora - timedelta(days=1))
            .not_valid_after(agora + timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=True,
                                         crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
            .sign(chave, hashes.SHA256()))
    return cert, chave


def salvar_ac(ac, pasta):
    from cryptography.hazmat.primitives.serialization import Encoding
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / 'raiz.crt').write_bytes(ac[0].public_bytes(Encoding.PEM))
    return str(pasta)


def assinar(pdf, ac, titular='FULANO DE TAL:12345678900'):
    """PDF assinado (anexado ao final, como faz o assinador do gov.br) com um certificado emitido pela `ac`."""
    import io
    from datetime import datetime, timedelta, timezone

    from asn1crypto import keys, x509 as asn1_x509
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
    from cryptography.x509.oid import NameOID
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import signers
    from pyhanko_certvalidator.registry import SimpleCertificateStore

    ac_cert, ac_chave = ac
    chave = ec.generate_private_key(ec.SECP256R1())
    agora = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, titular)]))
            .issuer_name(ac_cert.subject).public_key(chave.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(agora - timedelta(hours=1))
            .not_valid_after(agora + timedelta(days=1))
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=True, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .sign(ac_chave, hashes.SHA256()))
    signer = signers.SimpleSigner(
        signing_cert=asn1_x509.Certificate.load(cert.public_bytes(Encoding.DER)),
        signing_key=keys.PrivateKeyInfo.load(chave.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())),
        cert_registry=SimpleCertificateStore.from_certs([asn1_x509.Certificate.load(ac_cert.public_bytes(Encoding.DER))]))
    saida = signers.sign_pdf(IncrementalPdfFileWriter(io.BytesIO(pdf), strict=False),
                             signers.PdfSignatureMetadata(field_name='Assinatura1'), signer=signer)
    return saida.getvalue()
