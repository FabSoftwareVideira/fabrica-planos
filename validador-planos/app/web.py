import logging
import os
import tempfile
import threading
import time
import unicodedata
import zipfile
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, Response, jsonify, redirect, request, send_file, send_from_directory

from . import csvsaida, dashboard, detalhes, historico, pipeline, relatorio
from .andamento import Andamento
from .config import carregar
from .extrator import PdfIlegivel, extrair_texto

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

cfg = carregar()
andamento = Andamento()
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # soma dos PDFs de um envio

# Serializa o início da validação e as alterações na pasta de planos: não se mexe nos PDFs
# enquanto um lote está sendo validado.
_operacao = threading.Lock()


def _json(obj, status=200):
    resp = jsonify(obj)
    resp.status_code = status
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp


def _ocupado():
    return _json({'status': 'ocupado', 'mensagem': 'Já existe uma validação em andamento'}, 409)


def _email():
    """E-mail de quem fez login, repassado pelo proxy; vazio sem login."""
    return (request.headers.get('X-Usuario-Email') or '').strip().lower()


def _eh_admin():
    return not cfg.exigir_login or _email() in cfg.admins


@app.before_request
def _exigir_login():
    # O proxy só deixa passar quem fez login; isto barra quem chegar ao app sem passar por ele.
    if cfg.exigir_login and not _email() and request.path != '/health':
        return _texto('Login necessário.', 401)


def _somente_admin(rota):
    """Envio, exclusão e validação ficam com os e-mails de ADMIN_EMAILS; os demais só consultam."""
    @wraps(rota)
    def verificar(*args, **kwargs):
        if not _eh_admin():
            return _json({'erro': 'Apenas administradores podem fazer isso'}, 403)
        return rota(*args, **kwargs)
    return verificar


def _iniciar_se_livre():
    """Devolve None se iniciou a validação, ou um motivo ('ocupado' / 'sem_planos')."""
    with _operacao:
        nomes = pipeline.listar_pdfs(cfg.planos_dir)
        if not nomes:
            return 'sem_planos'
        if not andamento.iniciar(len(nomes)):
            return 'ocupado'
        threading.Thread(target=pipeline.executar, args=(cfg, andamento, nomes), daemon=True).start()
        return None


# Os caminhos /webhook/... mantêm compatíveis a página validacao.html e os links antigos do n8n.
@app.get('/')
def raiz():
    return redirect('/dashboard')


def _revalidar_se_livre(nome):
    with _operacao:
        if not os.path.isfile(os.path.join(cfg.planos_dir, nome)):
            return 'sem_arquivo'
        if not andamento.iniciar(1, unico=nome):
            return 'ocupado'
        threading.Thread(target=pipeline.revalidar, args=(cfg, andamento, nome), daemon=True).start()
        return None


@app.post('/validar')
@app.post('/webhook/validar')
@_somente_admin
def validar():
    nome = request.args.get('arquivo')
    if nome is not None:  # revalidar só este plano, atualizando a última validação
        if not pipeline.nome_valido(nome):
            return _json({'erro': 'Arquivo inválido'}, 400)
        motivo = _revalidar_se_livre(nome)
        if motivo == 'sem_arquivo':
            return _json({'status': 'sem_arquivo',
                          'mensagem': 'Esse PDF não está mais na pasta de planos; envie-o de novo para revalidar'}, 404)
        return _ocupado() if motivo else _json({'status': 'iniciado', 'arquivo': nome})
    motivo = _iniciar_se_livre()
    if motivo == 'ocupado':
        return _ocupado()
    if motivo == 'sem_planos':
        return _json({'status': 'sem_planos', 'mensagem': 'Nenhum PDF encontrado na pasta de planos'}, 422)
    return _json({'status': 'iniciado'})


@app.get('/status')
def status():
    return _json(andamento.resumo())


def _texto(mensagem, status):
    return Response(mensagem, status, mimetype='text/plain; charset=utf-8')


def _execucao_pedida(execucoes):
    """A execução do parâmetro ?validacao= (padrão: a mais recente). None se o id não existir."""
    id_ = request.args.get('validacao')
    if not id_:
        return execucoes[0] if execucoes else None
    return next((e for e in execucoes if e.id == id_), None)


@app.get('/dashboard')
@app.get('/webhook/dashboard')
def pagina_dashboard():
    execucoes = historico.listar(cfg.historico_dir)
    execucao = _execucao_pedida(execucoes)
    if request.args.get('validacao') and execucao is None:
        return redirect('/dashboard')  # validação que saiu do histórico
    linhas = csvsaida.ler_csv(execucao.csv_path) if execucao else []
    html = dashboard.gerar_html(linhas, cfg.pdf_max_mb, execucoes, execucao, _email(), _eh_admin())
    return Response(html, mimetype='text/html; charset=utf-8')


@app.get('/relatorio')
def pagina_relatorio():
    nome = request.args.get('arquivo', '')
    execucoes = historico.listar(cfg.historico_dir)
    execucao = _execucao_pedida(execucoes)
    if execucao is None:
        return _texto('Validação não encontrada no histórico.', 404)
    linhas = csvsaida.ler_csv(execucao.csv_path)
    indice = next((i for i, l in enumerate(linhas) if l.get('Arquivo') == nome), None)
    if not pipeline.nome_valido(nome) or indice is None:
        return _texto('Plano não encontrado nessa validação.', 404)
    det = detalhes.ler(execucao.detalhes_dir, nome)
    eh_ultima = execucao.id == execucoes[0].id
    pode_revalidar = eh_ultima and _eh_admin() and os.path.isfile(os.path.join(cfg.planos_dir, nome))
    html = relatorio.gerar_html(linhas, indice, det, execucao, eh_ultima, pode_revalidar)
    return Response(html, mimetype='text/html; charset=utf-8')


@app.get('/validacoes')
def listar_validacoes():
    return _json({'validacoes': [{**e.meta(), 'pdfs': len(e.pdfs())} for e in historico.listar(cfg.historico_dir)]})


def _execucao_ou_404(id_):
    execucao = historico.obter(cfg.historico_dir, id_)
    if execucao is None:
        return None, _texto('Validação não encontrada no histórico.', 404)
    return execucao, None


@app.get('/validacoes/<id_>/csv')
def baixar_csv(id_):
    execucao, erro = _execucao_ou_404(id_)
    if erro:
        return erro
    return send_file(execucao.csv_path, mimetype='text/csv', as_attachment=True,
                     download_name=f'validacao-{execucao.id}.csv')


@app.get('/validacoes/<id_>/pdf')
def pdf_da_validacao(id_):
    execucao, erro = _execucao_ou_404(id_)
    if erro:
        return erro
    nome = request.args.get('arquivo', '')
    if not pipeline.nome_valido(nome) or nome not in execucao.pdfs():
        return _texto('O PDF dessa validação não está guardado (só a última guarda os PDFs).', 404)
    return send_from_directory(execucao.pdfs_dir, nome, mimetype='application/pdf')


@app.get('/validacoes/<id_>/pdfs.zip')
def baixar_zip(id_):
    execucao, erro = _execucao_ou_404(id_)
    if erro:
        return erro
    nomes = execucao.pdfs()
    if not nomes:
        return _texto('Os PDFs são guardados só da última validação.', 404)
    # PDFs já são comprimidos: ZIP_STORED evita gastar CPU à toa.
    arquivo = tempfile.SpooledTemporaryFile(max_size=50 * 1024 * 1024)
    with zipfile.ZipFile(arquivo, 'w', zipfile.ZIP_STORED) as zip_:
        for nome in nomes:
            zip_.write(os.path.join(execucao.pdfs_dir, nome), nome)
    arquivo.seek(0)
    return send_file(arquivo, mimetype='application/zip', as_attachment=True,
                     download_name=f'planos-validacao-{execucao.id}.zip')


@app.get('/pdf')
@app.get('/webhook/pdf')
def pdf():
    nome = request.args.get('arquivo', '')
    if not pipeline.nome_valido(nome):
        return _json({'erro': 'Arquivo inválido'}, 400)
    return send_from_directory(cfg.planos_dir, nome, mimetype='application/pdf')


@app.get('/planos')
def listar_planos():
    planos = []
    for nome in pipeline.listar_pdfs(cfg.planos_dir):
        info = os.stat(os.path.join(cfg.planos_dir, nome))
        planos.append({
            'nome': nome,
            'tamanho': info.st_size,
            'modificado': datetime.fromtimestamp(info.st_mtime).isoformat(timespec='seconds'),
        })
    return _json({'planos': planos})


def _nome_enviado(arquivo):
    # Navegadores antigos mandam o caminho completo; o macOS manda acentos decompostos (NFD).
    nome = (arquivo.filename or '').replace('\\', '/').rsplit('/', 1)[-1].strip()
    return unicodedata.normalize('NFC', nome)


def _tamanho(arquivo):
    arquivo.stream.seek(0, os.SEEK_END)
    tamanho = arquivo.stream.tell()
    arquivo.stream.seek(0)
    return tamanho


def _motivo_recusa(nome, arquivo):
    """Checagens que não precisam gravar o arquivo; devolve o motivo da recusa ou None."""
    if not pipeline.nome_valido(nome) or nome.startswith('.'):
        return 'Apenas arquivos .pdf são aceitos'
    if _tamanho(arquivo) > cfg.pdf_max_mb * 1024 * 1024:
        return f'Arquivo maior que {cfg.pdf_max_mb} MB'
    if arquivo.stream.read(5) != b'%PDF-':
        return 'O conteúdo não é um PDF'
    arquivo.stream.seek(0)
    return None


@app.post('/planos')
@_somente_admin
def enviar_planos():
    arquivos = request.files.getlist('arquivos')
    if not arquivos:
        return _json({'erro': 'Nenhum arquivo enviado'}, 400)
    with _operacao:
        if andamento.rodando:
            return _ocupado()
        salvos, recusados = [], []
        for arquivo in arquivos:
            nome = _nome_enviado(arquivo)
            motivo = _motivo_recusa(nome, arquivo)
            if motivo:
                recusados.append({'nome': nome, 'motivo': motivo})
                continue
            destino = os.path.join(cfg.planos_dir, nome)
            temporario = destino + '.enviando'
            arquivo.save(temporario)
            # Só entra na pasta o PDF que abre e tem texto; digitalizados precisam de OCR antes.
            try:
                extrair_texto(temporario)
            except PdfIlegivel as erro:
                os.remove(temporario)
                recusados.append({'nome': nome, 'motivo': str(erro)})
                continue
            substituido = os.path.exists(destino)
            os.replace(temporario, destino)
            salvos.append({'nome': nome, 'substituido': substituido})
    logging.getLogger(__name__).info('Upload: %d salvo(s), %d recusado(s)', len(salvos), len(recusados))
    return _json({'salvos': salvos, 'recusados': recusados}, 200 if salvos else 400)


@app.delete('/planos')
@_somente_admin
def excluir_plano():
    nome = request.args.get('arquivo', '')
    if not pipeline.nome_valido(nome):
        return _json({'erro': 'Arquivo inválido'}, 400)
    with _operacao:
        if andamento.rodando:
            return _ocupado()
        caminho = os.path.join(cfg.planos_dir, nome)
        if not os.path.isfile(caminho):
            return _json({'erro': 'Arquivo não encontrado'}, 404)
        os.remove(caminho)
    logging.getLogger(__name__).info('Plano excluído: %s', nome)
    return _json({'excluido': nome})


@app.delete('/planos/todos')
@_somente_admin
def excluir_todos():
    """Esvazia a pasta de planos. O histórico (e os PDFs da última validação, para o zip) continuam."""
    with _operacao:
        if andamento.rodando:
            return _ocupado()
        nomes = pipeline.listar_pdfs(cfg.planos_dir)
        for nome in nomes:
            os.remove(os.path.join(cfg.planos_dir, nome))
    logging.getLogger(__name__).info('Todos os planos excluídos: %d arquivo(s)', len(nomes))
    return _json({'excluidos': len(nomes)})


@app.errorhandler(413)
def grande_demais(_erro):
    limite = app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)
    return _json({'erro': f'Envio maior que {limite} MB; mande menos arquivos por vez'}, 413)


@app.get('/health')
def health():
    return _json({'status': 'ok'})


def _agendador():
    """Dispara a validação todo dia na hora configurada, se não houver outra em andamento."""
    while True:
        agora = datetime.now()
        alvo = agora.replace(hour=cfg.hora_agendada, minute=0, second=0, microsecond=0)
        if alvo <= agora:
            alvo += timedelta(days=1)
        time.sleep((alvo - agora).total_seconds())
        motivo = _iniciar_se_livre()
        if motivo:
            logging.getLogger(__name__).info('Validação agendada não iniciada: %s', motivo)


def _preparar_historico():
    # Ao subir não há validação rodando: dá para migrar o resultado da versão anterior e limpar sobras.
    try:
        historico.migrar_legado(cfg.historico_dir, cfg.csv_path, os.path.join(cfg.resultados_dir, 'detalhes'),
                                csvsaida.ler_csv)
        historico.podar(cfg.historico_dir, cfg.historico_max)
        lock_antigo = os.path.join(cfg.resultados_dir, 'validacao.lock')  # da versão com lock em arquivo
        if os.path.exists(lock_antigo):
            os.remove(lock_antigo)
    except OSError:
        logging.getLogger(__name__).exception('Falha ao preparar o histórico de validações')


_preparar_historico()

if cfg.agendar:
    threading.Thread(target=_agendador, daemon=True).start()
