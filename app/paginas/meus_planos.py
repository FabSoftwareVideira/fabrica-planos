# Página "Meus planos" (templates/meus_planos.html).


def contexto(email='', max_mb=10, assinatura_api=False):
    """`assinatura_api`: se o botão "Assinar com gov.br" (API de assinatura) aparece nos planos aprovados."""
    return {'email': email, 'max_mb': int(max_mb), 'assinatura_api': assinatura_api}
