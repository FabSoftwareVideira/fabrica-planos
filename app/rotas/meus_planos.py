from flask import Blueprint, render_template, request

from ..avaliacao import pipeline
from ..paginas import meus_planos
from ..servicos import assinatura, revisao
from ..servicos.planos import Ocupado, Proibido
from .comum import email, json_, nome as nome_usuario, ocupado, servicos

# "Meus planos": cada servidor entrega os próprios planos (a entrega oficial, que vai para a mesma pasta
# do NDE), acompanha a avaliação e pode substituí-los ou excluí-los. Não mexe nos planos dos outros.
bp = Blueprint('meus_planos', __name__, url_prefix='/meus-planos')


def _dono():
    return email() or 'local'  # sem login (uso local), todos os envios ficam com o mesmo dono


@bp.get('')
def pagina():
    return render_template('meus_planos.html', **meus_planos.contexto(email(), servicos().cfg.pdf_max_mb))


@bp.get('/lista')
def listar():
    s = servicos()
    planos = s.planos.do_professor(_dono())
    vigentes = s.revisao.vigentes()
    for plano in planos:  # parecer da coordenação/NDE/NDB, que vale sobre a avaliação da IA
        plano['revisao'] = revisao.resumo(vigentes.get(plano['nome']))
        # Aprovado na revisão: o professor assina pelo gov.br e envia o PDF assinado
        plano['assinatura'] = assinatura.resumo(s.assinaturas.vigente(plano['nome']))
        plano['pode_assinar'] = s.assinaturas.liberado(plano['nome'], _dono())
    return json_({'planos': planos})


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


@bp.post('/assinatura')
def enviar_assinado():
    """PDF do plano aprovado, assinado pelo professor no assinador do gov.br (ver servicos/assinatura.py)."""
    s = servicos()
    nome = request.form.get('arquivo', '')
    pdf = request.files.get('pdf')
    if not pipeline.nome_valido(nome) or pdf is None:
        return json_({'erro': 'Envie o PDF assinado do plano'}, 400)
    dados = pdf.stream.read(s.cfg.pdf_max_mb * 1024 * 1024 + 1)
    if len(dados) > s.cfg.pdf_max_mb * 1024 * 1024:
        return json_({'erro': f'Arquivo maior que {s.cfg.pdf_max_mb} MB'}, 400)
    if not dados.startswith(b'%PDF-'):
        return json_({'erro': 'O conteúdo não é um PDF'}, 400)
    usuario = _dono()
    try:
        registro = s.assinaturas.registrar(nome, usuario, nome_usuario() or (s.usuarios.obter(usuario) or {}).get('nome', ''),
                                           dados)
    except assinatura.NaoLiberado:
        return json_({'erro': 'Só quem enviou o plano o assina, e só depois de aprovado na revisão da '
                              'coordenação, do NDE ou do NDB'}, 403)
    except assinatura.AssinaturaInvalida as erro:
        return json_({'erro': str(erro)}, 422)
    return json_({'assinatura': assinatura.resumo(registro)})
