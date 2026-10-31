import hashlib
import os
from datetime import datetime

from flask import current_app, url_for

# Funções disponíveis em todos os templates (registradas em app/fabrica.py).
CORES = {
    'OK': '#22c55e',
    'INCOMPLETO': '#eab308',
    'PENDENTE': '#eab308',
}


def cor(status):
    return CORES.get(status, '#ef4444')


def data_br(iso):
    try:
        return datetime.fromisoformat(iso).strftime('%d/%m/%Y %H:%M')
    except (TypeError, ValueError):
        return '—'


_versoes = {}


def estatico(arquivo):
    """URL de um arquivo de app/static com a versão (hash do conteúdo) no endereço: depois de um deploy
    o navegador baixa o CSS/JS novo em vez de usar o que estava em cache."""
    if arquivo not in _versoes:
        with open(os.path.join(current_app.static_folder, arquivo), 'rb') as f:
            _versoes[arquivo] = hashlib.sha1(f.read()).hexdigest()[:10]
    return url_for('static', filename=arquivo, v=_versoes[arquivo])


def logo_ifc():
    """URL do logotipo do IFC, se o arquivo estiver em static/img (SVG de preferência); vazio sem ele."""
    for nome in ('img/logo-ifc.svg', 'img/logo-ifc.png'):
        if os.path.exists(os.path.join(current_app.static_folder, nome)):
            return estatico(nome)
    return ''


def _usuario():
    # Importado aqui: rotas.comum depende do Flask montado, e as rotas importam este pacote
    from ..rotas.comum import eh_admin, email
    return {'usuario_email': email(), 'usuario_admin': bool(email()) and eh_admin()}


def ano_atual():
    return datetime.now().year


def registrar(app):
    app.jinja_env.globals.update(cor=cor, estatico=estatico, ano_atual=ano_atual, logo_ifc=logo_ifc)
    app.context_processor(_usuario)
    app.jinja_env.filters['data_br'] = data_br
    # Sem espaços e quebras sobrando em volta dos blocos {% ... %}
    app.jinja_env.trim_blocks = True
    app.jinja_env.lstrip_blocks = True
