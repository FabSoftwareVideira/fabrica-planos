"""Limite de requisições (app/limites.py e rotas/publico.py: _limitar)."""
from app import limites
from app.limites import Limitador


def test_janela_deslizante():
    agora = [100.0]
    lim = Limitador(relogio=lambda: agora[0])
    assert [lim.conferir('k', 3, 60) for _ in range(3)] == [0, 0, 0]
    assert lim.conferir('k', 3, 60) == 61  # o mais antigo sai da janela daqui a 60 s
    assert lim.conferir('outra', 3, 60) == 0  # cada chave conta à parte
    agora[0] += 30
    assert lim.conferir('k', 3, 60) == 31
    agora[0] += 31
    assert lim.conferir('k', 3, 60) == 0  # os três primeiros saíram da janela


def test_limpa_chaves_antigas():
    agora = [0.0]
    lim = Limitador(relogio=lambda: agora[0])
    for i in range(10001):
        lim.conferir(f'k{i}', 5, 60)
    agora[0] += 7200
    lim.conferir('nova', 5, 60)
    assert len(lim._pedidos) < 10


def test_regras():
    nome = lambda metodo, caminho: (limites.regra(metodo, caminho) or ('isenta',))[0]
    assert nome('GET', '/auth/govbr/login') == 'login' and nome('GET', '/assinatura/govbr/iniciar') == 'login'
    assert nome('POST', '/meus-planos') == 'envio' and nome('GET', '/meus-planos') == 'geral'
    assert nome('GET', '/coordenacao/assinados.zip') == 'exportacao'
    assert nome('GET', '/transparencia/3.pdf') == 'pdf_publico' and nome('GET', '/transparencia/3') == 'publico'
    assert nome('GET', '/') == 'publico' and nome('GET', '/dashboard') == 'geral'
    assert nome('GET', '/static/css/ds.css') == nome('GET', '/auth/verificar') == nome('GET', '/health') == 'isenta'


def test_acima_do_limite_responde_429(fabrica, monkeypatch):
    monkeypatch.setattr(limites, 'REGRAS', (('publico', None, lambda c: c == '/privacidade', 'ip', 2, 60),
                                            ('geral', None, lambda c: True, 'usuario', 1000, 60)))
    c, _ = fabrica(exigir_login=True)
    assert [c.get('/privacidade').status_code for _ in range(2)] == [200, 200]
    r = c.get('/privacidade', headers={'Accept': 'text/html'})
    assert r.status_code == 429 and int(r.headers['Retry-After']) > 0
    assert 'Muitas requisições' in r.get_data(as_text=True) and 'class="erro-codigo"' in r.get_data(as_text=True)
    assert c.get('/privacidade', headers={'X-Planos-Cliente': '10.9.9.9'}).status_code == 200  # outro IP


def test_por_usuario_e_desligavel(fabrica, monkeypatch):
    monkeypatch.setattr(limites, 'REGRAS', (('geral', None, lambda c: True, 'usuario', 1, 60),))
    c, _ = fabrica(exigir_login=True, admins=frozenset({'a@ifc.edu.br'}))
    assert c.get('/dashboard', headers={'X-Usuario-Email': 'a@ifc.edu.br'}).status_code == 200
    r = c.get('/dashboard', headers={'X-Usuario-Email': 'a@ifc.edu.br'})
    assert r.status_code == 429 and r.get_data(as_text=True).startswith('Muitas requisições')
    assert c.get('/dashboard', headers={'X-Usuario-Email': 'b@ifc.edu.br'}).status_code != 429
    c, _ = fabrica(exigir_login=True, admins=frozenset({'a@ifc.edu.br'}), limites=False)
    assert all(c.get('/dashboard', headers={'X-Usuario-Email': 'a@ifc.edu.br'}).status_code == 200 for _ in range(3))
