import os

from flask import Blueprint, redirect, render_template, request, send_file

from .comum import servicos, texto
from .publico import ja_logado

# Área de transparência, pública (sem login; liberada também no Caddy): os planos de ensino assinados, para
# qualquer pessoa consultar (servicos/transparencia.py). URLs fixas, para divulgar:
#   /transparencia                 lista, com filtros por período, curso, fase, docente e disciplina
#   /transparencia/<id>            o plano (a versão assinada vigente)
#   /transparencia/<id>.pdf        o PDF assinado vigente
#   /transparencia/<id>/v<n>       uma versão assinada (marcada "substituída" se houver uma mais nova)
#   /transparencia/<id>/v<n>.pdf   o PDF assinado dessa versão
bp = Blueprint('transparencia', __name__, url_prefix='/transparencia')

FILTROS = ('periodo', 'curso', 'fase', 'docente', 'q')


@bp.get('')
def lista():
    filtros = {f: (request.args.get(f) or '').strip()[:80] for f in FILTROS}
    planos, opcoes = servicos().transparencia.listar(filtros['periodo'], filtros['curso'], filtros['fase'],
                                                     filtros['docente'], filtros['q'])
    return render_template('transparencia.html', planos=planos, opcoes=opcoes, filtros=filtros,
                           filtrado=any(filtros.values()), ja_logado=ja_logado())


def _plano_ou_404(oferta_id):
    return servicos().transparencia.plano(oferta_id)


@bp.get('/<int:oferta_id>')
def plano(oferta_id):
    p = _plano_ou_404(oferta_id)
    if not p:
        return texto('Plano não encontrado ou ainda não assinado.', 404)
    return render_template('transparencia_plano.html', plano=p, versao=p['assinadas'][0], ja_logado=ja_logado())


@bp.get('/<int:oferta_id>/v<int:numero>')
def versao(oferta_id, numero):
    p = _plano_ou_404(oferta_id)
    v = next((v for v in (p or {}).get('assinadas', []) if v['numero'] == numero), None)
    if not v:
        return texto('Versão não encontrada ou não assinada.', 404)
    return render_template('transparencia_plano.html', plano=p, versao=v, ja_logado=ja_logado())


def _pdf(p, numero):
    caminho = servicos().transparencia.caminho_pdf(p, numero) if p else None
    if not caminho or not os.path.isfile(caminho):
        return texto('PDF não encontrado.', 404)
    codigo = (p['codigo'] or 'plano').replace(' ', '')
    resp = send_file(caminho, mimetype='application/pdf',
                     download_name=f"plano-{p['periodo']}-{codigo}-T{p['turma']}-v{numero}-assinado.pdf")
    resp.headers['Cache-Control'] = 'public, max-age=300'
    return resp


@bp.get('/<int:oferta_id>.pdf')
def pdf_vigente(oferta_id):
    p = _plano_ou_404(oferta_id)
    return _pdf(p, p['versao']) if p else texto('PDF não encontrado.', 404)


@bp.get('/<int:oferta_id>/v<int:numero>.pdf')
def pdf_versao(oferta_id, numero):
    return _pdf(_plano_ou_404(oferta_id), numero)


@bp.get('/')
def com_barra():
    return redirect('/transparencia', 301)
