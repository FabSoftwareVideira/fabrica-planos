from urllib.parse import quote

from flask import Blueprint, redirect, render_template, request, send_from_directory

from ..armazenamento import csvsaida, detalhes, historico
from ..avaliacao import identificacao, pipeline
from ..paginas import dashboard, relatorio
from ..servicos import revisao
from .comum import eh_admin, email, json_, mesma_origem, nome as nome_usuario, pode_exportar, servicos, texto

# Consulta (qualquer servidor logado): dashboard, relatório de um plano, andamento e PDFs da pasta.
# Os caminhos /webhook/... mantêm compatíveis a página validacao.html e os links antigos do n8n.
bp = Blueprint('painel', __name__)


def resultado_atual():
    """A validação atual (só ela é guardada), ou None se nenhuma terminou ainda."""
    execucoes = historico.listar(servicos().cfg.historico_dir)
    return execucoes[0] if execucoes else None


def dados_da_validacao():
    """Validação atual, linhas do CSV e, por arquivo, identificação (curso e período), docentes e resumo
    da revisão vigente. Usados pelo dashboard e pela visão da coordenação."""
    execucao = resultado_atual()
    linhas = csvsaida.ler_csv(execucao.csv_path) if execucao else []
    ocultos = servicos().planos.nomes_ocultos()  # tirados do painel pelo administrador (PDF e avaliação ficam)
    linhas = [l for l in linhas if l.get('Arquivo') not in ocultos]
    # Curso, período e docentes de cada plano, lidos do texto guardado nos detalhes.
    dets = {l.get('Arquivo'): detalhes.ler(execucao.detalhes_dir, l.get('Arquivo')) for l in linhas}
    idents = {nome: identificacao.de_detalhes(det) for nome, det in dets.items()}
    docentes = {nome: identificacao.docentes((det or {}).get('texto', '')) for nome, det in dets.items()}
    revisoes = {nome: revisao.resumo(r) for nome, r in servicos().revisao.vigentes().items()}
    return execucao, linhas, idents, docentes, revisoes


def revisaveis(idents):
    """Planos que quem está vendo pode revisar (tem papel no curso deles e não os enviou)."""
    return {nome for nome, ident in idents.items() if servicos().revisao.papel(email(), ident, nome)}


@bp.get('/dashboard')
@bp.get('/webhook/dashboard')
def pagina_dashboard():
    cfg = servicos().cfg
    execucao, linhas, idents, docentes, revisoes = dados_da_validacao()
    # Nos planos que pode revisar, o card ganha o botão Revisar.
    return render_template('dashboard.html', **dashboard.contexto(
        linhas, cfg.pdf_max_mb, execucao, email(), eh_admin(), idents, docentes, revisoes,
        exportar=pode_exportar(), revisaveis=revisaveis(idents)))


@bp.get('/relatorio')
def pagina_relatorio():
    s = servicos()
    nome = request.args.get('arquivo', '')
    execucao = resultado_atual()
    if execucao is None:
        return texto('Nenhuma validação concluída ainda.', 404)
    linhas = csvsaida.ler_csv(execucao.csv_path)
    indice = next((i for i, l in enumerate(linhas) if l.get('Arquivo') == nome), None)
    if not pipeline.nome_valido(nome) or indice is None:
        return texto('Plano não encontrado na validação atual.', 404)
    det = detalhes.ler(execucao.detalhes_dir, nome)
    pode_revalidar = eh_admin() and s.planos.existe(nome)
    ident = identificacao.de_detalhes(det)
    ctx = relatorio.contexto(linhas, indice, det, execucao, pode_revalidar, email())
    ctx.update(relatorio.contexto_revisao(revisao.resumo(s.revisao.vigente(nome)), s.revisao.papel(email(), ident, nome),
                                          ident, request.args.get('aviso', ''), s.revisao.eh_autor(email(), nome)))
    return render_template('relatorio.html', **ctx)


@bp.post('/revisao')
def revisar():
    """Parecer da coordenação, do NDE ou do NDB sobre a avaliação da IA de um plano (ou desfazê-lo)."""
    if not mesma_origem():
        return texto('Origem inválida', 403)
    s = servicos()
    nome = request.form.get('arquivo', '')
    execucao = resultado_atual()
    linhas = csvsaida.ler_csv(execucao.csv_path) if execucao else []
    linha = next((l for l in linhas if l.get('Arquivo') == nome), None)
    if not pipeline.nome_valido(nome) or linha is None:
        return texto('Plano não encontrado na validação atual.', 404)
    ident = identificacao.de_detalhes(detalhes.ler(execucao.detalhes_dir, nome))
    usuario = email() or 'local'
    if s.revisao.eh_autor(usuario, nome):
        return texto('Você enviou este plano e não pode revisá-lo; o parecer fica com outro membro da '
                     'coordenação, do NDE ou do NDB.', 403)
    try:
        if request.form.get('acao') == 'desfazer':
            s.revisao.desfazer(nome, usuario, ident)
            aviso = 'desfeita'
        else:
            nome_revisor = nome_usuario() or (s.usuarios.obter(usuario) or {}).get('nome', '')
            s.revisao.registrar(nome, usuario, nome_revisor, ident, request.form.get('status', ''),
                                request.form.get('comentario', ''), linha.get('Status Geral', ''))
            aviso = 'salva'
    except revisao.Proibido:
        return texto('Só a coordenação, o NDE ou o NDB do curso do plano podem revisá-lo.', 403)
    except revisao.Invalido:
        aviso = 'incompleta'
    return redirect(f'/relatorio?arquivo={quote(nome)}&aviso={aviso}#revisao', 303)


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
    pasta = servicos().planos
    planos = pasta.listar()
    for plano in planos:  # o botão Excluir só nos planos que quem vê pode excluir; nos demais, Ocultar
        plano['pode_excluir'] = eh_admin() and pasta.pode_excluir(plano['nome'], email())
    return json_({'planos': planos})
