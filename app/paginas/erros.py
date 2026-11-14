from flask import render_template, request

# Páginas de erro (templates/erro.html), no padrão do Design System gov.br. Só para quem navega (o navegador
# pede uma página HTML); as chamadas das páginas (fetch) continuam recebendo JSON ou texto.

# código: (título, explicação, ícone, tipo da mensagem do DS)
ERROS = {
    400: ('Pedido inválido', 'O endereço ou os dados enviados não estão no formato esperado.', 'exclamation-circle', 'warning'),
    401: ('Login necessário', 'Entre com a sua conta institucional para abrir esta página.', 'user-lock', 'warning'),
    403: ('Acesso negado', 'Você não tem permissão para abrir esta página ou fazer esta ação.', 'ban', 'warning'),
    404: ('Página não encontrada', 'O endereço não existe, ou o que você procura foi removido ou mudou de lugar.',
          'search', 'info'),
    405: ('Ação não permitida', 'Esta página não aceita esse tipo de pedido.', 'ban', 'warning'),
    409: ('Ação em andamento', 'Há uma validação ou outra ação em andamento. Tente de novo em instantes.',
          'hourglass-half', 'info'),
    413: ('Arquivo grande demais', 'O envio passou do tamanho máximo aceito.', 'file-upload', 'warning'),
    500: ('Erro interno', 'Algo deu errado do nosso lado. O erro foi registrado; tente de novo em instantes. Se '
          'continuar, avise a coordenação ou a Fábrica de Software do IFC Videira.', 'bug', 'danger'),
    502: ('Serviço indisponível', 'Um serviço de que esta página depende não respondeu. Tente de novo em instantes.',
          'plug', 'danger'),
    503: ('Serviço indisponível', 'O sistema está temporariamente indisponível. Tente de novo em instantes.',
          'tools', 'danger'),
}


def quer_pagina():
    """O navegador está abrindo uma página (e não uma chamada fetch, que espera JSON ou texto)."""
    if request.method not in ('GET', 'HEAD'):
        return False
    aceita = request.accept_mimetypes
    return aceita.accept_html and aceita['text/html'] >= aceita['application/json']


def dados(status):
    """(título, explicação, ícone, tipo) do código; os desconhecidos usam o da família (4xx ou 5xx)."""
    if status in ERROS:
        return ERROS[status]
    return ERROS[500] if status >= 500 else ERROS[400]


def pagina(status, detalhe=''):
    """A página de erro com o código e, se houver, o detalhe (a mensagem da rota que recusou o pedido)."""
    titulo, explicacao, icone, tipo = dados(status)
    return render_template('erro.html', codigo=status, titulo=titulo, explicacao=explicacao, icone=icone,
                           tipo=tipo, detalhe=detalhe if detalhe and detalhe.rstrip('.') != titulo else ''), status
