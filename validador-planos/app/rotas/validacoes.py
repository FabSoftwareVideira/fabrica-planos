import os
import tempfile
import zipfile

from flask import Blueprint, request, send_file, send_from_directory

from ..armazenamento import historico
from ..avaliacao import pipeline
from .comum import json_, servicos, texto

# Histórico das validações: resumo de cada uma, CSV, PDFs guardados e zip da última.
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


@bp.get('/<id_>/csv')
def baixar_csv(id_):
    execucao, erro = _execucao_ou_404(id_)
    if erro:
        return erro
    return send_file(execucao.csv_path, mimetype='text/csv', as_attachment=True,
                     download_name=f'validacao-{execucao.id}.csv')


@bp.get('/<id_>/pdf')
def pdf_da_validacao(id_):
    execucao, erro = _execucao_ou_404(id_)
    if erro:
        return erro
    nome = request.args.get('arquivo', '')
    if not pipeline.nome_valido(nome) or nome not in execucao.pdfs():
        return texto('O PDF dessa validação não está guardado (só a última guarda os PDFs).', 404)
    return send_from_directory(execucao.pdfs_dir, nome, mimetype='application/pdf')


@bp.get('/<id_>/pdfs.zip')
def baixar_zip(id_):
    execucao, erro = _execucao_ou_404(id_)
    if erro:
        return erro
    nomes = execucao.pdfs()
    if not nomes:
        return texto('Os PDFs são guardados só da última validação.', 404)
    # PDFs já são comprimidos: ZIP_STORED evita gastar CPU à toa.
    arquivo = tempfile.SpooledTemporaryFile(max_size=50 * 1024 * 1024)
    with zipfile.ZipFile(arquivo, 'w', zipfile.ZIP_STORED) as zip_:
        for nome in nomes:
            zip_.write(os.path.join(execucao.pdfs_dir, nome), nome)
    arquivo.seek(0)
    return send_file(arquivo, mimetype='application/zip', as_attachment=True,
                     download_name=f'planos-validacao-{execucao.id}.zip')
