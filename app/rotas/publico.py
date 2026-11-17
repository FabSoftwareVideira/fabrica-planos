from urllib.parse import quote

from flask import Blueprint, current_app, redirect, render_template, request
from werkzeug.exceptions import HTTPException

from ..paginas import erros, inicio
from . import govbr
from .comum import eh_admin, email, json_, mesma_origem, nome, servicos, texto

# Rotas sem login e a barreira de login das demais.
bp = Blueprint('publico', __name__)

PUBLICAS = {'/', '/health', '/entrar', '/privacidade'}
# CSS, JS, fontes e ícones: a página inicial (pública) também usa, e nada ali é sigiloso. Transparência: os
# planos assinados, para qualquer pessoa (rotas/transparencia.py)
PREFIXOS_PUBLICOS = ('/static/', '/transparencia')
# Login com gov.br (ida, volta e saída) e a verificação de sessão consultada pelo Caddy (rotas/govbr.py)
PREFIXOS_LOGIN = ('/auth/',)


# Com o login simulado (desenvolvimento), a página de login e a saída também são públicas
PREFIXOS_LOGIN_SIMULADO = ('/dev/', '/oauth2/')

# Métodos que não alteram nada; os demais só são aceitos vindos de páginas desta aplicação
METODOS_SEGUROS = {'GET', 'HEAD', 'OPTIONS'}

# Cabeçalhos de segurança de todas as respostas. As páginas ainda têm scripts e atributos de evento
# embutidos (onclick, onchange), por isso 'unsafe-inline' nos scripts; o resto (CSS, JS, fontes, imagens,
# fetch) só pode vir da própria aplicação, e nenhum outro site pode exibi-la num iframe.
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; object-src 'none'; "
       "base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
CABECALHOS_SEGURANCA = {
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'same-origin',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=(), usb=()',
}


@bp.before_app_request
def exigir_login():
    # Envio, exclusão, validação e revisão só a partir das páginas do próprio sistema: um site de fora
    # não consegue disparar essas ações com o login de quem o visita (o navegador manda Origin nelas).
    if request.method not in METODOS_SEGUROS and not mesma_origem():
        return texto('Origem inválida.', 403)
    # O proxy só deixa passar quem fez login; isto barra quem chegar ao app sem passar por ele.
    cfg = servicos().cfg
    if cfg.login_simulado and request.path.startswith(PREFIXOS_LOGIN_SIMULADO):
        return None
    if request.path.startswith(PREFIXOS_LOGIN):
        return None
    if (cfg.exigir_login and not email() and request.path not in PUBLICAS
            and not request.path.startswith(PREFIXOS_PUBLICOS)):
        if cfg.login_simulado and request.headers.get('Sec-Fetch-Mode') == 'navigate':
            return redirect('/dev/login?rd=' + quote(request.full_path.rstrip('?')), 303)  # no lugar do Google
        return texto('Login necessário.', 401)
    usuario = email()
    if not usuario or request.path.startswith(PREFIXOS_PUBLICOS):
        return None
    # Cadastra no primeiro acesso e guarda o nome; quem foi desativado perde o acesso
    # (administradores de ADMIN_EMAILS nunca são barrados, para ninguém trancar o sistema).
    try:
        cadastro = servicos().usuarios.registrar_acesso(usuario, nome())
    except Exception:  # o cadastro não pode derrubar o sistema
        current_app.logger.exception('Falha ao registrar o acesso de %s', usuario)
        return None
    if not cadastro['ativo'] and not eh_admin() and request.path not in PUBLICAS:
        if request.headers.get('Sec-Fetch-Mode') == 'navigate' or 'text/html' in request.headers.get('Accept', ''):
            return render_template('acesso_desativado.html', email=usuario), 403
        return json_({'erro': 'Seu acesso foi desativado por um administrador'}, 403)


def _csp():
    """A página inicial pode carregar o /logout do gov.br num iframe oculto (saída em segundo plano)."""
    cfg = servicos().cfg
    if request.path == '/' and cfg.govbr_ativo:
        return CSP + '; frame-src ' + cfg.govbr_url.split('/', 3)[0] + '//' + cfg.govbr_url.split('/', 3)[2]
    return CSP


@bp.after_app_request
def cabecalhos_seguranca(resp):
    for nome_, valor in CABECALHOS_SEGURANCA.items():
        resp.headers.setdefault(nome_, valor)
    # Só nas páginas: num PDF a CSP atrapalharia o visualizador do navegador
    if resp.mimetype == 'text/html':
        resp.headers.setdefault('Content-Security-Policy', _csp())
    return resp


@bp.app_errorhandler(HTTPException)
def erro_http(erro):
    """Erros HTTP (404, 405, 413...) e os inesperados (500, já registrados no log pelo Flask): a página de
    erro para quem navega; JSON com `erro` para as chamadas das páginas (fetch). Redirecionamentos internos
    do Flask (3xx) passam como estão."""
    status = erro.code or 500
    if status < 400:
        return erro
    mensagem = ''
    if status == 413:
        limite = current_app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)
        mensagem = f'Envio maior que {limite} MB; mande menos arquivos por vez'
    if erros.quer_pagina():
        return erros.pagina(status, mensagem)
    return json_({'erro': mensagem or erros.dados(status)[0]}, status)


def ja_logado():
    """Nas páginas públicas (o Caddy não confere o login nelas): quem tem a sessão gov.br do app ou o cookie
    do Google vê "Acessar" no cabeçalho. Se o cookie do Google tiver expirado, o painel pede login."""
    return bool(email() or govbr.sessao() or any(n.startswith(govbr.COOKIE_GOOGLE) for n in request.cookies))


@bp.get('/')
def raiz():
    """Página inicial pública, com o botão de login."""
    cfg = servicos().cfg
    rd = govbr.destino(request.args.get('rd', ''))
    # Depois do Sair de uma sessão gov.br: encerra também a do gov.br, num iframe oculto (rotas/govbr.py: sair)
    sair_govbr = cfg.govbr_url + '/logout' if cfg.govbr_ativo and request.args.get('saiu') == 'govbr' else ''
    return render_template('inicio.html', sair_govbr=sair_govbr, ja_logado=not sair_govbr and ja_logado(),
                           **inicio.contexto(rd, cfg.govbr_ativo, cfg.login_google or cfg.login_simulado))


@bp.get('/privacidade')
def privacidade():
    """Aviso de privacidade (LGPD) e de cookies, público."""
    return render_template('privacidade.html')


@bp.get('/health')
def health():
    return json_({'status': 'ok'})
