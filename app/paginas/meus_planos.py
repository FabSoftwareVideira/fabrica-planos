from datetime import date

# Página "Meus planos" (templates/meus_planos.html): as disciplinas do professor separadas por período, com o
# período letivo atual e o próximo primeiro.


def periodos_em_destaque(hoje=None):
    """{período: rótulo} do atual e do próximo, nos cursos semestrais ('2026.2', '2027.1') e anuais ('2026',
    '2027'). O 1º semestre vai de janeiro a junho."""
    hoje = hoje or date.today()
    if hoje.month <= 6:
        atual, proximo = f'{hoje.year}.1', f'{hoje.year}.2'
    else:
        atual, proximo = f'{hoje.year}.2', f'{hoje.year + 1}.1'
    return {atual: 'Atual', str(hoje.year): 'Atual', proximo: 'Próximo', str(hoje.year + 1): 'Próximo'}


def contexto(email='', max_mb=10, assinatura_api=False, hoje=None, homologacao=False):
    """`assinatura_api`: se o botão "Assinar com gov.br" (API de assinatura) aparece nos planos aprovados;
    `homologacao`: se ela usa o ambiente de testes do gov.br (o botão avisa que a assinatura é de teste)."""
    return {'email': email, 'max_mb': int(max_mb), 'assinatura_api': assinatura_api,
            'assinatura_homologacao': bool(assinatura_api and homologacao), 'destaques': periodos_em_destaque(hoje)}
