# Página "Meus planos" (templates/meus_planos.html).


def contexto(email='', max_mb=10):
    return {'email': email, 'max_mb': int(max_mb)}
