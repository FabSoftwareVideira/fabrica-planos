from flask import Blueprint, current_app, render_template, request

from ..paginas import inicio
from .comum import eh_admin, email, json_, nome, servicos, texto

# Rotas sem login e a barreira de login das demais.
bp = Blueprint('publico', __name__)

PUBLICAS = {'/', '/health'}
# CSS, JS, fontes e ícones: a página inicial (pública) também usa, e nada ali é sigiloso
PREFIXOS_PUBLICOS = ('/static/',)


@bp.before_app_request
def exigir_login():
    # O proxy só deixa passar quem fez login; isto barra quem chegar ao app sem passar por ele.
    if (servicos().cfg.exigir_login and not email() and request.path not in PUBLICAS
            and not request.path.startswith(PREFIXOS_PUBLICOS)):
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


@bp.app_errorhandler(413)
def grande_demais(_erro):
    limite = current_app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)
    return json_({'erro': f'Envio maior que {limite} MB; mande menos arquivos por vez'}, 413)


@bp.get('/')
def raiz():
    """Página inicial pública, com o botão de login."""
    return render_template('inicio.html', **inicio.contexto())


@bp.get('/health')
def health():
    return json_({'status': 'ok'})
