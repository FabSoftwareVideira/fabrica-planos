from flask import Blueprint, request

from ..avaliacao import pipeline
from ..paginas import meus_planos
from ..servicos.planos import Ocupado, Proibido
from .comum import email, html, json_, ocupado, servicos

# "Meus planos": cada servidor entrega os próprios planos (a entrega oficial, que vai para a mesma pasta
# do NDE), acompanha a avaliação e pode substituí-los ou excluí-los. Não mexe nos planos dos outros.
bp = Blueprint('meus_planos', __name__, url_prefix='/meus-planos')


def _dono():
    return email() or 'local'  # sem login (uso local), todos os envios ficam com o mesmo dono


@bp.get('')
def pagina():
    return html(meus_planos.gerar_html(email(), servicos().cfg.pdf_max_mb))


@bp.get('/lista')
def listar():
    return json_({'planos': servicos().planos.do_professor(_dono())})


@bp.post('')
def enviar():
    arquivos = request.files.getlist('arquivos')
    if not arquivos:
        return json_({'erro': 'Nenhum arquivo enviado'}, 400)
    salvos, recusados = servicos().planos.enviar_do_professor(arquivos, _dono())
    return json_({'salvos': salvos, 'recusados': recusados}, 200 if salvos else 400)


@bp.delete('')
def excluir():
    nome = request.args.get('arquivo', '')
    if not pipeline.nome_valido(nome):
        return json_({'erro': 'Arquivo inválido'}, 400)
    try:
        servicos().planos.excluir_do_professor(nome, _dono())
    except Proibido:
        return json_({'erro': 'Você só pode excluir os planos que enviou'}, 403)
    except Ocupado:
        return ocupado()
    return json_({'excluido': nome})
