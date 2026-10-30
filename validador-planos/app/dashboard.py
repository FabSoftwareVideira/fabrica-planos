from html import escape

from .csvsaida import CAMPOS_COLUNA

CORES = {
    'OK': '#22c55e',
    'INCOMPLETO': '#eab308',
    'PENDENTE': '#eab308',
}


def _cor(status):
    return CORES.get(status, '#ef4444')


def _badge(status):
    return (
        '<span style="background:' + _cor(status) + ';color:#fff;padding:2px 8px;border-radius:10px;'
        'font-size:11px;font-weight:600;white-space:nowrap">' + escape(status or '-') + '</span>'
    )


def _card(linha):
    nome = (linha.get('Arquivo') or '').replace('2024-1 - ', '').replace('.pdf', '')
    topicos = []
    for rotulo, _ in CAMPOS_COLUNA:
        status = linha.get(rotulo, '')
        obs = linha.get(rotulo + ' Obs', '')
        topicos.append(
            '<div style="border:1px solid #e5e7eb;border-left:4px solid ' + _cor(status) + ';border-radius:8px;'
            'padding:10px 12px;background:#fafafa">'
            '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px">'
            '<span style="font-size:13px;font-weight:600">' + escape(rotulo) + '</span>' + _badge(status) + '</div>'
            + ('<div style="font-size:12px;color:#6b7280;margin-top:6px">' + escape(obs) + '</div>' if obs else '')
            + '</div>'
        )
    link = (
        '<a href="/pdf?arquivo=' + escape(linha.get('Arquivo', ''), quote=True) + '" target="_blank" rel="noopener" '
        'style="font-size:13px;color:#2563eb;text-decoration:none;font-weight:600;white-space:nowrap" '
        'onclick="event.stopPropagation()">📄 Abrir PDF</a>'
    )
    observacao = linha.get('Observação Geral', '')
    return (
        '<details style="background:#fff;border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,.1);margin-bottom:12px">'
        '<summary style="display:flex;align-items:center;gap:12px;padding:14px 16px;cursor:pointer;list-style:none">'
        '<span style="font-weight:600;flex:1">' + escape(nome) + '</span>' + _badge(linha.get('Status Geral', ''))
        + link + '<span style="color:#9ca3af;font-size:12px">▼ detalhes</span></summary>'
        '<div style="padding:0 16px 16px">'
        + ('<p style="margin:0 0 12px;font-size:13px;color:#6b7280">' + escape(observacao) + '</p>' if observacao else '')
        + '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px">'
        + ''.join(topicos) + '</div></div></details>'
    )


def gerar_html(linhas, atualizado_em):
    total = len(linhas)
    ok = sum(1 for l in linhas if l.get('Status Geral') == 'OK')
    pendente = sum(1 for l in linhas if l.get('Status Geral') == 'PENDENTE')
    problema = total - ok - pendente

    def pct(n):
        return round(n / total * 100) if total else 0

    cartoes = (
        '<div style="background:#fff;border-radius:12px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.1)">'
        '<div style="font-size:13px;color:#6b7280">Total de planos</div>'
        '<div style="font-size:32px;font-weight:700">' + str(total) + '</div></div>'
    )
    for rotulo, valor, cor in (('Aprovados', ok, '#22c55e'), ('Pendentes', pendente, '#eab308'),
                               ('Com problemas', problema, '#ef4444')):
        cartoes += (
            '<div style="background:#fff;border-radius:12px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.1);'
            'border-left:4px solid ' + cor + '"><div style="font-size:13px;color:#6b7280">' + rotulo + '</div>'
            '<div style="font-size:32px;font-weight:700;color:' + cor + '">' + str(valor)
            + ' <span style="font-size:14px;color:#9ca3af">(' + str(pct(valor)) + '%)</span></div></div>'
        )

    corpo = ''.join(_card(l) for l in linhas) if linhas else (
        '<p style="color:#6b7280">Nenhuma validação concluída ainda.</p>'
    )
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Validação de Planos de Ensino</title>'
        '<style>details summary::-webkit-details-marker{display:none}</style></head>'
        '<body style="margin:0;font-family:system-ui,-apple-system,sans-serif;background:#f3f4f6;color:#111827">'
        '<div style="max-width:1100px;margin:0 auto;padding:32px 16px">'
        '<h1 style="margin:0 0 4px">📋 Validação de Planos de Ensino</h1>'
        '<p style="margin:0 0 24px;color:#6b7280">Resultado da última validação: ' + escape(atualizado_em) + '</p>'
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px;margin-bottom:24px">'
        + cartoes + '</div>' + corpo +
        '</div></body></html>'
    )
