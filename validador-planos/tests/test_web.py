import io
import os

os.environ.setdefault('AGENDAR', '0')  # antes de importar app.web, para não subir o agendador

import pytest

from app import web
from app.andamento import Andamento
from app.config import Config

PDF = b'%PDF-1.4 conteudo'


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    planos = tmp_path / 'planos'
    planos.mkdir()
    cfg = Config(
        planos_dir=str(planos), resultados_dir=str(tmp_path / 'res'),
        ollama_url='http://ollama:11434', modelo='m', num_ctx=1, hora_agendada=5, agendar=False,
    )
    monkeypatch.setattr(web, 'cfg', cfg)
    monkeypatch.setattr(web, 'andamento', Andamento())
    return web.app.test_client(), planos


def _envio(*arquivos):
    return {'arquivos': [(io.BytesIO(conteudo), nome) for nome, conteudo in arquivos]}


def test_upload_lista_e_exclui(cliente):
    c, planos = cliente
    r = c.post('/planos', data=_envio(('Plano Á.pdf', PDF), ('b.pdf', PDF)), content_type='multipart/form-data')
    assert r.status_code == 200
    assert [s['nome'] for s in r.json['salvos']] == ['Plano Á.pdf', 'b.pdf']
    assert (planos / 'Plano Á.pdf').read_bytes() == PDF

    assert [p['nome'] for p in c.get('/planos').json['planos']] == ['Plano Á.pdf', 'b.pdf']

    r = c.post('/planos', data=_envio(('b.pdf', PDF)), content_type='multipart/form-data')
    assert r.json['salvos'] == [{'nome': 'b.pdf', 'substituido': True}]

    assert c.delete('/planos?arquivo=b.pdf').status_code == 200
    assert not (planos / 'b.pdf').exists()
    assert c.delete('/planos?arquivo=b.pdf').status_code == 404


def test_upload_recusa_nome_e_conteudo_invalidos(cliente):
    c, planos = cliente
    r = c.post('/planos', data=_envio(('x.txt', PDF), ('falso.pdf', b'nao e pdf'), ('../fora.pdf', PDF)),
               content_type='multipart/form-data')
    assert r.status_code == 200  # '../fora.pdf' vira 'fora.pdf', dentro da pasta
    assert [s['nome'] for s in r.json['salvos']] == ['fora.pdf']
    assert {x['nome'] for x in r.json['recusados']} == {'x.txt', 'falso.pdf'}
    assert sorted(os.listdir(planos)) == ['fora.pdf']


def test_exclusao_recusa_caminho(cliente):
    c, _ = cliente
    assert c.delete('/planos?arquivo=../x.pdf').status_code == 400


def test_validacao_em_andamento_bloqueia_alteracoes(cliente):
    c, planos = cliente
    (planos / 'a.pdf').write_bytes(PDF)
    web.andamento.iniciar(1)
    assert c.post('/validar').status_code == 409
    assert c.post('/planos', data=_envio(('b.pdf', PDF)), content_type='multipart/form-data').status_code == 409
    assert c.delete('/planos?arquivo=a.pdf').status_code == 409
    status = c.get('/status').json
    assert status['rodando'] and status['total'] == 1


def test_validar_sem_planos(cliente):
    c, _ = cliente
    assert c.post('/validar').status_code == 422
    assert not c.get('/status').json['rodando']


def test_dashboard_tem_controles(cliente):
    c, _ = cliente
    html = c.get('/dashboard').get_data(as_text=True)
    assert 'id="validar"' in html and 'id="soltar"' in html


def _resultado(planos_dir, cfg):
    from app import csvsaida
    validacao = {'status_geral': 'PENDENTE', 'obs_geral': 'falta algo',
                 'ementa': {'status': 'OK', 'obs': 'ementa boa'}}
    csvsaida.escrever_csv(cfg.csv_path, [csvsaida.linha_resultado('Plano Á.pdf', str(planos_dir), validacao)])


def test_relatorio_mostra_avaliacao_e_texto_extraido(cliente):
    from app import detalhes
    c, planos = cliente
    _resultado(planos, web.cfg)
    detalhes.salvar(web.cfg.detalhes_dir, 'Plano Á.pdf', {
        'arquivo': 'Plano Á.pdf', 'modelo': 'qwen', 'texto': 'TEXTO <BRUTO>',
        'secoes': {'ementa': 'Estudo de <matrizes>', 'ref_basicas': 2, 'ref_complementares': 5},
        'prompt': 'PROMPT', 'resposta_ia': '{"ementa": {"status": "OK"}}',
    })
    html = c.get('/relatorio?arquivo=Plano%20%C3%81.pdf').get_data(as_text=True)
    assert 'ementa boa' in html
    assert 'Estudo de &lt;matrizes&gt;' in html  # texto escapado
    assert 'TEXTO &lt;BRUTO&gt;' in html and 'PROMPT' in html
    assert '<strong>2</strong> básica(s)' in html
    assert 'Nada foi extraído' in html  # campos sem texto


def test_relatorio_sem_detalhes_avisa(cliente):
    c, planos = cliente
    _resultado(planos, web.cfg)
    r = c.get('/relatorio?arquivo=Plano%20%C3%81.pdf')
    assert r.status_code == 200
    assert 'Rode a validação de novo' in r.get_data(as_text=True)


def test_relatorio_de_plano_desconhecido(cliente):
    c, _ = cliente
    assert c.get('/relatorio?arquivo=x.pdf').status_code == 404
    assert c.get('/relatorio?arquivo=../x.pdf').status_code == 404
