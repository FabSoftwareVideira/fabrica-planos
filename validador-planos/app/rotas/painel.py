from flask import Blueprint, redirect, render_template, request, send_from_directory

from ..armazenamento import csvsaida, detalhes, historico
from ..avaliacao import identificacao, pipeline
from ..paginas import dashboard, relatorio
from .comum import eh_admin, email, json_, servicos, texto

# Consulta (qualquer servidor logado): dashboard, relatório de um plano, andamento e PDFs da pasta.
# Os caminhos /webhook/... mantêm compatíveis a página validacao.html e os links antigos do n8n.
bp = Blueprint('painel', __name__)


def execucao_pedida(execucoes):
    """A execução do parâmetro ?validacao= (padrão: a mais recente). None se o id não existir."""
    id_ = request.args.get('validacao')
    if not id_:
        return execucoes[0] if execucoes else None
    return next((e for e in execucoes if e.id == id_), None)


@bp.get('/dashboard')
@bp.get('/webhook/dashboard')
def pagina_dashboard():
    cfg = servicos().cfg
    execucoes = historico.listar(cfg.historico_dir)
    execucao = execucao_pedida(execucoes)
    if request.args.get('validacao') and execucao is None:
        return redirect('/dashboard')  # validação que saiu do histórico
    linhas = csvsaida.ler_csv(execucao.csv_path) if execucao else []
    # Curso, período e docentes de cada plano, lidos do texto guardado nos detalhes, para agrupar.
    dets = {l.get('Arquivo'): detalhes.ler(execucao.detalhes_dir, l.get('Arquivo')) for l in linhas}
    idents = {nome: identificacao.de_detalhes(det) for nome, det in dets.items()}
    docentes = {nome: identificacao.docentes((det or {}).get('texto', '')) for nome, det in dets.items()}
    return render_template('dashboard.html', **dashboard.contexto(linhas, cfg.pdf_max_mb, execucoes, execucao, email(),
                                                                  eh_admin(), idents, docentes))


@bp.get('/relatorio')
def pagina_relatorio():
    s = servicos()
    nome = request.args.get('arquivo', '')
    execucoes = historico.listar(s.cfg.historico_dir)
    execucao = execucao_pedida(execucoes)
    if execucao is None:
        return texto('Validação não encontrada no histórico.', 404)
    linhas = csvsaida.ler_csv(execucao.csv_path)
    indice = next((i for i, l in enumerate(linhas) if l.get('Arquivo') == nome), None)
    if not pipeline.nome_valido(nome) or indice is None:
        return texto('Plano não encontrado nessa validação.', 404)
    det = detalhes.ler(execucao.detalhes_dir, nome)
    eh_ultima = execucao.id == execucoes[0].id
    pode_revalidar = eh_ultima and eh_admin() and s.planos.existe(nome)
    return render_template('relatorio.html',
                           **relatorio.contexto(linhas, indice, det, execucao, eh_ultima, pode_revalidar,
                                                      email()))


@bp.get('/status')
def status():
    return json_(servicos().validador.status())


@bp.get('/pdf')
@bp.get('/webhook/pdf')
def pdf():
    nome = request.args.get('arquivo', '')
    if not pipeline.nome_valido(nome):
        return json_({'erro': 'Arquivo inválido'}, 400)
    return send_from_directory(servicos().cfg.planos_dir, nome, mimetype='application/pdf')


@bp.get('/planos')
def listar_planos():
    return json_({'planos': servicos().planos.listar()})
