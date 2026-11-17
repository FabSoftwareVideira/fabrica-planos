"""Área de transparência (servicos/transparencia.py e rotas/transparencia.py): os planos assinados, públicos, com
URL fixa por plano (a versão assinada vigente) e por versão."""
from pathlib import Path

import requests

from conftest import PDF_COM_TEXTO as PDF_NOVO, enviar_plano
from test_web import NDE, _ApiFalsa, _plano_cc, _aprovado_para_assinar, _assinar_pelo_govbr, _resultado, _servicos

HOMOLOGACAO = dict(assinatura_client_id='cli', assinatura_client_secret='seg', segredo_sessao='chave',
                   assinatura_ambiente='homologacao', assinatura_oauth_url='https://cas.staging.iti.br/oauth2.0',
                   assinatura_api_url='https://assinatura-api.staging.iti.br/externo/v2')


def _assinado(fabrica, tmp_path, monkeypatch):
    monkeypatch.setattr(requests, 'post', _ApiFalsa())
    c, dono = _aprovado_para_assinar(fabrica, tmp_path, **HOMOLOGACAO)
    oferta = _servicos(c).disciplinas.do_arquivo('web.pdf')
    return c, dono, oferta['id']


def test_sem_assinatura_nada_e_publicado(fabrica, tmp_path, monkeypatch):
    monkeypatch.setattr(requests, 'post', _ApiFalsa())
    c, _ = _aprovado_para_assinar(fabrica, tmp_path, **HOMOLOGACAO)  # aprovado, mas sem assinar
    id_ = _servicos(c).disciplinas.do_arquivo('web.pdf')['id']
    r = c.get('/transparencia')  # sem login
    assert r.status_code == 200 and 'Ainda não há planos assinados publicados.' in r.get_data(as_text=True)
    assert c.get(f'/transparencia/{id_}').status_code == 404
    assert c.get(f'/transparencia/{id_}.pdf').status_code == 404


def test_plano_assinado_e_publico(fabrica, tmp_path, monkeypatch):
    c, dono, id_ = _assinado(fabrica, tmp_path, monkeypatch)
    assert _resultado(_assinar_pelo_govbr(c, dono)[2])['assinatura'] == 'ok'

    html = c.get('/transparencia').get_data(as_text=True)  # sem login
    assert f'href="/transparencia/{id_}"' in html and 'Desenvolvimento Web I' in html and '1 plano assinado' in html
    assert 'Fulano de Tal' in html and 'fulano@ifc.edu.br' not in html  # nome sim, e-mail nunca

    pagina = c.get(f'/transparencia/{id_}').get_data(as_text=True)
    assert 'Desenvolvimento Web I' in pagina and '(vigente)' in pagina and 'FULANO DE TAL' in pagina
    assert f'href="/transparencia/{id_}/v1.pdf"' in pagina and 'substituída' not in pagina

    for url in (f'/transparencia/{id_}.pdf', f'/transparencia/{id_}/v1.pdf'):
        r = c.get(url)
        assert r.status_code == 200 and r.mimetype == 'application/pdf' and b'(AssinaturaGovBr)' in r.data
        assert '-v1-assinado.pdf' in r.headers['Content-Disposition']
    assert c.get(f'/transparencia/{id_}/v2.pdf').status_code == 404
    assert c.get('/transparencia/999999').status_code == 404
    assert c.get('/transparencia/').headers['Location'].endswith('/transparencia')


def test_filtros(fabrica, tmp_path, monkeypatch):
    c, dono, id_ = _assinado(fabrica, tmp_path, monkeypatch)
    _assinar_pelo_govbr(c, dono)
    achou = f'href="/transparencia/{id_}"'
    for filtro in ('curso=CC', 'periodo=2026.2', 'fase=4', 'q=web', 'q=ccc0723', 'docente=fulano'):
        assert achou in c.get('/transparencia?' + filtro).get_data(as_text=True), filtro
    for filtro in ('curso=IN', 'periodo=2025.1', 'fase=1', 'q=calculo', 'docente=beltrano'):
        html = c.get('/transparencia?' + filtro).get_data(as_text=True)
        assert achou not in html and 'Nenhum plano assinado com esses filtros.' in html, filtro
    assert '<option value="2026.2">' in c.get('/transparencia').get_data(as_text=True)


def test_nova_versao_mantem_a_assinada_publicada(fabrica, tmp_path, monkeypatch):
    """Enquanto a versão nova não é assinada, a URL do plano segue mostrando a anterior, "em atualização"; depois,
    a nova passa a ser a vigente, e a anterior continua no seu link, marcada como substituída."""
    c, dono, id_ = _assinado(fabrica, tmp_path, monkeypatch)
    _assinar_pelo_govbr(c, dono)
    v1 = c.get(f'/transparencia/{id_}.pdf').data

    def ia_fora(*a, **k):
        raise requests.ConnectionError('IA fora do ar nos testes')
    monkeypatch.setattr(requests, 'post', ia_fora)
    r = enviar_plano(c, id_, PDF_NOVO, dono)
    assert r.status_code == 200, r.get_data(as_text=True)
    pagina = c.get(f'/transparencia/{id_}').get_data(as_text=True)
    assert 'Em atualização' in c.get('/transparencia').get_data(as_text=True)
    assert 'versão nova deste plano' in pagina and f'/transparencia/{id_}/v1.pdf' in pagina
    assert c.get(f'/transparencia/{id_}.pdf').data == v1

    # Avaliada, aprovada e assinada a versão 2, ela é a vigente; a 1 segue no seu link, substituída
    _plano_cc(c, Path(_servicos(c).cfg.planos_dir), status='OK')  # a avaliação da IA (simulada)
    c.post('/revisao', headers=NDE, data={'arquivo': 'web.pdf', 'status': 'OK', 'comentario': ''})
    monkeypatch.setattr(requests, 'post', _ApiFalsa())
    assert _resultado(_assinar_pelo_govbr(c, dono)[2])['assinatura'] == 'ok'
    pagina = c.get(f'/transparencia/{id_}').get_data(as_text=True)
    assert f'/transparencia/{id_}/v2.pdf' in pagina and 'versão nova deste plano' not in pagina
    antiga = c.get(f'/transparencia/{id_}/v1').get_data(as_text=True)
    assert 'Esta é a versão 1, substituída' in antiga and '(substituída)' in antiga
    assert c.get(f'/transparencia/{id_}/v1.pdf').data == v1
    assert c.get(f'/transparencia/{id_}.pdf').data != v1
    assert c.get(f'/transparencia/{id_}/v9').status_code == 404


def test_zip_da_coordenacao_so_com_assinados_dos_cursos_que_coordena(fabrica, tmp_path, monkeypatch):
    import io
    import zipfile
    from test_web import _dar_papel
    c, dono, id_ = _assinado(fabrica, tmp_path, monkeypatch)
    _dar_papel(c, 'coord@ifc.edu.br', papel='coordenador')  # de CC
    _dar_papel(c, 'coord.in@ifc.edu.br', curso='IN', papel='coordenador')
    coord, outro = {'X-Usuario-Email': 'coord@ifc.edu.br'}, {'X-Usuario-Email': 'coord.in@ifc.edu.br'}
    url = '/coordenacao/assinados.zip?curso=CC&periodo=2026.2'

    # Aprovado, mas ainda sem assinatura: nada a exportar
    assert 'assinados.zip' not in c.get('/coordenacao?curso=CC&periodo=2026.2', headers=coord).get_data(as_text=True)
    assert c.get(url, headers=coord).status_code == 404

    _assinar_pelo_govbr(c, dono)
    html = c.get('/coordenacao?curso=CC&periodo=2026.2', headers=coord).get_data(as_text=True)
    assert 'href="/coordenacao/assinados.zip?curso=CC&amp;periodo=2026.2"' in html and '1 plano assinado' in html
    assert '/csv' not in html and 'CSV' not in html
    r = c.get(url, headers=coord)
    assert r.status_code == 200 and r.mimetype == 'application/zip'
    assert 'planos-assinados-cc-2026.2.zip' in r.headers['Content-Disposition']
    with zipfile.ZipFile(io.BytesIO(r.data)) as z:
        [nome] = z.namelist()
        assert nome == '2026.2-CCC0723-T01-desenvolvimento-web-i-v1-assinado.pdf'
        assert z.read(nome) == c.get(f'/transparencia/{id_}.pdf').data  # o assinado, não o original
    assert c.get('/coordenacao/assinados.zip?curso=CC', headers=coord).status_code == 200  # todos os períodos

    # Quem não coordena o curso não exporta: outro coordenador, NDE, docente
    for cab in (outro, NDE, dono):
        assert c.get(url, headers=cab).status_code == 403
    assert c.get('/coordenacao/assinados.zip', headers=coord).status_code == 403  # sem curso
    assert c.get(url, headers={'X-Usuario-Email': 'admin@ifc.edu.br'}).status_code == 200  # administração


def test_versao_nova_nao_herda_aprovacao_nem_assinatura(fabrica, tmp_path, monkeypatch):
    """Mesmo com o mesmo tamanho e a mesma data (em segundos) do PDF anterior, a versão nova começa sem a
    revisão e a assinatura dele (que ficam no histórico)."""
    import os
    c, dono, id_ = _assinado(fabrica, tmp_path, monkeypatch)
    _assinar_pelo_govbr(c, dono)
    caminho = Path(_servicos(c).cfg.planos_dir) / 'web.pdf'
    antes = os.stat(caminho)

    def ia_fora(*a, **k):
        raise requests.ConnectionError('IA fora do ar nos testes')
    monkeypatch.setattr(requests, 'post', ia_fora)
    assert enviar_plano(c, id_, caminho.read_bytes(), dono).status_code == 200  # mesmo conteúdo e tamanho
    os.utime(caminho, (antes.st_atime, antes.st_mtime))  # e a mesma data: o carimbo antigo
    s = _servicos(c)
    assert s.revisao.vigente('web.pdf') is None and s.assinaturas.vigente('web.pdf') is None
    [plano] = c.get('/meus-planos/lista', headers=dono).json['planos']
    assert plano['assinatura'] is None and [v['numero'] for v in plano['versoes']] == [1]
    assert plano['versoes'][0]['signatario'] == 'FULANO DE TAL'  # a assinada ficou no histórico
    assert c.get(f'/transparencia/{id_}/v1.pdf').status_code == 200
