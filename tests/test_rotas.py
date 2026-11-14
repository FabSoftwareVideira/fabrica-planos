"""Testes de integração das rotas (app/rotas) nos caminhos de erro e nas bordas que os fluxos principais
de test_web.py não percorrem: login gov.br e verificação de sessão para o Caddy, administração, "Meus
planos", coordenação, histórico de validações e a barreira de login."""
import base64
import io
import json

import pytest
import requests

from app.avaliacao import pipeline
from app.rotas import govbr
from conftest import PDF_COM_TEXTO, servicos_de

PDF = PDF_COM_TEXTO
ADMIN = {'X-Usuario-Email': 'admin@ifc.edu.br'}
FULANO = {'X-Usuario-Email': 'fulano@ifc.edu.br'}
GOVBR = dict(exigir_login=True, admins=frozenset({'admin@ifc.edu.br'}), govbr_client_id='cliente',
             govbr_client_secret='segredo', segredo_sessao='chave-de-teste', cookie_seguro=False)


class Resposta:
    """Resposta falsa de requests.post/get."""

    def __init__(self, status=200, corpo=None, cabecalhos=None, texto=''):
        self.status_code, self._corpo, self.headers, self.text = status, corpo, cabecalhos or {}, texto

    def json(self):
        if self._corpo is None:
            raise ValueError('não é JSON')
        return self._corpo


def _id_token(**carga):
    parte = base64.urlsafe_b64encode(json.dumps(carga).encode()).decode().rstrip('=')
    return f'cabecalho.{parte}.assinatura'


@pytest.fixture
def admin(fabrica):
    return fabrica(exigir_login=True, admins=frozenset({'admin@ifc.edu.br'}))


@pytest.fixture
def sem_ia(monkeypatch):
    monkeypatch.setattr(pipeline, 'revalidar', lambda cfg, andamento, nome: andamento.finalizar())
    monkeypatch.setattr(pipeline, 'executar', lambda cfg, andamento, nomes: andamento.finalizar())


# gov.br: funções -------------------------------------------------------------------------------------

@pytest.mark.parametrize('valor, esperado', [
    ('/meus-planos', '/meus-planos'), ('/a?b=1', '/a?b=1'), ('', '/dashboard'), (None, '/dashboard'),
    ('//outro.site', '/dashboard'), ('https://outro.site', '/dashboard'), ('/\\outro.site', '/dashboard'),
])
def test_destino_so_aceita_caminhos_do_site(valor, esperado):
    assert govbr.destino(valor) == esperado


@pytest.mark.parametrize('token', [None, '', 'sem-pontos', 'a.%%%.c', 'a.' + base64.urlsafe_b64encode(b'[').decode()])
def test_claims_de_token_malformado(token):
    assert govbr._claims(token) is None


def test_claims_le_a_carga_sem_padding():
    assert govbr._claims(_id_token(sub='123', name='Ana')) == {'sub': '123', 'name': 'Ana'}


def test_chave_do_cpf_e_hmac_que_depende_do_segredo(fabrica):
    c, _ = fabrica(**GOVBR)
    with c.application.app_context():
        chave = govbr._chave_cpf('12345678900')
        assert chave == govbr._chave_cpf('12345678900') != govbr._chave_cpf('12345678901')
        assert len(chave) == 64 and '12345678900' not in chave
    c2, _ = fabrica(**dict(GOVBR, segredo_sessao='outra-chave'))
    with c2.application.app_context():
        assert govbr._chave_cpf('12345678900') != chave


# gov.br: ida e volta ---------------------------------------------------------------------------------

def _ida(c):
    from urllib.parse import parse_qs, urlsplit
    r = c.get('/auth/govbr/login?rd=/meus-planos')
    return {k: v[0] for k, v in parse_qs(urlsplit(r.headers['Location']).query).items()}


def test_govbr_desligado(fabrica):
    c, _ = fabrica(exigir_login=True)
    for url in ('/auth/govbr/login', '/auth/govbr/callback?code=x&state=y'):
        assert c.get(url).status_code == 404
    assert c.get('/conta/govbr/vincular', headers=FULANO).status_code == 404


def test_volta_sem_a_ida_ou_cancelada(fabrica):
    c, _ = fabrica(**GOVBR)
    r = c.get('/auth/govbr/callback?code=x&state=y')  # sem o cookie da ida
    assert r.status_code == 400 and 'expirou' in r.get_data(as_text=True)
    _ida(c)
    r = c.get('/auth/govbr/callback?error=access_denied&state=y')
    assert r.status_code == 400 and 'cancelado' in r.get_data(as_text=True)


@pytest.mark.parametrize('resposta, registro', [
    (Resposta(401, texto='{"error": "invalid_client"}'), 'invalid_client'),
    (Resposta(200, corpo=None), 'Falha na troca'),  # corpo que não é JSON
])
def test_troca_do_codigo_recusada(fabrica, monkeypatch, caplog, resposta, registro):
    c, _ = fabrica(**GOVBR)
    ida = _ida(c)
    monkeypatch.setattr(requests, 'post', lambda url, **kw: resposta)
    r = c.get(f"/auth/govbr/callback?code=abc&state={ida['state']}")
    assert r.status_code == 502 and 'Tente de novo em instantes' in r.get_data(as_text=True)
    assert registro in caplog.text
    assert c.get('/auth/verificar').status_code == 401


def test_gov_br_fora_do_ar(fabrica, monkeypatch, caplog):
    c, _ = fabrica(**GOVBR)
    ida = _ida(c)

    def tempo_esgotado(url, **kw):
        raise requests.ConnectTimeout('Connection to sso.acesso.gov.br timed out')
    monkeypatch.setattr(requests, 'post', tempo_esgotado)
    r = c.get(f"/auth/govbr/callback?code=abc&state={ida['state']}")
    assert r.status_code == 502 and 'timed out' in caplog.text


def test_vincular_sem_o_cpf_na_resposta(fabrica, monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    c, _ = fabrica(**GOVBR)
    r = c.get('/conta/govbr/vincular?rd=/dashboard', headers=FULANO)
    ida = {k: v[0] for k, v in parse_qs(urlsplit(r.headers['Location']).query).items()}
    claims = {'iss': 'https://sso.acesso.gov.br', 'aud': ['cliente'], 'nonce': ida['nonce'], 'exp': 9999999999}
    monkeypatch.setattr(requests, 'post', lambda url, **kw: Resposta(corpo={'id_token': _id_token(**claims)}))
    r = c.get(f"/auth/govbr/callback?code=abc&state={ida['state']}")
    assert r.status_code == 400 and 'vincular de novo' in r.get_data(as_text=True)


def test_vincular_sem_login_manda_entrar(fabrica):
    c, _ = fabrica(**dict(GOVBR, exigir_login=False))
    assert c.get('/conta/govbr/vincular').headers['Location'] == '/entrar?rd=/conta/govbr/vincular'


def test_vincular_volta_para_o_destino_pedido(fabrica, monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    c, _ = fabrica(**GOVBR)
    r = c.get('/conta/govbr/vincular?rd=/dashboard', headers=FULANO)
    ida = {k: v[0] for k, v in parse_qs(urlsplit(r.headers['Location']).query).items()}
    claims = {'iss': 'https://sso.acesso.gov.br', 'aud': 'cliente', 'nonce': ida['nonce'], 'exp': 9999999999,
              'sub': '11122233344'}
    monkeypatch.setattr(requests, 'post', lambda url, **kw: Resposta(corpo={'id_token': _id_token(**claims)}))
    r = c.get(f"/auth/govbr/callback?code=abc&state={ida['state']}")
    assert r.headers['Location'] == '/dashboard' and servicos_de(c).usuarios.tem_govbr('fulano@ifc.edu.br')
    r = c.post('/conta/govbr/desvincular', headers=FULANO, data={'rd': '/administracao'})
    assert r.headers['Location'] == '/administracao' and not servicos_de(c).usuarios.tem_govbr('fulano@ifc.edu.br')


# Verificação de sessão (Caddy) e entrada ---------------------------------------------------------------

def test_verificar_pergunta_ao_oauth2_proxy_so_com_o_cookie_do_google(fabrica, monkeypatch):
    c, _ = fabrica(**GOVBR)
    pedidos = []

    def proxy(url, **kw):
        pedidos.append((url, kw))
        return Resposta(202, cabecalhos={'X-Auth-Request-Email': 'fulano@ifc.edu.br', 'Authorization': 'Bearer t'})
    monkeypatch.setattr(requests, 'get', proxy)
    assert c.get('/auth/verificar').status_code == 401 and not pedidos  # sem cookie, nem pergunta
    c.set_cookie('_planos_login_0', 'parte-do-cookie')
    r = c.get('/auth/verificar')
    assert r.status_code == 200 and r.headers['X-Usuario-Email'] == 'fulano@ifc.edu.br'
    assert r.headers['X-Usuario-Token'] == 'Bearer t'
    url, kw = pedidos[0]
    assert url == 'http://oauth2-proxy:4180/oauth2/auth' and '_planos_login_0=parte-do-cookie' in kw['headers']['Cookie']


@pytest.mark.parametrize('resposta', [Resposta(401), Resposta(202, cabecalhos={})])
def test_verificar_sem_sessao_no_google(fabrica, monkeypatch, resposta):
    c, _ = fabrica(**GOVBR)
    monkeypatch.setattr(requests, 'get', lambda url, **kw: resposta)
    c.set_cookie('_planos_login', 'expirado')
    assert c.get('/auth/verificar').status_code == 401


def test_verificar_com_oauth2_proxy_fora_do_ar(fabrica, monkeypatch, caplog):
    c, _ = fabrica(**GOVBR)

    def fora(url, **kw):
        raise requests.ConnectionError('recusada')
    monkeypatch.setattr(requests, 'get', fora)
    c.set_cookie('_planos_login', 'x')
    assert c.get('/auth/verificar').status_code == 503 and 'oauth2-proxy indisponível' in caplog.text


def test_verificar_ignora_o_google_desligado(fabrica, monkeypatch):
    c, _ = fabrica(**dict(GOVBR, login_google=False))
    monkeypatch.setattr(requests, 'get', lambda url, **kw: pytest.fail('não devia perguntar ao oauth2-proxy'))
    c.set_cookie('_planos_login', 'x')
    assert c.get('/auth/verificar').status_code == 401


def test_entrar_escolhe_o_login(fabrica):
    c, _ = fabrica(exigir_login=True)  # só Google
    assert c.get('/entrar?rd=/meus-planos').headers['Location'] == '/oauth2/start?rd=/meus-planos'
    c, _ = fabrica(**GOVBR)  # os dois: a página inicial com os botões
    assert c.get('/entrar?rd=/meus-planos').headers['Location'] == '/?rd=/meus-planos#entrar'


def test_sair_sem_o_google(fabrica):
    c, _ = fabrica(**dict(GOVBR, login_google=False))
    assert c.get('/auth/sair').headers['Location'] == '/'
    assert c.get('/auth/gov/logout').headers['Location'] == '/'


# Barreira de login ---------------------------------------------------------------------------------------

def test_falha_no_cadastro_nao_derruba_a_pagina(admin, monkeypatch, caplog):
    c, _ = admin

    def falha(*a, **k):
        raise RuntimeError('banco fora do ar')
    monkeypatch.setattr(servicos_de(c).usuarios, 'registrar_acesso', falha)
    assert c.get('/status', headers=FULANO).status_code == 200
    assert 'Falha ao registrar o acesso' in caplog.text


def test_envio_grande_demais_responde_em_json(admin):
    c, _ = admin
    c.application.config['MAX_CONTENT_LENGTH'] = 1024 * 1024
    r = c.post('/meus-planos', headers=FULANO, data={'arquivos': [(io.BytesIO(b'x' * (1024 * 1024 + 10)), 'a.pdf')]},
               content_type='multipart/form-data')
    assert r.status_code == 413 and 'Envio maior que 1 MB' in r.json['erro']


def test_post_de_outro_site_e_recusado(admin):
    c, _ = admin
    r = c.post('/administracao/backup', headers={**ADMIN, 'Origin': 'https://outro.site'})
    assert r.status_code == 403


# Administração ---------------------------------------------------------------------------------------------

def test_backup_so_para_administradores(admin):
    c, _ = admin
    for metodo, url in (('get', '/administracao/backup/x.zip'), ('post', '/administracao/backup'),
                        ('post', '/administracao/backup/x.zip/restaurar'), ('post', '/administracao/backup/x.zip/excluir'),
                        ('post', '/administracao/usuarios/ativo')):
        r = getattr(c, metodo)(url, headers=FULANO)
        assert r.status_code == 302 and r.headers['Location'] == '/dashboard', url


def test_backup_ocupado_e_falha_inesperada_na_restauracao(admin, monkeypatch):
    c, _ = admin
    s = servicos_de(c)
    s.backup._em_andamento = True
    assert c.post('/administracao/backup', headers=ADMIN).headers['Location'].endswith('aviso=ocupado')
    s.backup._em_andamento = False

    def quebra(nome):
        raise KeyError('inesperado')
    monkeypatch.setattr(s.backup, 'restaurar', quebra)
    r = c.post('/administracao/backup/20261101-030000-manual.zip/restaurar', headers=ADMIN)
    assert r.status_code == 303 and r.headers['Location'].endswith('aviso=erro')


def test_ativar_usuario_que_nao_existe(admin):
    c, _ = admin
    r = c.post('/administracao/usuarios/ativo', headers=ADMIN,
               data={'email': 'ninguem@ifc.edu.br', 'ativo': '0', 'voltar': '/administracao/usuarios?pagina=2'})
    assert r.headers['Location'] == '/administracao/usuarios?pagina=2&aviso=inexistente'
    r = c.post('/administracao/usuarios/ativo', headers=ADMIN, data={'email': 'x@ifc.edu.br', 'voltar': 'https://fora'})
    assert r.headers['Location'].startswith('/administracao/usuarios?aviso=')


def test_validar_todos_os_planos(admin, sem_ia):
    c, planos = admin
    assert c.post('/validar', headers=ADMIN).status_code == 422  # pasta vazia
    (planos / 'a.pdf').write_bytes(PDF)
    r = c.post('/validar', headers=ADMIN)
    assert r.status_code == 200 and r.json == {'status': 'iniciado'}


@pytest.mark.parametrize('metodo', ['post', 'delete'])
def test_ocultar_com_nome_invalido(admin, metodo):
    c, _ = admin
    for nome in ('', 'a.txt', '../a.pdf'):
        assert getattr(c, metodo)('/planos/ocultar?arquivo=' + nome, headers=ADMIN).status_code == 400


# Meus planos ----------------------------------------------------------------------------------------------

def test_meus_planos_pedidos_invalidos(admin):
    c, _ = admin
    assert c.post('/meus-planos', headers=FULANO, data={}, content_type='multipart/form-data').status_code == 400
    r = c.post('/meus-planos', headers=FULANO, data={'oferta': 'x', 'arquivo': (io.BytesIO(PDF), 'a.pdf')},
               content_type='multipart/form-data')
    assert r.status_code == 400 and 'disciplina' in r.json['erro']
    assert c.delete('/meus-planos?arquivo=../a.pdf', headers=FULANO).status_code == 400


def test_nao_exclui_o_plano_em_avaliacao(admin, sem_ia):
    from conftest import dar_disciplina, enviar_plano
    c, planos = admin
    o = dar_disciplina(c, 'fulano@ifc.edu.br')
    enviar_plano(c, o, PDF, cab=FULANO)
    servicos_de(c).validador.andamento.iniciar(1, unico=o['arquivo'])
    r = c.delete('/meus-planos?arquivo=' + o['arquivo'], headers=FULANO)
    assert r.status_code == 409 and (planos / o['arquivo']).exists()


@pytest.mark.parametrize('dados, nome, mensagem', [
    (None, 'a.pdf', 'Envie o PDF assinado'),
    (PDF, '../a.pdf', 'Envie o PDF assinado'),
    (b'texto qualquer', 'a.pdf', 'não é um PDF'),
    (b'%PDF-' + b'0' * (1024 * 1024), 'a.pdf', 'maior que 1 MB'),
])
def test_pdf_assinado_invalido(admin, dados, nome, mensagem):
    c, _ = admin
    form = {'arquivo': nome}
    if dados is not None:
        form['pdf'] = (io.BytesIO(dados), 'assinado.pdf')
    r = c.post('/meus-planos/assinatura', headers=FULANO, data=form, content_type='multipart/form-data')
    assert r.status_code == 400 and mensagem in r.json['erro']


def test_erro_inesperado_ao_conferir_a_assinatura(admin, monkeypatch, caplog):
    c, _ = admin

    def quebra(*a, **k):
        raise ZeroDivisionError
    monkeypatch.setattr(servicos_de(c).assinaturas, 'registrar', quebra)
    r = c.post('/meus-planos/assinatura', headers=FULANO, data={'arquivo': 'a.pdf', 'pdf': (io.BytesIO(PDF), 'a.pdf')},
               content_type='multipart/form-data')
    assert r.status_code == 500 and 'Erro interno' in r.json['erro'] and 'Falha ao conferir' in caplog.text


# Coordenação e histórico ------------------------------------------------------------------------------------

def test_nao_ha_mais_liberacao_de_reenvio(admin):
    c, _ = admin
    assert c.post('/coordenacao/liberar', headers=ADMIN, data={'arquivo': 'a.pdf'}).status_code in (404, 405)


@pytest.mark.parametrize('numero, extra', [('x', ''), ('1', ''), ('1', '&assinado=1')])
def test_versao_que_nao_existe(admin, numero, extra):
    c, _ = admin
    r = c.get(f'/meus-planos/versao?arquivo=a.pdf&numero={numero}{extra}', headers=FULANO)
    assert r.status_code == (400 if numero == 'x' else 404)


@pytest.mark.parametrize('url', ['/validacoes/20990101-000000/csv', '/validacoes/20990101-000000/pdf?arquivo=a.pdf',
                                 '/validacoes/20990101-000000/pdfs.zip'])
def test_validacao_que_nao_existe(admin, url):
    c, _ = admin
    assert c.get(url, headers=ADMIN).status_code == 404
