"""Disciplinas do semestre (app/servicos/disciplinas.py, app/armazenamento/ofertas.py e app/rotas/disciplinas.py):
a matriz do PPC, a grade de cada semestre montada pela coordenação, os docentes de cada disciplina e o
caminho completo até o professor enviar o plano. Integração com o PostgreSQL de TEST_DATABASE_URL."""
import io
from datetime import date

import pytest

from app.armazenamento import ppc
from app.armazenamento.ofertas import nome_do_arquivo
from app.rotas.disciplinas import _sugerir_periodo
from app.servicos.disciplinas import ComPlano, Invalido
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
def test_periodo_sugerido_e_o_proximo_semestre(hoje, periodo):
    assert _sugerir_periodo(hoje) == periodo


# Rotas da coordenação -------------------------------------------------------------------------------------

def _local(r):
    assert r.status_code == 303, r.get_data(as_text=True)
    return r.headers['Location']


def test_so_coordenacao_e_administracao_veem_a_pagina(app):
    c, _, _ = app
    assert c.get('/disciplinas', headers=NDE).headers['Location'] == '/dashboard'
    assert c.get('/disciplinas', headers=FULANO).headers['Location'] == '/dashboard'
    for cab in (COORD, ADMIN):
        html = c.get('/disciplinas', headers=cab).get_data(as_text=True)
        assert 'Novo semestre' in html and 'href="/disciplinas"' in html  # item do menu
    assert 'href="/disciplinas"' not in c.get('/dashboard', headers=NDE).get_data(as_text=True)


def test_coordenador_monta_o_semestre_pela_pagina(app):
    c, _, d = app
    html = c.get('/disciplinas', headers=COORD).get_data(as_text=True)
    assert 'name="fase" value="1"' in html and 'Incluir disciplinas das fases' in html
    local = _local(c.post('/disciplinas/semestre', headers=COORD,
                          data={'curso': 'CC', 'periodo': '2026.2', 'fase': ['2', '4']}))
    assert local == '/disciplinas?curso=CC&periodo=2026.2&aviso=fases'
    html = c.get(local, headers=COORD).get_data(as_text=True)
    assert 'Ciência da Computação · 2026.2' in html and '(14 disciplinas)' in html
    assert '2ª fase' in html and '4ª fase' in html and 'Desenvolvimento Web I' in html
    assert 'Nenhum docente: ninguém pode enviar o plano' in html
    assert 'aviso=nenhuma' in _local(c.post('/disciplinas/semestre', headers=COORD,
                                            data={'curso': 'CC', 'periodo': '2026.2', 'fase': '4'}))
    erro = _local(c.post('/disciplinas/semestre', headers=COORD, data={'curso': 'CC', 'periodo': 'x', 'fase': '4'}))
    assert 'erro=Per%C3%ADodo+inv%C3%A1lido' in erro
    assert 'erro=Fase' in _local(c.post('/disciplinas/semestre', headers=COORD,
                                        data={'curso': 'CC', 'periodo': '2026.2', 'fase': 'abc'}))
    # O NDE não monta
    assert c.post('/disciplinas/semestre', headers=NDE, data={'curso': 'CC', 'periodo': '2026.2', 'fase': '1'}).status_code == 403
    assert len(d.ofertas.listar(periodo='2026.2')) == 14


def test_coordenador_edita_vincula_e_remove(app):
    c, planos, d = app
    d.adicionar_fases('CC', '2026.2', [4], 'x')
    web = next(o for o in d.ofertas.listar(periodo='2026.2') if o['codigo'] == 'CCC0723')
    base = f"/disciplinas/{web['id']}"
    ancora = f"#oferta-{web['id']}"

    assert _local(c.post(base + '/alterar', headers=COORD, data={'nome': 'Web I', 'codigo': 'CCC0723',
                                                                 'carga_horaria': '60', 'turma': '01'})).endswith('aviso=alterada' + ancora)
    assert 'erro=' in _local(c.post(base + '/alterar', headers=COORD, data={'nome': '', 'turma': '01'}))

    r = c.post(base + '/docentes', headers=COORD, data={'docentes': 'fulano@ifc.edu.br, novo@ifc.edu.br'})
    assert _local(r).endswith('aviso=docentes' + ancora)
    assert d.oferta(web['id'])['docentes'] == ['fulano@ifc.edu.br', 'novo@ifc.edu.br']
    assert 'erro=E-mail+inv' in _local(c.post(base + '/docentes', headers=COORD, data={'docentes': 'x@gmail.com'}))
    html = c.get('/disciplinas?curso=CC&periodo=2026.2', headers=COORD).get_data(as_text=True)
    assert 'novo@ifc.edu.br <small>(ainda não entrou)</small>' in html and 'Web I' in html

    nova = _local(c.post(base + '/turma', headers=COORD))
    assert 'aviso=turma' in nova and len(d.ofertas.listar(periodo='2026.2')) == 8

    # Com plano enviado, não remove
    (planos / web['arquivo']).write_bytes(PDF_COM_TEXTO)
    assert 'aviso=com_plano' in _local(c.post(base + '/remover', headers=COORD))
    (planos / web['arquivo']).unlink()
    assert 'aviso=removida' in _local(c.post(base + '/remover', headers=COORD))
    assert d.oferta(web['id']) is None

    # Sem permissão, disciplina que não existe e post de outro site
    outra = d.ofertas.listar(periodo='2026.2')[0]
    assert c.post(f"/disciplinas/{outra['id']}/turma", headers=NDE).status_code == 403
    assert c.post('/disciplinas/999999/remover', headers=COORD).status_code == 404
    assert c.post(f"/disciplinas/{outra['id']}/turma", headers={**COORD, 'Origin': 'https://fora'}).status_code == 403


def test_incluir_disciplina_da_matriz_ou_avulsa_pela_pagina(app):
    c, _, d = app
    d.adicionar_fases('CC', '2026.2', [4], 'x')
    html = c.get('/disciplinas?curso=CC&periodo=2026.2', headers=COORD).get_data(as_text=True)
    assert '<optgroup label="1ª fase">' in html and 'CCC0723 · Desenvolvimento Web I' not in html  # já está
    algoritmos = next(cp for cp in d.ofertas.matriz('CC') if cp['codigo'] == 'CCC0701')
    r = c.post('/disciplinas/incluir', headers=COORD, data={'curso': 'CC', 'periodo': '2026.2', 'componente': str(algoritmos['id'])})
    assert 'aviso=incluida' in _local(r)
    r = c.post('/disciplinas/incluir', headers=COORD, data={'curso': 'CC', 'periodo': '2026.2', 'nome': 'Tópicos',
                                                            'codigo': '', 'carga_horaria': '30', 'fase': '7'})
    assert 'aviso=incluida' in _local(r)
    assert 'erro=' in _local(c.post('/disciplinas/incluir', headers=COORD, data={'curso': 'CC', 'periodo': '2026.2', 'nome': ''}))
    assert 'erro=' in _local(c.post('/disciplinas/incluir', headers=COORD, data={'curso': 'CC', 'periodo': '2026.2', 'componente': 'x'}))
    assert c.post('/disciplinas/incluir', headers=NDE, data={'curso': 'CC', 'periodo': '2026.2', 'nome': 'X'}).status_code == 403
    nomes = [o['nome'] for o in d.ofertas.listar(periodo='2026.2')]
    assert 'Algoritmos' in nomes and 'Tópicos' in nomes


# Do semestre ao plano enviado ---------------------------------------------------------------------------

def test_da_grade_do_semestre_ao_plano_no_painel(app, monkeypatch):
    from app.avaliacao import pipeline
    monkeypatch.setattr(pipeline, 'revalidar', lambda cfg, andamento, nome: andamento.finalizar())
    c, planos, d = app
    # Sem disciplina vinculada, o professor não tem onde enviar
    assert c.get('/meus-planos/lista', headers=FULANO).json['planos'] == []

    c.post('/disciplinas/semestre', headers=COORD, data={'curso': 'CC', 'periodo': '2026.2', 'fase': '4'})
    web = next(o for o in d.ofertas.listar(periodo='2026.2') if o['codigo'] == 'CCC0723')
    c.post(f"/disciplinas/{web['id']}/docentes", headers=COORD, data={'docentes': 'fulano@ifc.edu.br'})

    [disciplina] = c.get('/meus-planos/lista', headers=FULANO).json['planos']
    assert disciplina['situacao'] == 'sem_plano' and disciplina['grupo'] == 'CC|2026.2'
    pdf = gerar_pdf(['CCC0723 - DESENVOLVIMENTO WEB I (60h) - Turma: 01 (2026.2)']
                    + ['Linha de texto do plano de ensino numero %d.' % i for i in range(8)])
    r = enviar_plano(c, web, pdf, cab=FULANO, nome='qualquer coisa.pdf')
    assert r.status_code == 200 and r.json['aviso'] == '' and (planos / web['arquivo']).exists()

    html = c.get('/disciplinas?curso=CC&periodo=2026.2', headers=COORD).get_data(as_text=True)
    assert 'Plano enviado' in html
    # Um docente da disciplina não revisa o plano dela
    c.post(f"/disciplinas/{web['id']}/docentes", headers=COORD, data={'docentes': 'fulano@ifc.edu.br, nde@ifc.edu.br'})
    assert servicos_de(c).revisao.eh_autor('nde@ifc.edu.br', web['arquivo'])
    assert not servicos_de(c).revisao.eh_autor('coord@ifc.edu.br', web['arquivo'])


def test_disciplina_removida_some_de_meus_planos(app):
    c, _, d = app
    o = d.adicionar_avulsa('CC', '2026.2', 'X', '', 60, 1, 'x')
    d.definir_docentes(o['id'], 'fulano@ifc.edu.br')
    assert len(c.get('/meus-planos/lista', headers=FULANO).json['planos']) == 1
    c.post(f"/disciplinas/{o['id']}/remover", headers=COORD)
    assert c.get('/meus-planos/lista', headers=FULANO).json['planos'] == []
    r = c.post('/meus-planos', headers=FULANO, data={'oferta': str(o['id']), 'arquivo': (io.BytesIO(PDF_COM_TEXTO), 'a.pdf')},
               content_type='multipart/form-data')
    assert r.status_code == 400 and 'não encontrada' in r.json['erro']
