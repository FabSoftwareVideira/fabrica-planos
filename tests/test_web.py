import io
import os
from pathlib import Path

import pytest

from app.config import Config
from app.fabrica import criar_app
from conftest import PDF_COM_TEXTO, PDF_SEM_TEXTO

PDF = PDF_COM_TEXTO


@pytest.fixture
def fabrica(tmp_path):
    """Cria a aplicação com pastas temporárias; as avaliações rodam na hora, sem thread."""
    def criar(**opcoes):
        planos = tmp_path / 'planos'
        planos.mkdir(exist_ok=True)
        cfg = Config(
            planos_dir=str(planos), resultados_dir=str(tmp_path / 'res'), ollama_url='http://ollama:11434',
            modelo='m', num_ctx=1, hora_agendada=5, agendar=False, pdf_max_mb=1, **opcoes,
        )
        return criar_app(cfg, executar=lambda tarefa: tarefa()).test_client(), planos
    return criar


@pytest.fixture
def cliente(fabrica):
    return fabrica()


def _servicos(c):
    return c.application.extensions['servicos']


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
    _servicos(c).validador.andamento.iniciar(1)
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
    assert 'id="validar"' in html and 'id="soltar"' not in html  # envio de PDFs fica na administração
    adm = c.get('/administracao').get_data(as_text=True)
    assert 'id="soltar"' in adm and 'id="lista"' in adm and 'id="validar"' in adm


def _execucao(c, nomes, quando, validacao=None, pdfs=()):
    """Cria no histórico uma validação concluída com esses planos."""
    from datetime import datetime

    from app.armazenamento import csvsaida, historico
    validacao = validacao or {'status_geral': 'OK'}
    execucao = historico.criar(_servicos(c).cfg.historico_dir, datetime(2026, 10, 30, quando))
    linhas = [csvsaida.linha_resultado(n, '/x', validacao) for n in nomes]
    csvsaida.escrever_csv(execucao.csv_path, linhas)
    for nome in pdfs:
        (Path(execucao.pdfs_dir) / nome).write_bytes(PDF)
    historico.gravar_meta(execucao, {'finalizado_em': f'2026-10-30T{quando:02d}:30:00', 'total': len(linhas),
                                     'processados': len(linhas), 'erro': '', 'modelo': 'm', **historico.contar(linhas)})
    return execucao


def test_relatorio_mostra_avaliacao_e_texto_extraido(cliente):
    from app.armazenamento import detalhes
    c, _ = cliente
    validacao = {'status_geral': 'PENDENTE', 'obs_geral': 'falta algo', 'ementa': {'status': 'OK', 'obs': 'ementa boa'}}
    execucao = _execucao(c, ['Plano Á.pdf'], 10, validacao)
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
    _execucao(c, ['Plano Á.pdf'], 10)
    r = c.get('/relatorio?arquivo=Plano%20%C3%81.pdf')
    assert r.status_code == 200
    assert 'texto extraído não está disponível' in r.get_data(as_text=True)


def test_relatorio_navega_entre_planos_e_volta_ao_card(cliente):
    c, _ = cliente
    execucao = _execucao(c, ['a.pdf', 'b.pdf', 'c.pdf'], 10)
    html = c.get('/relatorio?arquivo=b.pdf').get_data(as_text=True)
    assert 'href="/dashboard#plano-1"' in html
    assert 'href="/relatorio?arquivo=a.pdf"' in html and 'href="/relatorio?arquivo=c.pdf"' in html
    assert 'Plano 2 de 3' in html
    primeiro = c.get('/relatorio?arquivo=a.pdf').get_data(as_text=True)
    assert '<span class="off">‹ Anterior</span>' in primeiro

    dashboard = c.get('/dashboard').get_data(as_text=True)
    assert 'id="plano-1"' in dashboard and 'const MAX_MB = 1, ADMIN = true, EXPORTAR = true;' in dashboard


def test_relatorio_de_plano_desconhecido(cliente):
    c, _ = cliente
    assert c.get('/relatorio?arquivo=x.pdf').status_code == 404
    _execucao(c, ['a.pdf'], 10)
    assert c.get('/relatorio?arquivo=x.pdf').status_code == 404
    assert c.get('/relatorio?arquivo=../x.pdf').status_code == 404


def test_dashboard_mostra_so_a_validacao_atual(cliente):
    c, _ = cliente
    _execucao(c, ['velho.pdf'], 9)
    nova = _execucao(c, ['novo.pdf'], 11, pdfs=['novo.pdf'])
    html = c.get('/dashboard').get_data(as_text=True)
    assert 'novo.pdf' in html and 'velho.pdf' not in html
    assert 'id="historico"' not in html  # sem seletor de validações anteriores
    assert f'/validacoes/{nova.id}/pdfs.zip' in html and f'/validacoes/{nova.id}/csv' in html
    assert 'href="/dashboard#plano-0"' in c.get('/relatorio?arquivo=novo.pdf').get_data(as_text=True)
    assert c.get('/relatorio?arquivo=velho.pdf').status_code == 404


def test_zip_csv_e_pdf_da_ultima_validacao(cliente):
    import io
    import zipfile
    c, _ = cliente
    antiga = _execucao(c, ['a.pdf'], 9)
    nova = _execucao(c, ['a.pdf', 'b.pdf'], 10, pdfs=['a.pdf', 'b.pdf'])

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
    _servicos(c).validador.andamento.iniciar(1)
    assert c.delete('/planos/todos').status_code == 409
    _servicos(c).validador.andamento.finalizar()
    r = c.delete('/planos/todos')
    assert r.json == {'excluidos': 2}
    assert list(planos.iterdir()) == []


def test_revalidar_pela_rota(cliente, monkeypatch):
    from app.avaliacao import pipeline
    c, planos = cliente
    chamadas = []
    monkeypatch.setattr(pipeline, 'revalidar', lambda cfg, andamento, nome: chamadas.append(nome))
    assert c.post('/validar?arquivo=sumiu.pdf').status_code == 404
    assert c.post('/validar?arquivo=../x.pdf').status_code == 400
    (planos / 'a.pdf').write_bytes(PDF)
    r = c.post('/validar?arquivo=a.pdf')
    assert r.json == {'status': 'iniciado', 'arquivo': 'a.pdf', 'posicao': 0}
    _servicos(c).validador.andamento.finalizar()
    assert chamadas == ['a.pdf']
    assert _servicos(c).validador.andamento.resumo()['unico'] == 'a.pdf'


def test_dashboard_tem_filtros_e_revalidar(cliente):
    c, planos = cliente
    validacao = {'status_geral': 'PENDENTE', 'horario_atendimento': {'status': 'INCOMPLETO', 'obs': ''}}
    _execucao(c, ['a.pdf', 'b.pdf'], 10, validacao)
    html = c.get('/dashboard').get_data(as_text=True)
    assert 'id="busca"' in html and 'data-status="PENDENTE"' in html
    assert 'Pendentes (2)' in html and 'id="campo"' not in html and 'id="revisao"' not in html
    assert 'class="revalidar" data-arquivo="a.pdf"' in html

    (planos / 'a.pdf').write_bytes(PDF)
    assert 'id="revalidar"' in c.get('/relatorio?arquivo=a.pdf').get_data(as_text=True)
    assert 'id="revalidar"' not in c.get('/relatorio?arquivo=b.pdf').get_data(as_text=True)  # não está na pasta


@pytest.fixture
def com_login(fabrica):
    """Login exigido, com admin@ifc.edu.br como único administrador."""
    return fabrica(exigir_login=True, admins=frozenset({'admin@ifc.edu.br'}))


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
    _execucao(c, ['a.pdf'], 10)
    html = c.get('/dashboard', headers=SERVIDOR).get_data(as_text=True)
    # Quem está logado e o papel aparecem no cabeçalho
    assert 'fulano@ifc.edu.br' in html and 'papel-usuario">Consulta<' in html and 'href="/oauth2/sign_out"' in html
    assert 'id="validar"' not in html and 'id="soltar"' not in html and 'class="revalidar"' not in html
    assert 'ADMIN = false,' in html and 'href="/meus-planos"' in html and 'href="/administracao"' not in html
    r = c.get('/administracao', headers=SERVIDOR)
    assert r.status_code == 302 and r.headers['Location'].endswith('/dashboard')
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
    assert 'admin@ifc.edu.br' in html and 'papel-usuario">Administrador<' in html and 'id="validar"' in html
    assert 'href="/administracao"' in html
    assert 'id="soltar"' in c.get('/administracao', headers=ADMIN).get_data(as_text=True)
    r = c.post('/planos', headers=ADMIN, data=_envio(('b.pdf', PDF)), content_type='multipart/form-data')
    assert r.status_code == 200
    assert c.delete('/planos?arquivo=b.pdf', headers=ADMIN).status_code == 200


def test_revalidacoes_esperam_na_fila(cliente, monkeypatch):
    from app.avaliacao import pipeline
    c, planos = cliente
    chamadas = []
    monkeypatch.setattr(pipeline, 'revalidar', lambda cfg, andamento, nome: chamadas.append(nome))
    for nome in ('a.pdf', 'b.pdf'):
        (planos / nome).write_bytes(PDF)
    _servicos(c).validador.andamento.iniciar(1)  # outra validação rodando
    assert c.post('/validar?arquivo=a.pdf').json == {'status': 'na_fila', 'arquivo': 'a.pdf', 'posicao': 1}
    assert c.post('/validar?arquivo=b.pdf').json['posicao'] == 2
    assert c.post('/validar?arquivo=a.pdf').json['posicao'] == 1  # não entra duas vezes
    assert c.get('/status').json['fila'] == ['a.pdf', 'b.pdf']
    (planos / 'a.pdf').unlink()  # excluído enquanto esperava: é pulado
    _servicos(c).validador.andamento.finalizar()
    _servicos(c).validador.proximo_da_fila()
    assert chamadas == ['b.pdf'] and c.get('/status').json['fila'] == []


def test_professor_entrega_e_acompanha_o_proprio_plano(com_login, monkeypatch):
    from app.armazenamento import detalhes
    from app.avaliacao import pipeline
    c, planos = com_login
    chamadas = []
    monkeypatch.setattr(pipeline, 'revalidar', lambda cfg, andamento, nome: (chamadas.append(nome), andamento.finalizar()))
    assert 'id="soltar"' in c.get('/meus-planos', headers=SERVIDOR).get_data(as_text=True)

    r = c.post('/meus-planos', headers=SERVIDOR, data=_envio(('meu.pdf', PDF)), content_type='multipart/form-data')
    assert r.json['salvos'] == [{'nome': 'meu.pdf', 'substituido': False, 'posicao': 0}]
    assert chamadas == ['meu.pdf'] and (planos / 'meu.pdf').exists()
    [plano] = c.get('/meus-planos/lista', headers=SERVIDOR).json['planos']
    assert plano['situacao'] == 'aguardando'  # a avaliação falsa não gravou resultado

    execucao = _execucao(c, ['meu.pdf'], 23, {'status_geral': 'PENDENTE'})
    detalhes.salvar(execucao.detalhes_dir, 'meu.pdf', {'validado_em': '2099-01-01T00:00:00'})
    [plano] = c.get('/meus-planos/lista', headers=SERVIDOR).json['planos']
    assert plano['situacao'] == 'avaliado' and plano['status'] == 'PENDENTE' and 'Ementa' in plano['problemas']

    # Outra pessoa não vê o plano na lista dela, nem o substitui ou exclui
    assert c.get('/meus-planos/lista', headers=ADMIN).json['planos'] == []
    r = c.post('/meus-planos', headers=ADMIN, data=_envio(('meu.pdf', PDF)), content_type='multipart/form-data')
    assert r.status_code == 400 and 'outra pessoa' in r.json['recusados'][0]['motivo']
    assert c.delete('/meus-planos?arquivo=meu.pdf', headers=ADMIN).status_code == 403
    assert c.get('/planos', headers=ADMIN).json['planos'][0]['dono'] == 'fulano@ifc.edu.br'

    # O dono substitui e exclui
    r = c.post('/meus-planos', headers=SERVIDOR, data=_envio(('meu.pdf', PDF)), content_type='multipart/form-data')
    assert r.json['salvos'][0]['substituido'] and chamadas == ['meu.pdf', 'meu.pdf']
    assert c.delete('/meus-planos?arquivo=meu.pdf', headers=SERVIDOR).status_code == 200
    assert not (planos / 'meu.pdf').exists()
    assert c.get('/meus-planos/lista', headers=SERVIDOR).json['planos'] == []


def test_professor_nao_assume_plano_sem_dono(com_login):
    c, planos = com_login
    (planos / 'antigo.pdf').write_bytes(PDF)  # veio do Drive ou do administrador
    r = c.post('/meus-planos', headers=SERVIDOR, data=_envio(('antigo.pdf', PDF)), content_type='multipart/form-data')
    assert r.status_code == 400
    assert c.delete('/meus-planos?arquivo=antigo.pdf', headers=SERVIDOR).status_code == 403


def test_dashboard_traz_dados_para_agrupar(cliente):
    from app.armazenamento import detalhes
    c, _ = cliente
    execucao = _execucao(c, ['web.pdf', 'design.pdf', 'avulso.pdf'], 10, pdfs=['web.pdf', 'design.pdf'])
    textos = {
        'web.pdf': 'CCC0723 - DESENVOLVIMENTO WEB I (60h) - Turma: 01 (2026.2)\n'
                   'Matrícula Docente(s)\n1773245 FULANO DE TAL - 60h\n',
        'design.pdf': 'INC0713-1 - WEB DESIGN (60h) - Turma: 03 (2026)\n'
                      'Turma: [TÉCNICO EM INFORMÁTICA INTEGRADO AO ENSINO MÉDIO - IN07 (MT) - A (2026)]',
    }
    for nome, texto in textos.items():  # sem 'identificacao_plano': como uma validação antiga
        detalhes.salvar(execucao.detalhes_dir, nome, {'texto': texto})
    html = c.get('/dashboard').get_data(as_text=True)
    assert '<select id="agrupar">' in html and '<option value="docente">Docente</option>' in html
    assert f'id="resultados" data-validacao="{execucao.id}"' in html
    assert ('data-pdf="1" data-cp="CC|2026.2" data-cp-titulo="Ciência da Computação · 2º semestre de 2026"'
            in html)
    assert 'data-periodo="2026" data-periodo-titulo="2026 (anual)"' in html
    assert 'data-docente="Fulano de Tal"' in html and 'data-cp="-"' in html
    assert 'CCC0723 · Desenvolvimento Web I · Turma 01 · 60h · Fulano de Tal' in html
    # Filtro de curso e período na ordem dos grupos; os sem identificação no fim
    opcoes = [html.index(f'<option value="{v}">') for v in ('CC|2026.2', 'IN|2026', '-')]
    assert opcoes == sorted(opcoes)


def test_zip_de_um_grupo(cliente):
    import zipfile
    c, _ = cliente
    execucao = _execucao(c, ['a.pdf', 'b.pdf', 'c.pdf'], 10, pdfs=['a.pdf', 'b.pdf', 'c.pdf'])
    r = c.get(f'/validacoes/{execucao.id}/pdfs.zip?arquivo=a.pdf&arquivo=c.pdf&arquivo=fora.pdf'
              '&nome=Ciência da Computação · 2º semestre de 2026')
    assert r.status_code == 200
    assert sorted(zipfile.ZipFile(io.BytesIO(r.data)).namelist()) == ['a.pdf', 'c.pdf']
    assert f'planos-ciencia-da-computacao-2o-semestre-de-2026-validacao-{execucao.id}.zip' in r.headers[
        'Content-Disposition']
    assert c.get(f'/validacoes/{execucao.id}/pdfs.zip?arquivo=fora.pdf').status_code == 404


def test_meus_planos_agrupados_por_curso_e_periodo(com_login, monkeypatch):
    from app.avaliacao import pipeline
    from conftest import gerar_pdf
    c, _ = com_login
    monkeypatch.setattr(pipeline, 'revalidar', lambda cfg, andamento, nome: andamento.finalizar())
    def plano(cabecalho):
        return gerar_pdf([cabecalho] + ['Linha de texto do plano de ensino numero %d.' % i for i in range(6)])
    envio = _envio(('web.pdf', plano('CCC0723 - DESENVOLVIMENTO WEB I (60h) - Turma: 01 (2026.2)')),
                   ('algebra.pdf', plano('CCC0707 - ALGEBRA LINEAR (60h) - Turma: 01 (2026.1)')),
                   ('outro.pdf', PDF))
    assert c.post('/meus-planos', headers=SERVIDOR, data=envio, content_type='multipart/form-data').status_code == 200
    planos = c.get('/meus-planos/lista', headers=SERVIDOR).json['planos']
    assert [(p['nome'], p['grupo_titulo']) for p in planos] == [
        ('web.pdf', 'Ciência da Computação · 2º semestre de 2026'),
        ('algebra.pdf', 'Ciência da Computação · 1º semestre de 2026'),
        ('outro.pdf', 'Sem identificação de curso e período'),
    ]
    assert planos[0]['componente'] == 'CCC0723 · Desenvolvimento Web I · Turma 01'


def test_paginas_usam_css_e_js_de_static_com_versao(cliente):
    import re
    c, _ = cliente
    for pagina in ('/dashboard', '/meus-planos', '/administracao'):
        html = c.get(pagina).get_data(as_text=True)
        arquivos = re.findall(r'(?:href|src)="(/static/[^"?]+)\?v=[0-9a-f]{10}"', html)
        assert arquivos, pagina
        for caminho in arquivos:
            assert c.get(caminho).status_code == 200
    inicio = c.get('/').get_data(as_text=True)
    assert 'vendor/govbr-ds/govbr-ds.min.css' in inicio
    # Rodapé com o crédito da Fábrica de Software
    assert 'href="https://fabrica.videira.ifc.edu.br"' in inicio


def test_static_e_publico_para_a_pagina_inicial(com_login):
    # A página inicial (sem login) usa o CSS do Design System; o resto continua exigindo login
    c, _ = com_login
    assert c.get('/static/css/ds.css').status_code == 200
    assert c.get('/static/vendor/govbr-ds/govbr-ds.min.css').status_code == 200
    assert c.get('/static/../dashboard').status_code in (401, 404)
    assert c.get('/dashboard').status_code == 401


# --- Usuários: cadastro no login, nome do token, ativação e tela da administração ---

def _token(**carga):
    import base64
    import json
    parte = base64.urlsafe_b64encode(json.dumps(carga).encode()).decode().rstrip('=')
    return f'Bearer eyJhbGciOiJSUzI1NiJ9.{parte}.assinatura'


def test_login_cadastra_usuario_com_nome_do_token(com_login):
    c, _ = com_login
    cab = {**SERVIDOR, 'X-Usuario-Token': _token(email='fulano@ifc.edu.br', name='Fulano  de Tal')}
    html = c.get('/dashboard', headers=cab).get_data(as_text=True)
    usuario = _servicos(c).usuarios.obter('fulano@ifc.edu.br')
    assert usuario['nome'] == 'Fulano de Tal' and usuario['ativo'] == 1
    assert '<span class="email">Fulano de Tal</span>' in html
    # Sem o token, vale o nome guardado; token de outra conta é ignorado
    assert 'Fulano de Tal' in c.get('/meus-planos', headers=SERVIDOR).get_data(as_text=True)
    outro = {**SERVIDOR, 'X-Usuario-Token': _token(email='outro@ifc.edu.br', name='Intruso')}
    c.get('/dashboard', headers=outro)
    assert _servicos(c).usuarios.obter('fulano@ifc.edu.br')['nome'] == 'Fulano de Tal'
    assert c.get('/dashboard', headers={**SERVIDOR, 'X-Usuario-Token': 'lixo'}).status_code == 200


def test_usuario_desativado_perde_acesso_e_admin_nao_pode_ser_desativado(com_login):
    c, _ = com_login
    c.get('/dashboard', headers=SERVIDOR)
    c.get('/dashboard', headers=ADMIN)
    r = c.post('/administracao/usuarios/ativo', headers=ADMIN,
               data={'email': 'fulano@ifc.edu.br', 'ativo': '0', 'voltar': '/administracao/usuarios?q=fulano'})
    assert r.status_code == 303 and r.headers['Location'].endswith('/administracao/usuarios?q=fulano&aviso=desativado')
    bloqueado = c.get('/dashboard', headers={**SERVIDOR, 'Accept': 'text/html'})
    assert bloqueado.status_code == 403 and 'Acesso desativado' in bloqueado.get_data(as_text=True)
    api = c.get('/planos', headers=SERVIDOR)
    assert api.status_code == 403 and 'desativado' in api.get_json()['erro']
    assert c.get('/', headers=SERVIDOR).status_code == 200  # a página inicial continua aberta

    r = c.post('/administracao/usuarios/ativo', headers=ADMIN, data={'email': 'admin@ifc.edu.br', 'ativo': '0'})
    assert r.headers['Location'].endswith('aviso=admin')
    assert _servicos(c).usuarios.obter('admin@ifc.edu.br')['ativo'] == 1
    # Redirecionamento só para a própria tela; origem de outro site é recusada
    r = c.post('/administracao/usuarios/ativo', headers=ADMIN,
               data={'email': 'fulano@ifc.edu.br', 'ativo': '1', 'voltar': 'https://mal.example/'})
    assert r.headers['Location'].endswith('/administracao/usuarios?aviso=ativado')
    assert c.get('/dashboard', headers=SERVIDOR).status_code == 200
    assert c.post('/administracao/usuarios/ativo', headers={**ADMIN, 'Origin': 'https://mal.example'},
                  data={'email': 'fulano@ifc.edu.br', 'ativo': '0'}).status_code == 403
    # Quem só consulta não chega à tela nem altera
    assert c.get('/administracao/usuarios', headers=SERVIDOR).status_code == 302
    c.post('/administracao/usuarios/ativo', headers=SERVIDOR, data={'email': 'fulano@ifc.edu.br', 'ativo': '0'})
    assert _servicos(c).usuarios.obter('fulano@ifc.edu.br')['ativo'] == 1


def test_tela_de_usuarios_filtra_e_pagina(com_login):
    c, _ = com_login
    usuarios = _servicos(c).usuarios
    for i in range(45):
        usuarios.registrar_acesso(f'pessoa{i:02d}@ifc.edu.br', f'Pessoa {i:02d}')
    usuarios.registrar_acesso('admin@ifc.edu.br', 'Chefe')
    usuarios.definir_ativo('pessoa07@ifc.edu.br', False)

    html = c.get('/administracao/usuarios?ordem=email', headers=ADMIN).get_data(as_text=True)
    assert 'aria-current="page"><i class="fas fa-users"' in html and '46 cadastrados · 45 ativos · 1 desativados' in html
    assert '1–20 de 46' in html and 'pessoa18@ifc.edu.br' in html and 'pessoa19@ifc.edu.br' not in html
    assert 'href="/administracao/usuarios?ordem=email&amp;pagina=3"' in html
    assert 'Protegido' in html and '(você)' in html  # o admin aparece primeiro na ordem por e-mail

    html = c.get('/administracao/usuarios?ordem=email&pagina=3', headers=ADMIN).get_data(as_text=True)
    assert '41–46 de 46' in html and 'pessoa44@ifc.edu.br' in html
    html = c.get('/administracao/usuarios?ordem=email&pagina=99', headers=ADMIN).get_data(as_text=True)
    assert '41–46 de 46' in html  # página além do fim mostra a última

    html = c.get('/administracao/usuarios?situacao=inativos', headers=ADMIN).get_data(as_text=True)
    assert '1–1 de 1' in html and 'pessoa07@ifc.edu.br' in html and '>Ativar<' not in html and 'Ativar' in html
    html = c.get('/administracao/usuarios?q=pessoa 1', headers=ADMIN).get_data(as_text=True)
    assert '1–10 de 10' in html
    html = c.get('/administracao/usuarios?papel=admin', headers=ADMIN).get_data(as_text=True)
    assert '1–1 de 1' in html and 'Chefe' in html
    html = c.get('/administracao/usuarios?q=ninguem', headers=ADMIN).get_data(as_text=True)
    assert 'Nenhum usuário com esses filtros.' in html
    assert 'href="/administracao/usuarios"' in c.get('/administracao', headers=ADMIN).get_data(as_text=True)



# Revisão manual (coordenação/NDE/NDB) ---------------------------------------------------------------

NDE = {'X-Usuario-Email': 'nde@ifc.edu.br'}
CABECALHO_CC = 'CCC0723 - DESENVOLVIMENTO WEB I (60h) - Turma: 01 (2026.2)\n'


def _plano_cc(c, planos, nome='web.pdf', status='PENDENTE'):
    """Validação atual com um plano de Ciência da Computação (CC) avaliado pela IA, com o PDF na pasta."""
    from app.armazenamento import detalhes
    execucao = _execucao(c, [nome], 10, {'status_geral': status})
    detalhes.salvar(execucao.detalhes_dir, nome, {'texto': CABECALHO_CC + 'Ementa: ...'})
    (planos / nome).write_bytes(PDF)
    return execucao


def _dar_papel(c, email, curso='CC', papel='nde'):
    c.get('/dashboard', headers={'X-Usuario-Email': email})  # entra no cadastro no primeiro acesso
    return c.post('/administracao/usuarios/papel', headers=ADMIN,
                  data={'email': email, 'curso': curso, 'papel': papel, 'acao': 'adicionar'})


def test_papeis_nos_cursos(com_login):
    c, _ = com_login
    usuarios = _servicos(c).usuarios
    r = _dar_papel(c, 'nde@ifc.edu.br')
    assert r.status_code == 303 and 'aviso=papel_adicionado' in r.headers['Location']
    assert usuarios.papeis('nde@ifc.edu.br') == [('CC', 'nde')]
    assert 'aviso=papel_invalido' in _dar_papel(c, 'nde@ifc.edu.br', curso='XX').headers['Location']
    assert 'aviso=inexistente' in c.post('/administracao/usuarios/papel', headers=ADMIN, data={
        'email': 'ninguem@ifc.edu.br', 'curso': 'CC', 'papel': 'nde', 'acao': 'adicionar'}).headers['Location']
    # Quem não é administrador não dá papéis
    c.post('/administracao/usuarios/papel', headers=SERVIDOR,
           data={'email': 'fulano@ifc.edu.br', 'curso': 'CC', 'papel': 'coordenador', 'acao': 'adicionar'})
    assert usuarios.papeis('fulano@ifc.edu.br') == []

    html = c.get('/administracao/usuarios?papel=revisor', headers=ADMIN).get_data(as_text=True)
    assert 'nde@ifc.edu.br' in html and 'fulano@ifc.edu.br' not in html and 'CC · NDE' in html
    r = c.post('/administracao/usuarios/papel', headers=ADMIN,
               data={'email': 'nde@ifc.edu.br', 'curso': 'CC', 'papel': 'nde', 'acao': 'remover'})
    assert 'aviso=papel_removido' in r.headers['Location'] and usuarios.papeis('nde@ifc.edu.br') == []


def test_so_quem_tem_papel_no_curso_revisa(com_login):
    c, planos = com_login
    _plano_cc(c, planos)
    _dar_papel(c, 'nde@ifc.edu.br', curso='IN')  # papel em outro curso não vale
    _dar_papel(c, 'outro@ifc.edu.br')
    html = c.get('/relatorio?arquivo=web.pdf', headers=NDE).get_data(as_text=True)
    assert 'action="/revisao"' not in html and 'Aguardando a revisão' in html
    r = c.post('/revisao', headers=NDE, data={'arquivo': 'web.pdf', 'status': 'OK', 'comentario': 'ok'})
    assert r.status_code == 403
    assert c.post('/revisao', headers=ADMIN, data={'arquivo': 'web.pdf', 'status': 'OK'}).status_code == 403
    assert 'action="/revisao"' in c.get('/relatorio?arquivo=web.pdf',
                                        headers={'X-Usuario-Email': 'outro@ifc.edu.br'}).get_data(as_text=True)


def test_parecer_vale_sobre_a_ia_e_um_pdf_novo_reabre(com_login):
    c, planos = com_login
    _plano_cc(c, planos, status='PENDENTE')
    _dar_papel(c, 'nde@ifc.edu.br')
    # Discordar da IA (ou não aprovar) exige comentário
    r = c.post('/revisao', headers=NDE, data={'arquivo': 'web.pdf', 'status': 'OK'})
    assert 'aviso=incompleta' in r.headers['Location']
    assert _servicos(c).revisao.vigente('web.pdf') is None
    r = c.post('/revisao', headers=NDE, data={'arquivo': 'web.pdf', 'status': 'OK', 'comentario': 'Ementa está completa.'})
    assert r.status_code == 303 and 'aviso=salva' in r.headers['Location']

    html = c.get('/dashboard', headers=SERVIDOR).get_data(as_text=True)
    assert 'data-status="OK"' in html and 'data-revisado="1"' in html and 'Revisado' in html
    assert 'a IA tinha avaliado como PENDENTE' in html and 'Ementa está completa.' in html
    relatorio = c.get('/relatorio?arquivo=web.pdf', headers=SERVIDOR).get_data(as_text=True)
    assert 'IA: PENDENTE' in relatorio and 'action="/revisao"' not in relatorio  # servidor só vê

    (planos / 'web.pdf').write_bytes(PDF + b'% versao nova')  # o professor mandou outro PDF
    assert _servicos(c).revisao.vigente('web.pdf') is None
    html = c.get('/dashboard', headers=SERVIDOR).get_data(as_text=True)
    assert 'data-status="PENDENTE"' in html and 'data-revisado="0"' in html


def test_desfazer_revisao(com_login):
    c, planos = com_login
    _plano_cc(c, planos, status='OK')
    _dar_papel(c, 'nde@ifc.edu.br')
    assert 'aviso=salva' in c.post('/revisao', headers=NDE, data={'arquivo': 'web.pdf', 'status': 'OK'}).headers[
        'Location']  # concordar e aprovar dispensa comentário
    assert _servicos(c).revisao.vigente('web.pdf')['revisor_email'] == 'nde@ifc.edu.br'
    r = c.post('/revisao', headers=NDE, data={'arquivo': 'web.pdf', 'acao': 'desfazer'})
    assert 'aviso=desfeita' in r.headers['Location'] and _servicos(c).revisao.vigente('web.pdf') is None
    assert c.post('/revisao', headers=NDE, data={'arquivo': 'nao-existe.pdf', 'status': 'OK'}).status_code == 404


def test_professor_ve_o_parecer(com_login, monkeypatch):
    from app.avaliacao import pipeline
    from conftest import gerar_pdf
    c, planos = com_login
    monkeypatch.setattr(pipeline, 'revalidar', lambda cfg, andamento, nome: andamento.finalizar())
    pdf = gerar_pdf([CABECALHO_CC.strip()] + ['Linha de texto do plano de ensino numero %d.' % i for i in range(6)])
    c.post('/meus-planos', headers=SERVIDOR, data=_envio(('web.pdf', pdf)), content_type='multipart/form-data')
    from app.armazenamento import detalhes
    execucao = _execucao(c, ['web.pdf'], 10, {'status_geral': 'OK'})
    detalhes.salvar(execucao.detalhes_dir, 'web.pdf', {'texto': CABECALHO_CC, 'validado_em': '2099-01-01T00:00:00'})
    _dar_papel(c, 'nde@ifc.edu.br')
    c.post('/revisao', headers=NDE, data={'arquivo': 'web.pdf', 'status': 'PENDENTE', 'comentario': 'Falta o cronograma.'})
    [plano] = c.get('/meus-planos/lista', headers=SERVIDOR).json['planos']
    assert plano['revisao']['status'] == 'PENDENTE' and plano['revisao']['comentario'] == 'Falta o cronograma.'
    assert plano['revisao']['papel'] == 'NDE' and not plano['revisao']['concorda']


# Login simulado (só desenvolvimento) -------------------------------------------------------------------

NAVEGAR = {'Sec-Fetch-Mode': 'navigate'}


@pytest.fixture
def dev(fabrica):
    return fabrica(exigir_login=True, login_simulado=True, admins=frozenset({'admin@ifc.edu.br'}))


def test_login_simulado_leva_a_escolha_de_persona(dev):
    c, _ = dev
    r = c.get('/dashboard?x=1', headers=NAVEGAR)
    assert r.status_code == 303 and r.headers['Location'] == '/dev/login?rd=/dashboard%3Fx%3D1'
    assert c.get('/planos').status_code == 401  # requisições da página continuam recebendo 401
    html = c.get('/dev/login').get_data(as_text=True)
    assert 'Carlos Coordenador' in html and 'Modo de desenvolvimento' in html


def test_persona_entra_com_nome_e_papeis(dev):
    c, _ = dev
    r = c.post('/dev/login', data={'email': 'coordenacao.cc@ifc.edu.br', 'rd': '/meus-planos'})
    assert r.status_code == 303 and r.headers['Location'] == '/meus-planos'
    html = c.get('/dashboard').get_data(as_text=True)
    assert 'Carlos Coordenador' in html and 'Trocar usuário' in html and 'papel-usuario">Coordenação<' in html
    assert _servicos(c).usuarios.papeis('coordenacao.cc@ifc.edu.br') == [('CC', 'coordenador')]
    assert c.get('/administracao').status_code == 302  # não é administrador

    c.post('/dev/login', data={'email': 'admin@ifc.edu.br'})  # troca de usuário
    assert c.get('/administracao').status_code == 200
    c.post('/dev/login', data={'email': 'qualquer@ifc.edu.br', 'nome': 'Fulana Livre'})
    assert 'Fulana Livre' in c.get('/dashboard').get_data(as_text=True)

    r = c.get('/oauth2/sign_out')
    assert r.status_code == 303 and r.headers['Location'] == '/'
    assert c.get('/planos').status_code == 401


def test_login_simulado_recusa_outro_dominio(dev):
    c, _ = dev
    for endereco in ('aluno@estudantes.ifc.edu.br', 'alguem@gmail.com', ''):
        r = c.post('/dev/login', data={'email': endereco})
        assert r.status_code == 403 and 'só entram contas @ifc.edu.br' in r.get_data(as_text=True)
    assert c.get('/planos').status_code == 401


def test_sem_login_simulado_o_cookie_nao_vale(com_login):
    c, _ = com_login
    c.set_cookie('dev_usuario', 'admin%40ifc.edu.br%0AAna')
    assert c.get('/planos').status_code == 401
    assert c.get('/dev/login').status_code == 401
    assert c.post('/dev/login', data={'email': 'admin@ifc.edu.br'}).status_code == 401


def test_so_coordenacao_e_administracao_baixam_csv_e_zip(com_login):
    c, planos = com_login
    execucao = _plano_cc(c, planos)
    (Path(execucao.pdfs_dir) / 'web.pdf').write_bytes(PDF)
    _dar_papel(c, 'nde@ifc.edu.br')
    _dar_papel(c, 'coord@ifc.edu.br', papel='coordenador')
    coord = {'X-Usuario-Email': 'coord@ifc.edu.br'}
    rotas = (f'/validacoes/{execucao.id}/csv', f'/validacoes/{execucao.id}/pdfs.zip')
    for cab in (SERVIDOR, NDE):
        assert all(c.get(r, headers=cab).status_code == 403 for r in rotas)
        html = c.get('/dashboard', headers=cab).get_data(as_text=True)
        assert '/csv"' not in html and 'pdfs.zip' not in html and 'EXPORTAR = false' in html
        # cada plano e PDF continua abrindo
        assert c.get(f'/validacoes/{execucao.id}/pdf?arquivo=web.pdf', headers=cab).status_code == 200
    for cab in (coord, ADMIN):
        assert all(c.get(r, headers=cab).status_code == 200 for r in rotas)
        assert 'EXPORTAR = true' in c.get('/dashboard', headers=cab).get_data(as_text=True)


def test_card_tem_botao_revisar_para_quem_pode_revisar(com_login):
    c, planos = com_login
    _plano_cc(c, planos)
    _dar_papel(c, 'nde@ifc.edu.br')
    assert 'class="revisar" href="/relatorio?arquivo=web.pdf#revisao"' in c.get(
        '/dashboard', headers=NDE).get_data(as_text=True)
    for cab in (SERVIDOR, ADMIN):
        assert 'class="revisar"' not in c.get('/dashboard', headers=cab).get_data(as_text=True)


def test_visao_da_coordenacao_por_curso(com_login):
    from app.armazenamento import detalhes
    c, planos = com_login
    execucao = _execucao(c, ['web.pdf', 'tec.pdf'], 10, {'status_geral': 'PENDENTE'})
    detalhes.salvar(execucao.detalhes_dir, 'web.pdf', {'texto': CABECALHO_CC + 'Ementa: ...'})
    detalhes.salvar(execucao.detalhes_dir, 'tec.pdf', {'texto': 'INC0713-1 - WEB DESIGN (60h) - Turma: 03 (2026)\n'})
    (planos / 'web.pdf').write_bytes(PDF)
    _dar_papel(c, 'coord@ifc.edu.br', papel='coordenador')
    coord = {'X-Usuario-Email': 'coord@ifc.edu.br'}

    # Quem não coordena não vê a área nem o item no menu
    for cab in (SERVIDOR, NDE):
        assert c.get('/coordenacao', headers=cab).status_code == 302
        assert 'href="/coordenacao"' not in c.get('/dashboard', headers=cab).get_data(as_text=True)

    html = c.get('/coordenacao', headers=coord).get_data(as_text=True)
    assert 'href="/coordenacao"' in html and 'Ciência da Computação' in html and '2º semestre de 2026' in html
    assert 'Desenvolvimento Web I' in html and 'Web Design' not in html  # só o curso dele
    assert 'href="/relatorio?arquivo=web.pdf#revisao"' in html and '<strong>0</strong> de 1 plano(s) revisados' in html
    assert c.get('/coordenacao?curso=IN', headers=coord).get_data(as_text=True).count('Web Design') == 0

    adm = c.get('/coordenacao', headers=ADMIN).get_data(as_text=True)  # administração escolhe o curso
    assert '<option value="CC" selected>' in adm and '<option value="IN">' in adm
    assert 'Web Design' in c.get('/coordenacao?curso=IN', headers=ADMIN).get_data(as_text=True)


def test_cabecalhos_de_seguranca(cliente):
    c, planos = cliente
    (planos / 'a.pdf').write_bytes(PDF)
    pagina = c.get('/dashboard')
    assert "frame-ancestors 'none'" in pagina.headers['Content-Security-Policy']
    assert pagina.headers['X-Frame-Options'] == 'DENY' and pagina.headers['X-Content-Type-Options'] == 'nosniff'
    assert 'Access-Control-Allow-Origin' not in c.get('/status').headers  # JSON não é lido por outros sites
    pdf = c.get('/pdf?arquivo=a.pdf')
    assert pdf.status_code == 200 and 'Content-Security-Policy' not in pdf.headers  # visualizador do navegador
    assert pdf.headers['X-Content-Type-Options'] == 'nosniff'


def test_acoes_vindas_de_outro_site_sao_recusadas(cliente):
    c, planos = cliente
    (planos / 'a.pdf').write_bytes(PDF)
    fora = {'Origin': 'https://site-malicioso.example'}
    assert c.post('/validar', headers=fora).status_code == 403
    assert c.delete('/planos?arquivo=a.pdf', headers=fora).status_code == 403
    assert c.post('/planos', headers=fora, data=_envio(('b.pdf', PDF)),
                  content_type='multipart/form-data').status_code == 403
    assert (planos / 'a.pdf').exists() and not (planos / 'b.pdf').exists()
    # A própria página (mesma origem) continua podendo
    assert c.delete('/planos?arquivo=a.pdf', headers={'Origin': 'http://localhost'}).status_code == 200
