from functools import wraps

from flask import Response, current_app, jsonify, request

# O que todas as rotas usam: os serviços da aplicação, quem está logado e as respostas padrão.


def servicos():
    """Serviços criados pela fábrica (app/fabrica.py) para esta aplicação."""
    return current_app.extensions['servicos']


def email():
    """E-mail de quem fez login, repassado pelo proxy; vazio sem login."""
    return (request.headers.get('X-Usuario-Email') or '').strip().lower()


def eh_admin():
    cfg = servicos().cfg
    return not cfg.exigir_login or email() in cfg.admins


def somente_admin(rota):
    """Envio, exclusão e validação ficam com os e-mails de ADMIN_EMAILS; os demais só consultam."""
    @wraps(rota)
    def verificar(*args, **kwargs):
        if not eh_admin():
            return json_({'erro': 'Apenas administradores podem fazer isso'}, 403)
        return rota(*args, **kwargs)
    return verificar


def json_(obj, status=200):
    resp = jsonify(obj)
    resp.status_code = status
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp


def texto(mensagem, status):
    return Response(mensagem, status, mimetype='text/plain; charset=utf-8')


def html(conteudo):
    return Response(conteudo, mimetype='text/html; charset=utf-8')


def ocupado():
    return json_({'status': 'ocupado', 'mensagem': 'Já existe uma validação em andamento'}, 409)
