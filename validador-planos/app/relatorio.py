import json
from html import escape
from urllib.parse import quote

from .csvsaida import CAMPOS_COLUNA
from .dashboard import _badge, _cor, data_br
from .prompt import LIMITE_PADRAO, LIMITES

# Relatório de um plano: avaliação de cada campo ao lado do texto que foi extraído para ele.

EXPLICACOES = {
    'coerencia': 'Avalia em conjunto os objetivos, a metodologia e os procedimentos de avaliação.',
    'referencias': 'Avaliada por contagem automática (mín. 3 básicas e 5 complementares), sem a IA.',
}

ESTILO = (
    'body{margin:0;font-family:system-ui,-apple-system,sans-serif;background:#f3f4f6;color:#111827}'
    '.pagina{max-width:1100px;margin:0 auto;padding:24px 16px 32px}'
    '.nav{position:sticky;top:0;z-index:1;background:rgba(243,244,246,.95);backdrop-filter:blur(4px);'
    'border-bottom:1px solid #e5e7eb}'
    '.nav>div{max-width:1100px;margin:0 auto;padding:10px 16px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}'
    '.nav a,.nav span.off{font-size:14px;font-weight:600;text-decoration:none;color:#2563eb;padding:6px 10px;'
    'border-radius:8px;white-space:nowrap}'
    '.nav a:hover{background:#e0e7ff}.nav span.off{color:#d1d5db}'
    '.nav .voltar{background:#2563eb;color:#fff}.nav .voltar:hover{background:#1d4ed8}'
    '.nav .pos{margin-left:auto;font-size:13px;color:#6b7280}'
    'h1{margin:0 0 8px;font-size:24px;overflow-wrap:anywhere}'
    '.meta{color:#6b7280;font-size:14px;margin:0 0 16px;display:flex;gap:16px;flex-wrap:wrap;align-items:center}'
    '.meta a{color:#2563eb;font-weight:600;text-decoration:none}'
    '.caixa{background:#fff;border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,.1);padding:16px 20px;margin-bottom:12px}'
    '.campo{border-left:4px solid var(--cor)}'
    '.cab{display:flex;justify-content:space-between;align-items:center;gap:8px}'
    '.cab h2{margin:0;font-size:16px}'
    '.obs{margin:8px 0 0;font-size:14px;color:#374151}'
    '.nota{margin:8px 0 0;font-size:12px;color:#9ca3af}'
    '.aviso{background:#fef3c7;color:#92400e;border-radius:8px;padding:12px 16px;margin-bottom:16px;font-size:14px}'
    'pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.5 ui-monospace,Consolas,monospace;background:#f8fafc;'
    'border:1px solid #e5e7eb;border-radius:8px;padding:10px 12px;margin:10px 0 0;max-height:320px;overflow:auto}'
    'pre.vazio{color:#dc2626;font-family:inherit}'
    'details.caixa>summary{cursor:pointer;font-weight:600}'
    'details.caixa pre{max-height:600px}'
)


def _texto(texto, chave):
    if not (texto or '').strip():
        return '<pre class="vazio">Nada foi extraído para este campo.</pre>'
    limite = LIMITES.get(chave, LIMITE_PADRAO)
    nota = ''
    if len(texto) > limite:
        nota = f'<p class="nota">A IA recebeu só os primeiros {limite} de {len(texto)} caracteres.</p>'
    return '<pre>' + escape(texto) + '</pre>' + nota


def _campo(rotulo, chave, linha, sec):
    status = linha.get(rotulo, '')
    obs = linha.get(rotulo + ' Obs', '')
    corpo = '<p class="obs">' + escape(obs) + '</p>' if obs else ''
    if chave in EXPLICACOES:
        corpo += '<p class="nota">' + EXPLICACOES[chave] + '</p>'
    if sec is not None:
        if chave == 'referencias':
            corpo += '<p class="obs">Contagem: <strong>{}</strong> básica(s) e <strong>{}</strong> complementar(es).</p>'.format(
                sec.get('ref_basicas', 0), sec.get('ref_complementares', 0))
        if chave != 'coerencia':
            corpo += _texto(sec.get(chave, ''), chave)
    return (
        '<section class="caixa campo" style="--cor:' + _cor(status) + '"><div class="cab">'
        '<h2>' + escape(rotulo) + '</h2>' + _badge(status) + '</div>' + corpo + '</section>'
    )


def _bruto(titulo, texto):
    if not texto:
        return ''
    return '<details class="caixa"><summary>' + titulo + '</summary><pre>' + escape(texto) + '</pre></details>'


def _resposta(raw):
    try:
        return json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return raw


def _link_plano(linhas, indice, validacao, texto, tecla):
    if not 0 <= indice < len(linhas):
        return '<span class="off">' + texto + '</span>'
    nome = linhas[indice].get('Arquivo', '')
    return ('<a href="/relatorio?validacao=' + validacao + '&arquivo=' + quote(nome) + '" title="'
            + escape(nome, quote=True) + '" data-tecla="' + tecla + '">' + texto + '</a>')


def _navegacao(linhas, indice, validacao, eh_ultima, data):
    # Para a última validação o dashboard dispensa o ?validacao=, como no link do menu.
    dashboard = '/dashboard' + ('' if eh_ultima else '?validacao=' + validacao)
    rotulo = 'Plano ' + str(indice + 1) + ' de ' + str(len(linhas))
    if not eh_ultima:
        rotulo += ' · validação anterior de ' + escape(data)
    return (
        '<nav class="nav"><div>'
        '<a class="voltar" href="' + dashboard + '#plano-' + str(indice) + '" data-tecla="Escape">← Voltar ao dashboard</a>'
        + _link_plano(linhas, indice - 1, validacao, '‹ Anterior', 'ArrowLeft')
        + _link_plano(linhas, indice + 1, validacao, 'Próximo ›', 'ArrowRight')
        + '<span class="pos">' + rotulo + '</span>'
        '</div></nav>'
    )


# Atalhos: Esc volta ao dashboard, ← e → passam para o plano anterior/próximo.
ATALHOS = (
    "document.addEventListener('keydown',e=>{if(e.ctrlKey||e.metaKey||e.altKey)return;"
    "const a=document.querySelector('.nav a[data-tecla=\"'+e.key+'\"]');if(a)location.href=a.href;});"
)


def gerar_html(linhas, indice, det, execucao, eh_ultima=True):
    linha = linhas[indice]
    nome = linha.get('Arquivo', '')
    sec = (det or {}).get('secoes')
    aviso = ''
    if det is None:
        aviso = ('<div class="aviso">O texto extraído não está disponível: este plano foi validado antes de o '
                 'relatório existir.</div>')
    elif det.get('erro'):
        aviso = '<div class="aviso">Falha ao validar: ' + escape(det['erro']) + '</div>'

    meta = [_badge(linha.get('Status Geral', '')), 'Validado em ' + escape(linha.get('Data Validação', ''))]
    if det and det.get('modelo'):
        meta.append('Modelo ' + escape(det['modelo']))
    if nome in execucao.pdfs():
        meta.append('<a href="/validacoes/' + execucao.id + '/pdf?arquivo=' + quote(nome)
                    + '" target="_blank" rel="noopener">📄 Abrir PDF</a>')
    else:
        meta.append('PDF não guardado (só a última validação guarda os PDFs)')

    observacao = linha.get('Observação Geral', '')
    data = data_br((execucao.meta() or {}).get('finalizado_em'))
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Relatório: ' + escape(nome) + '</title><style>' + ESTILO + '</style></head>'
        '<body>' + _navegacao(linhas, indice, execucao.id, eh_ultima, data)
        + '<div class="pagina"><h1>' + escape(nome.removesuffix('.pdf')) + '</h1>'
        '<div class="meta">' + ''.join('<span>' + m + '</span>' for m in meta) + '</div>'
        + aviso
        + ('<div class="caixa"><strong>Observação geral:</strong> ' + escape(observacao) + '</div>' if observacao else '')
        + ''.join(_campo(rotulo, chave, linha, sec) for rotulo, chave in CAMPOS_COLUNA)
        + _bruto('Texto completo extraído do PDF', (det or {}).get('texto'))
        + _bruto('Prompt enviado à IA', (det or {}).get('prompt'))
        + _bruto('Resposta da IA (antes das regras automáticas)', _resposta((det or {}).get('resposta_ia')))
        + '</div><script>' + ATALHOS + '</script></body></html>'
    )
