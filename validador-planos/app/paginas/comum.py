from datetime import datetime
from html import escape

# Peças visuais usadas por mais de uma página (dashboard e relatório).
CORES = {
    'OK': '#22c55e',
    'INCOMPLETO': '#eab308',
    'PENDENTE': '#eab308',
}


def cor(status):
    return CORES.get(status, '#ef4444')


def selo(status):
    return (
        '<span style="background:' + cor(status) + ';color:#fff;padding:2px 8px;border-radius:10px;'
        'font-size:11px;font-weight:600;white-space:nowrap">' + escape(status or '-') + '</span>'
    )


def data_br(iso):
    try:
        return datetime.fromisoformat(iso).strftime('%d/%m/%Y %H:%M')
    except (TypeError, ValueError):
        return '—'
