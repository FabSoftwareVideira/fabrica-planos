# Página de administração (templates/administracao.html): gestão dos PDFs e validação.


def contexto(usuario='', max_mb=10):
    return {'usuario': usuario, 'admin': True, 'max_mb': int(max_mb)}
