import logging
import os
import threading
import time
from datetime import datetime, timedelta

from flask import Flask, Response, jsonify, request, send_from_directory

from . import csvsaida, dashboard, lock, pipeline
from .config import carregar

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

cfg = carregar()
app = Flask(__name__)

# Serializa a checagem e a gravação do lock para que duas chamadas simultâneas não iniciem duas validações.
_inicio = threading.Lock()


def _json(obj, status=200):
    resp = jsonify(obj)
    resp.status_code = status
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp


def _iniciar_se_livre():
    """Devolve None se iniciou a validação, ou um motivo ('ocupado' / 'sem_planos')."""
    with _inicio:
        if lock.ocupado(cfg.lock_path):
            return 'ocupado'
        if not pipeline.listar_pdfs(cfg.planos_dir):
            return 'sem_planos'
        lock.atualizar(cfg.lock_path)
        threading.Thread(target=pipeline.executar, args=(cfg,), daemon=True).start()
        return None


@app.post('/validar')
def validar():
    motivo = _iniciar_se_livre()
    if motivo == 'ocupado':
        return _json({'status': 'ocupado', 'mensagem': 'Já existe uma validação em andamento'}, 409)
    if motivo == 'sem_planos':
        return _json({'status': 'sem_planos', 'mensagem': 'Nenhum PDF encontrado na pasta de planos'}, 422)
    return _json({'status': 'iniciado'})


@app.get('/dashboard')
def pagina_dashboard():
    linhas = csvsaida.ler_csv(cfg.csv_path)
    atualizado = ''
    if os.path.exists(cfg.csv_path):
        atualizado = datetime.fromtimestamp(os.path.getmtime(cfg.csv_path)).strftime('%d/%m/%Y %H:%M')
    return Response(dashboard.gerar_html(linhas, atualizado), mimetype='text/html; charset=utf-8')


@app.get('/pdf')
def pdf():
    nome = request.args.get('arquivo', '')
    if not pipeline.nome_valido(nome):
        return _json({'erro': 'Arquivo inválido'}, 400)
    return send_from_directory(cfg.planos_dir, nome, mimetype='application/pdf')


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
