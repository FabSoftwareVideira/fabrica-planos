import logging

import os

from flask import Blueprint, render_template, request, send_file

from ..avaliacao import pipeline
from ..paginas import meus_planos
from ..servicos import assinatura, revisao
from ..servicos.planos import NaoEncontrado, Ocupado, Proibido, Protegido, Recusado, versao_protegida
from .comum import email, json_, nome as nome_usuario, ocupado, servicos, texto

# "Meus planos": cada professor vê as disciplinas em que a coordenação o vinculou como docente e entrega
# o plano de cada uma (a entrega oficial, que vai para a mesma pasta do NDE), acompanha a avaliação e pode
# atualizá-lo (mesmo assinado: a versão anterior vai para o histórico) ou excluí-lo. Sem disciplina vinculada,
# não há onde enviar plano.
log = logging.getLogger(__name__)
bp = Blueprint('meus_planos', __name__, url_prefix='/meus-planos')


def _dono():
    return email() or 'local'  # sem login (uso local), todos os envios ficam com o mesmo dono


@bp.get('')
def pagina():
    cfg = servicos().cfg
    return render_template('meus_planos.html', **meus_planos.contexto(
        email(), cfg.pdf_max_mb, cfg.assinatura_api_ativa, homologacao=cfg.assinatura_ambiente == 'homologacao'))


@bp.get('/lista')
def listar():
    s = servicos()
    planos = s.planos.do_professor(_dono())
    vigentes = s.revisao.vigentes()
    nomes = [p['nome'] for p in planos]
    versoes = s.planos.versoes.de_varios(nomes) if s.planos.versoes else {}
    ultimos = s.planos.versoes.ultimos_numeros(nomes) if s.planos.versoes else {}
    for plano in planos:  # parecer da coordenação/NDE/NDB, que vale sobre a avaliação da IA
        plano['revisao'] = revisao.resumo(vigentes.get(plano['nome']))
        # Aprovado na revisão: o professor assina pelo gov.br e envia o PDF assinado
        plano['assinatura'] = assinatura.resumo(s.assinaturas.vigente(plano['nome']))
        plano['pode_assinar'] = s.assinaturas.liberado(plano['nome'], _dono())
        # Versões anteriores (a atual é a seguinte à última arquivada, mesmo que ela tenha sido excluída)
        plano['versoes'] = versoes.get(plano['nome'], [])
        for v in plano['versoes']:  # aprovada e assinada: fica guardada
            v['protegida'] = versao_protegida(v)
        plano['versao'] = ultimos.get(plano['nome'], 0) + 1 if plano['tem_plano'] else None
    return json_({'planos': planos})


@bp.get('/versao')
def baixar_versao():
    """PDF de uma versão anterior do plano (?arquivo=, ?numero=; ?assinado=1 para o assinado)."""
    s = servicos()
    nome = request.args.get('arquivo', '')
    try:
        numero = int(request.args.get('numero', ''))
    except ValueError:
        return texto('Versão inválida.', 400)
    versao = s.planos.versoes.obter(nome, numero) if pipeline.nome_valido(nome) and s.planos.versoes else None
    assinado = request.args.get('assinado') == '1'
    if not versao or (assinado and not versao['tem_assinado']):
        return texto('Versão não encontrada.', 404)
    caminho = s.planos.versoes.caminho(nome, numero, assinado)
    if not os.path.isfile(caminho):
        return texto('Versão não encontrada.', 404)
    sufixo = '-assinado' if assinado else ''
    return send_file(caminho, mimetype='application/pdf',
                     download_name=f"{os.path.splitext(nome)[0]}-v{numero}{sufixo}.pdf")


@bp.post('')
def enviar():
    """PDF do plano de uma disciplina (campo `oferta`) em que quem envia é docente."""
    arquivo = request.files.get('arquivo')
    if arquivo is None:
        return json_({'erro': 'Nenhum arquivo enviado'}, 400)
    try:
        oferta_id = int(request.form.get('oferta', ''))
    except ValueError:
        return json_({'erro': 'Escolha a disciplina do plano'}, 400)
    s = servicos()
    oferta = s.disciplinas.oferta(oferta_id)
    # Nomes dos docentes da disciplina, para conferir com o docente escrito no PDF (só gera aviso)
    nomes = [d['nome'] for d in s.disciplinas.nomes(oferta['docentes'])] if oferta else []
    if nome_usuario() and _dono() in (oferta or {}).get('docentes', []):
        nomes.append(nome_usuario())  # o nome da conta, mesmo antes de o cadastro guardá-lo
    nomes = list(dict.fromkeys(n for n in nomes if n))
    try:
        salvo = s.planos.enviar_para_oferta(oferta_id, arquivo, _dono(), nomes)
    except Recusado as erro:
        return json_({'erro': str(erro)}, 400)
    return json_(salvo)


@bp.delete('')
def excluir():
    nome = request.args.get('arquivo', '')
    if not pipeline.nome_valido(nome):
        return json_({'erro': 'Arquivo inválido'}, 400)
    try:
        servicos().planos.excluir_do_professor(nome, _dono())
    except Proibido:
        return json_({'erro': 'Você só pode excluir os planos das suas disciplinas'}, 403)
    except Protegido:
        return json_({'erro': 'O plano assinado não pode ser excluído; para corrigi-lo, use Atualizar (a versão '
                              'assinada fica no histórico)'}, 403)
    except Ocupado:
        return ocupado()
    return json_({'excluido': nome})


@bp.delete('/versao')
def excluir_versao():
    """Exclui uma versão anterior do plano (?arquivo=, ?numero=), menos a aprovada e assinada."""
    nome = request.args.get('arquivo', '')
    try:
        numero = int(request.args.get('numero', ''))
    except ValueError:
        return json_({'erro': 'Versão inválida'}, 400)
    if not pipeline.nome_valido(nome):
        return json_({'erro': 'Arquivo inválido'}, 400)
    try:
        servicos().planos.excluir_versao(nome, numero, _dono())
    except Proibido:
        return json_({'erro': 'Você só pode excluir as versões dos planos das suas disciplinas'}, 403)
    except NaoEncontrado:
        return json_({'erro': 'Versão não encontrada'}, 404)
    except Protegido:
        return json_({'erro': 'A versão aprovada e assinada fica guardada e não pode ser excluída'}, 403)
    return json_({'excluida': numero})


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
    except Exception:  # falha inesperada: registra no log e responde com uma mensagem, não com a página de erro
        log.exception('Falha ao conferir o PDF assinado de %s', nome)
        return json_({'erro': 'Erro interno ao conferir a assinatura; tente de novo ou avise a administração'}, 500)
    return json_({'assinatura': assinatura.resumo(registro)})
