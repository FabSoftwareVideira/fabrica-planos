import logging
import secrets
from urllib.parse import urlencode

from flask import Blueprint, redirect, request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from ..avaliacao import pipeline
from ..servicos import assinatura, assinatura_api
from .comum import email, nome as nome_usuario, servicos

# Assinatura do plano pela API do gov.br (servicos/assinatura_api.py): "Assinar com gov.br" em "Meus planos"
# leva ao gov.br (/iniciar), que volta em /callback com o código; o app troca o código pelo token, assina
# o PDF aprovado e volta a "Meus planos" com o resultado. As duas rotas exigem login (Caddy).

log = logging.getLogger(__name__)
bp = Blueprint('assinatura_govbr', __name__, url_prefix='/assinatura/govbr')

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
    estado = {'state': secrets.token_urlsafe(24), 'nonce': secrets.token_urlsafe(24), 'arquivo': nome,
              'email': _usuario()}
    resp = redirect(cliente.url_autorizacao(_redirect_uri(), estado['state'], estado['nonce']), 302)
    resp.set_cookie(COOKIE, _serializador().dumps(estado), max_age=DURACAO, httponly=True,
                    secure=s.cfg.cookie_seguro, samesite='Lax', path='/assinatura/govbr')
    return resp


@bp.get('/callback')
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
            resp = _voltar(assinatura='ok', arquivo=nome, signatario=registro['signatario'])
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

