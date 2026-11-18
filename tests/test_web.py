import io
import os
from pathlib import Path

import pytest

from conftest import PDF_COM_TEXTO, PDF_SEM_TEXTO, dar_disciplina, enviar_plano

PDF = PDF_COM_TEXTO


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


def test_upload_lista_e_exclui(cliente, sem_ia):
    c, planos = cliente
    o = dar_disciplina(c)
    r = enviar_plano(c, o, PDF, nome='Plano Á qualquer nome.pdf')
    assert r.status_code == 200 and r.json['nome'] == o['arquivo'] and not r.json['substituido']
    assert o['arquivo'] == '2026.2-CCC0723-T01-%d.pdf' % o['id']  # o nome vem da disciplina, não do arquivo
    assert (planos / o['arquivo']).read_bytes() == PDF
    assert [p['nome'] for p in c.get('/planos').json['planos']] == [o['arquivo']]

    r = enviar_plano(c, o, PDF)
    assert r.json['substituido'] and sorted(os.listdir(planos)) == [o['arquivo']]

    assert c.delete('/meus-planos?arquivo=' + o['arquivo']).status_code == 200
    assert not (planos / o['arquivo']).exists()


def test_administrador_nao_envia_planos(cliente):
    c, planos = cliente
    assert c.post('/planos', data=_envio(('b.pdf', PDF)), content_type='multipart/form-data').status_code == 405
    adm = c.get('/administracao').get_data(as_text=True)
    assert 'id="soltar"' not in adm and 'id="lista"' in adm
    assert not (planos / 'b.pdf').exists()


def test_validar_meus_planos_so_os_sem_revisao_humana(com_login, sem_ia, monkeypatch):
    c, planos = com_login
    s = _servicos(c)
    eu = 'fulano@ifc.edu.br'
    r = c.post('/meus-planos/validar', headers=SERVIDOR)
    assert r.status_code == 422 and 'ainda não enviou' in r.json['mensagem']
    a, b = dar_disciplina(c, eu), dar_disciplina(c, eu, codigo='CCC0724', nome='Banco de Dados')
    dar_disciplina(c, eu, codigo='CCC0725', nome='Sem plano')
    outro = dar_disciplina(c, 'outro@ifc.edu.br', codigo='CCC0726', nome='De outro docente')
    for o, cab in ((a, SERVIDOR), (b, SERVIDOR), (outro, {'X-Usuario-Email': 'outro@ifc.edu.br'})):
        assert enviar_plano(c, o, PDF, cab=cab).status_code == 200
    s.revisao.revisoes.salvar(b['arquivo'], s.revisao.assinatura(b['arquivo']), 'OK', 'OK', '', 'CC',
                              'nde@ifc.edu.br', 'NDE', 'nde')
    na_fila = []
    monkeypatch.setattr(s.validador, 'enfileirar', na_fila.append)
    r = c.post('/meus-planos/validar', headers=SERVIDOR)
    assert r.status_code == 200 and r.json == {'status': 'iniciado', 'planos': 1} and na_fila == [a['arquivo']]
    s.revisao.revisoes.salvar(a['arquivo'], s.revisao.assinatura(a['arquivo']), 'PENDENTE', 'OK', 'corrigir', 'CC',
                              'nde@ifc.edu.br', 'NDE', 'nde')
    r = c.post('/meus-planos/validar', headers=SERVIDOR)
    assert r.status_code == 422 and 'revisados' in r.json['mensagem'] and na_fila == [a['arquivo']]


def test_upload_pede_a_disciplina_e_um_pdf(cliente, sem_ia):
    c, planos = cliente
    o = dar_disciplina(c)
    sem_disciplina = c.post('/meus-planos', data={'arquivo': (io.BytesIO(PDF), 'a.pdf')}, content_type='multipart/form-data')
    assert sem_disciplina.status_code == 400 and 'disciplina' in sem_disciplina.json['erro']
    assert enviar_plano(c, 999999, PDF).json['erro'] == 'Disciplina não encontrada.'
    assert c.post('/meus-planos', data={'oferta': str(o['id'])}).status_code == 400
    r = enviar_plano(c, o, b'nao e pdf', nome='falso.pdf')
    assert r.status_code == 400 and 'não é um PDF' in r.json['erro']
    assert enviar_plano(c, o, PDF, nome='x.txt').status_code == 200  # o nome do arquivo não importa
    assert sorted(os.listdir(planos)) == [o['arquivo']]


def test_upload_recusa_pdf_grande_digitalizado_ou_corrompido(cliente, sem_ia):
    c, planos = cliente
    o = dar_disciplina(c)
    grande = PDF + b'%' + b'0' * (1024 * 1024)
    assert 'maior que 1 MB' in enviar_plano(c, o, grande).json['erro']
    assert 'OCR' in enviar_plano(c, o, PDF_SEM_TEXTO).json['erro']
    assert 'não pôde ser aberto' in enviar_plano(c, o, b'%PDF-1.4 lixo').json['erro']
    assert os.listdir(planos) == []  # nenhum temporário sobra
    assert enviar_plano(c, o, PDF).status_code == 200
    assert sorted(os.listdir(planos)) == [o['arquivo']]


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
    assert 'id="plano-1"' in dashboard and 'const MAX_MB = 1, ADMIN = true;' in dashboard


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
    assert 'pdfs.zip' not in html and '/csv' not in html  # a exportação fica na coordenação
    assert 'href="/dashboard#plano-0"' in c.get('/relatorio?arquivo=novo.pdf').get_data(as_text=True)
    assert c.get('/relatorio?arquivo=velho.pdf').status_code == 404


def test_pdf_da_ultima_validacao(cliente):
    c, _ = cliente
    antiga = _execucao(c, ['a.pdf'], 9)
    nova = _execucao(c, ['a.pdf', 'b.pdf'], 10, pdfs=['a.pdf', 'b.pdf'])
    assert c.get(f'/validacoes/{nova.id}/pdf?arquivo=b.pdf').data == PDF
    assert c.get(f'/validacoes/{antiga.id}/pdf?arquivo=a.pdf').status_code == 404
    assert c.get('/validacoes/..%2Fx/pdf?arquivo=a.pdf').status_code == 404
    for rota in (f'/validacoes/{nova.id}/csv', f'/validacoes/{nova.id}/pdfs.zip'):  # exportações removidas
        assert c.get(rota).status_code == 404
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


def test_admin_so_exclui_pdf_sem_disciplina_e_oculta_os_das_disciplinas(com_login):
    from app.armazenamento import csvsaida
    c, planos = com_login
    (planos / 'prof.pdf').write_bytes(PDF)
    dar_disciplina(c, 'fulano@ifc.edu.br', arquivo='prof.pdf')
    (planos / 'solto.pdf').write_bytes(PDF)  # copiado direto para a pasta: sem disciplina
    execucao = _execucao(c, ['prof.pdf', 'solto.pdf'], 10)

    lista = {p['nome']: p for p in c.get('/planos', headers=ADMIN).json['planos']}
    assert lista['solto.pdf']['pode_excluir'] and lista['solto.pdf']['dono'] == ''
    assert not lista['prof.pdf']['pode_excluir'] and lista['prof.pdf']['dono'] == 'fulano@ifc.edu.br'
    assert lista['prof.pdf']['disciplina'] == 'CCC0723 · Desenvolvimento Web I · Turma 01'

    # O plano de uma disciplina: não exclui, mas oculta do painel
    r = c.delete('/planos?arquivo=prof.pdf', headers=ADMIN)
    assert r.status_code == 403 and 'ocultados' in r.json['erro']
    assert c.post('/planos/ocultar?arquivo=prof.pdf', headers=ADMIN).status_code == 200
    html = c.get('/dashboard', headers=SERVIDOR).get_data(as_text=True)
    assert 'href="/relatorio?arquivo=prof.pdf"' not in html and 'href="/relatorio?arquivo=solto.pdf"' in html
    assert 'prof.pdf' in [l['Arquivo'] for l in csvsaida.ler_csv(execucao.csv_path)]  # a avaliação continua
    assert c.get('/planos', headers=ADMIN).json['planos'][0]['oculto']
    assert c.delete('/planos/ocultar?arquivo=prof.pdf', headers=ADMIN).status_code == 200
    assert 'href="/relatorio?arquivo=prof.pdf"' in c.get('/dashboard', headers=SERVIDOR).get_data(as_text=True)

    # Sem disciplina: exclui
    assert c.delete('/planos?arquivo=solto.pdf', headers=ADMIN).status_code == 200
    assert [l['Arquivo'] for l in csvsaida.ler_csv(execucao.csv_path)] == ['prof.pdf']
    assert c.post('/planos/ocultar?arquivo=sumiu.pdf', headers=ADMIN).status_code == 404


def test_versao_nova_do_pdf_volta_ao_painel(cliente, sem_ia):
    c, planos = cliente
    o = dar_disciplina(c)
    enviar_plano(c, o, PDF)
    _execucao(c, [o['arquivo']], 10)
    c.post('/planos/ocultar?arquivo=' + o['arquivo'])
    assert 'href="/relatorio?arquivo=%s"' % o['arquivo'] not in c.get('/dashboard').get_data(as_text=True)
    enviar_plano(c, o, PDF)
    assert 'href="/relatorio?arquivo=%s"' % o['arquivo'] in c.get('/dashboard').get_data(as_text=True)


def test_professor_exclui_o_plano_da_sua_disciplina_com_a_avaliacao(com_login):
    from app.armazenamento import csvsaida
    c, planos = com_login
    (planos / 'meu.pdf').write_bytes(PDF)
    dar_disciplina(c, 'fulano@ifc.edu.br', 'beltrano@ifc.edu.br', arquivo='meu.pdf')
    execucao = _execucao(c, ['meu.pdf'], 10)
    assert c.delete('/meus-planos?arquivo=meu.pdf', headers={'X-Usuario-Email': 'outro@ifc.edu.br'}).status_code == 403
    assert c.delete('/meus-planos?arquivo=meu.pdf', headers={'X-Usuario-Email': 'beltrano@ifc.edu.br'}).status_code == 200
    assert csvsaida.ler_csv(execucao.csv_path) == [] and not (planos / 'meu.pdf').exists()
    oferta = _servicos(c).disciplinas.do_arquivo('meu.pdf')
    assert oferta['enviado_em'] is None and oferta['docentes'] == ['beltrano@ifc.edu.br', 'fulano@ifc.edu.br']


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
    assert 'ADMIN = false;' in html and 'href="/meus-planos"' in html and 'href="/administracao"' not in html
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


def test_professor_entrega_e_acompanha_o_plano_da_sua_disciplina(com_login, monkeypatch):
    from app.armazenamento import detalhes
    from app.avaliacao import pipeline
    c, planos = com_login
    chamadas = []
    monkeypatch.setattr(pipeline, 'revalidar', lambda cfg, andamento, nome: (chamadas.append(nome), andamento.finalizar()))
    o = dar_disciplina(c, 'fulano@ifc.edu.br')
    nome = o['arquivo']
    [plano] = c.get('/meus-planos/lista', headers=SERVIDOR).json['planos']
    assert plano['situacao'] == 'sem_plano' and plano['oferta_id'] == o['id'] and not plano['tem_plano']
    assert plano['disciplina'] == 'Desenvolvimento Web I (Turma 01)' and plano['fase'] == 4

    r = enviar_plano(c, o, PDF, cab=SERVIDOR)
    assert r.json == {'nome': nome, 'substituido': False, 'posicao': 0, 'aviso': '', 'versao_anterior': None}
    assert chamadas == [nome] and (planos / nome).exists()
    [plano] = c.get('/meus-planos/lista', headers=SERVIDOR).json['planos']
    assert plano['situacao'] == 'aguardando' and plano['tem_plano']  # a avaliação falsa não gravou resultado

    execucao = _execucao(c, [nome], 23, {'status_geral': 'PENDENTE'})
    detalhes.salvar(execucao.detalhes_dir, nome, {'validado_em': '2099-01-01T00:00:00'})
    [plano] = c.get('/meus-planos/lista', headers=SERVIDOR).json['planos']
    assert plano['situacao'] == 'avaliado' and plano['status'] == 'PENDENTE' and 'Ementa' in plano['problemas']

    # Quem não é docente da disciplina não a vê, nem envia, substitui ou exclui o plano dela
    assert c.get('/meus-planos/lista', headers=ADMIN).json['planos'] == []
    r = enviar_plano(c, o, PDF, cab=ADMIN)
    assert r.status_code == 400 and 'não é docente' in r.json['erro']
    assert c.delete(f'/meus-planos?arquivo={nome}', headers=ADMIN).status_code == 403
    assert c.get('/planos', headers=ADMIN).json['planos'][0]['dono'] == 'fulano@ifc.edu.br'

    # O docente substitui e exclui
    r = enviar_plano(c, o, PDF, cab=SERVIDOR)
    assert r.json['substituido'] and chamadas == [nome, nome]
    assert c.delete(f'/meus-planos?arquivo={nome}', headers=SERVIDOR).status_code == 200
    assert not (planos / nome).exists()
    assert c.get('/meus-planos/lista', headers=SERVIDOR).json['planos'][0]['situacao'] == 'sem_plano'


def test_sem_disciplina_vinculada_nao_ha_onde_enviar(com_login):
    c, planos = com_login
    (planos / 'antigo.pdf').write_bytes(PDF)  # copiado direto para a pasta: sem disciplina
    assert c.get('/meus-planos/lista', headers=SERVIDOR).json['planos'] == []
    assert 'Nenhuma disciplina vinculada' in c.get('/static/js/meus_planos.js').get_data(as_text=True)
    assert c.delete('/meus-planos?arquivo=antigo.pdf', headers=SERVIDOR).status_code == 403


def test_docente_cadastrado_depois_ve_a_disciplina_no_primeiro_acesso(com_login):
    c, _ = com_login
    dar_disciplina(c, 'novo.docente@ifc.edu.br')
    novo = {'X-Usuario-Email': 'novo.docente@ifc.edu.br'}
    [plano] = c.get('/meus-planos/lista', headers=novo).json['planos']
    assert plano['docentes'] == [{'email': 'novo.docente@ifc.edu.br', 'nome': '', 'cadastrado': True}]


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


def test_meus_planos_agrupados_por_periodo_e_fase(com_login):
    c, _ = com_login
    dar_disciplina(c, 'fulano@ifc.edu.br')  # 2026.2, 4ª fase
    dar_disciplina(c, 'fulano@ifc.edu.br', periodo='2026.1', codigo='CCC0707', nome='Álgebra Linear', fase=2)
    dar_disciplina(c, 'fulano@ifc.edu.br', codigo='CCC0715', nome='Banco de Dados I', fase=3)
    dar_disciplina(c, 'fulano@ifc.edu.br', 'outra@ifc.edu.br', codigo='', nome='Tópicos em Visão Computacional', fase=6)
    planos = c.get('/meus-planos/lista', headers=SERVIDOR).json['planos']
    assert [(p['disciplina'], p['grupo_titulo']) for p in planos] == [
        ('Banco de Dados I (Turma 01)', 'Ciência da Computação · 2º semestre de 2026'),
        ('Desenvolvimento Web I (Turma 01)', 'Ciência da Computação · 2º semestre de 2026'),
        ('Tópicos em Visão Computacional (Turma 01)', 'Ciência da Computação · 2º semestre de 2026'),
        ('Álgebra Linear (Turma 01)', 'Ciência da Computação · 1º semestre de 2026'),
    ]
    assert planos[1]['componente'] == 'CCC0723 · Desenvolvimento Web I · Turma 01'
    assert [d['email'] for d in planos[2]['docentes']] == ['fulano@ifc.edu.br', 'outra@ifc.edu.br']


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
    o = dar_disciplina(c, 'fulano@ifc.edu.br', arquivo='web.pdf')
    enviar_plano(c, o, pdf, cab=SERVIDOR)
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


def test_docente_do_plano_nao_o_revisa(com_login):
    c, planos = com_login
    _plano_cc(c, planos, status='PENDENTE')
    dar_disciplina(c, 'nde@ifc.edu.br', arquivo='web.pdf')  # o próprio NDE enviou
    _dar_papel(c, 'nde@ifc.edu.br')
    _dar_papel(c, 'outro@ifc.edu.br')
    OUTRO = {'X-Usuario-Email': 'outro@ifc.edu.br'}

    html = c.get('/relatorio?arquivo=web.pdf', headers=NDE).get_data(as_text=True)
    assert 'action="/revisao"' not in html and 'Você é docente deste plano' in html
    assert 'class="revisar"' not in c.get('/dashboard', headers=NDE).get_data(as_text=True)
    r = c.post('/revisao', headers=NDE, data={'arquivo': 'web.pdf', 'status': 'OK', 'comentario': 'ok'})
    assert r.status_code == 403 and 'Você é docente deste plano' in r.get_data(as_text=True)
    assert _servicos(c).revisao.vigente('web.pdf') is None

    # Outro membro revisa; o autor também não desfaz a revisão dele
    assert 'class="revisar"' in c.get('/dashboard', headers=OUTRO).get_data(as_text=True)
    r = c.post('/revisao', headers=OUTRO, data={'arquivo': 'web.pdf', 'status': 'OK', 'comentario': 'Completo.'})
    assert 'aviso=salva' in r.headers['Location']
    assert c.post('/revisao', headers=NDE, data={'arquivo': 'web.pdf', 'acao': 'desfazer'}).status_code == 403
    assert _servicos(c).revisao.vigente('web.pdf')['status'] == 'OK'


def test_coordenador_revisa_o_plano_da_propria_disciplina(com_login):
    c, planos = com_login
    _plano_cc(c, planos, status='OK')
    dar_disciplina(c, 'coord@ifc.edu.br', arquivo='web.pdf')  # o próprio coordenador enviou
    _dar_papel(c, 'coord@ifc.edu.br', papel='coordenador')
    COORD = {'X-Usuario-Email': 'coord@ifc.edu.br'}

    html = c.get('/relatorio?arquivo=web.pdf', headers=COORD).get_data(as_text=True)
    assert 'action="/revisao"' in html and 'Você é docente deste plano' not in html
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
    from conftest import assinar, gerar_ac, salvar_ac
    ac = gerar_ac()
    c, planos = fabrica(exigir_login=True, admins=frozenset({'admin@ifc.edu.br'}),
                        certificados_dir=salvar_ac(ac, tmp_path / 'certificados'))
    _plano_cc(c, planos, status='OK')
    dar_disciplina(c, 'fulano@ifc.edu.br', arquivo='web.pdf')
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

    # Só docente da disciplina assina; o PDF precisa estar assinado, pela AC aceita, por quem é do plano
    assert enviar(assinado, NDE).status_code == 403
    r = enviar(PDF)
    assert r.status_code == 422 and 'não tem assinatura' in r.json['erro']
    assert 'não é do gov.br' in enviar(assinar(PDF, gerar_ac())).json['erro']
    assert c.get('/pdf-assinado?arquivo=web.pdf', headers=SERVIDOR).status_code == 404
    # Nome do certificado diferente do professor e dos docentes: aceita, com alerta
    outro = {**SERVIDOR, 'X-Usuario-Token': _token(email='fulano@ifc.edu.br', name='Beltrano Pereira')}
    r = enviar(assinado, outro)
    assert r.status_code == 200 and 'não confere' in r.json['assinatura']['aviso']
    html = c.get('/relatorio?arquivo=web.pdf', headers=NDE).get_data(as_text=True)
    assert 'Atenção: O nome do certificado (FULANO DE TAL)' in html

    proprio = {**SERVIDOR, 'X-Usuario-Token': _token(email='fulano@ifc.edu.br', name='Fulano de Tal')}
    r = enviar(assinado, proprio)
    assert r.status_code == 200 and r.json['assinatura']['signatario'] == 'FULANO DE TAL'
    assert r.json['assinatura']['aviso'] == ''
    [plano] = c.get('/meus-planos/lista', headers=SERVIDOR).json['planos']
    assert plano['assinatura']['signatario'] == 'FULANO DE TAL'
    assert c.get('/pdf-assinado?arquivo=web.pdf', headers=NDE).data == assinado
    assert 'Assinado via gov.br por FULANO DE TAL' in c.get('/relatorio?arquivo=web.pdf', headers=NDE).get_data(as_text=True)
    assert '/pdf-assinado?arquivo=web.pdf' in c.get('/dashboard', headers=NDE).get_data(as_text=True)

    # Desfeita a aprovação, a assinatura deixa de valer
    c.post('/revisao', headers=NDE, data={'arquivo': 'web.pdf', 'acao': 'desfazer'})
    assert c.get('/meus-planos/lista', headers=SERVIDOR).json['planos'][0]['assinatura'] is None
    assert c.get('/pdf-assinado?arquivo=web.pdf', headers=NDE).status_code == 404


def test_plano_assinado_e_atualizado_e_a_versao_fica_no_historico(fabrica, tmp_path, monkeypatch):
    from app.avaliacao import pipeline
    from conftest import assinar, gerar_ac, salvar_ac
    monkeypatch.setattr(pipeline, 'revalidar', lambda cfg, andamento, nome: andamento.finalizar())
    ac = gerar_ac()
    c, planos = fabrica(exigir_login=True, admins=frozenset({'admin@ifc.edu.br'}),
                        certificados_dir=salvar_ac(ac, tmp_path / 'certificados'))
    _plano_cc(c, planos, status='OK')
    o = dar_disciplina(c, 'fulano@ifc.edu.br', arquivo='web.pdf')
    _servicos(c).disciplinas.ofertas.registrar_envio('web.pdf', 'fulano@ifc.edu.br')
    _dar_papel(c, 'nde@ifc.edu.br')
    COORD = {'X-Usuario-Email': 'coord@ifc.edu.br'}
    _dar_papel(c, 'coord@ifc.edu.br', papel='coordenador')

    c.post('/revisao', headers=NDE, data={'arquivo': 'web.pdf', 'status': 'OK'})
    proprio = {**SERVIDOR, 'X-Usuario-Token': _token(email='fulano@ifc.edu.br', name='Fulano de Tal')}
    assinado = assinar(PDF, ac)
    r = c.post('/meus-planos/assinatura', headers=proprio, content_type='multipart/form-data',
               data={'arquivo': 'web.pdf', 'pdf': (io.BytesIO(assinado), 'assinado.pdf')})
    assert r.status_code == 200
    [plano] = c.get('/meus-planos/lista', headers=SERVIDOR).json['planos']
    assert plano['versao'] == 1 and plano['versoes'] == [] and plano['assinatura']
    assert 'Liberar novo envio' not in c.get('/coordenacao', headers=COORD).get_data(as_text=True)

    # Assinado: o docente atualiza mesmo assim, e a versão assinada vai para o histórico
    novo = gerar_pdf_plano('Versão nova do plano.')
    r = enviar_plano(c, o, novo, cab=SERVIDOR)
    assert r.status_code == 200 and r.json['substituido'] and r.json['versao_anterior'] == 1
    assert (planos / 'web.pdf').read_bytes() == novo
    [plano] = c.get('/meus-planos/lista', headers=SERVIDOR).json['planos']
    assert plano['versao'] == 2 and plano['assinatura'] is None and plano['revisao'] is None  # recomeça
    [v1] = plano['versoes']
    assert (v1['numero'], v1['revisao_status'], v1['signatario'], v1['tem_assinado']) == (1, 'OK', 'FULANO DE TAL', True)
    assert v1['enviado_por'] == 'fulano@ifc.edu.br'
    assert c.get('/meus-planos/versao?arquivo=web.pdf&numero=1', headers=SERVIDOR).data == PDF
    r = c.get('/meus-planos/versao?arquivo=web.pdf&numero=1&assinado=1', headers=SERVIDOR)
    assert r.data == assinado and 'web-v1-assinado.pdf' in r.headers['Content-Disposition']

    # Mais uma versão: a 2 (sem assinatura) também vai para o histórico
    r = enviar_plano(c, o, PDF, cab=SERVIDOR)
    assert r.json['versao_anterior'] == 2
    [plano] = c.get('/meus-planos/lista', headers=SERVIDOR).json['planos']
    assert [v['numero'] for v in plano['versoes']] == [2, 1] and plano['versao'] == 3
    assert not plano['versoes'][0]['tem_assinado']
    assert c.get('/meus-planos/versao?arquivo=web.pdf&numero=2&assinado=1', headers=SERVIDOR).status_code == 404

    # PDF recusado não mexe no histórico
    assert enviar_plano(c, o, b'nao e pdf', cab=SERVIDOR).status_code == 400
    assert len(c.get('/meus-planos/lista', headers=SERVIDOR).json['planos'][0]['versoes']) == 2


def test_excluir_versoes_menos_a_aprovada_e_assinada(fabrica, tmp_path, monkeypatch):
    from app.avaliacao import pipeline
    from conftest import assinar, gerar_ac, salvar_ac
    monkeypatch.setattr(pipeline, 'revalidar', lambda cfg, andamento, nome: andamento.finalizar())
    ac = gerar_ac()
    c, planos = fabrica(exigir_login=True, admins=frozenset({'admin@ifc.edu.br'}),
                        certificados_dir=salvar_ac(ac, tmp_path / 'certificados'))
    _plano_cc(c, planos, status='OK')
    o = dar_disciplina(c, 'fulano@ifc.edu.br', arquivo='web.pdf')
    _dar_papel(c, 'nde@ifc.edu.br')
    c.post('/revisao', headers=NDE, data={'arquivo': 'web.pdf', 'status': 'OK'})
    proprio = {**SERVIDOR, 'X-Usuario-Token': _token(email='fulano@ifc.edu.br', name='Fulano de Tal')}
    c.post('/meus-planos/assinatura', headers=proprio, content_type='multipart/form-data',
           data={'arquivo': 'web.pdf', 'pdf': (io.BytesIO(assinar(PDF, ac)), 'assinado.pdf')})

    # A versão atual, assinada, não é excluída: o professor atualiza
    r = c.delete('/meus-planos?arquivo=web.pdf', headers=SERVIDOR)
    assert r.status_code == 403 and 'Enviar nova versão' in r.json['erro'] and (planos / 'web.pdf').exists()
    enviar_plano(c, o, gerar_pdf_plano('Versão 2.'), cab=SERVIDOR)  # v1 (assinada) vai para o histórico
    enviar_plano(c, o, gerar_pdf_plano('Versão 3.'), cab=SERVIDOR)  # v2 (sem revisão) também
    [plano] = c.get('/meus-planos/lista', headers=SERVIDOR).json['planos']
    assert plano['versao'] == 3 and [(v['numero'], v['protegida']) for v in plano['versoes']] == [(2, False), (1, True)]

    url = '/meus-planos/versao?arquivo=web.pdf&numero='
    assert c.delete(url + '2', headers={'X-Usuario-Email': 'outro@ifc.edu.br'}).status_code == 403
    r = c.delete(url + '1', headers=SERVIDOR)
    assert r.status_code == 403 and 'aprovada e assinada' in r.json['erro']
    assert c.delete(url + '2', headers=SERVIDOR).json == {'excluida': 2}
    assert c.delete(url + '2', headers=SERVIDOR).status_code == 404  # já excluída
    assert c.get(url + '2', headers=SERVIDOR).status_code == 404 and c.get(url + '1', headers=SERVIDOR).status_code == 200
    assert c.delete(url + 'x', headers=SERVIDOR).status_code == 400
    assert c.delete('/meus-planos/versao?arquivo=../x.pdf&numero=1', headers=SERVIDOR).status_code == 400

    # O número da versão excluída não volta: a próxima arquivada é a 3, e a atual passa a ser a 4
    assert enviar_plano(c, o, PDF, cab=SERVIDOR).json['versao_anterior'] == 3
    [plano] = c.get('/meus-planos/lista', headers=SERVIDOR).json['planos']
    assert plano['versao'] == 4 and [v['numero'] for v in plano['versoes']] == [3, 1]
    # Sem assinatura, a versão atual é excluída normalmente (as do histórico ficam)
    assert c.delete('/meus-planos?arquivo=web.pdf', headers=SERVIDOR).status_code == 200
    [plano] = c.get('/meus-planos/lista', headers=SERVIDOR).json['planos']
    assert plano['tem_plano'] is False and [v['numero'] for v in plano['versoes']] == [3, 1]


def gerar_pdf_plano(*linhas):
    from conftest import gerar_pdf
    return gerar_pdf(list(linhas) + ['Linha de texto do plano de ensino numero %d.' % i for i in range(8)])


def test_meus_planos_por_periodo_com_o_atual_e_o_proximo_em_destaque(com_login):
    from datetime import date
    from app.paginas.meus_planos import periodos_em_destaque
    assert periodos_em_destaque(date(2026, 11, 14)) == {'2026.2': 'Atual', '2026': 'Atual', '2027.1': 'Próximo',
                                                        '2027': 'Próximo'}
    assert periodos_em_destaque(date(2026, 3, 1)) == {'2026.1': 'Atual', '2026': 'Atual', '2026.2': 'Próximo',
                                                      '2027': 'Próximo'}
    c, _ = com_login
    dar_disciplina(c, 'fulano@ifc.edu.br', periodo='2026.1')
    planos = c.get('/meus-planos/lista', headers=SERVIDOR).json['planos']
    assert planos[0]['periodo'] == '2026.1' and planos[0]['curso'] == 'Ciência da Computação'
    html = c.get('/meus-planos', headers=SERVIDOR).get_data(as_text=True)
    assert 'DESTAQUES = {' in html and 'id="periodos"' in html and '"Atual"' in html


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
    assert ida['code_challenge_method'] == ['S256'] and ida['scope'] == ['openid email profile govbr_confiabilidades govbr_confiabilidades_idtoken']
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

    # Sair apaga a sessão do app e vai ao /logout do gov.br (roteiro), que encerra a sessão dele e volta na URL
    # de Log Out (/auth/gov/logout), que leva à página inicial
    r = c.get('/auth/sair')
    assert r.headers['Location'] == ('https://sso.acesso.gov.br/logout?post_logout_redirect_uri='
                                     'http%3A%2F%2Flocalhost%2Fauth%2Fgov%2Flogout')
    assert c.get('/auth/verificar').status_code == 401
    assert c.get_cookie('_planos_govbr_sso') is None
    assert c.get('/auth/gov/logout').headers['Location'] == '/oauth2/sign_out?rd=%2F'
    assert '<iframe' not in c.get('/').get_data(as_text=True)
    # Sem ter passado pelo gov.br (entrou só pelo Google)
    assert c.get('/auth/sair').headers['Location'] == '/oauth2/sign_out?rd=%2F'


def test_login_govbr_recusado(fabrica, monkeypatch):
    c, _ = fabrica(**GOVBR)
    _, volta, _ = _login_govbr(c, monkeypatch, email='fulano@gmail.com', sub='')
    assert volta.status_code == 403 and '@ifc.edu.br' in volta.get_data(as_text=True)
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
    assert volta.status_code == 403 and 'Vincule' in html and '/oauth2/start?rd=/conta/govbr/vincular' in html
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
    from conftest import gerar_ac, salvar_ac
    c, planos = fabrica(exigir_login=True, admins=frozenset({'admin@ifc.edu.br'}), cookie_seguro=False,
                        certificados_dir=salvar_ac(gerar_ac(), tmp_path / 'certificados'), **opcoes)
    _plano_cc(c, planos, status='OK')
    dar_disciplina(c, 'fulano@ifc.edu.br', arquivo='web.pdf')
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
    pagina = c.get('/meus-planos', headers=dono).get_data(as_text=True)
    assert 'ASSINATURA_API = true' in pagina and 'ASSINATURA_HOMOLOGACAO = true' in pagina
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
    r = c.get('/pdf-assinado?arquivo=web.pdf', headers=NDE)
    assert r.data.startswith(b'%PDF') and b'(AssinaturaGovBr)' in r.data
    assert 'web-assinado.pdf' in r.headers['Content-Disposition']


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


# O plano é da disciplina; o PDF é só conferido (aviso) ------------------------------------------------

def _plano_de(docente, cabecalho='CCC0723 - DESENVOLVIMENTO WEB I (60h) - Turma: 01 (2026.2)'):
    from conftest import gerar_pdf
    return gerar_pdf([cabecalho, 'Ementa: algo do plano.',
                      'Matricula Docente(s)', '1234567 ' + docente + ' - 60h', 'Objetivos: mais texto do plano.']
                     + ['Linha de texto numero %d do plano de ensino de teste.' % i for i in range(8)])


FULANO = {**SERVIDOR, 'X-Usuario-Token': _token(email='fulano@ifc.edu.br', name='Fulano de Tal')}


def test_envio_confere_o_pdf_com_a_disciplina_e_so_avisa(com_login, sem_ia):
    c, planos = com_login
    o = dar_disciplina(c, 'fulano@ifc.edu.br', 'beltrano@ifc.edu.br')
    c.get('/dashboard', headers={'X-Usuario-Email': 'beltrano@ifc.edu.br',
                                 'X-Usuario-Token': _token(email='beltrano@ifc.edu.br', name='Beltrano Pereira')})
    # Mesmo nome, ou parecido (sobrenome a mais no PDF, acento, uma letra diferente): sem aviso
    for docente in ('FULANO DE TAL SILVA', 'FULANU DE TAL'):
        r = enviar_plano(c, o, _plano_de(docente), cab=FULANO)
        assert r.status_code == 200 and r.json['aviso'] == '', r.json
    # O outro docente da disciplina também vale
    assert enviar_plano(c, o, _plano_de('BELTRANO PEREIRA'), cab=FULANO).json['aviso'] == ''
    # Docente que não é da disciplina: aceito, com aviso para o professor e a coordenação
    r = enviar_plano(c, o, _plano_de('CICLANO SOUZA'), cab=FULANO)
    assert r.status_code == 200 and 'Ciclano Souza' in r.json['aviso']
    assert r.json['aviso'].count('Fulano de Tal') == 1 and 'Beltrano Pereira' in r.json['aviso']
    assert b'CICLANO SOUZA' in (planos / o['arquivo']).read_bytes()
    [plano] = c.get('/meus-planos/lista', headers=FULANO).json['planos']
    assert plano['aviso'] == r.json['aviso']
    # Outra disciplina ou outro período no PDF: aviso também
    r = enviar_plano(c, o, _plano_de('FULANO DE TAL', 'CCC0721 - BANCO DE DADOS II (60h) - Turma: 01 (2026.1)'), cab=FULANO)
    assert 'CCC0721' in r.json['aviso'] and 'CCC0723' in r.json['aviso'] and '2026.1' in r.json['aviso']
    # Sem o bloco de docentes nem o cabeçalho no PDF, não há o que conferir
    r = enviar_plano(c, o, PDF, cab=FULANO)
    assert r.json['aviso'] == '' and _servicos(c).disciplinas.do_arquivo(o['arquivo'])['aviso'] == ''


def test_aviso_aparece_para_a_coordenacao(com_login, sem_ia):
    c, _ = com_login
    o = dar_disciplina(c, 'fulano@ifc.edu.br')
    enviar_plano(c, o, _plano_de('CICLANO SOUZA'), cab=FULANO)
    _dar_papel(c, 'coord@ifc.edu.br', papel='coordenador')
    html = c.get('/disciplinas/CC/2026.2/disciplinas', headers={'X-Usuario-Email': 'coord@ifc.edu.br'}).get_data(as_text=True)
    assert 'plano enviado' in html and 'class="tag aviso"' in html and 'Ciclano Souza' in html


def test_sem_nome_no_cadastro_o_docente_nao_e_conferido(com_login, sem_ia):
    c, _ = com_login
    o = dar_disciplina(c, 'novo@ifc.edu.br')
    r = enviar_plano(c, o, _plano_de('BELTRANO PEREIRA'), cab={'X-Usuario-Email': 'novo@ifc.edu.br'})
    assert r.status_code == 200 and r.json['aviso'] == ''


def test_docente_exibido_e_o_da_disciplina(com_login, sem_ia):
    from app.armazenamento import detalhes
    c, planos = com_login
    o = dar_disciplina(c, 'fulano@ifc.edu.br')
    enviar_plano(c, o, _plano_de('FULANO DE TAL SILVA'), cab=FULANO)
    (planos / 'antigo.pdf').write_bytes(PDF)  # sem disciplina: vale o docente escrito no PDF
    execucao = _execucao(c, [o['arquivo'], 'antigo.pdf'], 10)
    detalhes.salvar(execucao.detalhes_dir, o['arquivo'], {'texto': 'Matrícula Docente(s)\n1234567 FULANO DE TAL SILVA - 60h\n'})
    detalhes.salvar(execucao.detalhes_dir, 'antigo.pdf', {'texto': 'Matrícula Docente(s)\n7654321 CICLANO SOUZA - 30h\n'})
    html = c.get('/dashboard', headers=ADMIN).get_data(as_text=True)
    assert 'data-docente="Fulano de Tal"' in html  # o nome do cadastro, não o do PDF
    assert 'data-docente="Ciclano Souza"' in html
    # Curso e período vêm da disciplina, mesmo sem o cabeçalho no texto do PDF
    assert 'data-cp="CC|2026.2"' in html


def test_aviso_de_privacidade_publico(fabrica):
    c, _ = fabrica(exigir_login=True)
    r = c.get('/privacidade')
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and 'LGPD' in html and '_planos_govbr' in html and 'cookies necessários' in html
    assert 'href="/privacidade"' in c.get('/').get_data(as_text=True)  # no rodapé


def test_entrar_do_cabecalho_leva_ao_login(fabrica):
    c, _ = fabrica(exigir_login=True)
    assert 'small entrar' not in c.get('/').get_data(as_text=True)  # na inicial, os botões de login estão na página
    assert 'href="/entrar?rd=/dashboard"' in c.get('/privacidade').get_data(as_text=True)


def test_tela_de_vincular_e_sem_entrar_na_inicial(fabrica, monkeypatch):
    c, _ = fabrica(**GOVBR)
    html = _login_govbr(c, monkeypatch, email='fulano@gmail.com')[1].get_data(as_text=True)
    assert 'Vincule sua conta gov.br' in html and 'Entrar com Google</a>' in html and '<svg' in html
    assert 'class="br-button primary small entrar"' not in c.get('/').get_data(as_text=True)


def test_meus_planos_tem_a_barra_de_status(com_login):
    c, _ = com_login
    for cab in (SERVIDOR, ADMIN):
        html = c.get('/meus-planos', headers=cab).get_data(as_text=True)
        assert 'class="barra-status"' in html and 'id="validar"' not in html  # sem "Validar agora" aqui
        assert 'id="validar-meus"' in html and 'Validar meus planos' in html
        assert html.index('js/status.js') < html.index('js/meus_planos.js') and 'ADMIN = false,' in html
    js = c.get('/static/js/meus_planos.js').get_data(as_text=True)
    assert 'function aoTerminar()' in js and 'const $ =' not in js  # $ e msg vêm de status.js


def test_retorno_cadastrado_no_govbr_repassa_ao_callback(fabrica):
    c, _ = fabrica(exigir_login=True)
    r = c.get('/auth/govbr/assinatura/callback?state=abc&code=OC-1')  # público: sem login
    assert r.status_code == 302 and r.headers['Location'] == '/assinatura/govbr/callback?state=abc&code=OC-1'
    assert c.get('/auth/govbr/assinatura/callback').headers['Location'] == '/assinatura/govbr/callback'


def test_login_govbr_guarda_o_nivel_da_conta(fabrica, monkeypatch):
    c, _ = fabrica(**GOVBR)
    _login_govbr(c, monkeypatch, reliability_info={'level': 'silver', 'reliabilities': []})
    usuarios = _servicos(c).usuarios
    assert usuarios.nivel_govbr('fulano@ifc.edu.br') == 'prata'
    _login_govbr(c, monkeypatch, reliability_info={'level': 'bronze'})
    assert usuarios.nivel_govbr('fulano@ifc.edu.br') == 'bronze'
    _login_govbr(c, monkeypatch)  # sem a informação: fica "não se sabe"
    assert usuarios.nivel_govbr('fulano@ifc.edu.br') == ''
    assert usuarios.nivel_govbr('ninguem@ifc.edu.br') == ''


def test_conta_bronze_nao_chega_a_autorizacao_da_assinatura(fabrica, tmp_path, monkeypatch):
    """Roteiro da assinatura gov.br: com conta bronze (ou de nível desconhecido), "Assinar com gov.br" não leva
    à tela de autorização; a página avisa e dá o link para elevar o nível."""
    c, dono = _aprovado_para_assinar(fabrica, tmp_path, assinatura_client_id='cli', assinatura_client_secret='seg',
                                     segredo_sessao='chave', assinatura_ambiente='homologacao',
                                     govbr_client_id='cliente', govbr_client_secret='segredo',
                                     assinatura_oauth_url='https://cas.staging.iti.br/oauth2.0',
                                     assinatura_api_url='https://assinatura-api.staging.iti.br/externo/v2')
    usuarios = _servicos(c).usuarios

    def ir():
        return c.get('/assinatura/govbr/iniciar?arquivo=web.pdf', headers=dono)
    pagina = c.get('/meus-planos', headers=dono).get_data(as_text=True)
    assert 'ASSINATURA_NIVEL = "sem_nivel"' in pagina and 'aviso-bronze' not in pagina
    # Login alternativo (Google), nível desconhecido: "Assinar" pede o login gov.br e volta para assinar
    r = ir()
    assert r.status_code == 302
    from urllib.parse import parse_qs, urlsplit
    destino = urlsplit(r.headers['Location'])
    assert destino.path == '/conta/govbr/vincular'
    assert parse_qs(destino.query)['rd'] == ['/assinatura/govbr/iniciar?arquivo=web.pdf&tentou=1']
    # Se nem depois do login o gov.br informar o nível, não insiste (sem laço)
    r = c.get('/assinatura/govbr/iniciar?arquivo=web.pdf&tentou=1', headers=dono)
    assert r.status_code == 303 and 'não informou o nível' in _resultado(r)['motivo']

    # Conta bronze: aviso fixo na página, com o link de upgrade; "Assinar" volta com o aviso, sem autorização
    usuarios.vincular_govbr('chave-cpf', 'fulano@ifc.edu.br', 'bronze')
    pagina = c.get('/meus-planos', headers=dono).get_data(as_text=True)
    assert 'ASSINATURA_NIVEL = "bronze"' in pagina and 'aviso-bronze' in pagina
    assert 'É necessário possuir conta gov.br nível prata ou ouro para utilizar o serviço de assinatura.' in pagina
    assert 'href="https://confiabilidades.acesso.gov.br/"' in pagina
    r = ir()
    assert r.status_code == 303 and _resultado(r)['assinatura'] == 'bronze'

    usuarios.definir_nivel_govbr('chave-cpf', 'ouro')
    assert 'ASSINATURA_NIVEL = "ok"' in c.get('/meus-planos', headers=dono).get_data(as_text=True)
    r = ir()
    assert r.status_code == 302 and r.headers['Location'].startswith('https://cas.staging.iti.br/oauth2.0/authorize?')


def test_pagina_inicial_mostra_acessar_para_quem_ja_entrou(fabrica, monkeypatch):
    c, _ = fabrica(**GOVBR)
    html = c.get('/').get_data(as_text=True)
    assert '> Acessar</a>' not in html
    c.set_cookie('_planos_login', 'qualquer')  # cookie do Google (oauth2-proxy)
    html = c.get('/').get_data(as_text=True)
    assert 'href="/dashboard"><i class="fas fa-arrow-right" aria-hidden="true"></i> Acessar</a>' in html
    c.delete_cookie('_planos_login')
    _login_govbr(c, monkeypatch)  # sessão gov.br do app
    assert '> Acessar</a>' in c.get('/').get_data(as_text=True)


def test_nivel_pela_api_quando_o_id_token_nao_traz(fabrica, monkeypatch):
    """"Verificar nível conta" do roteiro: sem reliability_info no ID token, o nível vem da API."""
    import requests
    pedidos = []

    def get(url, **kw):
        pedidos.append((url, kw))
        return _Resposta(corpo=[{'id': '1', 'dataAtualizacao': 'x'}, {'id': '2', 'dataAtualizacao': 'x'}])
    monkeypatch.setattr(requests, 'get', get)
    c, _ = fabrica(**GOVBR)
    _, volta, _ = _login_govbr(c, monkeypatch)
    assert volta.status_code == 302 and _servicos(c).usuarios.nivel_govbr('fulano@ifc.edu.br') == 'prata'
    url, kw = pedidos[0]
    assert url == 'https://api.acesso.gov.br/confiabilidades/v3/contas/12345678900/niveis'
    assert kw['params'] == {'response-type': 'ids'} and kw['headers']['Authorization'] == 'Bearer x'

    monkeypatch.setattr(requests, 'get', lambda url, **kw: _Resposta(status=500))
    _login_govbr(c, monkeypatch)
    assert _servicos(c).usuarios.nivel_govbr('fulano@ifc.edu.br') == ''


def test_bronze_sem_acesso_ve_o_aviso_no_login(fabrica, monkeypatch):
    """O roteiro pede o aviso de bronze mesmo para quem não tem acesso ao sistema."""
    c, _ = fabrica(**GOVBR)
    _, volta, _ = _login_govbr(c, monkeypatch, email='pessoal@gmail.com', reliability_info={'level': 'bronze'})
    html = volta.get_data(as_text=True)
    assert volta.status_code == 403 and 'aviso-bronze' in html and 'confiabilidades.acesso.gov.br' in html
    _, volta, _ = _login_govbr(c, monkeypatch, email='pessoal@gmail.com', reliability_info={'level': 'silver'})
    assert 'aviso-bronze' not in volta.get_data(as_text=True)


def test_assinar_so_com_nivel_conferido_ha_pouco(fabrica, tmp_path, monkeypatch):
    """O nível guardado pode ser de outra conta gov.br ou de antes de um upgrade: para ir à autorização, ele
    precisa ter sido informado pelo gov.br há poucos minutos; senão, "Assinar" passa de novo pelo Login Único."""
    from datetime import datetime, timedelta
    from urllib.parse import urlsplit
    from app.servicos import assinatura_api
    c, dono = _aprovado_para_assinar(fabrica, tmp_path, assinatura_client_id='cli', assinatura_client_secret='seg',
                                     segredo_sessao='chave', assinatura_ambiente='homologacao',
                                     govbr_client_id='cliente', govbr_client_secret='segredo',
                                     assinatura_oauth_url='https://cas.staging.iti.br/oauth2.0',
                                     assinatura_api_url='https://assinatura-api.staging.iti.br/externo/v2')
    usuarios = _servicos(c).usuarios
    usuarios.vincular_govbr('chave-cpf', 'fulano@ifc.edu.br', 'prata')
    assert usuarios.nivel_govbr_conferido('fulano@ifc.edu.br')[1]  # registrado agora

    def ir():
        return c.get('/assinatura/govbr/iniciar?arquivo=web.pdf', headers=dono)
    assert ir().headers['Location'].startswith('https://cas.staging.iti.br/')  # conferido agora: segue

    antigo = (datetime.now() - timedelta(seconds=assinatura_api.CONFERENCIA_VALE + 60)).isoformat(timespec='seconds')
    with usuarios._conexao() as con:
        con.execute('UPDATE vinculos_govbr SET nivel_em = %s', (antigo,))
    r = ir()
    assert r.status_code == 302 and urlsplit(r.headers['Location']).path == '/conta/govbr/vincular'

    with usuarios._conexao() as con:
        con.execute("UPDATE vinculos_govbr SET nivel = 'bronze'")
    assert _resultado(ir())['assinatura'] == 'bronze'  # bronze, mesmo antigo: nunca vai à autorização


def test_conferido_ha_pouco():
    from datetime import datetime, timedelta
    from app.servicos.assinatura_api import CONFERENCIA_VALE, conferido_ha_pouco
    agora = datetime(2026, 11, 18, 10, 0, 0)
    assert conferido_ha_pouco((agora - timedelta(seconds=60)).isoformat(), agora)
    assert not conferido_ha_pouco((agora - timedelta(seconds=CONFERENCIA_VALE + 1)).isoformat(), agora)
    assert not conferido_ha_pouco((agora + timedelta(seconds=60)).isoformat(), agora)  # no futuro
    assert not conferido_ha_pouco('', agora) and not conferido_ha_pouco(None, agora)


def test_sair_encerra_o_govbr_de_quem_entrou_pelo_google(fabrica, monkeypatch):
    """Quem entrou pelo Google e passou pelo gov.br (vínculo, ou antes de assinar) tem sessão aberta no gov.br:
    o Sair a encerra também, na URL de Log Out configurada."""
    c, _ = fabrica(**dict(GOVBR, govbr_logout_uri='https://planos.labia.ifc.edu.br/auth/gov/logout'))
    google = {'X-Usuario-Email': 'fulano@ifc.edu.br'}
    assert c.get('/auth/sair', headers=google).headers['Location'] == '/oauth2/sign_out?rd=%2F'
    _vincular_govbr(c, monkeypatch, google)
    assert c.get_cookie('_planos_govbr_sso') is not None
    r = c.get('/auth/sair', headers=google)
    assert r.headers['Location'] == ('https://sso.acesso.gov.br/logout?post_logout_redirect_uri='
                                     'https%3A%2F%2Fplanos.labia.ifc.edu.br%2Fauth%2Fgov%2Flogout')
    assert c.get_cookie('_planos_govbr_sso') is None
