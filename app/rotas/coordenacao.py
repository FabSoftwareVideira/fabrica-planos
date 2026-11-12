from urllib.parse import urlencode

from flask import Blueprint, redirect, render_template, request

from ..armazenamento import donos, liberacoes
from ..avaliacao import pipeline
from ..paginas import coordenacao
from .comum import cursos_coordenados, eh_admin, email, mesma_origem, servicos, texto
from .painel import dados_da_validacao, revisaveis

# Visão da coordenação: situação dos planos de cada curso. O coordenador vê os cursos que coordena (papel
# dado em Administração → Usuários); a administração vê todos os cursos da validação atual.
bp = Blueprint('coordenacao', __name__)


def _liberaveis(idents, cursos):
    """Planos cujo reenvio quem está vendo pode liberar (a coordenação do curso ou a administração)."""
    if eh_admin():
        return set(idents)
    return {nome for nome, ident in idents.items() if ident and ident['sigla_curso'] in cursos}


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
    assinaturas = {nome: r['assinatura'] for nome, r in revisoes.items() if r.get('assinatura')}
    liberados = set(liberacoes.ler(servicos().cfg.resultados_dir))
    ctx = coordenacao.contexto(execucao, linhas, idents, docentes, revisoes, cursos,
                               request.args.get('curso', ''), request.args.get('periodo', ''),
                               revisaveis(idents), assinaturas=assinaturas, liberados=liberados,
                               liberaveis=_liberaveis(idents, meus))
    return render_template('coordenacao.html', **ctx)


@bp.post('/coordenacao/liberar')
def liberar_reenvio():
    """Libera (ou cancela) o envio de uma nova versão de um plano já assinado pelo professor."""
    if not mesma_origem():
        return texto('Origem inválida', 403)
    s = servicos()
    nome = request.form.get('arquivo', '')
    if not pipeline.nome_valido(nome):
        return texto('Arquivo inválido', 400)
    _, _, idents, _, _ = dados_da_validacao()
    ident = idents.get(nome) or (donos.ler(s.cfg.resultados_dir).get(nome) or {}).get('identificacao')
    if not ident:
        return texto('Plano não encontrado na validação atual.', 404)
    if not (eh_admin() or s.revisao.eh_coordenador(email(), ident)):
        return texto('Só a coordenação do curso do plano (ou a administração) pode liberar um novo envio.', 403)
    if request.form.get('acao') == 'cancelar':
        liberacoes.cancelar(s.cfg.resultados_dir, nome)
    else:
        if not s.planos.assinado(nome):
            return texto('Este plano não está assinado.', 400)
        liberacoes.liberar(s.cfg.resultados_dir, nome, email() or 'local')
    consulta = urlencode({chave: valor for chave, valor in (
        ('curso', request.form.get('curso', '')),
        ('periodo', request.form.get('periodo', '')),
    ) if valor})
    return redirect('/coordenacao' + ('?' + consulta if consulta else ''), 303)
