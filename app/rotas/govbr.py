import base64
import hashlib
import json
import logging
import secrets
import time
from urllib.parse import quote, urlencode

import requests
from flask import Blueprint, Response, make_response, redirect, render_template, request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from .comum import servicos

# Login com a conta gov.br (Login Único, OpenID Connect com PKCE) e a verificação de sessão que o Caddy
# consulta a cada requisição (forward_auth em /auth/verificar).
#
# O app identifica as pessoas pelo e-mail institucional: o login gov.br só é aceito quando o e-mail da
# conta gov.br é do domínio da instituição (EMAIL_DOMINIO) e está verificado. A sessão gov.br é um cookie
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


def _recusa(motivo, status=403):
    return render_template('login_recusado.html', motivo=motivo), status


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
    verificador = secrets.token_urlsafe(48)
    estado = {'state': secrets.token_urlsafe(24), 'nonce': secrets.token_urlsafe(24), 'verificador': verificador,
              'rd': destino(request.args.get('rd', ''))}
    desafio = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).decode().rstrip('=')
    parametros = {
        'response_type': 'code', 'client_id': cfg.govbr_client_id, 'scope': ESCOPOS,
        'redirect_uri': _redirect_uri(), 'state': estado['state'], 'nonce': estado['nonce'],
        'code_challenge': desafio, 'code_challenge_method': 'S256',
    }
    resp = redirect(cfg.govbr_url + '/authorize?' + urlencode(parametros), 302)
    _cookie(resp, COOKIE_LOGIN, _serializador('login').dumps(estado), DURACAO_LOGIN)
    return resp


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
    endereco = str(claims.get('email') or '').strip().lower()
    verificado = claims.get('email_verified') in (True, 'true')
    if endereco.rpartition('@')[2] != cfg.email_dominio or not verificado:
        log.info('Login gov.br recusado: e-mail fora do domínio ou não verificado')
        return _recusa(f'Sua conta gov.br precisa ter o e-mail institucional (@{cfg.email_dominio}) cadastrado e '
                       'verificado. Altere o e-mail em contas.acesso.gov.br (Dados pessoais) e entre de novo.')
    nome = ' '.join(str(claims.get('name') or '').split())[:120]
    resp = redirect(estado['rd'], 302)
    _cookie(resp, COOKIE_SESSAO, _serializador('sessao').dumps({'email': endereco, 'nome': nome}), DURACAO_SESSAO)
    resp.delete_cookie(COOKIE_LOGIN, path='/')
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


def _fim_da_saida():
    """Depois da sessão gov.br: encerra a do Google (oauth2-proxy), se ligado, e volta à página inicial."""
    return redirect('/oauth2/sign_out?rd=/' if servicos().cfg.login_google else '/', 302)


@bp.get('/auth/sair')
def sair():
    """Encerra a sessão do app. Quem entrou pelo gov.br também sai do gov.br (senão o próximo "Entrar com
    gov.br" entraria direto na mesma conta): vai a /logout do gov.br, que volta em GOVBR_LOGOUT_URI."""
    cfg = servicos().cfg
    pelo_govbr = sessao() is not None
    if pelo_govbr and cfg.govbr_logout_uri:
        resp = make_response(redirect(cfg.govbr_url + '/logout?' + urlencode(
            {'post_logout_redirect_uri': cfg.govbr_logout_uri}), 302))
    else:
        resp = make_response(_fim_da_saida())
    resp.delete_cookie(COOKIE_SESSAO, path='/')
    return resp


@bp.get('/auth/gov/logout')
def volta_da_saida():
    """Retorno do gov.br depois da saída (endereço de logout registrado no gov.br)."""
    resp = make_response(_fim_da_saida())
    resp.delete_cookie(COOKIE_SESSAO, path='/')
    return resp
