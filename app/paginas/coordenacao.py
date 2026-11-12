from urllib.parse import quote, urlencode

from ..armazenamento.csvsaida import CAMPOS_COLUNA
from ..avaliacao import identificacao

# Visão da coordenação (templates/coordenacao.html): a situação dos planos de um curso na validação atual,
# por período. Cada coordenador vê os cursos que coordena; a administração vê todos. Com revisão vigente,
# o status do revisor vale sobre o da IA, como no dashboard.

SITUACOES = [('OK', 'Aprovados', '#22c55e'), ('PENDENTE', 'Pendentes', '#eab308'),
             ('REPROVADO', 'Reprovados', '#ef4444'), ('ERRO', 'Com erro', '#6b7280')]
TODOS = 'todos'


def _pct(n, total):
    return round(n / total * 100) if total else 0


def _contagem(planos):
    total = len(planos)
    return [{'status': status, 'rotulo': rotulo, 'cor': cor, 'n': n, 'pct': _pct(n, total)}
            for status, rotulo, cor in SITUACOES
            for n in [sum(1 for p in planos if p['status'] == status)]]


def _periodos(planos):
    """[(período, título)] dos planos, o mais recente primeiro."""
    vistos = {p['ident']['periodo']: p['ident'] for p in planos if p['ident'].get('periodo')}
    return [(per, identificacao.titulo_periodo(ident))
            for per, ident in sorted(vistos.items(), key=lambda par: identificacao.grupo_periodo(par[1])[2])]


def _plano(linha, ident, docentes, revisao, revisavel, assinatura=None, liberado=False, pode_liberar=False):
    arquivo = linha.get('Arquivo', '')
    relatorio = '/relatorio?arquivo=' + quote(arquivo)
    return {
        'arquivo': arquivo,
        'disciplina': ident['disciplina'] + (' · Turma ' + ident['turma'] if ident['turma'] else ''),
        'codigo': ident['codigo'],
        'ident': ident,
        'docentes': list(docentes) or ['Sem docente identificado'],
        'status': (revisao or {}).get('status') or linha.get('Status Geral', ''),
        'status_ia': linha.get('Status Geral', ''),
        'revisao': revisao,
        # Campos que a IA (e as regras) não aprovaram: o que mais falta nos planos do curso.
        'problemas': [rotulo for rotulo, _ in CAMPOS_COLUNA if linha.get(rotulo) != 'OK'],
        'url_relatorio': relatorio,
        'url_revisar': relatorio + '#revisao' if revisavel else '',
        # Plano assinado pelo professor: a coordenação pode liberar o envio de uma nova versão.
        'assinatura': assinatura,
        'liberado': liberado and bool(assinatura),
        'pode_liberar': pode_liberar and bool(assinatura),
    }


def _docentes(planos):
    """Linhas da tabela por docente: planos, situação de cada um e quantos aguardam revisão."""
    por_docente = {}
    for p in planos:
        for nome in p['docentes']:
            por_docente.setdefault(nome, []).append(p)
    linhas = []
    for nome, dele in por_docente.items():
        contagem = {c['status']: c['n'] for c in _contagem(dele)}
        linhas.append({'nome': nome, 'total': len(dele), 'contagem': contagem,
                       'aguardando': sum(1 for p in dele if not p['revisao']),
                       'pendencias': len(dele) - contagem['OK']})
    # Quem tem mais planos a ajustar primeiro.
    return sorted(linhas, key=lambda l: (-l['pendencias'], l['nome']))


def contexto(execucao, linhas, idents, docentes, revisoes, cursos, curso, periodo, revisaveis=(),
             exportar=True, assinaturas=None, liberados=(), liberaveis=()):
    """`cursos`: {sigla: nome} que o usuário pode ver; `curso` e `periodo`: os pedidos (vazios: o primeiro
    curso e o período mais recente dele). `assinaturas`: {arquivo: resumo}; `liberados`/`liberaveis`: nomes
    dos planos com reenvio liberado e dos que quem está vendo pode liberar."""
    assinaturas = assinaturas or {}
    ctx = {'execucao': execucao, 'cursos': list(cursos.items()), 'curso': '', 'nome_curso': '',
           'periodos': [], 'periodo': '', 'planos': [], 'meta': execucao.meta() if execucao else {}}
    if not cursos:
        return ctx
    curso = curso if curso in cursos else next(iter(cursos))
    ctx.update({'curso': curso, 'nome_curso': cursos[curso]})

    do_curso = [_plano(l, idents[l.get('Arquivo')], docentes.get(l.get('Arquivo'), ()),
                       revisoes.get(l.get('Arquivo')), l.get('Arquivo') in revisaveis,
                       assinaturas.get(l.get('Arquivo')), l.get('Arquivo') in liberados,
                       l.get('Arquivo') in liberaveis)
                for l in linhas if (idents.get(l.get('Arquivo')) or {}).get('sigla_curso') == curso]
    periodos = _periodos(do_curso)
    validos = [p for p, _ in periodos]
    periodo = periodo if periodo in validos or periodo == TODOS else (validos[0] if validos else TODOS)
    planos = do_curso if periodo == TODOS else [p for p in do_curso if p['ident'].get('periodo') == periodo]
    # Primeiro o que precisa de atenção: não aprovados e, depois, os que ninguém revisou ainda.
    planos.sort(key=lambda p: (p['status'] == 'OK', bool(p['revisao']), p['ident']['disciplina'], p['ident']['turma']))

    total = len(planos)
    revisados = sum(1 for p in planos if p['revisao'])
    discordam = sum(1 for p in planos if p['revisao'] and not p['revisao']['concorda'])
    campos = [(rotulo, n, _pct(n, total)) for rotulo, _ in CAMPOS_COLUNA
              for n in [sum(1 for p in planos if rotulo in p['problemas'])] if n]
    campos.sort(key=lambda c: -c[1])
    titulo_periodo = dict(periodos).get(periodo, 'Todos os períodos')
    zip_ = ''
    if exportar and execucao and total:
        guardados = set(execucao.pdfs())
        nomes = [p['arquivo'] for p in planos if p['arquivo'] in guardados]
        if nomes:
            zip_ = (f'/validacoes/{execucao.id}/pdfs.zip?'
                    + urlencode([('nome', cursos[curso] + ' ' + titulo_periodo)] + [('arquivo', n) for n in nomes]))
    ctx.update({
        'periodos': periodos + ([(TODOS, 'Todos os períodos')] if len(periodos) > 1 else []),
        'periodo': periodo,
        'titulo_periodo': titulo_periodo,
        'planos': planos,
        'total': total,
        'situacoes': _contagem(planos),
        'revisados': revisados,
        'aguardando': total - revisados,
        'pct_revisados': _pct(revisados, total),
        'discordam': discordam,
        'campos': campos,
        'docentes': _docentes(planos),
        'url_zip': zip_,
    })
    return ctx
