import logging
from urllib.parse import quote, urlencode

from flask import Blueprint, redirect, render_template, request

from ..servicos.disciplinas import ComPlano, Invalido, JaExiste
from .comum import eh_admin, email, mesma_origem, servicos, texto

# Disciplinas: a coordenação do curso (ou a administração) planeja cada período letivo num assistente em
# etapas, a partir da matriz do PPC: 1. período (o próximo é sugerido); 2. fases; 3. disciplinas (renomear,
# outra turma, avulsas); 4. docentes; 5. revisão e publicação. Cada etapa grava o rascunho; os docentes só
# veem as disciplinas depois de publicado. Formulários simples (POST e volta para a página), sem JavaScript.
log = logging.getLogger(__name__)
bp = Blueprint('disciplinas', __name__, url_prefix='/disciplinas')

ETAPAS = [('periodo', 'Período'), ('fases', 'Fases'), ('disciplinas', 'Disciplinas'), ('docentes', 'Docentes'),
          ('revisao', 'Revisão e publicação')]



def _etapas(tipo):
    """Nos cursos anuais (integrados), a etapa das fases é a dos anos (séries)."""
    return [(chave, 'Anos' if chave == 'fases' and tipo == 'anual' else rotulo) for chave, rotulo in ETAPAS]


AVISOS = {
    'criado': ('success', 'check-circle', 'Planejamento iniciado como rascunho. Escolha as fases (ou os anos) que terão turma.'),
    'ja_existe': ('info', 'info-circle', 'Já havia um planejamento para esse período: continue de onde parou.'),
    'fases': ('success', 'check-circle', 'Seleção salva. Confira as disciplinas do período.'),
    'incluida': ('success', 'check-circle', 'Disciplina incluída.'),
    'alterada': ('success', 'check-circle', 'Disciplina alterada.'),
    'turma': ('success', 'check-circle', 'Nova turma criada. Os docentes dela são vinculados na próxima etapa.'),
    'removida': ('success', 'check-circle', 'Disciplina removida do período.'),
    'com_plano': ('danger', 'times-circle', 'Esta disciplina já tem plano enviado; peça ao docente que o exclua antes de removê-la.'),
    'docentes': ('success', 'check-circle', 'Docentes salvos.'),
    'publicado': ('success', 'check-circle', 'Planejamento publicado: os docentes já veem as disciplinas em "Meus planos" e podem enviar os planos.'),
    'rascunho': ('info', 'info-circle', 'Planejamento de volta a rascunho: os docentes deixaram de ver estas disciplinas.'),
    'excluido': ('success', 'check-circle', 'Rascunho descartado.'),
    'nao_publica': ('danger', 'times-circle', 'O planejamento só volta a rascunho (ou é descartado) enquanto nenhum plano foi enviado.'),
}


def _endereco(curso, periodo, etapa, **consulta):
    base = f'/disciplinas/{quote(curso)}/{quote(periodo)}/{etapa}'
    consulta = {k: v for k, v in consulta.items() if v and k != 'ancora'}
    return base + ('?' + urlencode(consulta) if consulta else '')


def _ir(curso, periodo, etapa, aviso='', erro='', ancora=''):
    return redirect(_endereco(curso, periodo, etapa, aviso=aviso, erro=erro) + (f'#{ancora}' if ancora else ''), 303)


def _permitido(curso):
    return servicos().disciplinas.pode_gerenciar(email(), eh_admin(), curso)


def _proibido():
    return texto('Só a coordenação do curso (ou a administração) planeja as disciplinas.', 403)


def _ctx(curso, periodo, etapa, **extra):
    """Contexto comum das etapas: curso, planejamento, etapas e avisos."""
    s = servicos().disciplinas
    p = s.planejamento(curso, periodo)
    return dict(curso=curso, nome_curso=s.cursos().get(curso, curso), periodo=periodo, planejamento=p,
                etapas=_etapas(s.tipo(curso)), etapa=etapa, tipo=s.tipo(curso), aviso=AVISOS.get(request.args.get('aviso', '')),
                erro=request.args.get('erro', ''), **extra)


def _do_planejamento(curso, periodo):
    """(planejamento, resposta de erro) para as etapas: existe e quem pede pode gerenciar o curso."""
    if not _permitido(curso):
        return None, _proibido()
    p = servicos().disciplinas.planejamento(curso, periodo)
    if not p:
        return None, texto('Planejamento não encontrado.', 404)
    return p, None


# Lista e início ----------------------------------------------------------------------------------------

@bp.get('')
def lista():
    s = servicos().disciplinas
    cursos = s.cursos_gerenciaveis(email(), eh_admin())
    if not cursos:
        return redirect('/dashboard')
    grupos = [(sigla, nome, s.tipo(sigla), s.planejamentos(sigla), s.sugerir_periodo(sigla)) for sigla, nome in cursos.items()]
    return render_template('disciplinas_lista.html', grupos=grupos, aviso=AVISOS.get(request.args.get('aviso', '')),
                           erro=request.args.get('erro', ''))


@bp.get('/novo')
def novo():
    s = servicos().disciplinas
    cursos = s.cursos_gerenciaveis(email(), eh_admin())
    if not cursos:
        return redirect('/dashboard')
    curso = request.args.get('curso', '')
    curso = curso if curso in cursos else next(iter(cursos))
    return render_template('disciplinas_periodo.html', **_ctx(
        curso, '', 'periodo', cursos=cursos, sugestao=s.sugerir_periodo(curso),
        existentes=[p['periodo'] for p in s.planejamentos(curso)]))


@bp.post('/novo')
def criar():
    curso, periodo = request.form.get('curso', ''), request.form.get('periodo', '').strip()
    if not mesma_origem() or not _permitido(curso):
        return _proibido()
    try:
        servicos().disciplinas.criar_planejamento(curso, periodo, email() or 'local')
    except Invalido as erro:
        return redirect('/disciplinas/novo?' + urlencode({'curso': curso, 'erro': str(erro)}), 303)
    except JaExiste:
        return _ir(curso, periodo, 'fases', 'ja_existe')
    return _ir(curso, periodo, 'fases', 'criado')


@bp.get('/<curso>/<periodo>')
def continuar(curso, periodo):
    """Abre o planejamento na etapa em que faz sentido continuar."""
    p, erro = _do_planejamento(curso, periodo)
    if erro:
        return erro
    if p['situacao'] == 'publicado':
        etapa = 'revisao'
    elif not p['fases_lista'] and not p['disciplinas']:
        etapa = 'fases'
    elif p['sem_docente']:
        etapa = 'docentes'
    else:
        etapa = 'revisao'
    return redirect(_endereco(curso, periodo, etapa), 303)


# Etapas -----------------------------------------------------------------------------------------------------

@bp.get('/<curso>/<periodo>/fases')
def fases(curso, periodo):
    p, erro = _do_planejamento(curso, periodo)
    if erro:
        return erro
    s = servicos().disciplinas
    marcadas = p['fases_lista'] or ([] if p['disciplinas'] else s.fases_sugeridas(curso, periodo))
    if not p['fases_lista'] and p['disciplinas']:  # planejamento de antes das etapas: as fases das disciplinas
        marcadas = sorted({o['fase'] for o in s.ofertas.listar(curso=curso, periodo=periodo) if o['fase']})
    return render_template('disciplinas_fases.html', **_ctx(
        curso, periodo, 'fases', matriz=s.matriz_por_fase(curso), marcadas=set(marcadas),
        sugeridas=s.fases_sugeridas(curso, periodo)))


@bp.post('/<curso>/<periodo>/fases')
def salvar_fases(curso, periodo):
    _, erro = _do_planejamento(curso, periodo)
    if erro or not mesma_origem():
        return erro or _proibido()
    try:
        servicos().disciplinas.definir_fases(curso, periodo, request.form.getlist('fase'), email() or 'local')
    except (Invalido, ValueError) as e:
        return _ir(curso, periodo, 'fases', erro=str(e) if isinstance(e, Invalido) else 'Fase inválida.')
    return _ir(curso, periodo, 'disciplinas', 'fases')


@bp.get('/<curso>/<periodo>/disciplinas')
def disciplinas(curso, periodo):
    _, erro = _do_planejamento(curso, periodo)
    if erro:
        return erro
    s = servicos().disciplinas
    grade = s.semestre(curso, periodo)
    for _, ofertas in grade:
        for o in ofertas:
            o['tem_plano'] = servicos().planos.existe(o['arquivo'])
    no_periodo = {o['componente_id'] for _, ofertas in grade for o in ofertas}
    matriz = s.matriz_por_fase(curso)
    return render_template('disciplinas_grade.html', **_ctx(
        curso, periodo, 'disciplinas', grade=grade, total=sum(len(o) for _, o in grade),
        fora_do_periodo=[(f, [c for c in cs if c['id'] not in no_periodo]) for f, cs in matriz]))


@bp.get('/<curso>/<periodo>/docentes')
def docentes(curso, periodo):
    _, erro = _do_planejamento(curso, periodo)
    if erro:
        return erro
    usuarios = servicos().usuarios.listar(situacao='ativos', ordem='nome', por_pagina=2000)[0]
    return render_template('disciplinas_docentes.html', **_ctx(
        curso, periodo, 'docentes', grade=servicos().disciplinas.semestre(curso, periodo), usuarios=usuarios,
        dominio=servicos().cfg.email_dominio))


@bp.post('/<curso>/<periodo>/docentes')
def salvar_docentes(curso, periodo):
    _, erro = _do_planejamento(curso, periodo)
    if erro or not mesma_origem():
        return erro or _proibido()
    textos = {}
    for chave, valor in request.form.items():
        if chave.startswith('docentes-') and chave[9:].isdigit():
            textos[int(chave[9:])] = valor
    try:
        servicos().disciplinas.definir_docentes_em_lote(curso, periodo, textos)
    except Invalido as e:
        return _ir(curso, periodo, 'docentes', erro=str(e))
    return _ir(curso, periodo, 'revisao' if request.form.get('seguir') else 'docentes', 'docentes')


@bp.get('/<curso>/<periodo>/revisao')
def revisao(curso, periodo):
    p, erro = _do_planejamento(curso, periodo)
    if erro:
        return erro
    s = servicos().disciplinas
    grade = s.semestre(curso, periodo)
    ofertas = [o for _, os in grade for o in os]
    novos = sorted({d['email'] for o in ofertas for d in o['docentes_info'] if not d['cadastrado']})
    return render_template('disciplinas_revisao.html', **_ctx(
        curso, periodo, 'revisao', grade=grade, sem_docente=[o for o in ofertas if not o['docentes']],
        docentes=sorted({d['email'] for o in ofertas for d in o['docentes_info']}), novos=novos))


@bp.post('/<curso>/<periodo>/publicar')
def publicar(curso, periodo):
    _, erro = _do_planejamento(curso, periodo)
    if erro or not mesma_origem():
        return erro or _proibido()
    if not request.form.get('confirmo'):
        return _ir(curso, periodo, 'revisao', erro='Marque a confirmação de que o planejamento está completo para publicar.')
    try:
        servicos().disciplinas.publicar(curso, periodo, email() or 'local')
    except Invalido as e:
        return _ir(curso, periodo, 'revisao', erro=str(e))
    return _ir(curso, periodo, 'revisao', 'publicado')


@bp.post('/<curso>/<periodo>/rascunho')
def voltar_a_rascunho(curso, periodo):
    _, erro = _do_planejamento(curso, periodo)
    if erro or not mesma_origem():
        return erro or _proibido()
    try:
        servicos().disciplinas.voltar_a_rascunho(curso, periodo, email() or 'local')
    except ComPlano:
        return _ir(curso, periodo, 'revisao', 'nao_publica')
    return _ir(curso, periodo, 'revisao', 'rascunho')


@bp.post('/<curso>/<periodo>/excluir')
def excluir(curso, periodo):
    _, erro = _do_planejamento(curso, periodo)
    if erro or not mesma_origem():
        return erro or _proibido()
    try:
        servicos().disciplinas.excluir_planejamento(curso, periodo, email() or 'local')
    except ComPlano:
        return _ir(curso, periodo, 'revisao', 'nao_publica')
    return redirect('/disciplinas?aviso=excluido', 303)


# Ações em cada disciplina (etapa Disciplinas) --------------------------------------------------------------

@bp.post('/incluir')
def incluir():
    """Uma disciplina da matriz (de qualquer fase) ou uma avulsa, só neste período."""
    curso, periodo = request.form.get('curso', ''), request.form.get('periodo', '')
    if not mesma_origem() or not _permitido(curso):
        return _proibido()
    s = servicos().disciplinas
    try:
        if request.form.get('componente'):
            oferta = s.adicionar_componente(curso, periodo, int(request.form['componente']), email() or 'local')
        else:
            oferta = s.adicionar_avulsa(curso, periodo, *[request.form.get(c, '') for c in
                                                           ('nome', 'codigo', 'carga_horaria', 'fase')],
                                        email() or 'local')
    except (Invalido, ValueError) as erro:
        return _ir(curso, periodo, 'disciplinas', erro=str(erro) if isinstance(erro, Invalido) else 'Disciplina inválida.')
    return _ir(curso, periodo, 'disciplinas', 'incluida', ancora=f"oferta-{oferta['id']}")


def _da_oferta(id_):
    """(oferta, resposta de erro): a oferta, se existir e quem pede puder gerenciar o curso dela."""
    oferta = servicos().disciplinas.oferta(id_)
    if not oferta:
        return None, texto('Disciplina não encontrada.', 404)
    if not mesma_origem() or not _permitido(oferta['curso']):
        return None, _proibido()
    return oferta, None


@bp.post('/<int:id_>/alterar')
def alterar(id_):
    o, erro = _da_oferta(id_)
    if erro:
        return erro
    try:
        servicos().disciplinas.alterar(id_, *[request.form.get(c, '') for c in ('nome', 'codigo', 'carga_horaria', 'turma')])
    except Invalido as e:
        return _ir(o['curso'], o['periodo'], 'disciplinas', erro=str(e), ancora=f'oferta-{id_}')
    return _ir(o['curso'], o['periodo'], 'disciplinas', 'alterada', ancora=f'oferta-{id_}')


@bp.post('/<int:id_>/docentes')
def docentes_da_oferta(id_):
    o, erro = _da_oferta(id_)
    if erro:
        return erro
    try:
        servicos().disciplinas.definir_docentes(id_, request.form.get('docentes', ''))
    except Invalido as e:
        return _ir(o['curso'], o['periodo'], 'docentes', erro=str(e), ancora=f'oferta-{id_}')
    return _ir(o['curso'], o['periodo'], 'docentes', 'docentes', ancora=f'oferta-{id_}')


@bp.post('/<int:id_>/turma')
def nova_turma(id_):
    o, erro = _da_oferta(id_)
    if erro:
        return erro
    nova = servicos().disciplinas.nova_turma(id_, email() or 'local')
    return _ir(o['curso'], o['periodo'], 'disciplinas', 'turma', ancora=f"oferta-{nova['id']}")


@bp.post('/<int:id_>/remover')
def remover(id_):
    o, erro = _da_oferta(id_)
    if erro:
        return erro
    try:
        servicos().disciplinas.remover(id_, servicos().planos.existe)
    except ComPlano:
        return _ir(o['curso'], o['periodo'], 'disciplinas', 'com_plano', ancora=f'oferta-{id_}')
    return _ir(o['curso'], o['periodo'], 'disciplinas', 'removida')
