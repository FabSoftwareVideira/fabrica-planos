import logging
from datetime import date
from urllib.parse import urlencode

from flask import Blueprint, redirect, render_template, request

from ..servicos.disciplinas import ComPlano, Invalido
from .comum import eh_admin, email, mesma_origem, servicos, texto

# Disciplinas do semestre: a coordenação do curso (ou a administração) monta a grade de cada semestre a
# partir da matriz do PPC e vincula os docentes de cada disciplina. Formulários simples (POST e volta para
# a página), sem JavaScript.
log = logging.getLogger(__name__)
bp = Blueprint('disciplinas', __name__, url_prefix='/disciplinas')

AVISOS = {
    'fases': ('success', 'check-circle', 'Disciplinas das fases escolhidas incluídas no semestre.'),
    'nenhuma': ('info', 'info-circle', 'As disciplinas dessas fases já estavam no semestre.'),
    'incluida': ('success', 'check-circle', 'Disciplina incluída no semestre.'),
    'alterada': ('success', 'check-circle', 'Disciplina alterada.'),
    'docentes': ('success', 'check-circle', 'Docentes salvos. Eles já podem enviar o plano desta disciplina em "Meus planos".'),
    'turma': ('success', 'check-circle', 'Nova turma criada: vincule os docentes dela.'),
    'removida': ('success', 'check-circle', 'Disciplina removida do semestre.'),
    'com_plano': ('danger', 'times-circle', 'Esta disciplina já tem plano enviado; peça ao docente que o exclua antes de removê-la.'),
}


def _sugerir_periodo(hoje=None):
    """Próximo semestre a planejar: no 1º semestre do ano, o 2º; no 2º, o 1º do ano seguinte."""
    hoje = hoje or date.today()
    return f'{hoje.year}.2' if hoje.month <= 6 else f'{hoje.year + 1}.1'


def _voltar(curso, periodo, aviso='', erro='', ancora=''):
    consulta = urlencode({k: v for k, v in (('curso', curso), ('periodo', periodo), ('aviso', aviso),
                                            ('erro', erro)) if v})
    return redirect('/disciplinas?' + consulta + (f'#{ancora}' if ancora else ''), 303)


def _permitido(curso):
    return servicos().disciplinas.pode_gerenciar(email(), eh_admin(), curso)


@bp.get('')
def pagina():
    s = servicos().disciplinas
    cursos = s.cursos_gerenciaveis(email(), eh_admin())
    if not cursos:
        return redirect('/dashboard')
    curso = request.args.get('curso', '')
    curso = curso if curso in cursos else next(iter(cursos))
    periodos = s.periodos(curso)
    periodo = request.args.get('periodo', '') or (periodos[0] if periodos else '')
    grade = s.semestre(curso, periodo) if periodo else []
    for _, ofertas in grade:
        for o in ofertas:
            o['tem_plano'] = servicos().planos.existe(o['arquivo'])
    no_semestre = {o['componente_id'] for _, ofertas in grade for o in ofertas}
    sugestao = _sugerir_periodo()
    semestre_sugerido = periodo or sugestao
    # Fases sugeridas: as ímpares no 1º semestre e as pares no 2º
    impar = semestre_sugerido.endswith('.1')
    matriz = s.matriz_por_fase(curso)
    usuarios = servicos().usuarios.listar(situacao='ativos', ordem='nome', por_pagina=2000)[0]
    return render_template(
        'disciplinas.html', cursos=cursos, curso=curso, periodos=periodos, periodo=periodo, grade=grade,
        matriz=matriz, fora_do_semestre=[(f, [c for c in cs if c['id'] not in no_semestre]) for f, cs in matriz],
        fases_sugeridas={f for f, _ in matriz if (f % 2 == 1) == impar}, periodo_sugerido=sugestao,
        usuarios=usuarios, aviso=AVISOS.get(request.args.get('aviso', '')), erro=request.args.get('erro', ''),
        dominio=servicos().cfg.email_dominio, total=sum(len(o) for _, o in grade))


def _form(*campos):
    return [request.form.get(c, '') for c in campos]


@bp.post('/semestre')
def incluir_fases():
    curso, periodo = _form('curso', 'periodo')
    periodo = periodo.strip()
    if not mesma_origem() or not _permitido(curso):
        return texto('Só a coordenação do curso (ou a administração) monta as disciplinas do semestre.', 403)
    try:
        novas = servicos().disciplinas.adicionar_fases(curso, periodo, request.form.getlist('fase'), email() or 'local')
    except (Invalido, ValueError) as erro:
        return _voltar(curso, '', erro=str(erro) if isinstance(erro, Invalido) else 'Fase inválida.')
    return _voltar(curso, periodo, 'fases' if novas else 'nenhuma')


@bp.post('/incluir')
def incluir():
    """Uma disciplina da matriz (de qualquer fase) ou uma avulsa, só neste semestre."""
    curso, periodo = _form('curso', 'periodo')
    if not mesma_origem() or not _permitido(curso):
        return texto('Só a coordenação do curso (ou a administração) monta as disciplinas do semestre.', 403)
    s = servicos().disciplinas
    try:
        if request.form.get('componente'):
            oferta = s.adicionar_componente(curso, periodo, int(request.form['componente']), email() or 'local')
        else:
            nome, codigo, carga, fase = _form('nome', 'codigo', 'carga_horaria', 'fase')
            oferta = s.adicionar_avulsa(curso, periodo, nome, codigo, carga, fase, email() or 'local')
    except (Invalido, ValueError) as erro:
        return _voltar(curso, periodo, erro=str(erro) if isinstance(erro, Invalido) else 'Disciplina inválida.')
    return _voltar(curso, periodo, 'incluida', ancora=f"oferta-{oferta['id']}")


def _da_oferta(id_):
    """(oferta, resposta de erro): a oferta, se existir e quem pede puder gerenciar o curso dela."""
    oferta = servicos().disciplinas.oferta(id_)
    if not oferta:
        return None, texto('Disciplina não encontrada.', 404)
    if not mesma_origem() or not _permitido(oferta['curso']):
        return None, texto('Só a coordenação do curso (ou a administração) altera as disciplinas do semestre.', 403)
    return oferta, None


@bp.post('/<int:id_>/alterar')
def alterar(id_):
    oferta, erro = _da_oferta(id_)
    if erro:
        return erro
    try:
        servicos().disciplinas.alterar(id_, *_form('nome', 'codigo', 'carga_horaria', 'turma'))
    except Invalido as e:
        return _voltar(oferta['curso'], oferta['periodo'], erro=str(e), ancora=f'oferta-{id_}')
    return _voltar(oferta['curso'], oferta['periodo'], 'alterada', ancora=f'oferta-{id_}')


@bp.post('/<int:id_>/docentes')
def docentes(id_):
    oferta, erro = _da_oferta(id_)
    if erro:
        return erro
    try:
        servicos().disciplinas.definir_docentes(id_, request.form.get('docentes', ''))
    except Invalido as e:
        return _voltar(oferta['curso'], oferta['periodo'], erro=str(e), ancora=f'oferta-{id_}')
    return _voltar(oferta['curso'], oferta['periodo'], 'docentes', ancora=f'oferta-{id_}')


@bp.post('/<int:id_>/turma')
def nova_turma(id_):
    oferta, erro = _da_oferta(id_)
    if erro:
        return erro
    nova = servicos().disciplinas.nova_turma(id_, email() or 'local')
    return _voltar(oferta['curso'], oferta['periodo'], 'turma', ancora=f"oferta-{nova['id']}")


@bp.post('/<int:id_>/remover')
def remover(id_):
    oferta, erro = _da_oferta(id_)
    if erro:
        return erro
    try:
        servicos().disciplinas.remover(id_, servicos().planos.existe)
    except ComPlano:
        return _voltar(oferta['curso'], oferta['periodo'], 'com_plano', ancora=f'oferta-{id_}')
    return _voltar(oferta['curso'], oferta['periodo'], 'removida')
