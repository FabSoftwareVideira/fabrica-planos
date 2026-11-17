"""Páginas de erro (app/paginas/erros.py, templates/erro.html e o tratador em app/rotas/publico.py): a página no
padrão do Design System para quem navega; JSON ou texto para as chamadas das páginas (fetch)."""
import pytest

from app.paginas import erros

NAVEGADOR = {'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'}
ADMIN = {'X-Usuario-Email': 'admin@ifc.edu.br'}


@pytest.fixture
def app(fabrica):
    c, _ = fabrica(exigir_login=True, admins=frozenset({'admin@ifc.edu.br'}))
    return c


def test_pagina_nao_encontrada(app):
    r = app.get('/nao-existe', headers={**NAVEGADOR, **ADMIN})
    html = r.get_data(as_text=True)
    assert r.status_code == 404 and r.mimetype == 'text/html'
    assert 'Página não encontrada' in html and 'class="erro-codigo"' in html and '>404<' in html
    assert 'vendor/govbr-ds/govbr-ds.min.css' in html and 'br-message info' in html
    assert 'href="/dashboard"' in html and 'Ir para o painel' in html  # logado: volta ao painel
    assert '<title>Página não encontrada · Validação de Planos de Ensino</title>' in html


def test_chamada_da_pagina_recebe_json(app):
    r = app.get('/nao-existe', headers=ADMIN)  # fetch: sem pedir HTML
    assert r.status_code == 404 and r.json == {'erro': 'Página não encontrada'}
    r = app.get('/nao-existe', headers={**ADMIN, 'Accept': 'application/json'})
    assert r.json == {'erro': 'Página não encontrada'}
    assert app.post('/nao-existe', headers={**NAVEGADOR, **ADMIN}).is_json  # POST nunca é navegação


def test_metodo_nao_permitido(app):
    r = app.get('/validar', headers={**NAVEGADOR, **ADMIN})
    assert r.status_code == 405 and 'Ação não permitida' in r.get_data(as_text=True)


def test_mensagem_da_rota_vira_detalhe(app):
    r = app.get('/relatorio?arquivo=x.pdf', headers={**NAVEGADOR, **ADMIN})
    html = r.get_data(as_text=True)
    assert r.status_code == 404 and 'Detalhe:</strong> Nenhuma validação concluída ainda.' in html
    # Sem pedir HTML, o texto de sempre
    r = app.get('/relatorio?arquivo=x.pdf', headers=ADMIN)
    assert r.mimetype == 'text/plain' and r.get_data(as_text=True) == 'Nenhuma validação concluída ainda.'


def test_sem_login(app):
    r = app.get('/dashboard', headers=NAVEGADOR)
    html = r.get_data(as_text=True)
    assert r.status_code == 401 and 'Login necessário' in html
    assert 'href="/entrar?rd=/dashboard"' in html and 'Detalhe' not in html  # a mensagem repetiria o título
    assert app.get('/dashboard').get_data(as_text=True) == 'Login necessário.'


def test_acesso_negado(app):
    r = app.get('/coordenacao/assinados.zip?curso=CC', headers={**NAVEGADOR, 'X-Usuario-Email': 'fulano@ifc.edu.br'})
    assert r.status_code in (403, 404) and 'class="erro-codigo"' in r.get_data(as_text=True)


def test_erro_interno_mostra_a_pagina_sem_detalhes_tecnicos(fabrica, caplog):
    c, _ = fabrica(exigir_login=True, admins=frozenset({'admin@ifc.edu.br'}))

    def quebra():
        raise RuntimeError('segredo interno do servidor')
    c.application.add_url_rule('/quebra', 'quebra', quebra)
    r = c.get('/quebra', headers={**NAVEGADOR, **ADMIN})
    html = r.get_data(as_text=True)
    assert r.status_code == 500 and 'Erro interno' in html and 'br-message danger' in html
    assert 'segredo interno' not in html and 'Traceback' not in html
    assert 'segredo interno do servidor' in caplog.text  # registrado no log
    r = c.get('/quebra', headers=ADMIN)
    assert r.status_code == 500 and r.json == {'erro': 'Erro interno'}


def test_envio_grande_demais_continua_em_json(app):
    import io
    app.application.config['MAX_CONTENT_LENGTH'] = 1024 * 1024
    r = app.post('/meus-planos', headers={**NAVEGADOR, **ADMIN}, content_type='multipart/form-data',
                 data={'arquivo': (io.BytesIO(b'x' * (1024 * 1024 + 10)), 'a.pdf')})
    assert r.status_code == 413 and 'Envio maior que 1 MB' in r.json['erro']


def test_redirecionamento_do_flask_continua_funcionando(fabrica):
    c, _ = fabrica()
    c.application.add_url_rule('/pasta/', 'pasta', lambda: 'ok')
    r = c.get('/pasta', headers=NAVEGADOR)
    assert r.status_code == 308 and r.headers['Location'].endswith('/pasta/')


@pytest.mark.parametrize('codigo, titulo', [(400, 'Pedido inválido'), (418, 'Pedido inválido'), (409, 'Ação em andamento'),
                                            (502, 'Serviço indisponível'), (504, 'Erro interno')])
def test_titulos_por_codigo(codigo, titulo):
    assert erros.dados(codigo)[0] == titulo
