"""Diagnóstico do gov.br (app/diagnostico_govbr.py): sem rede, com a conferência de endereços trocada."""
from dataclasses import replace

import requests

from app import diagnostico_govbr
from app.config import Config

BASE = Config(planos_dir='p', resultados_dir='r', ollama_url='http://o', modelo='m', num_ctx=1, hora_agendada=0, agendar=False)


def _completa():
    return replace(BASE, govbr_client_id='login', govbr_client_secret='s1', segredo_sessao='chave',
                   assinatura_client_id='HNO7VC1ZL8', assinatura_client_secret='s2', assinatura_ambiente='homologacao',
                   assinatura_oauth_url='https://cas.staging.iti.br/oauth2.0',
                   assinatura_api_url='https://assinatura-api.staging.iti.br/externo/v2')


def test_tudo_certo_nao_mostra_segredos(capsys):
    pedidos = []
    assert diagnostico_govbr.main(_completa(), lambda url: (pedidos.append(url), (True, 'responde (HTTP 401)'))[1]) == 0
    saida = capsys.readouterr().out
    assert 's1' not in saida and 's2' not in saida and 'chave' not in saida
    assert 'GOVBR_ASSINATURA_CLIENT_SECRET: preenchido' in saida and 'ambiente homologacao' in saida
    assert '"Assinar com gov.br": ativo' in saida and 'FALHA' not in saida
    assert 'https://cas.staging.iti.br/oauth2.0/authorize' in pedidos
    assert 'https://assinatura-api.staging.iti.br/externo/v2/certificadoPublico' in pedidos


def test_aponta_o_que_falta(capsys):
    cfg = replace(_completa(), assinatura_client_secret='')
    assert diagnostico_govbr.main(cfg, lambda url: (False, 'sem resposta (ConnectTimeout)')) == 1
    saida = capsys.readouterr().out
    assert ' FALHA GOVBR_ASSINATURA_CLIENT_SECRET: VAZIO' in saida and 'sem resposta (ConnectTimeout)' in saida
    assert 'desligado' in saida


def test_simulada(capsys):
    cfg = replace(BASE, assinatura_ambiente='simulada', login_simulado=True)
    assert all(ok for ok, t in diagnostico_govbr.linhas(cfg, lambda url: (True, '')) if 'imulad' in t)


def test_alcanca(monkeypatch):
    class R:
        status_code = 401
    monkeypatch.setattr(requests, 'get', lambda *a, **k: R())
    assert diagnostico_govbr._alcanca('https://x') == (True, 'responde (HTTP 401)')

    def falha(*a, **k):
        raise requests.ConnectTimeout()
    monkeypatch.setattr(requests, 'get', falha)
    assert diagnostico_govbr._alcanca('https://x') == (False, 'sem resposta (ConnectTimeout)')
