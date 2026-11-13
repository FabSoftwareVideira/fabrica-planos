from urllib.parse import quote

from flask import Blueprint, current_app, redirect, render_template, request

from ..paginas import inicio
from . import govbr
from .comum import eh_admin, email, json_, mesma_origem, nome, servicos, texto

# Rotas sem login e a barreira de login das demais.
bp = Blueprint('publico', __name__)

PUBLICAS = {'/', '/health', '/entrar', '/privacidade'}
# CSS, JS, fontes e ícones: a página inicial (pública) também usa, e nada ali é sigiloso
PREFIXOS_PUBLICOS = ('/static/',)
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


@bp.after_app_request
def cabecalhos_seguranca(resp):
    for nome_, valor in CABECALHOS_SEGURANCA.items():
        resp.headers.setdefault(nome_, valor)
    # Só nas páginas: num PDF a CSP atrapalharia o visualizador do navegador
    if resp.mimetype == 'text/html':
        resp.headers.setdefault('Content-Security-Policy', CSP)
    return resp


@bp.app_errorhandler(413)
def grande_demais(_erro):
    limite = current_app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)
    return json_({'erro': f'Envio maior que {limite} MB; mande menos arquivos por vez'}, 413)


@bp.get('/')
def raiz():
    """Página inicial pública, com o botão de login."""
    cfg = servicos().cfg
    rd = govbr.destino(request.args.get('rd', ''))
    saiu_govbr = cfg.govbr_url + '/logout' if cfg.govbr_ativo and request.args.get('saiu') == 'govbr' else ''
    return render_template('inicio.html', saiu_govbr=saiu_govbr,
                           **inicio.contexto(rd, cfg.govbr_ativo, cfg.login_google or cfg.login_simulado))


@bp.get('/privacidade')
def privacidade():
    """Aviso de privacidade (LGPD) e de cookies, público."""
    return render_template('privacidade.html')


@bp.get('/health')
def health():
    return json_({'status': 'ok'})
