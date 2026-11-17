import os
import re
import tempfile
import unicodedata
import zipfile
from urllib.parse import urlencode

from flask import Blueprint, redirect, render_template, request, send_file

from ..paginas import coordenacao
from .comum import cursos_coordenados, eh_admin, servicos, texto
from .painel import dados_da_validacao, revisaveis
from ..limites import EXPORTACAO

# Visão da coordenação: situação dos planos de cada curso. O coordenador vê os cursos que coordena (papel
# dado em Administração → Usuários); a administração vê todos os cursos da validação atual.
bp = Blueprint('coordenacao', __name__)


@bp.get('/coordenacao')
def pagina():
    admin = eh_admin()
    meus = cursos_coordenados()
    if not admin and not meus:
        return redirect('/dashboard')
    execucao, linhas, idents, docentes, revisoes = dados_da_validacao()
    conhecidos = servicos().planos.cursos()
    if admin:
        siglas = sorted({i['sigla_curso'] for i in idents.values() if i} | set(meus))
    else:
        siglas = meus
    cursos = {sigla: conhecidos.get(sigla, sigla) for sigla in siglas}
    assinaturas = {nome: r['assinatura'] for nome, r in revisoes.items() if r.get('assinatura')}
    ctx = coordenacao.contexto(execucao, linhas, idents, docentes, revisoes, cursos,
                               request.args.get('curso', ''), request.args.get('periodo', ''),
                               revisaveis(idents), assinaturas=assinaturas, zip_assinados=_zip_assinados)
    return render_template('coordenacao.html', **ctx)


def _pode_exportar(curso):
    """O zip de um curso: só quem o coordena (ou a administração)."""
    return eh_admin() or curso in cursos_coordenados()


def _zip_assinados(curso, periodo):
    """(endereço do zip, quantos planos assinados) do curso e período ('' = todos os períodos)."""
    if not _pode_exportar(curso):
        return '', 0
    planos, _ = servicos().transparencia.listar(periodo=periodo, curso=curso)
    if not planos:
        return '', 0
    return '/coordenacao/assinados.zip?' + urlencode({'curso': curso, 'periodo': periodo}), len(planos)


def _slug(texto_):
    sem_acento = unicodedata.normalize('NFKD', texto_ or '').encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '-', sem_acento.lower()).strip('-')[:60]


@bp.get('/coordenacao/assinados.zip')
@EXPORTACAO
def zip_assinados():
    """Zip com os PDFs assinados (a versão assinada vigente de cada plano, a mesma da transparência) do curso
    e do período (vazio: todos). Só para quem coordena o curso, ou para a administração."""
    curso = (request.args.get('curso') or '').strip()
    periodo = (request.args.get('periodo') or '').strip()
    if not curso or not _pode_exportar(curso):
        return texto('Só a coordenação do curso (ou a administração) exporta os planos assinados dele.', 403)
    t = servicos().transparencia
    planos, _ = t.listar(periodo=periodo, curso=curso)
    if not planos:
        return texto('Nenhum plano assinado nesse curso e período.', 404)
    arquivo = tempfile.SpooledTemporaryFile(max_size=50 * 1024 * 1024)
    with zipfile.ZipFile(arquivo, 'w', zipfile.ZIP_STORED) as zip_:  # PDFs já são comprimidos
        for p in planos:
            caminho = t.caminho_pdf(p, p['versao'])
            if caminho and os.path.isfile(caminho):
                nome = (f"{p['periodo']}-{p['codigo'] or 'sem-codigo'}-T{p['turma']}-{_slug(p['disciplina'])}"
                        f"-v{p['versao']}-assinado.pdf")
                zip_.write(caminho, nome)
    arquivo.seek(0)
    return send_file(arquivo, mimetype='application/zip', as_attachment=True,
                     download_name=f"planos-assinados-{_slug(curso)}-{periodo or 'todos'}.zip")
