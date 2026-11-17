"""Brechas corrigidas na revisão de segurança: acesso ao app sem passar pelo Caddy, redirecionamento para fora
depois do login e fórmulas no CSV exportado."""
from app.armazenamento import csvsaida

PROXY = {'X-Planos-Proxy': 'segredo-do-caddy'}
ADMIN = {'X-Usuario-Email': 'admin@ifc.edu.br'}


def test_sem_o_segredo_do_caddy_ninguem_e_atendido(fabrica):
    """O app também está na rede do Ollama: quem o alcança direto não pode forjar X-Usuario-Email."""
    c, _ = fabrica(exigir_login=True, admins=frozenset({'admin@ifc.edu.br'}), proxy_segredo='segredo-do-caddy')
    assert c.get('/dashboard', headers=ADMIN).status_code == 403  # e-mail forjado, sem o segredo
    assert c.get('/dashboard', headers={**ADMIN, 'X-Planos-Proxy': 'outro'}).status_code == 403
    assert c.get('/auth/verificar').status_code == 403
    assert c.get('/transparencia').status_code == 403
    assert c.post('/validar', headers=ADMIN).status_code == 403
    assert c.get('/health').status_code == 200  # healthcheck do contêiner, direto no app
    assert c.get('/dashboard', headers={**ADMIN, **PROXY}).status_code == 200
    assert c.get('/transparencia', headers=PROXY).status_code == 200


def test_sem_segredo_configurado_nao_confere(fabrica):
    c, _ = fabrica(exigir_login=True, admins=frozenset({'admin@ifc.edu.br'}))
    assert c.get('/dashboard', headers=ADMIN).status_code == 200


def test_destino_do_login_so_neste_site():
    from app.rotas.govbr import destino
    for ruim in ('//evil.com', '/\evil.com', '/\t/evil.com', '/\n/evil.com', '/\r/evil.com', '/\x00x',
                 '/\x7f/evil.com', 'https://evil.com', 'evil.com', '', None):
        assert destino(ruim) == '/dashboard', repr(ruim)
    for bom in ('/meus-planos', '/relatorio?arquivo=a.pdf', '/transparencia/12'):
        assert destino(bom) == bom


def test_login_govbr_nao_leva_para_fora(fabrica):
    from test_web import GOVBR
    c, _ = fabrica(**GOVBR)
    r = c.get('/auth/govbr/login?rd=/%09/evil.com')
    assert r.status_code == 302
    from urllib.parse import parse_qs, urlsplit
    assert c.get_cookie('_planos_govbr_login') is not None
    assert 'evil' not in str(parse_qs(urlsplit(r.headers['Location']).query))


def test_csv_exportado_sem_formulas():
    linha = {'Arquivo': 'a.pdf', 'Observação Geral': '=HYPERLINK("http://evil","x")', 'Ementa Obs': '+1+1',
             'Metodologia Obs': '-2', 'Cronograma Obs': '@SUM(A1)', 'Referências Obs': 'normal'}
    texto = csvsaida.csv_em_bytes([linha]).decode('utf-8-sig')
    assert '"\'=HYPERLINK' in texto and '"\'+1+1"' in texto and '"\'-2"' in texto and '"\'@SUM(A1)"' in texto
    assert '"normal"' in texto
    assert csvsaida.sem_formula(None) == '' and csvsaida.sem_formula(3) == '3'


def test_csv_completo_da_validacao_tambem_sem_formulas(fabrica):
    from test_web import _execucao
    c, _ = fabrica(exigir_login=True, admins=frozenset({'admin@ifc.edu.br'}))
    execucao = _execucao(c, ['a.pdf'], 10, {'status_geral': 'OK', 'obs_geral': '=1+1'})
    r = c.get(f'/validacoes/{execucao.id}/csv', headers=ADMIN)
    assert r.status_code == 200 and '"\'=1+1"' in r.get_data(as_text=True)
