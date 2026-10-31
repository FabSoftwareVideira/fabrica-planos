from flask import Blueprint, redirect, render_template, request

from ..paginas import coordenacao
from .comum import cursos_coordenados, eh_admin, servicos
from .painel import dados_da_validacao, revisaveis

# Visão da coordenação: situação dos planos de cada curso. O coordenador vê os cursos que coordena (papel
# dado em Administração → Usuários); a administração vê todos os cursos da validação atual.
bp = Blueprint('coordenacao', __name__)


@bp.get('/coordenacao')
def pagina():
    admin = eh_admin()
    meus = cursos_coordenados()
    if not admin and not meus:
        return redirect('/dashboard')
    execucao, linhas, idents, docentes, revisoes = dados_da_validacao()
    conhecidos = servicos().planos.cursos()
    if admin:
        siglas = sorted({i['sigla_curso'] for i in idents.values() if i} | set(meus))
    else:
        siglas = meus
    cursos = {sigla: conhecidos.get(sigla, sigla) for sigla in siglas}
    ctx = coordenacao.contexto(execucao, linhas, idents, docentes, revisoes, cursos,
                               request.args.get('curso', ''), request.args.get('periodo', ''), revisaveis(idents))
    return render_template('coordenacao.html', **ctx)
