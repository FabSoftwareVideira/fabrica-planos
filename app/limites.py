import ipaddress
import logging

from flask import current_app, request
from flask_limiter import Limiter

# Limite de requisições com o Flask-Limiter (https://flask-limiter.readthedocs.io). Armazenamento em memória
# (memory://), janela deslizante (moving-window): o gunicorn roda com um só worker (o validador já depende
# disso), então o contador do processo vale para o sistema todo. Com mais workers ou réplicas, troque
# storage_uri por um Redis.
#
# Política (os números ficam bem acima do uso normal; o objetivo é barrar robôs, loops e abusos, e cada envio
# de plano dispara a IA, o recurso mais caro do servidor):
#   login, vínculo e assinatura gov.br       20 por minuto por IP           LOGIN
#   envio de planos e disparo de validação   30 por hora por usuário        ENVIO
#   zip dos assinados (coordenação)          10 por hora por usuário        EXPORTACAO
#   PDFs da transparência                    60 por minuto por IP           PDF_PUBLICO
#   páginas públicas                         120 por minuto por IP          PUBLICO
#   demais rotas                             600 por minuto por usuário     (padrão)
# Fora da contagem: arquivos estáticos, o healthcheck, a conferência do login que o Caddy faz a cada pedido e
# os IPs de LIMITES_ISENTOS. Acima do limite: 429 com Retry-After (página de erro para quem navega).

log = logging.getLogger(__name__)

# IP de quem pediu, como o Caddy o determinou ({client_ip}, atrás do Traefik do Dokploy); vale porque só se
# chega ao app pelo Caddy (PROXY_SEGREDO)
CABECALHO_CLIENTE = 'X-Planos-Cliente'
ISENTAS = ('/static/', '/health', '/auth/verificar')


def ip_do_cliente():
    return (request.headers.get(CABECALHO_CLIENTE) or request.remote_addr or '-').strip()


def usuario_ou_ip():
    """Chave das regras por usuário: o e-mail de quem entrou (repassado pelo Caddy) ou, sem login, o IP."""
    email = (request.headers.get('X-Usuario-Email') or '').strip().lower()
    return 'usuario:' + email if email else 'ip:' + ip_do_cliente()


def isento(ip, redes):
    """O IP está numa das redes isentas do limite (Config.limites_isentos)."""
    if not redes:
        return False
    try:
        endereco = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(endereco in rede for rede in redes)


def _registrar(limite):
    log.warning('Limite de requisições (%s) atingido por %s em %s', limite.limit, limite.key, request.path)


limiter = Limiter(key_func=usuario_ou_ip, default_limits=['600 per minute'], storage_uri='memory://',
                  strategy='moving-window', headers_enabled=True, on_breach=_registrar)


@limiter.request_filter
def _fora_da_contagem():
    if request.path.startswith(ISENTAS):
        return True
    return isento(ip_do_cliente(), current_app.extensions['servicos'].cfg.limites_isentos)


# Limites dos grupos, para decorar as rotas (abaixo do @bp.get/@bp.post)
LOGIN = limiter.shared_limit('20 per minute', scope='login', key_func=ip_do_cliente)
ENVIO = limiter.shared_limit('30 per hour', scope='envio', key_func=usuario_ou_ip)
EXPORTACAO = limiter.shared_limit('10 per hour', scope='exportacao', key_func=usuario_ou_ip)
PDF_PUBLICO = limiter.shared_limit('60 per minute', scope='pdf_publico', key_func=ip_do_cliente)
PUBLICO = limiter.shared_limit('120 per minute', scope='publico', key_func=ip_do_cliente)


def iniciar(app, ativo=True):
    """Liga o limitador ao app (LIMITES=0 desliga). Cada app começa com a contagem zerada."""
    app.config['RATELIMIT_ENABLED'] = bool(ativo)
    limiter.init_app(app)
    limiter.reset()
