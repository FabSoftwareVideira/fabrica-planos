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
