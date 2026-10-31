import base64
import json
from functools import wraps

from flask import Response, current_app, jsonify, request

# O que todas as rotas usam: os serviços da aplicação, quem está logado e as respostas padrão.


def servicos():
    """Serviços criados pela fábrica (app/fabrica.py) para esta aplicação."""
    return current_app.extensions['servicos']


def email():
    """E-mail de quem fez login, repassado pelo proxy; vazio sem login."""
    return (request.headers.get('X-Usuario-Email') or '').strip().lower()


def nome():
    """Nome de quem fez login, lido do ID token do Google que o oauth2-proxy repassa (via Caddy) em
    X-Usuario-Token; vazio se não vier. A assinatura não é conferida: o cabeçalho tem a mesma origem
    confiável do e-mail (o Caddy apaga o que vem do navegador e só ele o preenche)."""
    token = (request.headers.get('X-Usuario-Token') or '').strip()
    if token.lower().startswith('bearer '):
        token = token[7:].strip()
    partes = token.split('.')
    if len(partes) != 3:
        return ''
    try:
        carga = json.loads(base64.urlsafe_b64decode(partes[1] + '=' * (-len(partes[1]) % 4)))
    except (ValueError, TypeError):
        return ''
    if not isinstance(carga, dict) or str(carga.get('email', '')).strip().lower() not in ('', email()):
        return ''
    return ' '.join(str(carga.get('name') or '').split())[:120]


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


def ocupado():
    return json_({'status': 'ocupado', 'mensagem': 'Já existe uma validação em andamento'}, 409)
