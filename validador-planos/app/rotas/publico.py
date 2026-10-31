from flask import Blueprint, current_app, render_template, request

from ..paginas import inicio
from .comum import email, json_, servicos, texto

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
