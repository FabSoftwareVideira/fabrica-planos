import logging

from flask import Blueprint, redirect, render_template, request, send_from_directory

from ..armazenamento.usuarios import PAPEIS_CURSO
from ..avaliacao import pipeline
from ..paginas import administracao, backup as backup_pagina, usuarios
from ..servicos.backup import BackupInvalido, BackupOcupado
from ..servicos.planos import NaoEncontrado, Ocupado, Proibido
from .comum import eh_admin, email, json_, mesma_origem, ocupado, servicos, somente_admin, texto

log = logging.getLogger(__name__)

# Só administradores (ADMIN_EMAILS): disparar validações, enviar PDFs, excluir os que enviaram (ou sem dono),
# ocultar do painel os de outras pessoas, ativar/desativar usuários e dar os papéis de coordenação/NDE/NDB.
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
                            request.args.get('aviso', ''), s.planos.cursos())
    return render_template('usuarios.html', **ctx)


@bp.get('/administracao/backup')
def pagina_backup():
    if not eh_admin():
        return redirect('/dashboard')
    return render_template('backup.html', aviso=request.args.get('aviso', ''),
                           **backup_pagina.contexto(servicos().backup))


@bp.post('/administracao/backup')
def criar_backup():
    if not eh_admin():
        return redirect('/dashboard')
    if not mesma_origem():
        return 'Origem inválida', 403
    if not servicos().backup.iniciar('manual'):
        return redirect('/administracao/backup?aviso=ocupado', 303)
    return redirect('/administracao/backup?aviso=iniciado', 303)


@bp.get('/administracao/backup/<nome>')
def baixar_backup(nome):
    if not eh_admin():
        return redirect('/dashboard')
    servico = servicos().backup
    if not servico.caminho(nome):
        return texto('Backup não encontrado.', 404)
    return send_from_directory(servico.dir, nome, as_attachment=True, download_name=nome)


@bp.post('/administracao/backup/<nome>/restaurar')
def restaurar_backup(nome):
    if not eh_admin():
        return redirect('/dashboard')
    if not mesma_origem():
        return 'Origem inválida', 403
    try:
        servicos().backup.restaurar(nome)
    except BackupOcupado:
        aviso = 'ocupado'
    except BackupInvalido:
        aviso = 'invalido'
    except OSError:
        log.exception('Falha ao restaurar o backup %s', nome)
        aviso = 'erro'
    except Exception:  # nunca deixa a tela de administração com um erro 500
        log.exception('Falha inesperada ao restaurar o backup %s', nome)
        aviso = 'erro'
    else:
        aviso = 'restaurado'
    return redirect(f'/administracao/backup?aviso={aviso}', 303)


@bp.post('/administracao/backup/<nome>/excluir')
def excluir_backup(nome):
    if not eh_admin():
        return redirect('/dashboard')
    if not mesma_origem():
        return 'Origem inválida', 403
    aviso = 'excluido' if servicos().backup.excluir(nome) else 'inexistente'
    return redirect(f'/administracao/backup?aviso={aviso}', 303)


@bp.post('/administracao/usuarios/ativo')
def alterar_ativo():
    if not eh_admin():
        return redirect('/dashboard')
    voltar = request.form.get('voltar', '')
    if not voltar.startswith('/administracao/usuarios'):
        voltar = '/administracao/usuarios'
    separador = '&' if '?' in voltar else '?'
    if not mesma_origem():
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


@bp.post('/administracao/usuarios/papel')
def alterar_papel():
    """Dá ou tira de um usuário o papel de coordenação, NDE ou NDB num curso (quem pode revisar os planos dele)."""
    if not eh_admin():
        return redirect('/dashboard')
    voltar = request.form.get('voltar', '')
    if not voltar.startswith('/administracao/usuarios'):
        voltar = '/administracao/usuarios'
    separador = '&' if '?' in voltar else '?'
    if not mesma_origem():
        return 'Origem inválida', 403
    s = servicos()
    alvo = (request.form.get('email') or '').strip().lower()
    curso = (request.form.get('curso') or '').strip().upper()
    papel = request.form.get('papel', '')
    if request.form.get('acao') == 'remover':
        aviso = 'papel_removido' if s.usuarios.remover_papel(alvo, curso, papel) else 'papel_invalido'
    elif papel not in PAPEIS_CURSO or curso not in s.planos.cursos():
        aviso = 'papel_invalido'
    elif not s.usuarios.adicionar_papel(alvo, curso, papel):
        aviso = 'inexistente'
    else:
        aviso = 'papel_adicionado'
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


@bp.delete('/planos')
@somente_admin
def excluir_plano():
    """Exclui o PDF e a avaliação dele; só os planos que o administrador enviou ou sem dono."""
    nome = request.args.get('arquivo', '')
    if not pipeline.nome_valido(nome):
        return json_({'erro': 'Arquivo inválido'}, 400)
    try:
        servicos().planos.excluir(nome, email())
    except Ocupado:
        return ocupado()
    except NaoEncontrado:
        return json_({'erro': 'Arquivo não encontrado'}, 404)
    except Proibido:
        return json_({'erro': 'Você só pode excluir os planos que enviou; os de outras pessoas podem ser '
                              'ocultados do painel'}, 403)
    return json_({'excluido': nome})


@bp.post('/planos/ocultar')
@somente_admin
def ocultar_plano():
    """Tira o plano do painel sem apagar o PDF nem a avaliação (DELETE volta a mostrar)."""
    nome = request.args.get('arquivo', '')
    if not pipeline.nome_valido(nome):
        return json_({'erro': 'Arquivo inválido'}, 400)
    try:
        servicos().planos.ocultar(nome, email())
    except NaoEncontrado:
        return json_({'erro': 'Arquivo não encontrado'}, 404)
    return json_({'oculto': nome})


@bp.delete('/planos/ocultar')
@somente_admin
def mostrar_plano():
    nome = request.args.get('arquivo', '')
    if not pipeline.nome_valido(nome):
        return json_({'erro': 'Arquivo inválido'}, 400)
    servicos().planos.mostrar(nome, email())
    return json_({'mostrado': nome})
