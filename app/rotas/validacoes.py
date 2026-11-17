from flask import Blueprint, request, send_from_directory

from ..armazenamento import historico
from ..avaliacao import pipeline
from .comum import json_, servicos, texto

# Histórico das validações: resumo de cada uma e os PDFs guardados da última. A exportação (zip dos planos
# assinados) fica na coordenação (rotas/coordenacao.py).
bp = Blueprint('validacoes', __name__, url_prefix='/validacoes')


def _execucao_ou_404(id_):
    execucao = historico.obter(servicos().cfg.historico_dir, id_)
    if execucao is None:
        return None, texto('Validação não encontrada no histórico.', 404)
    return execucao, None


@bp.get('')
def listar_validacoes():
    execucoes = historico.listar(servicos().cfg.historico_dir)
    return json_({'validacoes': [{**e.meta(), 'pdfs': len(e.pdfs())} for e in execucoes]})


@bp.get('/<id_>/pdf')
def pdf_da_validacao(id_):
    execucao, erro = _execucao_ou_404(id_)
    if erro:
        return erro
    nome = request.args.get('arquivo', '')
    if not pipeline.nome_valido(nome) or nome not in execucao.pdfs():
        return texto('O PDF dessa validação não está guardado (só a última guarda os PDFs).', 404)
    return send_from_directory(execucao.pdfs_dir, nome, mimetype='application/pdf')
