import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from urllib.parse import quote, urlencode

import requests
from flask import Blueprint, Response, make_response, redirect, render_template, request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from .comum import email, mesma_origem, servicos

# Login com a conta gov.br (Login Único, OpenID Connect com PKCE) e a verificação de sessão que o Caddy
# consulta a cada requisição (forward_auth em /auth/verificar).
#
# O app identifica as pessoas pelo e-mail institucional. O login gov.br é aceito quando o e-mail da conta
# gov.br é do domínio da instituição (EMAIL_DOMINIO) e está verificado, ou quando a conta gov.br (o CPF) já
# foi vinculada a um usuário: quem tem e-mail pessoal no gov.br entra uma vez pelo Google institucional e
# vincula (/conta/govbr/vincular). Do CPF o app guarda só um HMAC com SEGREDO_SESSAO (trocar o segredo
# desfaz os vínculos; o próximo login com e-mail institucional, ou um novo vínculo, os refaz). A sessão gov.br é um cookie
# assinado pelo próprio app; sem ela, /auth/verificar pergunta ao oauth2-proxy pela sessão do Google.
# Nos dois casos o Caddy recebe os mesmos cabeçalhos (X-Usuario-Email e o token com o nome), então o resto
# do app não sabe por onde a pessoa entrou.

log = logging.getLogger(__name__)
bp = Blueprint('govbr', __name__)

COOKIE_SESSAO = '_planos_govbr'
COOKIE_LOGIN = '_planos_govbr_login'  # state, nonce e verificador PKCE durante a ida ao gov.br
# Cookie da sessão do Google (OAUTH2_PROXY_COOKIE_NAME no docker-compose.yml; o oauth2-proxy o divide em
# _planos_login_0, _1... quando fica grande). Sem ele, não há por que perguntar ao oauth2-proxy.
COOKIE_GOOGLE = '_planos_login'
DURACAO_SESSAO = 12 * 3600
DURACAO_LOGIN = 10 * 60
ESCOPOS = 'openid email profile'


def _serializador(sal):
    return URLSafeTimedSerializer(servicos().cfg.segredo_sessao, salt=sal)


def destino(valor):
    """Só caminhos deste site (nada de //outro-site ou https://...)."""
    return valor if valor and valor.startswith('/') and not valor.startswith('//') and '\\' not in valor else '/dashboard'


def _redirect_uri():
    cfg = servicos().cfg
    return cfg.govbr_redirect_uri or request.url_root.rstrip('/') + '/auth/govbr/callback'


def _cookie(resp, nome, valor, duracao):
    resp.set_cookie(nome, valor, max_age=duracao, httponly=True, secure=servicos().cfg.cookie_seguro,
                    samesite='Lax', path='/')


def _recusa(motivo, status=403, vincular=False):
    return render_template('login_recusado.html', motivo=motivo, vincular=vincular), status


def _claims(id_token):
    """Carga do ID token. A assinatura não é conferida: o token veio direto do endpoint de token do gov.br,
    por HTTPS, na troca do código (OpenID Connect Core 3.1.3.7). Emissor, público, nonce e validade são."""
    try:
        carga = id_token.split('.')[1]
        return json.loads(base64.urlsafe_b64decode(carga + '=' * (-len(carga) % 4)))
    except (IndexError, ValueError, AttributeError):
        return None


def sessao():
    """{'email', 'nome'} da sessão gov.br do cookie, ou None."""
    cfg = servicos().cfg
    valor = request.cookies.get(COOKIE_SESSAO)
    if not cfg.govbr_ativo or not valor:
        return None
    try:
        dados = _serializador('sessao').loads(valor, max_age=DURACAO_SESSAO)
    except BadSignature:
        return None
    return dados if isinstance(dados, dict) and dados.get('email') else None


def _chave_cpf(cpf):
    """HMAC do CPF (claim `sub` do gov.br): identifica a conta sem guardar o número."""
    return hmac.new(servicos().cfg.segredo_sessao.encode(), ('govbr-cpf:' + cpf).encode(), hashlib.sha256).hexdigest()


def _ir_ao_govbr(estado):
    """Redireciona ao /authorize do gov.br, guardando state, nonce e verificador PKCE no cookie."""
    cfg = servicos().cfg
    verificador = secrets.token_urlsafe(48)
    estado = {**estado, 'state': secrets.token_urlsafe(24), 'nonce': secrets.token_urlsafe(24),
              'verificador': verificador}
    desafio = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).decode().rstrip('=')
    parametros = {
        'response_type': 'code', 'client_id': cfg.govbr_client_id, 'scope': ESCOPOS,
        'redirect_uri': _redirect_uri(), 'state': estado['state'], 'nonce': estado['nonce'],
        'code_challenge': desafio, 'code_challenge_method': 'S256',
    }
    resp = redirect(cfg.govbr_url + '/authorize?' + urlencode(parametros), 302)
    _cookie(resp, COOKIE_LOGIN, _serializador('login').dumps(estado), DURACAO_LOGIN)
    return resp


def token_de_nome(endereco, nome):
    """Token no formato que rotas/comum.py: nome() lê (só a carga importa; vem do próprio app)."""
    carga = base64.urlsafe_b64encode(json.dumps({'email': endereco, 'name': nome}).encode()).decode().rstrip('=')
    return f'Bearer govbr.{carga}.govbr'


# Ida e volta do gov.br -------------------------------------------------------------------------------

@bp.get('/auth/govbr/login')
def login():
    cfg = servicos().cfg
    if not cfg.govbr_ativo:
        return _recusa('O login com gov.br não está configurado neste servidor.', 404)
    return _ir_ao_govbr({'rd': destino(request.args.get('rd', ''))})


@bp.get('/conta/govbr/vincular')
def vincular():
    """Quem já entrou (pelo Google, com o e-mail institucional) vai ao gov.br para ligar a conta gov.br a
    este usuário. Fica atrás do login do Caddy; o e-mail segue assinado no cookie até a volta."""
    cfg = servicos().cfg
    if not cfg.govbr_ativo:
        return _recusa('O login com gov.br não está configurado neste servidor.', 404)
    usuario = email()
    if not usuario:
        return redirect('/entrar?rd=/conta/govbr/vincular', 302)
    return _ir_ao_govbr({'rd': destino(request.args.get('rd', '') or '/meus-planos'), 'vincular': usuario})


@bp.post('/conta/govbr/desvincular')
def desvincular():
    usuario = email()
    if not usuario or not mesma_origem():
        return Response('Requisição recusada', 403)
    servicos().usuarios.desvincular_govbr(usuario)
    return redirect(destino(request.form.get('rd', '') or '/meus-planos'), 303)


@bp.get('/auth/govbr/callback')
def callback():
    cfg = servicos().cfg
    if not cfg.govbr_ativo:
        return _recusa('O login com gov.br não está configurado neste servidor.', 404)
    try:
        estado = _serializador('login').loads(request.cookies.get(COOKIE_LOGIN, ''), max_age=DURACAO_LOGIN)
    except BadSignature:
        estado = None
    if request.args.get('error'):
        log.info('gov.br devolveu erro no login: %s', request.args.get('error'))
        return _recusa('O login no gov.br foi cancelado ou não foi concluído. Tente de novo.', 400)
    if not estado or not secrets.compare_digest(request.args.get('state', ''), estado['state']):
        return _recusa('A tentativa de login expirou ou veio de outra aba. Tente entrar de novo.', 400)
    try:
        r = requests.post(cfg.govbr_url + '/token', timeout=15, auth=(cfg.govbr_client_id, cfg.govbr_client_secret),
                          data={'grant_type': 'authorization_code', 'code': request.args.get('code', ''),
                                'redirect_uri': _redirect_uri(), 'code_verifier': estado['verificador']})
        if r.status_code >= 400:
            # O corpo da recusa (ex.: {"error": "invalid_client"}) diz o motivo e não traz segredos
            log.warning('gov.br recusou a troca do código: HTTP %s %s', r.status_code, ' '.join(r.text.split())[:500])
            return _recusa('Não foi possível concluir o login com o gov.br agora. Tente de novo em instantes.', 502)
        tokens = r.json()
    except (requests.RequestException, ValueError) as erro:
        log.warning('Falha na troca do código com o gov.br (%s): %s', cfg.govbr_url, erro)
        return _recusa('Não foi possível concluir o login com o gov.br agora. Tente de novo em instantes.', 502)
    claims = _claims(tokens.get('id_token'))
    aud = (claims or {}).get('aud')
    if (not claims or claims.get('iss', '').rstrip('/') != cfg.govbr_url
            or cfg.govbr_client_id not in (aud if isinstance(aud, list) else [aud])
            or not secrets.compare_digest(str(claims.get('nonce', '')), estado['nonce'])
            or claims.get('exp', 0) < time.time()):
        log.warning('ID token do gov.br recusado (emissor, público, nonce ou validade)')
        return _recusa('A resposta do gov.br não pôde ser confirmada. Tente entrar de novo.', 400)
    cpf = str(claims.get('sub') or '').strip()
    usuarios = servicos().usuarios
    resp = redirect(estado['rd'], 302)
    resp.delete_cookie(COOKIE_LOGIN, path='/')
    if estado.get('vincular'):
        if not cpf:
            return _recusa('O gov.br não informou a conta. Tente vincular de novo.', 400)
        usuarios.vincular_govbr(_chave_cpf(cpf), estado['vincular'])
        log.info('Conta gov.br vinculada a %s', estado['vincular'])
        return resp
    endereco = str(claims.get('email') or '').strip().lower()
    verificado = claims.get('email_verified') in (True, 'true')
    if endereco.rpartition('@')[2] == cfg.email_dominio and verificado:
        if cpf:  # o próximo login segue valendo mesmo se o e-mail do gov.br mudar
            usuarios.vincular_govbr(_chave_cpf(cpf), endereco)
    else:
        endereco = usuarios.email_do_govbr(_chave_cpf(cpf)) if cpf else None
        if not endereco:
            log.info('Login gov.br recusado: e-mail fora do domínio ou não verificado, e conta não vinculada')
            return _recusa(f'Sua conta gov.br não tem o e-mail institucional (@{cfg.email_dominio}) e ainda não '
                           'foi vinculada a um usuário. Entre uma vez com a conta Google institucional e vincule '
                           'a sua conta gov.br; depois disso, o login com gov.br funciona direto.',
                           vincular=cfg.login_google)
    nome = ' '.join(str(claims.get('name') or '').split())[:120]
    _cookie(resp, COOKIE_SESSAO, _serializador('sessao').dumps({'email': endereco, 'nome': nome}), DURACAO_SESSAO)
    log.info('Login gov.br: %s', endereco)
    return resp


# Sessão: verificação (Caddy), entrar e sair ----------------------------------------------------------

@bp.get('/auth/verificar')
def verificar():
    """Consultado pelo Caddy (forward_auth) a cada requisição que exige login: 200 com o e-mail e o token
    de quem entrou, pelo gov.br ou pelo Google (oauth2-proxy), ou 401."""
    cfg = servicos().cfg
    dados = sessao()
    if dados:
        resp = Response(status=200)
        resp.headers['X-Usuario-Email'] = dados['email']
        resp.headers['X-Usuario-Token'] = token_de_nome(dados['email'], dados.get('nome', ''))
        return resp
    if cfg.login_google and any(n.startswith(COOKIE_GOOGLE) for n in request.cookies):
        try:
            r = requests.get(cfg.oauth2_proxy_url + '/oauth2/auth', timeout=5, allow_redirects=False,
                             headers={'Cookie': request.headers['Cookie']})
        except requests.RequestException as erro:
            log.warning('oauth2-proxy indisponível: %s', erro)
            return Response('Login indisponível', 503)
        if r.status_code in (200, 202) and r.headers.get('X-Auth-Request-Email'):
            resp = Response(status=200)
            resp.headers['X-Usuario-Email'] = r.headers['X-Auth-Request-Email']
            if r.headers.get('Authorization'):
                resp.headers['X-Usuario-Token'] = r.headers['Authorization']
            return resp
    return Response('Login necessário', 401)


@bp.get('/entrar')
def entrar():
    """Para onde o Caddy manda quem abre uma página sem login: direto ao único login disponível ou, com os
    dois, à página inicial com os botões."""
    cfg = servicos().cfg
    rd = destino(request.args.get('rd', ''))
    if cfg.govbr_ativo and not cfg.login_google:
        return redirect('/auth/govbr/login?rd=' + quote(rd), 302)
    if not cfg.govbr_ativo:
        return redirect('/oauth2/start?rd=' + quote(rd), 302)
    return redirect('/?rd=' + quote(rd) + '#entrar', 302)


def _fim_da_saida(destino_final='/'):
    """Encerra a sessão do Google (oauth2-proxy), se ligado, e volta à página inicial."""
    if servicos().cfg.login_google:
        return redirect('/oauth2/sign_out?rd=' + quote(destino_final, safe=''), 302)
    return redirect(destino_final, 302)


@bp.get('/auth/sair')
def sair():
    """Encerra a sessão do app (gov.br e Google) e volta à página inicial. Não passa pelo /logout do gov.br:
    sem o endereço de saída cadastrado lá, o gov.br não volta ao app. A sessão no próprio gov.br continua
    aberta no navegador (como em qualquer serviço que entra com gov.br)."""
    resp = make_response(_fim_da_saida())
    resp.delete_cookie(COOKIE_SESSAO, path='/')
    return resp


@bp.get('/auth/gov/logout')
def volta_da_saida():
    """Endereço de saída antigo (cadastrado no gov.br): só encerra a sessão e volta à página inicial."""
    resp = make_response(_fim_da_saida())
    resp.delete_cookie(COOKIE_SESSAO, path='/')
    return resp
