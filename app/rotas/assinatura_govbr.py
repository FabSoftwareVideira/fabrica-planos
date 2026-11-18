import logging
import secrets
from urllib.parse import urlencode

from flask import Blueprint, redirect, request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from ..avaliacao import pipeline
from ..servicos import assinatura, assinatura_api
from .comum import email, nome as nome_usuario, servicos
from ..limites import LOGIN

# Assinatura do plano pela API do gov.br (servicos/assinatura_api.py): "Assinar com gov.br" em "Meus planos"
# leva ao gov.br (/iniciar), que volta em /callback com o código; o app troca o código pelo token, assina
# o PDF aprovado e volta a "Meus planos" com o resultado. As duas rotas exigem login (Caddy).

log = logging.getLogger(__name__)
bp = Blueprint('assinatura_govbr', __name__, url_prefix='/assinatura/govbr')
# Endereço de retorno cadastrado no gov.br para as credenciais de homologação. Fica em /auth/ (público no
# Caddy, sem o e-mail de quem entrou) e fora do caminho do cookie: só repassa o retorno a /callback.
retorno = Blueprint('assinatura_govbr_retorno', __name__)

COOKIE = '_planos_assinatura'  # state, nonce, plano e quem pediu, durante a ida ao gov.br
DURACAO = 10 * 60


def _serializador():
    cfg = servicos().cfg
    # Na assinatura simulada (desenvolvimento) pode não haver SEGREDO_SESSAO
    return URLSafeTimedSerializer(cfg.segredo_sessao or 'assinatura-simulada-desenvolvimento', salt='assinatura')


def _redirect_uri():
    cfg = servicos().cfg
    return cfg.assinatura_redirect_uri or request.url_root.rstrip('/') + '/assinatura/govbr/callback'


def _usuario():
    return email() or 'local'  # sem login (uso local), como em "Meus planos"


def _voltar(**parametros):
    """De volta a "Meus planos", com o resultado na query string (a página mostra a mensagem)."""
    return redirect('/meus-planos?' + urlencode(parametros), 303)


@bp.get('/iniciar')
@LOGIN
def iniciar():
    s = servicos()
    cliente = assinatura_api.cliente(s.cfg)
    nome = request.args.get('arquivo', '')
    if cliente is None:
        return _voltar(assinatura='erro', arquivo=nome,
                       motivo='A assinatura pela API do gov.br não está configurada neste servidor.')
    if not pipeline.nome_valido(nome) or not s.assinaturas.liberado(nome, _usuario()):
        return _voltar(assinatura='erro', arquivo=nome,
                       motivo='Só quem enviou o plano o assina, e só depois de aprovado na revisão.')
    # Roteiro: o nível da conta é conferido ANTES de qualquer chamada da assinatura; conta bronze nunca chega
    # à tela de autorização. Sem o nível, ou com ele conferido há mais de alguns minutos (pode ser de outra conta
    # gov.br, ou de antes de um upgrade), "Assinar" passa pelo Login Único, que informa o nível da conta que
    # está no gov.br agora (a mesma que vai assinar), e volta aqui.
    nivel, quando = s.usuarios.nivel_govbr_conferido(_usuario())
    situacao = assinatura_api.pode_assinar(s.cfg, nivel)
    if (situacao == 'ok' and s.cfg.govbr_ativo and s.cfg.assinatura_ambiente != 'simulada'
            and not assinatura_api.conferido_ha_pouco(quando)):
        situacao = 'sem_nivel'
    if situacao == 'bronze':
        return _voltar(assinatura='bronze', arquivo=nome)
    if situacao == 'sem_nivel':
        if request.args.get('tentou'):  # o gov.br não informou o nível nem depois do login
            return _voltar(assinatura='erro', arquivo=nome, motivo=assinatura_api.MENSAGEM_SEM_NIVEL)
        volta = '/assinatura/govbr/iniciar?' + urlencode({'arquivo': nome, 'tentou': '1'})
        return redirect('/conta/govbr/vincular?' + urlencode({'rd': volta}), 302)
    estado = {'state': secrets.token_urlsafe(24), 'nonce': secrets.token_urlsafe(24), 'arquivo': nome,
              'email': _usuario()}
    resp = redirect(cliente.url_autorizacao(_redirect_uri(), estado['state'], estado['nonce']), 302)
    resp.set_cookie(COOKIE, _serializador().dumps(estado), max_age=DURACAO, httponly=True,
                    secure=s.cfg.cookie_seguro, samesite='Lax', path='/assinatura/govbr')
    return resp


@bp.get('/callback')
@LOGIN
def callback():
    s = servicos()
    cliente = assinatura_api.cliente(s.cfg)
    try:
        estado = _serializador().loads(request.cookies.get(COOKIE, ''), max_age=DURACAO)
    except BadSignature:
        estado = None
    nome = (estado or {}).get('arquivo', '')
    if cliente is None:
        resp = _voltar(assinatura='erro', motivo='A assinatura pela API do gov.br não está configurada neste servidor.')
    elif request.args.get('error'):
        log.info('Assinatura gov.br: o gov.br devolveu erro: %s', request.args.get('error'))
        resp = _voltar(assinatura='erro', arquivo=nome, motivo='A assinatura foi cancelada no gov.br.')
    elif (not estado or not secrets.compare_digest(request.args.get('state', ''), estado['state'])
          or estado['email'] != _usuario()):
        resp = _voltar(assinatura='erro', arquivo=nome,
                       motivo='A tentativa de assinatura expirou ou veio de outra aba. Clique em "Assinar com gov.br" de novo.')
    else:
        try:
            token = cliente.token(request.args.get('code', ''), _redirect_uri())
            usuario = _usuario()
            nome_conta = nome_usuario() or (s.usuarios.obter(usuario) or {}).get('nome', '')
            registro = s.assinaturas.assinar_pela_api(nome, usuario, nome_conta, cliente, token)
            resp = _voltar(assinatura='ok', arquivo=nome, signatario=registro['signatario'],
                           **({'aviso': registro['aviso']} if registro.get('aviso') else {}))
        except assinatura.NaoLiberado:
            resp = _voltar(assinatura='erro', arquivo=nome,
                           motivo='O plano não pode mais ser assinado: ele mudou ou a aprovação foi desfeita.')
        except (assinatura_api.FalhaApi, assinatura.AssinaturaInvalida) as erro:
            resp = _voltar(assinatura='erro', arquivo=nome, motivo=str(erro))
        except Exception:
            log.exception('Falha na assinatura pela API de %s', nome)
            resp = _voltar(assinatura='erro', arquivo=nome,
                           motivo='Erro interno ao assinar; tente de novo ou avise a administração.')
    resp.delete_cookie(COOKIE, path='/assinatura/govbr')
    return resp


@retorno.get('/auth/govbr/assinatura/callback')
@LOGIN
def retorno_cadastrado():
    consulta = request.query_string.decode('ascii', 'ignore')
    return redirect('/assinatura/govbr/callback' + ('?' + consulta if consulta else ''), 302)
