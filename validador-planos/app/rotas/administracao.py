from urllib.parse import urlsplit

from flask import Blueprint, redirect, render_template, request

from ..avaliacao import pipeline
from ..paginas import administracao, usuarios
from ..servicos.planos import NaoEncontrado, Ocupado
from .comum import eh_admin, email, json_, ocupado, servicos, somente_admin

# Só administradores (ADMIN_EMAILS): disparar validações, enviar/excluir quaisquer PDFs da pasta e
# ativar/desativar usuários.
bp = Blueprint('administracao', __name__)


@bp.get('/administracao')
def pagina():
    if not eh_admin():  # quem só consulta vai para os resultados
        return redirect('/dashboard')
    return render_template('administracao.html', **administracao.contexto(email(), servicos().cfg.pdf_max_mb))


@bp.get('/administracao/usuarios')
def pagina_usuarios():
    if not eh_admin():
        return redirect('/dashboard')
    s = servicos()
    ctx = usuarios.contexto(s.usuarios, s.cfg.admins, usuarios.filtros(request.args), email(),
                            request.args.get('aviso', ''))
    return render_template('usuarios.html', **ctx)


def _mesma_origem():
    """Formulário enviado por esta aplicação (o navegador manda Origin nos POSTs)."""
    origem = request.headers.get('Origin')
    return not origem or urlsplit(origem).netloc == request.host


@bp.post('/administracao/usuarios/ativo')
def alterar_ativo():
    if not eh_admin():
        return redirect('/dashboard')
    voltar = request.form.get('voltar', '')
    if not voltar.startswith('/administracao/usuarios'):
        voltar = '/administracao/usuarios'
    separador = '&' if '?' in voltar else '?'
    if not _mesma_origem():
        return 'Origem inválida', 403
    s = servicos()
    alvo = (request.form.get('email') or '').strip().lower()
    ativo = request.form.get('ativo') == '1'
    if not ativo and alvo in s.cfg.admins:
        aviso = 'admin'  # quem está em ADMIN_EMAILS não pode ser desativado (evita trancar o sistema)
    elif not s.usuarios.definir_ativo(alvo, ativo):
        aviso = 'inexistente'
    else:
        aviso = 'ativado' if ativo else 'desativado'
    return redirect(f'{voltar}{separador}aviso={aviso}', 303)


@bp.post('/validar')
@bp.post('/webhook/validar')
@somente_admin
def validar():
    s = servicos()
    nome = request.args.get('arquivo')
    if nome is not None:  # revalidar só este plano, atualizando a última validação
        if not pipeline.nome_valido(nome):
            return json_({'erro': 'Arquivo inválido'}, 400)
        if not s.planos.existe(nome):
            return json_({'status': 'sem_arquivo',
                          'mensagem': 'Esse PDF não está mais na pasta de planos; envie-o de novo para revalidar'}, 404)
        posicao = s.validador.enfileirar(nome)  # com outra validação rodando, espera a vez em vez de recusar
        return json_({'status': 'na_fila' if posicao else 'iniciado', 'arquivo': nome, 'posicao': posicao})
    motivo = s.validador.iniciar_lote()
    if motivo == 'ocupado':
        return ocupado()
    if motivo == 'sem_planos':
        return json_({'status': 'sem_planos', 'mensagem': 'Nenhum PDF encontrado na pasta de planos'}, 422)
    return json_({'status': 'iniciado'})


@bp.post('/planos')
@somente_admin
def enviar_planos():
    arquivos = request.files.getlist('arquivos')
    if not arquivos:
        return json_({'erro': 'Nenhum arquivo enviado'}, 400)
    try:
        salvos, recusados = servicos().planos.enviar(arquivos)
    except Ocupado:
        return ocupado()
    return json_({'salvos': salvos, 'recusados': recusados}, 200 if salvos else 400)


@bp.delete('/planos')
@somente_admin
def excluir_plano():
    nome = request.args.get('arquivo', '')
    if not pipeline.nome_valido(nome):
        return json_({'erro': 'Arquivo inválido'}, 400)
    try:
        servicos().planos.excluir(nome)
    except Ocupado:
        return ocupado()
    except NaoEncontrado:
        return json_({'erro': 'Arquivo não encontrado'}, 404)
    return json_({'excluido': nome})


@bp.delete('/planos/todos')
@somente_admin
def excluir_todos():
    try:
        return json_({'excluidos': servicos().planos.excluir_todos()})
    except Ocupado:
        return ocupado()
