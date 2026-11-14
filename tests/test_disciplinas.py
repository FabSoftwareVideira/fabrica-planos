"""Disciplinas do período letivo (app/servicos/disciplinas.py, app/armazenamento/ofertas.py e
app/rotas/disciplinas.py): a matriz do PPC, o planejamento de cada período (rascunho e publicação), montado
pela coordenação no assistente em etapas, os docentes de cada disciplina e o caminho completo até o professor
enviar o plano. Integração com o PostgreSQL de TEST_DATABASE_URL."""
import io
from datetime import date

import pytest

from app.armazenamento import ppc
from app.armazenamento.ofertas import nome_do_arquivo
from app.servicos.disciplinas import ComPlano, Invalido, JaExiste
from conftest import PDF_COM_TEXTO, enviar_plano, gerar_pdf, servicos_de

ADMIN = {'X-Usuario-Email': 'admin@ifc.edu.br'}
COORD = {'X-Usuario-Email': 'coord@ifc.edu.br'}
NDE = {'X-Usuario-Email': 'nde@ifc.edu.br'}
FULANO = {'X-Usuario-Email': 'fulano@ifc.edu.br'}


@pytest.fixture
def app(fabrica):
    """App com login; coord@ é coordenador de CC e nde@ é do NDE de CC."""
    c, planos = fabrica(exigir_login=True, admins=frozenset({'admin@ifc.edu.br'}))
    s = servicos_de(c)
    for e in ('coord@ifc.edu.br', 'nde@ifc.edu.br'):
        s.usuarios.registrar_acesso(e)
    s.usuarios.adicionar_papel('coord@ifc.edu.br', 'CC', 'coordenador')
    s.usuarios.adicionar_papel('nde@ifc.edu.br', 'CC', 'nde')
    return c, planos, s.disciplinas


# Matriz e serviço ---------------------------------------------------------------------------------------

def test_matriz_do_ppc_de_ciencia_da_computacao(app):
    _, _, d = app
    matriz = d.ofertas.matriz('CC')
    assert len(matriz) == len(ppc.MATRIZES['CC']) == 52
    fases = dict(d.matriz_por_fase('CC'))
    assert sorted(fases) == list(range(1, 9))
    assert sum(c['carga_horaria'] for c in fases[1]) == 330
    assert all(sum(c['carga_horaria'] for c in fases[f]) == 360 for f in range(2, 9))
    assert [c['nome'] for c in fases[6] if not c['codigo']] == ['Optativa I']
    assert d.cursos() == {'CC': 'Ciência da Computação'}


def test_matriz_e_preenchida_uma_vez_so(app):
    from app.armazenamento.ofertas import Ofertas
    _, _, d = app
    Ofertas(d.ofertas.banco)  # o app subindo de novo
    assert len(d.ofertas.matriz('CC')) == 52


def test_semestre_pelas_fases(app):
    _, _, d = app
    assert d.adicionar_fases('CC', '2026.2', ['2', '4', '6', '8'], 'coord@ifc.edu.br') == 7 + 7 + 6 + 6
    assert d.adicionar_fases('CC', '2026.2', ['4'], 'coord@ifc.edu.br') == 0  # já estavam
    grade = dict(d.semestre('CC', '2026.2'))
    assert sorted(grade) == [2, 4, 6, 8]
    web = next(o for o in grade[4] if o['codigo'] == 'CCC0723')
    assert web['turma'] == '01' and web['arquivo'] == f"2026.2-CCC0723-T01-{web['id']}.pdf"
    optativa = next(o for o in grade[6] if o['nome'] == 'Optativa I')
    assert optativa['arquivo'] == f"2026.2-OPT-T01-{optativa['id']}.pdf"
    assert d.periodos('CC') == ['2026.2']
    d.adicionar_fases('CC', '2027.1', [1], 'coord@ifc.edu.br')
    assert d.periodos('CC') == ['2027.1', '2026.2']


@pytest.mark.parametrize('curso, periodo, fases, mensagem', [
    ('CC', '2026/2', [1], 'Período inválido'), ('CC', '', [1], 'Período inválido'),
    ('XX', '2026.2', [1], 'Curso desconhecido'), ('CC', '2026.2', [], 'pelo menos uma fase'),
])
def test_semestre_invalido(app, curso, periodo, fases, mensagem):
    _, _, d = app
    with pytest.raises(Invalido, match=mensagem):
        d.adicionar_fases(curso, periodo, fases, 'x')


def test_renomear_vale_so_no_semestre(app):
    _, _, d = app
    d.adicionar_fases('CC', '2026.2', [6], 'x')
    optativa = next(o for o in d.ofertas.listar(periodo='2026.2') if o['nome'] == 'Optativa I')
    d.alterar(optativa['id'], '  Tópicos em   Visão Computacional ', 'cco0790', '60', '01')
    o = d.oferta(optativa['id'])
    assert o['nome'] == 'Tópicos em Visão Computacional' and o['codigo'] == 'CCO0790'
    assert o['arquivo'] == optativa['arquivo']  # o PDF do plano continua o mesmo
    assert 'Optativa I' in [c['nome'] for c in d.ofertas.matriz('CC')]  # a matriz não muda
    for nome, turma, msg in (('', '01', 'nome'), ('X', '', 'Turma'), ('X', 'A/B', 'Turma')):
        with pytest.raises(Invalido, match=msg):
            d.alterar(o['id'], nome, '', 60, turma)
    with pytest.raises(Invalido, match='não encontrada'):
        d.alterar(999999, 'X', '', 60, '01')


def test_outra_turma_e_disciplina_avulsa(app):
    _, _, d = app
    d.adicionar_fases('CC', '2026.2', [4], 'x')
    web = next(o for o in d.ofertas.listar(periodo='2026.2') if o['codigo'] == 'CCC0723')
    d.definir_docentes(web['id'], 'fulano@ifc.edu.br')
    t2 = d.nova_turma(web['id'], 'coord@ifc.edu.br')
    t3 = d.nova_turma(web['id'], 'coord@ifc.edu.br')
    assert (t2['turma'], t3['turma']) == ('02', '03') and t2['docentes'] == [] and t2['fase'] == 4
    assert t2['arquivo'] != web['arquivo']
    avulsa = d.adicionar_avulsa('CC', '2026.2', 'Tópicos Especiais', 'cco0800', 'x', 'abc', 'coord@ifc.edu.br')
    assert (avulsa['codigo'], avulsa['carga_horaria'], avulsa['fase'], avulsa['componente_id']) == ('CCO0800', 0, None, None)
    assert dict(d.semestre('CC', '2026.2'))[None] == [{**avulsa, 'docentes_info': []}]
    with pytest.raises(Invalido, match='nome'):
        d.adicionar_avulsa('CC', '2026.2', ' ', '', 60, 1, 'x')
    # Uma disciplina da matriz de outra fase
    algoritmos = next(c for c in d.ofertas.matriz('CC') if c['codigo'] == 'CCC0701')
    o = d.adicionar_componente('CC', '2026.2', algoritmos['id'], 'x')
    assert o['fase'] == 1 and o['carga_horaria'] == 90
    assert d.adicionar_componente('CC', '2026.2', algoritmos['id'], 'x')['turma'] == '02'
    with pytest.raises(Invalido, match='matriz'):
        d.adicionar_componente('CC', '2026.2', 999999, 'x')


def test_docentes_pelo_email_institucional(app):
    c, _, d = app
    o = d.adicionar_avulsa('CC', '2026.2', 'X', '', 60, 1, 'x')
    emails = d.definir_docentes(o['id'], ' Fulano@IFC.edu.br,  beltrano@ifc.edu.br;\nfulano@ifc.edu.br ')
    assert emails == ['fulano@ifc.edu.br', 'beltrano@ifc.edu.br', 'fulano@ifc.edu.br']
    assert d.oferta(o['id'])['docentes'] == ['beltrano@ifc.edu.br', 'fulano@ifc.edu.br']  # sem repetir
    servicos_de(c).usuarios.registrar_acesso('fulano@ifc.edu.br', 'Fulano de Tal')
    assert d.nomes(['fulano@ifc.edu.br', 'beltrano@ifc.edu.br']) == [
        {'email': 'fulano@ifc.edu.br', 'nome': 'Fulano de Tal', 'cadastrado': True},
        {'email': 'beltrano@ifc.edu.br', 'nome': '', 'cadastrado': False}]
    for invalido in ('alguem@gmail.com', 'aluno@estudantes.ifc.edu.br', 'sem-arroba'):
        with pytest.raises(Invalido, match=invalido):
            d.definir_docentes(o['id'], 'fulano@ifc.edu.br, ' + invalido)
    assert d.oferta(o['id'])['docentes'] == ['beltrano@ifc.edu.br', 'fulano@ifc.edu.br']  # nada mudou
    d.definir_docentes(o['id'], '')
    assert d.oferta(o['id'])['docentes'] == []


def test_remover_disciplina_so_sem_plano(app):
    _, _, d = app
    o = d.adicionar_avulsa('CC', '2026.2', 'X', '', 60, 1, 'x')
    with pytest.raises(ComPlano):
        d.remover(o['id'], lambda arquivo: True)
    d.remover(o['id'], lambda arquivo: False)
    assert d.oferta(o['id']) is None


def test_quem_gerencia_as_disciplinas(app):
    _, _, d = app
    assert d.cursos_gerenciaveis('admin@ifc.edu.br', True) == {'CC': 'Ciência da Computação'}
    assert d.cursos_gerenciaveis('coord@ifc.edu.br', False) == {'CC': 'Ciência da Computação'}
    assert d.cursos_gerenciaveis('nde@ifc.edu.br', False) == {}
    assert d.pode_gerenciar('coord@ifc.edu.br', False, 'CC') and not d.pode_gerenciar('coord@ifc.edu.br', False, 'IN')


def test_identificacao_do_plano_vem_da_disciplina(app):
    _, _, d = app
    o = d.adicionar_avulsa('CC', '2026.1', 'Tópicos', 'CCO0800', 30, 7, 'x')
    ident = d.identificacao(o)
    assert ident == {'codigo': 'CCO0800', 'disciplina': 'Tópicos', 'carga_horaria': 30, 'turma': '01',
                     'sigla_curso': 'CC', 'curso': 'Ciência da Computação', 'ano': '2026', 'semestre': 1,
                     'periodo': '2026.1', 'oferta': 'semestral', 'fase': 7, 'oferta_id': o['id']}
    assert d.identificacao(None) is None
    anual = d.ofertas.criar('CC', '2026', 'Anual', fase=None)
    assert d.identificacao(anual)['oferta'] == 'anual' and d.identificacao(anual)['semestre'] is None


@pytest.mark.parametrize('oferta, nome', [
    ({'id': 7, 'periodo': '2026.2', 'codigo': 'CCC0723', 'turma': '01'}, '2026.2-CCC0723-T01-7.pdf'),
    ({'id': 8, 'periodo': '2026.2', 'codigo': '', 'turma': 'A'}, '2026.2-OPT-T01-8.pdf'.replace('T01', 'TA')),
    ({'id': 9, 'periodo': '2026', 'codigo': 'INC0713-1', 'turma': '0/3'}, '2026-INC07131-T03-9.pdf'),
])
def test_nome_do_arquivo_do_plano(oferta, nome):
    assert nome_do_arquivo(oferta) == nome


@pytest.mark.parametrize('hoje, periodo', [(date(2026, 3, 1), '2026.2'), (date(2026, 6, 30), '2026.2'),
                                           (date(2026, 7, 1), '2027.1'), (date(2026, 12, 31), '2027.1')])
def test_periodo_sugerido_e_o_proximo_semestre(app, hoje, periodo):
    _, _, d = app
    assert d.sugerir_periodo('CC', hoje) == periodo


def test_periodo_sugerido_pula_os_ja_planejados(app):
    _, _, d = app
    d.criar_planejamento('CC', '2027.1', 'x')
    d.criar_planejamento('CC', '2027.2', 'x')
    assert d.sugerir_periodo('CC', date(2026, 11, 14)) == '2028.1'


def test_curso_anual(app, monkeypatch):
    _, _, d = app
    monkeypatch.setitem(ppc.TIPOS, 'CC', 'anual')
    assert d.sugerir_periodo('CC', date(2026, 3, 1)) == '2026'
    assert d.sugerir_periodo('CC', date(2026, 8, 1)) == '2027'
    assert d.fases_sugeridas('CC', '2027') == list(range(1, 9))
    with pytest.raises(Invalido, match='anual'):
        d.criar_planejamento('CC', '2027.1', 'x')
    d.criar_planejamento('CC', '2027', 'x')
    assert d.sugerir_periodo('CC', date(2026, 8, 1)) == '2028'


def test_fases_sugeridas_no_semestral(app):
    _, _, d = app
    assert d.fases_sugeridas('CC', '2027.1') == [1, 3, 5, 7]
    assert d.fases_sugeridas('CC', '2027.2') == [2, 4, 6, 8]


# Planejamento: rascunho e publicação ---------------------------------------------------------------------

def test_planejamento_comeca_como_rascunho(app):
    _, _, d = app
    d.criar_planejamento('CC', '2027.1', 'coord@ifc.edu.br')
    p = d.planejamento('CC', '2027.1')
    assert p['situacao'] == 'rascunho' and p['disciplinas'] == 0 and p['fases_lista'] == []
    with pytest.raises(JaExiste):
        d.criar_planejamento('CC', '2027.1', 'coord@ifc.edu.br')
    with pytest.raises(Invalido, match='Período'):
        d.criar_planejamento('CC', '2027', 'x')  # CC é semestral
    assert d.planejamento('CC', '2030.1') is None


def test_mudar_as_fases_tira_as_disciplinas_sem_plano(app):
    _, _, d = app
    d.criar_planejamento('CC', '2027.2', 'x')
    assert d.definir_fases('CC', '2027.2', [2, 4], 'x') == (14, 0, 0)
    avulsa = d.adicionar_avulsa('CC', '2027.2', 'Tópicos', '', 60, 4, 'x')
    web = next(o for o in d.ofertas.listar(periodo='2027.2') if o['codigo'] == 'CCC0723')
    d.ofertas.registrar_envio(web['arquivo'], 'fulano@ifc.edu.br')  # já tem plano
    assert d.definir_fases('CC', '2027.2', [2, 6], 'x') == (6, 6, 1)
    nomes = {o['nome'] for o in d.ofertas.listar(periodo='2027.2')}
    assert 'Desenvolvimento Web I' in nomes and 'Tópicos' in nomes and 'Banco de Dados II' not in nomes
    assert d.planejamento('CC', '2027.2')['fases_lista'] == [2, 6]
    assert avulsa['id'] in {o['id'] for o in d.ofertas.listar(periodo='2027.2')}
    with pytest.raises(Invalido, match='fase'):
        d.definir_fases('CC', '2027.2', [], 'x')


def test_docentes_em_lote(app):
    _, _, d = app
    d.definir_fases('CC', '2027.1', [1], 'x')
    a, b = d.ofertas.listar(periodo='2027.1')[:2]
    assert d.definir_docentes_em_lote('CC', '2027.1', {a['id']: 'fulano@ifc.edu.br', b['id']: '', 999: 'x@ifc.edu.br'}) == 2
    assert d.oferta(a['id'])['docentes'] == ['fulano@ifc.edu.br'] and d.oferta(b['id'])['docentes'] == []
    with pytest.raises(Invalido, match=f"{b['nome']}: alguem@gmail.com"):
        d.definir_docentes_em_lote('CC', '2027.1', {a['id']: 'beltrano@ifc.edu.br', b['id']: 'alguem@gmail.com'})
    assert d.oferta(a['id'])['docentes'] == ['fulano@ifc.edu.br']  # com erro, nada é gravado


def test_publicar_voltar_a_rascunho_e_descartar(app):
    _, _, d = app
    d.criar_planejamento('CC', '2027.1', 'x')
    with pytest.raises(Invalido, match='pelo menos uma disciplina'):
        d.publicar('CC', '2027.1', 'x')
    d.definir_fases('CC', '2027.1', [1], 'x')
    algoritmos = next(o for o in d.ofertas.listar(periodo='2027.1') if o['codigo'] == 'CCC0701')
    d.definir_docentes(algoritmos['id'], 'fulano@ifc.edu.br')
    assert d.do_professor('fulano@ifc.edu.br') == [] and not d.publicado(algoritmos)  # rascunho: não vê
    d.publicar('CC', '2027.1', 'coord@ifc.edu.br')
    p = d.planejamento('CC', '2027.1')
    assert p['situacao'] == 'publicado' and p['publicado_por'] == 'coord@ifc.edu.br' and p['publicado_em']
    assert [o['id'] for o in d.do_professor('fulano@ifc.edu.br')] == [algoritmos['id']]
    with pytest.raises(ComPlano):
        d.excluir_planejamento('CC', '2027.1', 'x')  # publicado não se descarta
    d.voltar_a_rascunho('CC', '2027.1', 'x')
    assert d.do_professor('fulano@ifc.edu.br') == [] and d.planejamento('CC', '2027.1')['publicado_em'] is None
    d.publicar('CC', '2027.1', 'x')
    d.ofertas.registrar_envio(algoritmos['arquivo'], 'fulano@ifc.edu.br')
    with pytest.raises(ComPlano):
        d.voltar_a_rascunho('CC', '2027.1', 'x')  # com plano enviado, fica publicado
    d.criar_planejamento('CC', '2027.2', 'x')
    d.definir_fases('CC', '2027.2', [2], 'x')
    d.excluir_planejamento('CC', '2027.2', 'x')
    assert d.planejamento('CC', '2027.2') is None and d.ofertas.listar(periodo='2027.2') == []
    for metodo in (d.publicar, d.voltar_a_rascunho, d.excluir_planejamento):
        with pytest.raises(Invalido, match='não encontrado'):
            metodo('CC', '2030.1', 'x')


def test_ofertas_antigas_ficam_num_planejamento_publicado(app):
    from app.armazenamento.ofertas import Ofertas
    _, _, d = app
    d.ofertas.criar('CC', '2025.2', 'Antiga', 'CCC0701', 60, 1)  # de antes dos planejamentos
    Ofertas(d.ofertas.banco)  # o app subindo de novo
    assert d.planejamento('CC', '2025.2')['situacao'] == 'publicado'


# Assistente da coordenação ---------------------------------------------------------------------------------

def _local(r):
    assert r.status_code == 303, r.get_data(as_text=True)
    return r.headers['Location']


def test_so_coordenacao_e_administracao_planejam(app):
    c, _, d = app
    for url in ('/disciplinas', '/disciplinas/novo'):
        assert c.get(url, headers=NDE).headers['Location'] == '/dashboard'
    d.criar_planejamento('CC', '2027.1', 'x')
    for etapa in ('fases', 'disciplinas', 'docentes', 'revisao'):
        assert c.get(f'/disciplinas/CC/2027.1/{etapa}', headers=NDE).status_code == 403
        assert c.get(f'/disciplinas/CC/2030.1/{etapa}', headers=COORD).status_code == 404
    assert c.post('/disciplinas/novo', headers=NDE, data={'curso': 'CC', 'periodo': '2027.2'}).status_code == 403
    for acao in ('fases', 'docentes', 'publicar', 'rascunho', 'excluir'):
        assert c.post(f'/disciplinas/CC/2027.1/{acao}', headers=NDE).status_code == 403
    for cab in (COORD, ADMIN):
        html = c.get('/disciplinas', headers=cab).get_data(as_text=True)
        assert 'Planejar ' in html and 'href="/disciplinas"' in html  # item do menu
    assert 'href="/disciplinas"' not in c.get('/dashboard', headers=NDE).get_data(as_text=True)


def test_assistente_do_periodo_ate_a_publicacao(app, monkeypatch):
    from app.rotas import disciplinas as rotas
    c, _, d = app
    monkeypatch.setattr(d, 'sugerir_periodo', lambda curso, hoje=None: '2027.1')
    html = c.get('/disciplinas', headers=COORD).get_data(as_text=True)
    assert 'Planejar 2027.1' in html and 'Nenhum período planejado ainda' in html

    # 1. Período: o próximo é sugerido
    html = c.get('/disciplinas/novo', headers=COORD).get_data(as_text=True)
    assert 'value="2027.1"' in html and '1. Período letivo' in html
    assert 'erro=Per' in _local(c.post('/disciplinas/novo', headers=COORD, data={'curso': 'CC', 'periodo': '2027'}))
    assert _local(c.post('/disciplinas/novo', headers=COORD, data={'curso': 'CC', 'periodo': '2027.1'})) == \
        '/disciplinas/CC/2027.1/fases?aviso=criado'
    assert 'aviso=ja_existe' in _local(c.post('/disciplinas/novo', headers=COORD, data={'curso': 'CC', 'periodo': '2027.1'}))
    assert _local(c.get('/disciplinas/CC/2027.1', headers=COORD)) == '/disciplinas/CC/2027.1/fases'

    # 2. Fases: vêm marcadas as ímpares (1º semestre), e dá para mudar
    html = c.get('/disciplinas/CC/2027.1/fases', headers=COORD).get_data(as_text=True)
    assert 'name="fase" value="1" checked' in html and 'name="fase" value="2">' in html and 'Rascunho' in html
    assert 'erro=Escolha' in _local(c.post('/disciplinas/CC/2027.1/fases', headers=COORD, data={}))
    assert 'erro=Fase' in _local(c.post('/disciplinas/CC/2027.1/fases', headers=COORD, data={'fase': 'x'}))
    assert _local(c.post('/disciplinas/CC/2027.1/fases', headers=COORD, data={'fase': ['1', '3']})) == \
        '/disciplinas/CC/2027.1/disciplinas?aviso=fases'
    html = c.get('/disciplinas/CC/2027.1/fases', headers=COORD).get_data(as_text=True)
    assert 'name="fase" value="3" checked' in html and 'name="fase" value="5">' in html  # o que foi salvo

    # 3. Disciplinas
    html = c.get('/disciplinas/CC/2027.1/disciplinas', headers=COORD).get_data(as_text=True)
    assert '3. Disciplinas do período <span class="contagem">(13)</span>' in html and 'Algoritmos' in html
    assert _local(c.get('/disciplinas/CC/2027.1', headers=COORD)) == '/disciplinas/CC/2027.1/docentes'

    # 4. Docentes, todos num formulário
    ofertas = d.ofertas.listar(periodo='2027.1')
    algoritmos = next(o for o in ofertas if o['codigo'] == 'CCC0701')
    html = c.get('/disciplinas/CC/2027.1/docentes', headers=COORD).get_data(as_text=True)
    assert f'name="docentes-{algoritmos["id"]}"' in html and 'Salvar rascunho' in html
    r = c.post('/disciplinas/CC/2027.1/docentes', headers=COORD,
               data={f'docentes-{algoritmos["id"]}': 'fulano@ifc.edu.br', 'docentes-x': 'ignorado'})
    assert _local(r) == '/disciplinas/CC/2027.1/docentes?aviso=docentes'
    r = c.post('/disciplinas/CC/2027.1/docentes', headers=COORD,
               data={f'docentes-{algoritmos["id"]}': 'fulano@ifc.edu.br, x@gmail.com', 'seguir': '1'})
    assert 'erro=E-mail' in _local(r)
    r = c.post('/disciplinas/CC/2027.1/docentes', headers=COORD,
               data={f'docentes-{algoritmos["id"]}': 'fulano@ifc.edu.br', 'seguir': '1'})
    assert _local(r) == '/disciplinas/CC/2027.1/revisao?aviso=docentes'

    # 5. Revisão e publicação, com confirmação
    html = c.get('/disciplinas/CC/2027.1/revisao', headers=COORD).get_data(as_text=True)
    assert '12 disciplinas sem docente' in html and 'fulano@ifc.edu.br' in html and 'Publicar planejamento' in html
    assert 'Ainda não entraram no sistema: fulano@ifc.edu.br' in html
    assert c.get('/meus-planos/lista', headers=FULANO).json['planos'] == []  # rascunho: o professor não vê
    assert 'erro=Marque' in _local(c.post('/disciplinas/CC/2027.1/publicar', headers=COORD, data={}))
    r = c.post('/disciplinas/CC/2027.1/publicar', headers=COORD, data={'confirmo': '1'})
    assert _local(r) == '/disciplinas/CC/2027.1/revisao?aviso=publicado'
    html = c.get(_local(r), headers=COORD).get_data(as_text=True)
    assert 'Planejamento publicado' in html and 'Voltar a rascunho' in html and 'Descartar rascunho' not in html
    [disciplina] = c.get('/meus-planos/lista', headers=FULANO).json['planos']
    assert disciplina['disciplina'] == 'Algoritmos (Turma 01)'
    assert _local(c.get('/disciplinas/CC/2027.1', headers=COORD)) == '/disciplinas/CC/2027.1/revisao'
    html = c.get('/disciplinas', headers=COORD).get_data(as_text=True)
    assert '2027.1' in html and 'Publicado' in html and '12</b> sem docente' in html

    # Voltar a rascunho (sem planos enviados) e descartar
    assert 'aviso=rascunho' in _local(c.post('/disciplinas/CC/2027.1/rascunho', headers=COORD))
    assert c.get('/meus-planos/lista', headers=FULANO).json['planos'] == []
    assert _local(c.post('/disciplinas/CC/2027.1/excluir', headers=COORD)) == '/disciplinas?aviso=excluido'
    assert d.planejamento('CC', '2027.1') is None
    assert rotas.ETAPAS[0][0] == 'periodo'


def test_com_plano_enviado_nao_volta_a_rascunho(app, monkeypatch):
    from app.avaliacao import pipeline
    monkeypatch.setattr(pipeline, 'revalidar', lambda cfg, andamento, nome: andamento.finalizar())
    c, _, d = app
    d.definir_fases('CC', '2027.1', [1], 'x')
    o = next(o for o in d.ofertas.listar(periodo='2027.1') if o['codigo'] == 'CCC0701')
    d.definir_docentes(o['id'], 'fulano@ifc.edu.br')
    assert enviar_plano(c, o, PDF_COM_TEXTO, cab=FULANO).status_code == 400  # rascunho: não envia
    d.publicar('CC', '2027.1', 'x')
    assert enviar_plano(c, o, PDF_COM_TEXTO, cab=FULANO).status_code == 200
    assert 'aviso=nao_publica' in _local(c.post('/disciplinas/CC/2027.1/rascunho', headers=COORD))
    assert 'aviso=nao_publica' in _local(c.post('/disciplinas/CC/2027.1/excluir', headers=COORD))
    assert d.planejamento('CC', '2027.1')['situacao'] == 'publicado'
    html = c.get('/disciplinas/CC/2027.1/revisao', headers=COORD).get_data(as_text=True)
    assert 'Voltar a rascunho' not in html and '1</b><span>plano enviado' in html


def test_acoes_em_cada_disciplina(app):
    c, planos, d = app
    d.definir_fases('CC', '2027.2', [4], 'x')
    web = next(o for o in d.ofertas.listar(periodo='2027.2') if o['codigo'] == 'CCC0723')
    base = f"/disciplinas/{web['id']}"
    ancora = f"#oferta-{web['id']}"
    pagina = '/disciplinas/CC/2027.2/disciplinas'

    assert _local(c.post(base + '/alterar', headers=COORD, data={'nome': 'Web I', 'codigo': 'CCC0723',
                                                                 'carga_horaria': '60', 'turma': '01'})) == pagina + '?aviso=alterada' + ancora
    assert 'erro=' in _local(c.post(base + '/alterar', headers=COORD, data={'nome': '', 'turma': '01'}))
    r = c.post(base + '/docentes', headers=COORD, data={'docentes': 'fulano@ifc.edu.br, novo@ifc.edu.br'})
    assert _local(r) == '/disciplinas/CC/2027.2/docentes?aviso=docentes' + ancora
    assert 'erro=E-mail+inv' in _local(c.post(base + '/docentes', headers=COORD, data={'docentes': 'x@gmail.com'}))
    html = c.get('/disciplinas/CC/2027.2/docentes', headers=COORD).get_data(as_text=True)
    assert 'novo@ifc.edu.br <small>(ainda não entrou)</small>' in html

    assert 'aviso=turma' in _local(c.post(base + '/turma', headers=COORD))
    assert len(d.ofertas.listar(periodo='2027.2')) == 8

    (planos / web['arquivo']).write_bytes(PDF_COM_TEXTO)
    assert 'aviso=com_plano' in _local(c.post(base + '/remover', headers=COORD))
    (planos / web['arquivo']).unlink()
    assert _local(c.post(base + '/remover', headers=COORD)) == pagina + '?aviso=removida'
    assert d.oferta(web['id']) is None

    outra = d.ofertas.listar(periodo='2027.2')[0]
    assert c.post(f"/disciplinas/{outra['id']}/turma", headers=NDE).status_code == 403
    assert c.post('/disciplinas/999999/remover', headers=COORD).status_code == 404
    assert c.post(f"/disciplinas/{outra['id']}/turma", headers={**COORD, 'Origin': 'https://fora'}).status_code == 403


def test_incluir_disciplina_da_matriz_ou_avulsa(app):
    c, _, d = app
    d.definir_fases('CC', '2027.2', [4], 'x')
    html = c.get('/disciplinas/CC/2027.2/disciplinas', headers=COORD).get_data(as_text=True)
    assert '<optgroup label="1ª fase">' in html and 'CCC0723 · Desenvolvimento Web I' not in html  # já está
    algoritmos = next(cp for cp in d.ofertas.matriz('CC') if cp['codigo'] == 'CCC0701')
    dados = {'curso': 'CC', 'periodo': '2027.2'}
    assert 'aviso=incluida' in _local(c.post('/disciplinas/incluir', headers=COORD, data={**dados, 'componente': str(algoritmos['id'])}))
    r = c.post('/disciplinas/incluir', headers=COORD, data={**dados, 'nome': 'Tópicos', 'codigo': '', 'carga_horaria': '30', 'fase': '7'})
    assert 'aviso=incluida' in _local(r)
    assert 'erro=' in _local(c.post('/disciplinas/incluir', headers=COORD, data={**dados, 'nome': ''}))
    assert 'erro=' in _local(c.post('/disciplinas/incluir', headers=COORD, data={**dados, 'componente': 'x'}))
    assert c.post('/disciplinas/incluir', headers=NDE, data={**dados, 'nome': 'X'}).status_code == 403
    nomes = [o['nome'] for o in d.ofertas.listar(periodo='2027.2')]
    assert 'Algoritmos' in nomes and 'Tópicos' in nomes
    html = c.get('/disciplinas/CC/2027.2/revisao', headers=COORD).get_data(as_text=True)
    assert 'Avulsas (sem fase)' not in html and '7ª fase' in html


# Do planejamento ao plano enviado --------------------------------------------------------------------------

def test_do_planejamento_ao_plano_no_painel(app, monkeypatch):
    from app.avaliacao import pipeline
    monkeypatch.setattr(pipeline, 'revalidar', lambda cfg, andamento, nome: andamento.finalizar())
    c, planos, d = app
    assert c.get('/meus-planos/lista', headers=FULANO).json['planos'] == []

    c.post('/disciplinas/novo', headers=COORD, data={'curso': 'CC', 'periodo': '2026.2'})
    c.post('/disciplinas/CC/2026.2/fases', headers=COORD, data={'fase': '4'})
    web = next(o for o in d.ofertas.listar(periodo='2026.2') if o['codigo'] == 'CCC0723')
    c.post('/disciplinas/CC/2026.2/docentes', headers=COORD, data={f"docentes-{web['id']}": 'fulano@ifc.edu.br'})
    c.post('/disciplinas/CC/2026.2/publicar', headers=COORD, data={'confirmo': '1'})

    [disciplina] = c.get('/meus-planos/lista', headers=FULANO).json['planos']
    assert disciplina['situacao'] == 'sem_plano' and disciplina['grupo'] == 'CC|2026.2'
    pdf = gerar_pdf(['CCC0723 - DESENVOLVIMENTO WEB I (60h) - Turma: 01 (2026.2)']
                    + ['Linha de texto do plano de ensino numero %d.' % i for i in range(8)])
    r = enviar_plano(c, web, pdf, cab=FULANO, nome='qualquer coisa.pdf')
    assert r.status_code == 200 and r.json['aviso'] == '' and (planos / web['arquivo']).exists()

    html = c.get('/disciplinas/CC/2026.2/disciplinas', headers=COORD).get_data(as_text=True)
    assert 'plano enviado' in html
    # Um docente da disciplina não revisa o plano dela
    c.post(f"/disciplinas/{web['id']}/docentes", headers=COORD, data={'docentes': 'fulano@ifc.edu.br, nde@ifc.edu.br'})
    assert servicos_de(c).revisao.eh_autor('nde@ifc.edu.br', web['arquivo'])
    assert not servicos_de(c).revisao.eh_autor('coord@ifc.edu.br', web['arquivo'])


def test_disciplina_removida_some_de_meus_planos(app):
    c, _, d = app
    o = d.adicionar_avulsa('CC', '2026.2', 'X', '', 60, 1, 'x')
    d.definir_docentes(o['id'], 'fulano@ifc.edu.br')
    d.publicar('CC', '2026.2', 'x')
    assert len(c.get('/meus-planos/lista', headers=FULANO).json['planos']) == 1
    c.post(f"/disciplinas/{o['id']}/remover", headers=COORD)
    assert c.get('/meus-planos/lista', headers=FULANO).json['planos'] == []
    r = c.post('/meus-planos', headers=FULANO, data={'oferta': str(o['id']), 'arquivo': (io.BytesIO(PDF_COM_TEXTO), 'a.pdf')},
               content_type='multipart/form-data')
    assert r.status_code == 400 and 'não encontrada' in r.json['erro']
