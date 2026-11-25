"""Meu perfil (rotas/conta.py): nome escolhido que o login não sobrescreve, dados, conta gov.br e exportação."""
from test_web import GOVBR, _token

FULANO = {'X-Usuario-Email': 'fulano@ifc.edu.br', 'X-Usuario-Token': _token(email='fulano@ifc.edu.br', name='Fulano Tal')}


def test_nome_escolhido_vale_e_o_login_nao_sobrescreve(fabrica):
    c, _ = fabrica(exigir_login=True)
    html = c.get('/conta', headers=FULANO).get_data(as_text=True)
    assert 'value="Fulano Tal"' in html and 'fulano@ifc.edu.br' in html and 'Usar o nome da conta de login' not in html
    r = c.post('/conta/nome', headers=FULANO, data={'nome': '  Fulano   de Tal  Silva '})
    assert r.status_code == 303 and r.headers['Location'] == '/conta?aviso=nome'
    html = c.get('/conta', headers=FULANO).get_data(as_text=True)  # o token ainda diz "Fulano Tal"
    assert 'value="Fulano de Tal Silva"' in html and 'Nome atualizado.' not in html
    assert '<p class="perfil-nome">Fulano de Tal Silva</p>' in html  # cabeçalho
    assert 'O nome da sua conta de login é <strong>Fulano Tal</strong>' in html
    usuarios = c.application.extensions['servicos'].usuarios
    assert usuarios.obter('fulano@ifc.edu.br')['nome'] == 'Fulano de Tal Silva'

    assert c.post('/conta/nome', headers=FULANO, data={'nome': 'ab'}).headers['Location'] == '/conta?erro=nome'
    assert c.post('/conta/nome', headers={**FULANO, 'Origin': 'https://outro.site'}, data={'nome': 'X Y Z'}).status_code == 403

    r = c.post('/conta/nome', headers=FULANO, data={'acao': 'login'})
    assert r.headers['Location'] == '/conta?aviso=nome_login'
    c.get('/dashboard', headers=FULANO)
    assert usuarios.obter('fulano@ifc.edu.br')['nome'] == 'Fulano Tal'


def test_meus_dados_e_conta_govbr(fabrica):
    c, _ = fabrica(**GOVBR)
    usuarios = c.application.extensions['servicos'].usuarios
    c.get('/dashboard', headers=FULANO)
    html = c.get('/conta', headers=FULANO).get_data(as_text=True)
    assert 'Nenhuma conta gov.br vinculada.' in html and 'href="/conta/govbr/vincular?rd=/conta"' in html
    usuarios.vincular_govbr('chave', 'fulano@ifc.edu.br', 'bronze')
    html = c.get('/conta', headers=FULANO).get_data(as_text=True)
    assert 'nivel bronze' in html and 'aviso-bronze' in html and 'Desvincular' in html
    r = c.get('/conta/meus-dados.json', headers=FULANO)
    assert r.status_code == 200 and 'attachment' in r.headers['Content-Disposition']
    dados = r.json
    assert dados['email'] == 'fulano@ifc.edu.br' and dados['govbr']['nivel'] == 'bronze'
    assert 'chave' not in r.get_data(as_text=True)  # nem o resumo do CPF sai
    assert c.get('/conta').status_code == 401 and c.get('/conta/meus-dados.json').status_code == 401
