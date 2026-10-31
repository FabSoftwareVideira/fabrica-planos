from urllib.parse import quote

from ..armazenamento.csvsaida import CAMPOS_COLUNA
from ..avaliacao import identificacao

# Dashboard (templates/dashboard.html): resumo, filtros e um card por plano da validação atual. O status
# de cada plano é o da revisão manual (coordenação/NDE/NDB), quando houver uma vigente; senão, o da IA.

STATUS_FILTRO = [('OK', 'Aprovados'), ('PENDENTE', 'Pendentes'), ('REPROVADO', 'Reprovados'), ('ERRO', 'Com erro')]

AGRUPAMENTOS = [('cp', 'Curso e período'), ('periodo', 'Período'), ('curso', 'Curso'), ('docente', 'Docente'),
                ('status', 'Situação'), ('revisao', 'Revisão'), ('', 'Sem agrupar')]


def _dados_grupo(ident, docentes):
    """Pares (nome, valor) dos atributos data-* com a chave, o título e a ordem de cada forma de agrupar,
    usados pelo script do dashboard para montar os grupos no navegador."""
    dados = []
    for nome, funcao in (('cp', identificacao.grupo_curso_periodo), ('periodo', identificacao.grupo_periodo),
                         ('curso', identificacao.grupo_curso)):
        chave, titulo, ordem = funcao(ident)
        dados += [(nome, chave), (nome + '-titulo', titulo), (nome + '-ordem', ordem)]
    dados.append(('docente', ', '.join(docentes)))
    return dados


def _card(indice, linha, validacao, pdfs_guardados, admin, ident=None, docentes=(), revisao=None):
    arquivo = linha.get('Arquivo') or ''
    partes = []
    if ident:
        partes = [ident['codigo'], ident['disciplina']] + (['Turma ' + ident['turma']] if ident['turma'] else [])
        partes.append(str(ident['carga_horaria']) + 'h')
    partes += list(docentes)
    tem_pdf = arquivo in pdfs_guardados
    return {
        'indice': indice,
        'arquivo': arquivo,
        'nome': arquivo.replace('2024-1 - ', '').replace('.pdf', ''),
        'sub': ' · '.join(partes),
        'status': linha.get('Status Geral', ''),  # o da revisão, se houver
        'revisao': revisao,
        'problemas': '|'.join(rotulo for rotulo, _ in CAMPOS_COLUNA if linha.get(rotulo) != 'OK'),
        'observacao': linha.get('Observação Geral', ''),
        'topicos': [(rotulo, linha.get(rotulo, ''), linha.get(rotulo + ' Obs', '')) for rotulo, _ in CAMPOS_COLUNA],
        'dados': _dados_grupo(ident, docentes),
        # O relatório abre na mesma aba e volta para este card (âncora #plano-N).
        'url_relatorio': '/relatorio?arquivo=' + quote(arquivo),
        'url_pdf': '/validacoes/' + validacao + '/pdf?arquivo=' + quote(arquivo) if tem_pdf else '',
        'revalidar': admin,  # revalidar é coisa de administrador
    }


def _filtros(linhas, grupos, revisados):
    """Opções da barra de filtros (tudo é filtrado no navegador). Com um só curso e período, o filtro
    de grupo não aparece; os campos listados são só os que têm problema em algum plano."""
    chips = [('', 'Todos', len(linhas))]
    for status, rotulo in STATUS_FILTRO:
        n = sum(1 for l in linhas if l.get('Status Geral') == status)
        if n:
            chips.append((status, rotulo, n))
    return {
        'agrupamentos': AGRUPAMENTOS,
        'grupos': grupos if len(grupos) > 1 else [],
        'chips': chips,
        'campos': [rotulo for rotulo, _ in CAMPOS_COLUNA if any(l.get(rotulo) != 'OK' for l in linhas)],
        'revisao': [('', 'Revisados ou não'), ('1', f'Revisados ({revisados})'),
                    ('0', f'Aguardando revisão ({len(linhas) - revisados})')],
    }


def contexto(linhas, max_mb=10, execucao=None, usuario='', admin=True, idents=None, docentes=None, revisoes=None):
    """`revisoes`: {arquivo: resumo da revisão vigente} (servicos/revisao.py: resumo)."""
    revisoes = revisoes or {}
    # Com revisão vigente, o status do revisor substitui o da IA em tudo (resumo, filtros, agrupamento).
    linhas = [dict(l, **{'Status Geral': revisoes[l.get('Arquivo')]['status']}) if l.get('Arquivo') in revisoes else l
              for l in linhas]
    total = len(linhas)
    ok = sum(1 for l in linhas if l.get('Status Geral') == 'OK')
    pendente = sum(1 for l in linhas if l.get('Status Geral') == 'PENDENTE')
    problema = total - ok - pendente

    def pct(n):
        return round(n / total * 100) if total else 0

    ctx = {
        'max_mb': int(max_mb),
        'admin': admin,
        'usuario': usuario,
        'total': total,
        'resumo': [('Aprovados', ok, pct(ok), '#22c55e'), ('Pendentes', pendente, pct(pendente), '#eab308'),
                   ('Com problemas', problema, pct(problema), '#ef4444')],
        'execucao': execucao,
        'cards': [],
    }
    if execucao is None:
        return ctx

    ctx.update({'tem_pdfs': bool(execucao.pdfs()), 'meta': execucao.meta()})
    if linhas:
        pdfs = set(execucao.pdfs())
        idents, docentes = idents or {}, docentes or {}
        ctx['cards'] = [_card(i, l, execucao.id, pdfs, admin, idents.get(l.get('Arquivo')),
                              docentes.get(l.get('Arquivo'), ()), revisoes.get(l.get('Arquivo')))
                        for i, l in enumerate(linhas)]
        grupos = sorted({identificacao.grupo_curso_periodo(idents.get(l.get('Arquivo'))) for l in linhas},
                        key=lambda g: (g[2], g[1]))
        revisados = sum(1 for l in linhas if l.get('Arquivo') in revisoes)
        ctx['filtros'] = _filtros(linhas, [(chave, titulo) for chave, titulo, _ in grupos], revisados)
    return ctx
