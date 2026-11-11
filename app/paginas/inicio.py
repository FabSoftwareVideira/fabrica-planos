from ..armazenamento.csvsaida import CAMPOS_COLUNA

# Página inicial pública (templates/inicio.html): textos (e ícones) dos passos e a legenda de status.

PASSOS = [
    ('Envio dos PDFs', 'Os planos de ensino exportados do SIGAA são enviados pela coordenação.', 'file-upload'),
    ('Leitura', 'O texto de cada PDF é extraído e separado nas seções do plano.', 'file-alt'),
    ('Avaliação', 'Uma IA executada no servidor do campus confere se cada seção está completa.', 'robot'),
    ('Resultado', 'O painel mostra a situação de cada plano, com relatório campo a campo.', 'chart-bar'),
]

LEGENDA = [('OK', '#22c55e', 'campo completo'), ('INCOMPLETO', '#eab308', 'falta informação'),
           ('AUSENTE', '#ef4444', 'campo vazio ou não encontrado')]


def contexto(rd='/dashboard', govbr=False, google=True):
    """`rd`: para onde voltar depois do login; `govbr`/`google`: quais botões de login mostrar."""
    from urllib.parse import quote
    return {'passos': PASSOS, 'campos': CAMPOS_COLUNA, 'legenda': LEGENDA,
            'url_govbr': '/auth/govbr/login?rd=' + quote(rd) if govbr else '',
            'url_google': '/oauth2/start?rd=' + quote(rd) if google else ''}
