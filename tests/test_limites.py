"""Limite de requisições com o Flask-Limiter (app/limites.py): grupos por IP e por usuário, 429 com
Retry-After, IPs isentos e LIMITES=0."""
from app import limites
from app.config import _redes
from test_web import GOVBR

COORD = {'X-Usuario-Email': 'alguem@ifc.edu.br'}


def test_paginas_publicas_por_ip(fabrica):
    c, _ = fabrica(exigir_login=True)
    assert all(c.get('/privacidade').status_code == 200 for _ in range(120))
    r = c.get('/privacidade', headers={'Accept': 'text/html'})
    assert r.status_code == 429 and int(r.headers['Retry-After']) > 0
    html = r.get_data(as_text=True)
    assert 'Muitas requisições' in html and 'class="erro-codigo"' in html and '>429<' in html
    # O grupo é compartilhado (início, transparência...) e contado por IP: outro IP segue normal
    assert c.get('/transparencia').status_code == 429
    assert c.get('/privacidade', headers={'X-Planos-Cliente': '10.9.9.9'}).status_code == 200
    assert c.get('/static/css/ds.css').status_code == 200 and c.get('/health').status_code == 200  # fora


def test_login_por_ip(fabrica):
    c, _ = fabrica(**GOVBR)
    assert all(c.get('/auth/govbr/login').status_code == 302 for _ in range(20))
    r = c.get('/auth/govbr/login')
    assert r.status_code == 429 and r.json == {'erro': 'Muitas requisições'}  # sem pedir HTML: JSON


def test_exportacao_por_usuario(fabrica):
    c, _ = fabrica(exigir_login=True)
    url = '/coordenacao/assinados.zip?curso=CC'
    assert all(c.get(url, headers=COORD).status_code == 403 for _ in range(10))  # conta mesmo recusado
    assert c.get(url, headers=COORD).status_code == 429
    assert c.get(url, headers={'X-Usuario-Email': 'outra@ifc.edu.br'}).status_code == 403  # outro usuário


def test_ips_isentos(fabrica):
    redes = _redes('10.1.2.3, 192.168.10.0/24, invalido, 2001:db8::/32')
    assert len(redes) == 3
    assert limites.isento('10.1.2.3', redes) and limites.isento('192.168.10.77', redes)
    assert limites.isento('2001:db8::1', redes)
    assert not limites.isento('10.1.2.4', redes) and not limites.isento('lixo', redes)
    assert not limites.isento('10.1.2.3', ())
    c, _ = fabrica(exigir_login=True, limites_isentos=redes)
    interno = {'X-Planos-Cliente': '192.168.10.5'}
    assert all(c.get('/privacidade', headers=interno).status_code == 200 for _ in range(130))
    externo = {'X-Planos-Cliente': '8.8.8.8'}
    assert all(c.get('/privacidade', headers=externo).status_code == 200 for _ in range(120))
    assert c.get('/privacidade', headers=externo).status_code == 429


def test_desligado(fabrica):
    c, _ = fabrica(exigir_login=True, limites=False)
    assert all(c.get('/privacidade').status_code == 200 for _ in range(130))


def test_cada_app_comeca_zerado(fabrica):
    c, _ = fabrica(exigir_login=True)
    assert all(c.get('/privacidade').status_code == 200 for _ in range(120))
    c, _ = fabrica(exigir_login=True)
    assert c.get('/privacidade').status_code == 200
