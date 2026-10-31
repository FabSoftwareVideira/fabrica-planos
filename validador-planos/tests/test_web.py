import io
import os
from pathlib import Path

os.environ.setdefault('AGENDAR', '0')  # antes de importar app.web, para não subir o agendador

import pytest

from app import web
from app.andamento import Andamento
from app.config import Config
from conftest import PDF_COM_TEXTO, PDF_SEM_TEXTO

PDF = PDF_COM_TEXTO


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    planos = tmp_path / 'planos'
    planos.mkdir()
    cfg = Config(
        planos_dir=str(planos), resultados_dir=str(tmp_path / 'res'),
        ollama_url='http://ollama:11434', modelo='m', num_ctx=1, hora_agendada=5, agendar=False, pdf_max_mb=1,
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


def test_upload_recusa_pdf_grande_digitalizado_ou_corrompido(cliente):
    c, planos = cliente
    grande = PDF + b'%' + b'0' * (1024 * 1024)
    r = c.post('/planos', data=_envio(('grande.pdf', grande), ('scan.pdf', PDF_SEM_TEXTO),
                                      ('quebrado.pdf', b'%PDF-1.4 lixo'), ('bom.pdf', PDF)),
               content_type='multipart/form-data')
    motivos = {x['nome']: x['motivo'] for x in r.json['recusados']}
    assert 'maior que 1 MB' in motivos['grande.pdf']
    assert 'OCR' in motivos['scan.pdf']
    assert 'não pôde ser aberto' in motivos['quebrado.pdf']
    assert [s['nome'] for s in r.json['salvos']] == ['bom.pdf']
    assert sorted(os.listdir(planos)) == ['bom.pdf']  # nenhum temporário sobra


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


def _execucao(nomes, quando, validacao=None, pdfs=()):
    """Cria no histórico uma validação concluída com esses planos."""
    from datetime import datetime

    from app import csvsaida, historico
    validacao = validacao or {'status_geral': 'OK'}
    execucao = historico.criar(web.cfg.historico_dir, datetime(2026, 10, 30, quando))
    linhas = [csvsaida.linha_resultado(n, '/x', validacao) for n in nomes]
    csvsaida.escrever_csv(execucao.csv_path, linhas)
    for nome in pdfs:
        (Path(execucao.pdfs_dir) / nome).write_bytes(PDF)
    historico.gravar_meta(execucao, {'finalizado_em': f'2026-10-30T{quando:02d}:30:00', 'total': len(linhas),
                                     'processados': len(linhas), 'erro': '', 'modelo': 'm', **historico.contar(linhas)})
    return execucao


def test_relatorio_mostra_avaliacao_e_texto_extraido(cliente):
    from app import detalhes
    c, _ = cliente
    validacao = {'status_geral': 'PENDENTE', 'obs_geral': 'falta algo', 'ementa': {'status': 'OK', 'obs': 'ementa boa'}}
    execucao = _execucao(['Plano Á.pdf'], 10, validacao)
    detalhes.salvar(execucao.detalhes_dir, 'Plano Á.pdf', {
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
    c, _ = cliente
    _execucao(['Plano Á.pdf'], 10)
    r = c.get('/relatorio?arquivo=Plano%20%C3%81.pdf')
    assert r.status_code == 200
    assert 'texto extraído não está disponível' in r.get_data(as_text=True)


def test_relatorio_navega_entre_planos_e_volta_ao_card(cliente):
    c, _ = cliente
    execucao = _execucao(['a.pdf', 'b.pdf', 'c.pdf'], 10)
    html = c.get('/relatorio?arquivo=b.pdf').get_data(as_text=True)
    assert 'href="/dashboard#plano-1"' in html
    v = 'validacao=' + execucao.id
    assert f'href="/relatorio?{v}&arquivo=a.pdf"' in html and f'href="/relatorio?{v}&arquivo=c.pdf"' in html
    assert 'Plano 2 de 3' in html
    primeiro = c.get('/relatorio?arquivo=a.pdf').get_data(as_text=True)
    assert '<span class="off">‹ Anterior</span>' in primeiro

    dashboard = c.get('/dashboard').get_data(as_text=True)
    assert 'id="plano-1"' in dashboard and 'const MAX_MB = 1, ADMIN = true;' in dashboard


def test_relatorio_de_plano_desconhecido(cliente):
    c, _ = cliente
    assert c.get('/relatorio?arquivo=x.pdf').status_code == 404
    _execucao(['a.pdf'], 10)
    assert c.get('/relatorio?arquivo=x.pdf').status_code == 404
    assert c.get('/relatorio?arquivo=../x.pdf').status_code == 404
    assert c.get('/relatorio?validacao=20200101-000000&arquivo=a.pdf').status_code == 404


def test_dashboard_mostra_historico_e_validacao_anterior(cliente):
    c, _ = cliente
    antiga = _execucao(['velho.pdf'], 9)
    nova = _execucao(['novo.pdf'], 11, pdfs=['novo.pdf'])
    html = c.get('/dashboard').get_data(as_text=True)
    assert 'novo' in html and 'velho' not in html.split('id="historico"')[1].split('</select>')[1]
    assert f'/validacoes/{nova.id}/pdfs.zip' in html and f'/validacoes/{nova.id}/csv' in html
    assert '(última)' in html

    html = c.get('/dashboard?validacao=' + antiga.id).get_data(as_text=True)
    assert 'Você está vendo uma validação anterior' in html
    assert 'pdfs.zip' not in html  # PDFs antigos não são guardados
    assert '>📄 Abrir PDF<' not in html
    relatorio = c.get(f'/relatorio?validacao={antiga.id}&arquivo=velho.pdf').get_data(as_text=True)
    assert f'href="/dashboard?validacao={antiga.id}#plano-0"' in relatorio

    assert c.get('/dashboard?validacao=20200101-000000').status_code == 302


def test_zip_csv_e_pdf_da_ultima_validacao(cliente):
    import io
    import zipfile
    c, _ = cliente
    antiga = _execucao(['a.pdf'], 9)
    nova = _execucao(['a.pdf', 'b.pdf'], 10, pdfs=['a.pdf', 'b.pdf'])

    r = c.get(f'/validacoes/{nova.id}/pdfs.zip')
    assert r.status_code == 200 and r.mimetype == 'application/zip'
    assert f'planos-validacao-{nova.id}.zip' in r.headers['Content-Disposition']
    with zipfile.ZipFile(io.BytesIO(r.data)) as z:
        assert sorted(z.namelist()) == ['a.pdf', 'b.pdf']
        assert z.read('a.pdf') == PDF

    assert c.get(f'/validacoes/{antiga.id}/pdfs.zip').status_code == 404
    assert c.get(f'/validacoes/{antiga.id}/csv').data.startswith('﻿'.encode())  # BOM do CSV
    assert c.get(f'/validacoes/{nova.id}/pdf?arquivo=b.pdf').data == PDF
    assert c.get(f'/validacoes/{antiga.id}/pdf?arquivo=a.pdf').status_code == 404
    assert c.get('/validacoes/..%2Fx/csv').status_code == 404
    assert [v['id'] for v in c.get('/validacoes').json['validacoes']] == [nova.id, antiga.id]


def test_excluir_todos(cliente):
    c, planos = cliente
    for nome in ('a.pdf', 'b.pdf'):
        (planos / nome).write_bytes(PDF)
    web.andamento.iniciar(1)
    assert c.delete('/planos/todos').status_code == 409
    web.andamento.finalizar()
    r = c.delete('/planos/todos')
    assert r.json == {'excluidos': 2}
    assert list(planos.iterdir()) == []


def test_revalidar_pela_rota(cliente, monkeypatch):
    from app import pipeline
    c, planos = cliente
    chamadas = []
    monkeypatch.setattr(pipeline, 'revalidar', lambda cfg, andamento, nome: chamadas.append(nome))
    assert c.post('/validar?arquivo=sumiu.pdf').status_code == 404
    assert c.post('/validar?arquivo=../x.pdf').status_code == 400
    (planos / 'a.pdf').write_bytes(PDF)
    r = c.post('/validar?arquivo=a.pdf')
    assert r.json == {'status': 'iniciado', 'arquivo': 'a.pdf'}
    web.andamento.finalizar()
    assert chamadas == ['a.pdf']
    assert web.andamento.resumo()['unico'] == 'a.pdf'


def test_dashboard_tem_filtros_e_revalidar_so_na_ultima(cliente):
    c, planos = cliente
    validacao = {'status_geral': 'PENDENTE', 'horario_atendimento': {'status': 'INCOMPLETO', 'obs': ''}}
    antiga = _execucao(['a.pdf'], 9)
    _execucao(['a.pdf', 'b.pdf'], 10, validacao)
    html = c.get('/dashboard').get_data(as_text=True)
    assert 'id="busca"' in html and 'data-status="PENDENTE"' in html
    assert 'Pendentes (2)' in html and '<option value="Horário Atendimento">' in html
    assert 'class="revalidar" data-arquivo="a.pdf"' in html
    assert 'class="revalidar"' not in c.get('/dashboard?validacao=' + antiga.id).get_data(as_text=True)

    (planos / 'a.pdf').write_bytes(PDF)
    assert 'id="revalidar"' in c.get('/relatorio?arquivo=a.pdf').get_data(as_text=True)
    assert 'id="revalidar"' not in c.get('/relatorio?arquivo=b.pdf').get_data(as_text=True)  # não está na pasta


@pytest.fixture
def com_login(cliente, monkeypatch):
    """Login exigido, com admin@ifc.edu.br como único administrador."""
    from dataclasses import replace
    monkeypatch.setattr(web, 'cfg', replace(web.cfg, exigir_login=True, admins=frozenset({'admin@ifc.edu.br'})))
    return cliente


ADMIN = {'X-Usuario-Email': 'Admin@ifc.edu.br'}
SERVIDOR = {'X-Usuario-Email': 'fulano@ifc.edu.br'}


def test_sem_login_so_responde_inicio_e_health(com_login):
    c, _ = com_login
    assert c.get('/dashboard').status_code == 401
    assert c.get('/planos').status_code == 401
    assert c.post('/validar').status_code == 401
    assert c.get('/health').status_code == 200
    inicio = c.get('/')
    assert inicio.status_code == 200
    html = inicio.get_data(as_text=True)
    assert 'href="/dashboard"' in html and 'Entrar com Google' in html and 'Horário Atendimento' in html


def test_servidor_consulta_mas_nao_administra(com_login):
    c, planos = com_login
    (planos / 'a.pdf').write_bytes(PDF)
    _execucao(['a.pdf'], 10)
    html = c.get('/dashboard', headers=SERVIDOR).get_data(as_text=True)
    assert 'fulano@ifc.edu.br · consulta' in html and 'href="/oauth2/sign_out"' in html
    assert 'id="validar"' not in html and 'id="soltar"' not in html and 'class="revalidar"' not in html
    assert 'ADMIN = false;' in html
    assert 'id="revalidar"' not in c.get('/relatorio?arquivo=a.pdf', headers=SERVIDOR).get_data(as_text=True)
    assert c.get('/pdf?arquivo=a.pdf', headers=SERVIDOR).status_code == 200

    assert c.post('/validar', headers=SERVIDOR).status_code == 403
    assert c.post('/validar?arquivo=a.pdf', headers=SERVIDOR).status_code == 403
    assert c.post('/planos', headers=SERVIDOR, data=_envio(('b.pdf', PDF)),
                  content_type='multipart/form-data').status_code == 403
    assert c.delete('/planos?arquivo=a.pdf', headers=SERVIDOR).status_code == 403
    assert c.delete('/planos/todos', headers=SERVIDOR).status_code == 403
    assert (planos / 'a.pdf').exists()


def test_admin_administra(com_login):
    c, planos = com_login
    html = c.get('/dashboard', headers=ADMIN).get_data(as_text=True)
    assert 'admin@ifc.edu.br · administrador' in html and 'id="validar"' in html and 'id="soltar"' in html
    r = c.post('/planos', headers=ADMIN, data=_envio(('b.pdf', PDF)), content_type='multipart/form-data')
    assert r.status_code == 200
    assert c.delete('/planos?arquivo=b.pdf', headers=ADMIN).status_code == 200
