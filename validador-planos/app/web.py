import logging
import os
import threading
import time
import unicodedata
from datetime import datetime, timedelta

from flask import Flask, Response, jsonify, redirect, request, send_from_directory

from . import csvsaida, dashboard, detalhes, pipeline, relatorio
from .andamento import Andamento
from .config import carregar

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


@app.post('/validar')
@app.post('/webhook/validar')
def validar():
    motivo = _iniciar_se_livre()
    if motivo == 'ocupado':
        return _ocupado()
    if motivo == 'sem_planos':
        return _json({'status': 'sem_planos', 'mensagem': 'Nenhum PDF encontrado na pasta de planos'}, 422)
    return _json({'status': 'iniciado'})


@app.get('/status')
def status():
    return _json(andamento.resumo())


@app.get('/dashboard')
@app.get('/webhook/dashboard')
def pagina_dashboard():
    linhas = csvsaida.ler_csv(cfg.csv_path)
    atualizado = ''
    if os.path.exists(cfg.csv_path):
        atualizado = datetime.fromtimestamp(os.path.getmtime(cfg.csv_path)).strftime('%d/%m/%Y %H:%M')
    return Response(dashboard.gerar_html(linhas, atualizado), mimetype='text/html; charset=utf-8')


@app.get('/relatorio')
def pagina_relatorio():
    nome = request.args.get('arquivo', '')
    linha = next((l for l in csvsaida.ler_csv(cfg.csv_path) if l.get('Arquivo') == nome), None)
    if not pipeline.nome_valido(nome) or linha is None:
        return Response('Plano não encontrado no resultado da última validação.', 404,
                        mimetype='text/plain; charset=utf-8')
    det = detalhes.ler(cfg.detalhes_dir, nome)
    return Response(relatorio.gerar_html(linha, det), mimetype='text/html; charset=utf-8')


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


@app.post('/planos')
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
            if not pipeline.nome_valido(nome) or nome.startswith('.'):
                recusados.append({'nome': nome, 'motivo': 'Nome inválido ou não termina em .pdf'})
                continue
            if arquivo.stream.read(5) != b'%PDF-':
                recusados.append({'nome': nome, 'motivo': 'O conteúdo não é um PDF'})
                continue
            arquivo.stream.seek(0)
            destino = os.path.join(cfg.planos_dir, nome)
            substituido = os.path.exists(destino)
            temporario = destino + '.enviando'
            arquivo.save(temporario)
            os.replace(temporario, destino)
            salvos.append({'nome': nome, 'substituido': substituido})
    logging.getLogger(__name__).info('Upload: %d salvo(s), %d recusado(s)', len(salvos), len(recusados))
    return _json({'salvos': salvos, 'recusados': recusados}, 200 if salvos else 400)


@app.delete('/planos')
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


if cfg.agendar:
    threading.Thread(target=_agendador, daemon=True).start()
