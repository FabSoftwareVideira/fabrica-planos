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


@pytest.fixture
def sem_ia(monkeypatch):
    """Envios de "Meus planos" entram na fila de avaliação: aqui a avaliação só termina, sem chamar a IA."""
    from app.avaliacao import pipeline
    monkeypatch.setattr(pipeline, 'revalidar', lambda cfg, andamento, nome: andamento.finalizar())


def _enviar_meus(c, *arquivos, cab=None):
    return c.post('/meus-planos', headers=cab or {}, data=_envio(*arquivos), content_type='multipart/form-data')


def test_upload_lista_e_exclui(cliente, sem_ia):
    c, planos = cliente
    r = _enviar_meus(c, ('Plano Á.pdf', PDF), ('b.pdf', PDF))
    assert r.status_code == 200
    assert [s['nome'] for s in r.json['salvos']] == ['Plano Á.pdf', 'b.pdf']
    assert (planos / 'Plano Á.pdf').read_bytes() == PDF

    assert [p['nome'] for p in c.get('/planos').json['planos']] == ['Plano Á.pdf', 'b.pdf']

    r = _enviar_meus(c, ('b.pdf', PDF))
    assert [(s['nome'], s['substituido']) for s in r.json['salvos']] == [('b.pdf', True)]

    assert c.delete('/meus-planos?arquivo=b.pdf').status_code == 200
    assert not (planos / 'b.pdf').exists()


def test_administrador_nao_envia_planos(cliente):
    c, planos = cliente
    assert c.post('/planos', data=_envio(('b.pdf', PDF)), content_type='multipart/form-data').status_code == 405
    adm = c.get('/administracao').get_data(as_text=True)
    assert 'id="soltar"' not in adm and 'id="lista"' in adm
    assert not (planos / 'b.pdf').exists()


def test_upload_recusa_nome_e_conteudo_invalidos(cliente, sem_ia):
    c, planos = cliente
    r = _enviar_meus(c, ('x.txt', PDF), ('falso.pdf', b'nao e pdf'), ('../fora.pdf', PDF))
    assert r.status_code == 200  # '../fora.pdf' vira 'fora.pdf', dentro da pasta
    assert [s['nome'] for s in r.json['salvos']] == ['fora.pdf']
    assert {x['nome'] for x in r.json['recusados']} == {'x.txt', 'falso.pdf'}
    assert sorted(os.listdir(planos)) == ['fora.pdf']


def test_upload_recusa_pdf_grande_digitalizado_ou_corrompido(cliente, sem_ia):
    c, planos = cliente
    grande = PDF + b'%' + b'0' * (1024 * 1024)
    r = _enviar_meus(c, ('grande.pdf', grande), ('scan.pdf', PDF_SEM_TEXTO), ('quebrado.pdf', b'%PDF-1.4 lixo'),
                     ('bom.pdf', PDF))
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
    assert 'id="validar"' in html and 'id="soltar"' not in html  # quem envia planos é o professor
    adm = c.get('/administracao').get_data(as_text=True)
    assert 'id="soltar"' not in adm and 'id="lista"' in adm and 'id="validar"' in adm


def test_barra_de_utilidades_com_alto_contraste(cliente):
    c, _ = cliente
    for caminho in ('/', '/dashboard'):
        html = c.get(caminho).get_data(as_text=True)
        assert 'class="barra-utilidade"' in html
        assert 'SIGAA' in html and 'Portal do Campus' in html
        assert 'data-contraste' in html and 'Alto contraste' in html
        # O script do tema vem antes do CSS: aplica o alto contraste salvo sem piscar o tema claro
        assert html.index('js/contraste.js') < html.index('vendor/govbr-ds')
    assert 'html.alto-contraste' in c.get('/static/css/ds.css').get_data(as_text=True)


def test_cabecalho_com_logo_e_linha_colorida(cliente):
    c, _ = cliente
    html = c.get('/dashboard').get_data(as_text=True)
    assert 'class="logo"' in html and 'logo-ifc-videira.png' in html
    assert 'Validação de Planos de Ensino' in html
    assert 'Conferência automática dos planos de ensino' in html
    # O título da página fica discreto no conteúdo, não numa faixa do cabeçalho
    assert 'titulo-pagina' not in html
    assert '<p class="titulo-conteudo">Painel de validação</p>' in html
    css = c.get('/static/css/ds.css').get_data(as_text=True)
    assert 'linear-gradient(90deg,#7eba00 0 22%,#1351b4 22% 100%)' in css


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


def test_nao_ha_mais_excluir_todos(cliente):
    c, planos = cliente
    (planos / 'a.pdf').write_bytes(PDF)
    assert c.delete('/planos/todos').status_code in (404, 405)
    assert (planos / 'a.pdf').exists()


def test_excluir_tira_o_plano_da_validacao_e_do_painel(cliente):
    from app.armazenamento import csvsaida, detalhes
    c, planos = cliente
    s = _servicos(c)
    c.post('/planos', data=_envio(('a.pdf', PDF), ('b.pdf', PDF)), content_type='multipart/form-data')
    execucao = _execucao(c, ['a.pdf', 'b.pdf'], 10, pdfs=['a.pdf', 'b.pdf'])
    for nome in ('a.pdf', 'b.pdf'):
        detalhes.salvar(execucao.detalhes_dir, nome, {'texto': nome})
    s.planos.revisoes.salvar('a.pdf', 'x', 'OK', 'OK', '', 'CC', 'coord@ifc.edu.br', 'Coord', 'coordenador')
    assert 'href="/relatorio?arquivo=a.pdf"' in c.get('/dashboard').get_data(as_text=True)

    assert c.delete('/planos?arquivo=a.pdf').status_code == 200
    assert not (planos / 'a.pdf').exists()
    assert [l['Arquivo'] for l in csvsaida.ler_csv(execucao.csv_path)] == ['b.pdf']
    assert execucao.meta()['total'] == 1 and execucao.meta()['ok'] == 1
    assert detalhes.ler(execucao.detalhes_dir, 'a.pdf') is None and detalhes.ler(execucao.detalhes_dir, 'b.pdf')
    assert execucao.pdfs() == ['b.pdf']
    assert s.planos.revisoes.obter('a.pdf') is None
    html = c.get('/dashboard').get_data(as_text=True)
    assert 'href="/relatorio?arquivo=a.pdf"' not in html and 'href="/relatorio?arquivo=b.pdf"' in html
    assert c.get('/relatorio?arquivo=a.pdf').status_code == 404


def test_lista_traz_avaliacoes_sem_pdf_para_limpar(cliente):
    from app.armazenamento import csvsaida
    c, planos = cliente
    (planos / 'a.pdf').write_bytes(PDF)
    execucao = _execucao(c, ['a.pdf', 'velho.pdf'], 10)  # velho.pdf saiu da pasta antes desta versão
    lista = {p['nome']: p for p in c.get('/planos').json['planos']}
    assert lista['a.pdf']['na_pasta'] and not lista['velho.pdf']['na_pasta']
    assert lista['velho.pdf']['pode_excluir']  # sem dono: o administrador limpa
    assert c.delete('/planos?arquivo=velho.pdf').status_code == 200
    assert [l['Arquivo'] for l in csvsaida.ler_csv(execucao.csv_path)] == ['a.pdf']
    assert [p['nome'] for p in c.get('/planos').json['planos']] == ['a.pdf']
    assert c.delete('/planos?arquivo=velho.pdf').status_code == 404


def test_admin_so_exclui_os_proprios_e_oculta_os_dos_outros(com_login):
    from app.armazenamento import csvsaida, donos
    c, planos = com_login
    s = _servicos(c)
    (planos / 'prof.pdf').write_bytes(PDF)
    donos.definir(s.cfg.resultados_dir, 'prof.pdf', 'fulano@ifc.edu.br')
    (planos / 'solto.pdf').write_bytes(PDF)  # copiado direto para a pasta: sem dono
    (planos / 'meu.pdf').write_bytes(PDF)  # entregue pelo administrador como professor, em "Meus planos"
    donos.definir(s.cfg.resultados_dir, 'meu.pdf', 'admin@ifc.edu.br')
    execucao = _execucao(c, ['meu.pdf', 'prof.pdf', 'solto.pdf'], 10)

    lista = {p['nome']: p for p in c.get('/planos', headers=ADMIN).json['planos']}
    assert lista['meu.pdf']['pode_excluir'] and lista['solto.pdf']['pode_excluir']
    assert not lista['prof.pdf']['pode_excluir']

    # O plano de outra pessoa: não exclui nem substitui, mas oculta do painel
    r = c.delete('/planos?arquivo=prof.pdf', headers=ADMIN)
    assert r.status_code == 403 and 'ocultados' in r.json['erro']
    r = _enviar_meus(c, ('prof.pdf', PDF), cab=ADMIN)
    assert r.status_code == 400 and 'outra pessoa' in r.json['recusados'][0]['motivo']
    assert (planos / 'prof.pdf').exists() and s.planos.dono('prof.pdf') == 'fulano@ifc.edu.br'

    assert c.post('/planos/ocultar?arquivo=prof.pdf', headers=ADMIN).status_code == 200
    html = c.get('/dashboard', headers=SERVIDOR).get_data(as_text=True)
    assert 'href="/relatorio?arquivo=prof.pdf"' not in html and 'href="/relatorio?arquivo=meu.pdf"' in html
    assert 'prof.pdf' in [l['Arquivo'] for l in csvsaida.ler_csv(execucao.csv_path)]  # a avaliação continua
    assert c.get('/planos', headers=ADMIN).json['planos'][1]['oculto']
    assert c.delete('/planos/ocultar?arquivo=prof.pdf', headers=ADMIN).status_code == 200
    assert 'href="/relatorio?arquivo=prof.pdf"' in c.get('/dashboard', headers=SERVIDOR).get_data(as_text=True)

    # Os próprios e os sem dono: exclui
    assert c.delete('/planos?arquivo=meu.pdf', headers=ADMIN).status_code == 200
    assert c.delete('/planos?arquivo=solto.pdf', headers=ADMIN).status_code == 200
    assert [l['Arquivo'] for l in csvsaida.ler_csv(execucao.csv_path)] == ['prof.pdf']
    assert c.post('/planos/ocultar?arquivo=sumiu.pdf', headers=ADMIN).status_code == 404


def test_versao_nova_do_pdf_volta_ao_painel(cliente, sem_ia):
    c, planos = cliente
    _enviar_meus(c, ('a.pdf', PDF))
    _execucao(c, ['a.pdf'], 10)
    c.post('/planos/ocultar?arquivo=a.pdf')
    assert 'href="/relatorio?arquivo=a.pdf"' not in c.get('/dashboard').get_data(as_text=True)
    _enviar_meus(c, ('a.pdf', PDF))
    assert 'href="/relatorio?arquivo=a.pdf"' in c.get('/dashboard').get_data(as_text=True)


def test_professor_exclui_o_proprio_plano_com_a_avaliacao(com_login):
    from app.armazenamento import csvsaida, donos
    c, planos = com_login
    (planos / 'meu.pdf').write_bytes(PDF)
    donos.definir(_servicos(c).cfg.resultados_dir, 'meu.pdf', 'fulano@ifc.edu.br')
    execucao = _execucao(c, ['meu.pdf'], 10)
    assert c.delete('/meus-planos?arquivo=meu.pdf', headers=SERVIDOR).status_code == 200
    assert csvsaida.ler_csv(execucao.csv_path) == []


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
    assert 'fulano@ifc.edu.br' in html and 'papel-usuario">Consulta<' in html and 'href="/auth/sair"' in html
    assert 'id="validar"' not in html and 'id="soltar"' not in html and 'class="revalidar"' not in html
    assert 'ADMIN = false,' in html and 'href="/meus-planos"' in html and 'href="/administracao"' not in html
    r = c.get('/administracao', headers=SERVIDOR)
    assert r.status_code == 302 and r.headers['Location'].endswith('/dashboard')
    assert 'id="revalidar"' not in c.get('/relatorio?arquivo=a.pdf', headers=SERVIDOR).get_data(as_text=True)
    assert c.get('/pdf?arquivo=a.pdf', headers=SERVIDOR).status_code == 200

    assert c.post('/validar', headers=SERVIDOR).status_code == 403
    assert c.post('/validar?arquivo=a.pdf', headers=SERVIDOR).status_code == 403
    assert c.post('/planos', headers=SERVIDOR, data=_envio(('b.pdf', PDF)),
                  content_type='multipart/form-data').status_code == 405  # ninguém envia por aqui
    assert c.delete('/planos?arquivo=a.pdf', headers=SERVIDOR).status_code == 403
    assert c.post('/planos/ocultar?arquivo=a.pdf', headers=SERVIDOR).status_code == 403
    assert c.delete('/planos/ocultar?arquivo=a.pdf', headers=SERVIDOR).status_code == 403
    assert (planos / 'a.pdf').exists()


def test_admin_administra(com_login):
    c, planos = com_login
    html = c.get('/dashboard', headers=ADMIN).get_data(as_text=True)
    assert 'admin@ifc.edu.br' in html and 'papel-usuario">Administrador<' in html and 'id="validar"' in html
    assert 'href="/administracao"' in html
    assert 'id="lista"' in c.get('/administracao', headers=ADMIN).get_data(as_text=True)
    (planos / 'b.pdf').write_bytes(PDF)  # sem dono (copiado direto para a pasta): o administrador exclui
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
    assert 'href="https://fabrica.labia.ifc.edu.br"' in inicio


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


def test_quem_enviou_o_plano_nao_o_revisa(com_login):
    from app.armazenamento import donos
    c, planos = com_login
    _plano_cc(c, planos, status='PENDENTE')
    donos.definir(_servicos(c).cfg.resultados_dir, 'web.pdf', 'nde@ifc.edu.br')  # o próprio NDE enviou
    _dar_papel(c, 'nde@ifc.edu.br')
    _dar_papel(c, 'outro@ifc.edu.br')
    OUTRO = {'X-Usuario-Email': 'outro@ifc.edu.br'}

    html = c.get('/relatorio?arquivo=web.pdf', headers=NDE).get_data(as_text=True)
    assert 'action="/revisao"' not in html and 'Você enviou este plano' in html
    assert 'class="revisar"' not in c.get('/dashboard', headers=NDE).get_data(as_text=True)
    r = c.post('/revisao', headers=NDE, data={'arquivo': 'web.pdf', 'status': 'OK', 'comentario': 'ok'})
    assert r.status_code == 403 and 'Você enviou este plano' in r.get_data(as_text=True)
    assert _servicos(c).revisao.vigente('web.pdf') is None

    # Outro membro revisa; o autor também não desfaz a revisão dele
    assert 'class="revisar"' in c.get('/dashboard', headers=OUTRO).get_data(as_text=True)
    r = c.post('/revisao', headers=OUTRO, data={'arquivo': 'web.pdf', 'status': 'OK', 'comentario': 'Completo.'})
    assert 'aviso=salva' in r.headers['Location']
    assert c.post('/revisao', headers=NDE, data={'arquivo': 'web.pdf', 'acao': 'desfazer'}).status_code == 403
    assert _servicos(c).revisao.vigente('web.pdf')['status'] == 'OK'


def test_coordenador_revisa_o_proprio_plano(com_login):
    from app.armazenamento import donos
    c, planos = com_login
    _plano_cc(c, planos, status='OK')
    donos.definir(_servicos(c).cfg.resultados_dir, 'web.pdf', 'coord@ifc.edu.br')  # o próprio coordenador enviou
    _dar_papel(c, 'coord@ifc.edu.br', papel='coordenador')
    COORD = {'X-Usuario-Email': 'coord@ifc.edu.br'}

    html = c.get('/relatorio?arquivo=web.pdf', headers=COORD).get_data(as_text=True)
    assert 'action="/revisao"' in html and 'Você enviou este plano' not in html
    assert 'class="revisar"' in c.get('/dashboard', headers=COORD).get_data(as_text=True)
    r = c.post('/revisao', headers=COORD, data={'arquivo': 'web.pdf', 'status': 'OK'})
    assert r.status_code == 303 and 'aviso=salva' in r.headers['Location']
    revisao = _servicos(c).revisao.vigente('web.pdf')
    assert revisao['revisor_email'] == 'coord@ifc.edu.br' and revisao['papel'] == 'Coordenação'


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


# Assinatura do plano aprovado pelo professor (gov.br) --------------------------------------------------

def test_professor_assina_o_plano_depois_de_aprovado(fabrica, tmp_path):
    from app.armazenamento import donos
    from conftest import assinar, gerar_ac, salvar_ac
    ac = gerar_ac()
    c, planos = fabrica(exigir_login=True, admins=frozenset({'admin@ifc.edu.br'}),
                        certificados_dir=salvar_ac(ac, tmp_path / 'certificados'))
    _plano_cc(c, planos, status='OK')
    donos.definir(_servicos(c).cfg.resultados_dir, 'web.pdf', 'fulano@ifc.edu.br')
    _dar_papel(c, 'nde@ifc.edu.br')
    assinado = assinar(PDF, ac)

    def enviar(pdf, cab=SERVIDOR):
        return c.post('/meus-planos/assinatura', headers=cab, content_type='multipart/form-data',
                      data={'arquivo': 'web.pdf', 'pdf': (io.BytesIO(pdf), 'assinado.pdf')})

    # Antes da aprovação na revisão, não assina
    [plano] = c.get('/meus-planos/lista', headers=SERVIDOR).json['planos']
    assert plano['pode_assinar'] is False and plano['assinatura'] is None
    assert enviar(assinado).status_code == 403

    c.post('/revisao', headers=NDE, data={'arquivo': 'web.pdf', 'status': 'OK', 'comentario': ''})
    [plano] = c.get('/meus-planos/lista', headers=SERVIDOR).json['planos']
    assert plano['pode_assinar'] is True
    assert 'Aguardando a assinatura do docente' in c.get('/relatorio?arquivo=web.pdf', headers=NDE).get_data(as_text=True)

    # Só quem enviou assina; o PDF precisa estar assinado, pela AC aceita, por quem é do plano
    assert enviar(assinado, NDE).status_code == 403
    r = enviar(PDF)
    assert r.status_code == 422 and 'não tem assinatura' in r.json['erro']
    assert 'não é do gov.br' in enviar(assinar(PDF, gerar_ac())).json['erro']
    outro = {**SERVIDOR, 'X-Usuario-Token': _token(email='fulano@ifc.edu.br', name='Beltrano Pereira')}
    assert 'não é docente deste plano' in enviar(assinado, outro).json['erro']
    assert c.get('/pdf-assinado?arquivo=web.pdf', headers=SERVIDOR).status_code == 404

    proprio = {**SERVIDOR, 'X-Usuario-Token': _token(email='fulano@ifc.edu.br', name='Fulano de Tal')}
    r = enviar(assinado, proprio)
    assert r.status_code == 200 and r.json['assinatura']['signatario'] == 'FULANO DE TAL'
    [plano] = c.get('/meus-planos/lista', headers=SERVIDOR).json['planos']
    assert plano['assinatura']['signatario'] == 'FULANO DE TAL'
    assert c.get('/pdf-assinado?arquivo=web.pdf', headers=NDE).data == assinado
    assert 'Assinado via gov.br por FULANO DE TAL' in c.get('/relatorio?arquivo=web.pdf', headers=NDE).get_data(as_text=True)
    assert '/pdf-assinado?arquivo=web.pdf' in c.get('/dashboard', headers=NDE).get_data(as_text=True)

    # Desfeita a aprovação, a assinatura deixa de valer
    c.post('/revisao', headers=NDE, data={'arquivo': 'web.pdf', 'acao': 'desfazer'})
    assert c.get('/meus-planos/lista', headers=SERVIDOR).json['planos'][0]['assinatura'] is None
    assert c.get('/pdf-assinado?arquivo=web.pdf', headers=NDE).status_code == 404


def test_plano_assinado_so_e_reenviado_com_liberacao_da_coordenacao(fabrica, tmp_path, monkeypatch):
    from app.armazenamento import donos, liberacoes
    from app.avaliacao import pipeline
    from conftest import assinar, gerar_ac, salvar_ac
    monkeypatch.setattr(pipeline, 'revalidar', lambda cfg, andamento, nome: andamento.finalizar())
    ac = gerar_ac()
    c, planos = fabrica(exigir_login=True, admins=frozenset({'admin@ifc.edu.br'}),
                        certificados_dir=salvar_ac(ac, tmp_path / 'certificados'))
    _plano_cc(c, planos, status='OK')
    donos.definir(_servicos(c).cfg.resultados_dir, 'web.pdf', 'fulano@ifc.edu.br')
    _dar_papel(c, 'nde@ifc.edu.br')
    _dar_papel(c, 'coord@ifc.edu.br', papel='coordenador')
    COORD = {'X-Usuario-Email': 'coord@ifc.edu.br'}
    res = _servicos(c).cfg.resultados_dir

    c.post('/revisao', headers=NDE, data={'arquivo': 'web.pdf', 'status': 'OK'})
    proprio = {**SERVIDOR, 'X-Usuario-Token': _token(email='fulano@ifc.edu.br', name='Fulano de Tal')}
    r = c.post('/meus-planos/assinatura', headers=proprio, content_type='multipart/form-data',
               data={'arquivo': 'web.pdf', 'pdf': (io.BytesIO(assinar(PDF, ac)), 'assinado.pdf')})
    assert r.status_code == 200

    # Assinado: o professor não substitui o PDF (nem o dono do plano)
    r = c.post('/meus-planos', headers=SERVIDOR, data=_envio(('web.pdf', PDF)), content_type='multipart/form-data')
    assert r.status_code == 400 and 'já está assinado' in r.json['recusados'][0]['motivo']
    assert not liberacoes.liberado(res, 'web.pdf')

    # Só a coordenação do curso (ou a administração) libera o reenvio
    assert c.post('/coordenacao/liberar', headers=NDE, data={'arquivo': 'web.pdf'}).status_code == 403
    html = c.get('/coordenacao', headers=COORD).get_data(as_text=True)
    assert 'Liberar novo envio' in html and 'Assinado' in html
    r = c.post('/coordenacao/liberar', headers=COORD, data={'arquivo': 'web.pdf', 'curso': 'CC'})
    assert r.status_code == 303 and liberacoes.liberado(res, 'web.pdf')
    assert 'Cancelar liberação' in c.get('/coordenacao', headers=COORD).get_data(as_text=True)
    [plano] = c.get('/meus-planos/lista', headers=SERVIDOR).json['planos']
    assert plano['reenvio_liberado'] is True

    # Com a liberação, o envio passa e a liberação é consumida
    r = c.post('/meus-planos', headers=SERVIDOR, data=_envio(('web.pdf', PDF)), content_type='multipart/form-data')
    assert r.status_code == 200 and r.json['salvos'][0]['substituido']
    assert not liberacoes.liberado(res, 'web.pdf')


def test_excluir_o_plano_apaga_o_pdf_assinado(cliente):
    from app.armazenamento import assinaturas
    c, planos = cliente
    (planos / 'a.pdf').write_bytes(PDF)
    res = _servicos(c).cfg.resultados_dir
    assinaturas.gravar(res, 'a.pdf', b'%PDF-assinado', {'signatario': 'X'})
    assert c.delete('/planos?arquivo=a.pdf').status_code == 200
    assert 'a.pdf' not in assinaturas.ler(res)
    assert not os.path.exists(assinaturas.caminho_pdf(res, 'a.pdf'))


# Login com gov.br -------------------------------------------------------------------------------------

GOVBR = dict(exigir_login=True, admins=frozenset({'admin@ifc.edu.br'}), govbr_client_id='cliente',
             govbr_client_secret='segredo', segredo_sessao='chave-de-teste', cookie_seguro=False,
             govbr_redirect_uri='https://planos.labia.ifc.edu.br/auth/govbr/callback')


class _Resposta:
    def __init__(self, status=200, corpo=None, cabecalhos=None):
        self.status_code, self._corpo, self.headers = status, corpo or {}, cabecalhos or {}

    def json(self):
        return self._corpo

    @property
    def text(self):
        import json
        return json.dumps(self._corpo)

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))


def _id_token(**carga):
    import base64
    import json
    parte = base64.urlsafe_b64encode(json.dumps(carga).encode()).decode().rstrip('=')
    return f'eyJhbGciOiJSUzI1NiJ9.{parte}.assinatura'


def _login_govbr(c, monkeypatch, rd='/meus-planos', **claims):
    """Ida ao gov.br e volta com um ID token com estes claims (o endpoint de token é simulado)."""
    from urllib.parse import parse_qs, urlsplit
    import requests
    r = c.get('/auth/govbr/login?rd=' + rd)
    assert r.status_code == 302
    ida = parse_qs(urlsplit(r.headers['Location']).query)
    padrao = {'iss': 'https://sso.acesso.gov.br/', 'aud': 'cliente', 'nonce': ida['nonce'][0], 'exp': 9999999999,
              'sub': '12345678900', 'name': 'Fulano de Tal', 'email': 'fulano@ifc.edu.br', 'email_verified': True}
    padrao.update(claims)
    pedidos = []

    def post(url, **kw):
        pedidos.append((url, kw))
        return _Resposta(corpo={'id_token': _id_token(**padrao), 'access_token': 'x'})
    monkeypatch.setattr(requests, 'post', post)
    volta = c.get(f"/auth/govbr/callback?code=abc&state={ida['state'][0]}")
    return ida, volta, pedidos


def test_pagina_inicial_mostra_os_logins_ligados(fabrica):
    c, _ = fabrica(exigir_login=True)
    html = c.get('/').get_data(as_text=True)
    assert '/oauth2/start?rd=/dashboard' in html and '/auth/govbr/login' not in html
    c, _ = fabrica(**GOVBR)
    html = c.get('/?rd=/meus-planos').get_data(as_text=True)
    assert 'href="/auth/govbr/login?rd=/meus-planos"' in html and '/oauth2/start?rd=/meus-planos' in html
    c, _ = fabrica(**dict(GOVBR, login_google=False))
    html = c.get('/').get_data(as_text=True)
    assert '/auth/govbr/login' in html and '/oauth2/start' not in html
    # Para onde o Caddy manda quem abre uma página sem login
    assert c.get('/entrar?rd=/dashboard').headers['Location'] == '/auth/govbr/login?rd=/dashboard'
    assert c.get('/entrar?rd=//outro.site').headers['Location'] == '/auth/govbr/login?rd=/dashboard'


def test_login_govbr_com_email_institucional(fabrica, monkeypatch):
    c, _ = fabrica(**GOVBR)
    assert c.get('/auth/verificar').status_code == 401
    ida, volta, pedidos = _login_govbr(c, monkeypatch)
    assert ida['code_challenge_method'] == ['S256'] and ida['scope'] == ['openid email profile']
    assert ida['redirect_uri'] == ['https://planos.labia.ifc.edu.br/auth/govbr/callback']
    assert volta.status_code == 302 and volta.headers['Location'] == '/meus-planos'
    url, kw = pedidos[0]
    assert url == 'https://sso.acesso.gov.br/token' and kw['auth'] == ('cliente', 'segredo')
    assert kw['data']['code'] == 'abc' and len(kw['data']['code_verifier']) >= 43

    # O Caddy pergunta ao app e recebe o e-mail e o nome
    r = c.get('/auth/verificar')
    assert r.status_code == 200 and r.headers['X-Usuario-Email'] == 'fulano@ifc.edu.br'
    html = c.get('/meus-planos', headers={k: r.headers[k] for k in ('X-Usuario-Email', 'X-Usuario-Token')}).get_data(as_text=True)
    assert 'Fulano de Tal' in html

    # Sair apaga a sessão e volta à página inicial (sem passar pelo gov.br), que oferece sair do gov.br
    r = c.get('/auth/sair')
    assert r.headers['Location'] == '/oauth2/sign_out?rd=%2F'
    assert c.get('/auth/verificar').status_code == 401
    assert c.get('/auth/gov/logout').headers['Location'] == '/oauth2/sign_out?rd=%2F'
    # Sem sessão gov.br (entrou pelo Google)
    assert c.get('/auth/sair').headers['Location'] == '/oauth2/sign_out?rd=%2F'


def test_login_govbr_recusado(fabrica, monkeypatch):
    c, _ = fabrica(**GOVBR)
    _, volta, _ = _login_govbr(c, monkeypatch, email='fulano@gmail.com', sub='')
    assert volta.status_code == 403 and 'e-mail institucional' in volta.get_data(as_text=True)
    _, volta, _ = _login_govbr(c, monkeypatch, email_verified=False)
    assert volta.status_code == 403
    _, volta, _ = _login_govbr(c, monkeypatch, email='fulano@estudantes.ifc.edu.br')
    assert volta.status_code == 403
    for claims in ({'nonce': 'outro'}, {'aud': 'outro-cliente'}, {'iss': 'https://falso.example/'}, {'exp': 1}):
        _, volta, _ = _login_govbr(c, monkeypatch, **claims)
        assert volta.status_code == 400, claims
    assert c.get('/auth/verificar').status_code == 401
    # state que não é o da ida (outra aba, ou forjado)
    c.get('/auth/govbr/login')
    assert c.get('/auth/govbr/callback?code=abc&state=forjado').status_code == 400
    # Cookie de sessão adulterado
    c.set_cookie('_planos_govbr', 'eyJlbWFpbCI6ImFkbWluQGlmYy5lZHUuYnIifQ.xxx.yyy')
    assert c.get('/auth/verificar').status_code == 401


def _vincular_govbr(c, monkeypatch, cab, **claims):
    """Quem já entrou (cabeçalhos do Caddy) vai ao gov.br vincular a conta e volta."""
    from urllib.parse import parse_qs, urlsplit
    import requests
    r = c.get('/conta/govbr/vincular', headers=cab)
    assert r.status_code == 302, r.get_data(as_text=True)
    ida = parse_qs(urlsplit(r.headers['Location']).query)
    padrao = {'iss': 'https://sso.acesso.gov.br/', 'aud': 'cliente', 'nonce': ida['nonce'][0], 'exp': 9999999999,
              'sub': '12345678900', 'name': 'Fulano de Tal', 'email': 'fulano@gmail.com', 'email_verified': True}
    padrao.update(claims)
    monkeypatch.setattr(requests, 'post', lambda url, **kw: _Resposta(corpo={'id_token': _id_token(**padrao)}))
    return c.get(f"/auth/govbr/callback?code=abc&state={ida['state'][0]}")


def test_login_govbr_pela_conta_vinculada(fabrica, monkeypatch):
    c, _ = fabrica(**GOVBR)
    # Sem vínculo, o e-mail pessoal é recusado, com o caminho para vincular
    _, volta, _ = _login_govbr(c, monkeypatch, email='fulano@gmail.com')
    html = volta.get_data(as_text=True)
    assert volta.status_code == 403 and 'vincule' in html and '/oauth2/start?rd=/conta/govbr/vincular' in html
    # Entrou pelo Google: o cabeçalho oferece vincular
    google = {'X-Usuario-Email': 'fulano@ifc.edu.br'}
    assert 'href="/conta/govbr/vincular"' in c.get('/meus-planos', headers=google).get_data(as_text=True)
    volta = _vincular_govbr(c, monkeypatch, google)
    assert volta.status_code == 302 and volta.headers['Location'] == '/meus-planos'
    assert c.get('/auth/verificar').status_code == 401  # vincular não abre sessão gov.br
    html = c.get('/meus-planos', headers=google).get_data(as_text=True)
    assert 'action="/conta/govbr/desvincular"' in html and 'href="/conta/govbr/vincular"' not in html
    # O CPF não fica guardado
    s = _servicos(c)
    with s.usuarios._conexao() as con:
        [linha] = con.execute('SELECT * FROM vinculos_govbr').fetchall()
    assert linha['email'] == 'fulano@ifc.edu.br' and '12345678900' not in str(dict(linha))

    # Agora o login gov.br com e-mail pessoal entra como o usuário vinculado
    _, volta, _ = _login_govbr(c, monkeypatch, email='fulano@gmail.com')
    assert volta.status_code == 302 and volta.headers['Location'] == '/meus-planos'
    assert c.get('/auth/verificar').headers['X-Usuario-Email'] == 'fulano@ifc.edu.br'
    c.get('/auth/sair')
    # Outro CPF continua recusado
    assert _login_govbr(c, monkeypatch, email='outro@gmail.com', sub='99999999999')[1].status_code == 403

    # Desvincular (só pelo próprio site)
    assert c.post('/conta/govbr/desvincular', headers={**google, 'Origin': 'https://outro.site'}).status_code == 403
    assert c.post('/conta/govbr/desvincular', headers=google).status_code == 303
    assert _login_govbr(c, monkeypatch, email='fulano@gmail.com')[1].status_code == 403


def test_login_govbr_institucional_vincula_o_cpf(fabrica, monkeypatch):
    c, _ = fabrica(**GOVBR)
    _login_govbr(c, monkeypatch)  # e-mail institucional verificado: o CPF fica vinculado
    c.get('/auth/sair')
    # Depois, mesmo se o e-mail no gov.br mudar para um pessoal, o login continua
    _, volta, _ = _login_govbr(c, monkeypatch, email='fulano@gmail.com')
    assert volta.status_code == 302
    assert c.get('/auth/verificar').headers['X-Usuario-Email'] == 'fulano@ifc.edu.br'


def test_vincular_exige_login(fabrica):
    c, _ = fabrica(**GOVBR)
    assert c.get('/conta/govbr/vincular').status_code == 401  # sem login, o app nem chega à rota
    assert c.post('/conta/govbr/desvincular').status_code in (401, 403)


def test_login_govbr_troca_recusada_registra_o_motivo(fabrica, monkeypatch, caplog):
    from urllib.parse import parse_qs, urlsplit
    import requests
    c, _ = fabrica(**GOVBR)
    ida = parse_qs(urlsplit(c.get('/auth/govbr/login').headers['Location']).query)
    monkeypatch.setattr(requests, 'post', lambda url, **kw: _Resposta(401, {'error': 'invalid_client'}))
    volta = c.get(f"/auth/govbr/callback?code=abc&state={ida['state'][0]}")
    assert volta.status_code == 502 and 'Tente de novo' in volta.get_data(as_text=True)
    assert 'HTTP 401' in caplog.text and 'invalid_client' in caplog.text
    assert c.get('/auth/verificar').status_code == 401


def test_verificar_aceita_sessao_do_google(fabrica, monkeypatch):
    import requests
    c, _ = fabrica(**GOVBR)
    chamadas = []

    def get(url, **kw):
        chamadas.append((url, kw['headers']))
        return _Resposta(202, cabecalhos={'X-Auth-Request-Email': 'ciclana@ifc.edu.br', 'Authorization': 'Bearer t'})
    monkeypatch.setattr(requests, 'get', get)
    c.set_cookie('_planos_login', 'sessao-google')
    r = c.get('/auth/verificar')
    assert r.status_code == 200 and r.headers['X-Usuario-Email'] == 'ciclana@ifc.edu.br'
    assert r.headers['X-Usuario-Token'] == 'Bearer t'
    assert chamadas[0][0] == 'http://oauth2-proxy:4180/oauth2/auth' and '_planos_login=sessao-google' in chamadas[0][1]['Cookie']
    monkeypatch.setattr(requests, 'get', lambda url, **kw: _Resposta(401))
    assert c.get('/auth/verificar').status_code == 401
    # Com o Google desligado, nem pergunta ao oauth2-proxy
    c, _ = fabrica(**dict(GOVBR, login_google=False))
    c.set_cookie('_planos_login', 'sessao-google')
    monkeypatch.setattr(requests, 'get', get)
    assert c.get('/auth/verificar').status_code == 401


def test_login_govbr_desligado_sem_credenciais(fabrica):
    c, _ = fabrica(exigir_login=True)
    assert c.get('/auth/govbr/login').status_code == 404
    assert c.get('/entrar?rd=/dashboard').headers['Location'] == '/oauth2/start?rd=/dashboard'


# Assinatura pela API do gov.br ---------------------------------------------------------------------------

def _aprovado_para_assinar(fabrica, tmp_path, **opcoes):
    """Plano web.pdf de fulano@ifc.edu.br, aprovado pelo NDE de CC; devolve (cliente, cabeçalhos do dono)."""
    from app.armazenamento import donos
    from conftest import gerar_ac, salvar_ac
    c, planos = fabrica(exigir_login=True, admins=frozenset({'admin@ifc.edu.br'}), cookie_seguro=False,
                        certificados_dir=salvar_ac(gerar_ac(), tmp_path / 'certificados'), **opcoes)
    _plano_cc(c, planos, status='OK')
    donos.definir(_servicos(c).cfg.resultados_dir, 'web.pdf', 'fulano@ifc.edu.br')
    _dar_papel(c, 'nde@ifc.edu.br')
    c.post('/revisao', headers=NDE, data={'arquivo': 'web.pdf', 'status': 'OK', 'comentario': ''})
    return c, {**SERVIDOR, 'X-Usuario-Token': _token(email='fulano@ifc.edu.br', name='Fulano de Tal')}


class _ApiFalsa:
    """Responde no lugar do servidor OAuth e da API do ITI (requests.post), assinando com uma AC de teste."""

    def __init__(self, status_assinatura=200):
        self.status_assinatura = status_assinatura
        self.pedidos = []

    def __call__(self, url, **kw):
        import base64
        from unittest import mock
        from app.servicos.assinatura_api import ApiSimulada
        self.pedidos.append((url, kw))
        resposta = mock.Mock(status_code=200, ok=True)
        resposta.raise_for_status = lambda: None
        if url.endswith('/token'):
            resposta.json = lambda: {'access_token': 'token-de-teste', 'token_type': 'bearer', 'expires_in': 600}
        elif url.endswith('/assinarPKCS7'):
            resposta.status_code, resposta.ok = self.status_assinatura, self.status_assinatura == 200
            resposta.text = 'Cidadão não possui a identidade (Prata ou Ouro)'
            digest = base64.b64decode(kw['json']['hashBase64'])
            resposta.content = ApiSimulada(None).assinar_hash('t', digest, 'Fulano de Tal')
        return resposta


def _assinar_pelo_govbr(c, cab, arquivo='web.pdf', **callback):
    from urllib.parse import parse_qs, urlsplit
    r = c.get('/assinatura/govbr/iniciar?arquivo=' + arquivo, headers=cab)
    assert r.status_code == 302, r.headers.get('Location')
    ida = urlsplit(r.headers['Location'])
    q = {k: v[0] for k, v in parse_qs(ida.query).items()}
    volta = c.get('/assinatura/govbr/callback', headers=cab,
                  query_string={'code': 'codigo', 'state': q.get('state', ''), **callback})
    return ida, q, volta


def _resultado(volta):
    from urllib.parse import parse_qs, urlsplit
    assert volta.status_code == 303 and volta.headers['Location'].startswith('/meus-planos?')
    return {k: v[0] for k, v in parse_qs(urlsplit(volta.headers['Location']).query).items()}


def test_assina_pela_api_do_govbr_em_homologacao(fabrica, tmp_path, monkeypatch):
    import requests
    api = _ApiFalsa()
    monkeypatch.setattr(requests, 'post', api)
    c, dono = _aprovado_para_assinar(fabrica, tmp_path, assinatura_client_id='cli', assinatura_client_secret='seg',
                                     segredo_sessao='chave', assinatura_ambiente='homologacao',
                                     assinatura_oauth_url='https://cas.staging.iti.br/oauth2.0',
                                     assinatura_api_url='https://assinatura-api.staging.iti.br/externo/v2')
    assert 'ASSINATURA_API = true' in c.get('/meus-planos', headers=dono).get_data(as_text=True)
    ida, q, volta = _assinar_pelo_govbr(c, dono)
    assert ida.netloc == 'cas.staging.iti.br' and ida.path == '/oauth2.0/authorize'
    assert q['client_id'] == 'cli' and q['scope'] == 'sign govbr' and q['response_type'] == 'code'
    assert q['redirect_uri'] == 'http://localhost/assinatura/govbr/callback'
    resultado = _resultado(volta)
    assert resultado['assinatura'] == 'ok' and resultado['signatario'] == 'FULANO DE TAL', resultado
    token_url, token_kw = api.pedidos[0]
    assert token_url == 'https://cas.staging.iti.br/oauth2.0/token'
    assert token_kw['data']['grant_type'] == 'authorization_code' and token_kw['data']['code'] == 'codigo'
    assinar_url, assinar_kw = api.pedidos[1]
    assert assinar_url.endswith('/externo/v2/assinarPKCS7')
    assert assinar_kw['headers']['Authorization'] == 'Bearer token-de-teste'
    [plano] = c.get('/meus-planos/lista', headers=dono).json['planos']
    assert plano['assinatura']['signatario'] == 'FULANO DE TAL'
    pdf = c.get('/pdf-assinado?arquivo=web.pdf', headers=NDE).data
    assert pdf.startswith(b'%PDF') and b'(AssinaturaGovBr)' in pdf


def test_em_producao_so_valem_as_acs_de_app_certificados(fabrica, tmp_path, monkeypatch):
    import requests
    monkeypatch.setattr(requests, 'post', _ApiFalsa())
    c, dono = _aprovado_para_assinar(fabrica, tmp_path, assinatura_client_id='cli', assinatura_client_secret='seg',
                                     segredo_sessao='chave', assinatura_ambiente='producao')
    resultado = _resultado(_assinar_pelo_govbr(c, dono)[2])
    assert resultado['assinatura'] == 'erro' and 'não é do gov.br' in resultado['motivo']
    assert c.get('/meus-planos/lista', headers=dono).json['planos'][0]['assinatura'] is None


def test_erros_da_assinatura_pela_api(fabrica, tmp_path, monkeypatch):
    import requests
    api = _ApiFalsa(status_assinatura=403)
    monkeypatch.setattr(requests, 'post', api)
    c, dono = _aprovado_para_assinar(fabrica, tmp_path, assinatura_client_id='cli', assinatura_client_secret='seg',
                                     segredo_sessao='chave', assinatura_ambiente='homologacao')
    # Conta bronze (403 da API)
    assert 'prata ou ouro' in _resultado(_assinar_pelo_govbr(c, dono)[2])['motivo']
    # Cancelado no gov.br; state forjado (outra aba)
    assert 'cancelada' in _resultado(_assinar_pelo_govbr(c, dono, error='access_denied')[2])['motivo']
    c.get('/assinatura/govbr/iniciar?arquivo=web.pdf', headers=dono)
    volta = c.get('/assinatura/govbr/callback?code=x&state=forjado', headers=dono)
    assert 'expirou' in _resultado(volta)['motivo']
    # Quem não é dono do plano nem chega ao gov.br
    r = c.get('/assinatura/govbr/iniciar?arquivo=web.pdf', headers=NDE)
    assert 'Só quem enviou o plano' in _resultado(r)['motivo']
    assert len([u for u, _ in api.pedidos if u.endswith('/assinarPKCS7')]) == 1  # só a do bronze chamou a API


def test_sem_credenciais_nao_ha_assinatura_pela_api(fabrica, tmp_path):
    c, dono = _aprovado_para_assinar(fabrica, tmp_path)
    assert 'ASSINATURA_API = false' in c.get('/meus-planos', headers=dono).get_data(as_text=True)
    r = c.get('/assinatura/govbr/iniciar?arquivo=web.pdf', headers=dono)
    assert 'não está configurada' in _resultado(r)['motivo']


def test_assinatura_simulada_so_com_login_simulado(fabrica, tmp_path):
    # Desenvolvimento: sem ir ao gov.br
    c, dono = _aprovado_para_assinar(fabrica, tmp_path, login_simulado=True, assinatura_ambiente='simulada')
    r = c.get('/assinatura/govbr/iniciar?arquivo=web.pdf', headers=dono)
    assert r.headers['Location'].startswith('http://localhost/assinatura/govbr/callback?code=simulado')
    assert _resultado(c.get(r.headers['Location'], headers=dono))['assinatura'] == 'ok'
    # Fora do desenvolvimento, "simulada" não liga nada
    from app.config import Config
    assert not Config(planos_dir='', resultados_dir='', ollama_url='', modelo='', num_ctx=1, hora_agendada=5,
                      agendar=False, assinatura_ambiente='simulada').assinatura_api_ativa


# O plano é do professor que o enviou --------------------------------------------------------------------

def _plano_de(docente):
    from conftest import gerar_pdf
    return gerar_pdf(['CCC0723 - DESENVOLVIMENTO WEB I (60h) - Turma: 01 (2026.2)', 'Ementa: algo do plano.',
                      'Matricula Docente(s)', '1234567 ' + docente + ' - 60h', 'Objetivos: mais texto do plano.']
                     + ['Linha de texto numero %d do plano de ensino de teste.' % i for i in range(8)])


def test_envio_confere_o_docente_do_pdf_com_o_cadastro(com_login, sem_ia):
    c, planos = com_login
    fulano = {**SERVIDOR, 'X-Usuario-Token': _token(email='fulano@ifc.edu.br', name='Fulano de Tal')}
    # Mesmo nome, ou parecido (sobrenome a mais no PDF, acento, uma letra diferente)
    r = _enviar_meus(c, ('meu.pdf', _plano_de('FULANO DE TAL SILVA')), ('grafia.pdf', _plano_de('FULANU DE TAL')),
                     cab=fulano)
    assert [s['nome'] for s in r.json['salvos']] == ['meu.pdf', 'grafia.pdf'], r.json
    # Plano de outra pessoa: recusado, e a versão anterior fica
    r = _enviar_meus(c, ('meu.pdf', _plano_de('BELTRANO PEREIRA')), cab=fulano)
    assert r.status_code == 400 and 'Beltrano Pereira' in r.json['recusados'][0]['motivo']
    assert 'Fulano de Tal' in r.json['recusados'][0]['motivo']
    assert b'FULANO DE TAL SILVA' in (planos / 'meu.pdf').read_bytes()
    assert sorted(os.listdir(planos)) == ['grafia.pdf', 'meu.pdf']  # nenhum temporário sobra
    # Sem o bloco de docentes no PDF, não há o que conferir
    assert _enviar_meus(c, ('sem-docente.pdf', PDF), cab=fulano).status_code == 200


def test_sem_nome_no_cadastro_o_envio_nao_e_conferido(com_login, sem_ia):
    c, _ = com_login
    r = _enviar_meus(c, ('outro.pdf', _plano_de('BELTRANO PEREIRA')), cab={'X-Usuario-Email': 'novo@ifc.edu.br'})
    assert r.status_code == 200


def test_docente_exibido_e_o_do_cadastro(com_login, sem_ia):
    from app.armazenamento import detalhes
    c, planos = com_login
    fulano = {**SERVIDOR, 'X-Usuario-Token': _token(email='fulano@ifc.edu.br', name='Fulano de Tal')}
    _enviar_meus(c, ('meu.pdf', _plano_de('FULANO DE TAL SILVA')), cab=fulano)
    (planos / 'antigo.pdf').write_bytes(PDF)  # sem dono: vale o docente escrito no PDF
    execucao = _execucao(c, ['meu.pdf', 'antigo.pdf'], 10)
    detalhes.salvar(execucao.detalhes_dir, 'meu.pdf', {'texto': 'Matrícula Docente(s)\n1234567 FULANO DE TAL SILVA - 60h\n'})
    detalhes.salvar(execucao.detalhes_dir, 'antigo.pdf', {'texto': 'Matrícula Docente(s)\n7654321 CICLANO SOUZA - 30h\n'})
    html = c.get('/dashboard', headers=ADMIN).get_data(as_text=True)
    assert 'data-docente="Fulano de Tal"' in html  # o nome do cadastro, não o do PDF
    assert 'data-docente="Ciclano Souza"' in html


def test_aviso_de_privacidade_publico(fabrica):
    c, _ = fabrica(exigir_login=True)
    r = c.get('/privacidade')
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and 'LGPD' in html and '_planos_govbr' in html and 'cookies necessários' in html
    assert 'href="/privacidade"' in c.get('/').get_data(as_text=True)  # no rodapé


def test_entrar_do_cabecalho_leva_ao_login(fabrica):
    c, _ = fabrica(exigir_login=True)
    assert 'class="br-button primary small entrar" href="#entrar"' in c.get('/').get_data(as_text=True)
    assert 'href="/entrar?rd=/dashboard"' in c.get('/privacidade').get_data(as_text=True)
