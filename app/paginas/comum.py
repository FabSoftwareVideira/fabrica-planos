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
    for nome in ('img/logo-ifc.svg', 'img/logo-ifc.png', 'img/logo-ifc-videira.png'):
        if os.path.exists(os.path.join(current_app.static_folder, nome)):
            return estatico(nome)
    return ''


def _usuario():
    # Importado aqui: rotas.comum depende do Flask montado, e as rotas importam este pacote
    from ..rotas.comum import cursos_coordenados, eh_admin, email, nome, servicos
    usuario = email()
    nome_usuario = nome()
    if usuario and not nome_usuario:  # sem o token nesta requisição, vale o nome guardado no último login
        try:
            nome_usuario = (servicos().usuarios.obter(usuario) or {}).get('nome', '')
        except Exception:
            nome_usuario = ''
    admin = bool(usuario) and eh_admin()
    # Conta gov.br: o cabeçalho oferece vincular (para entrar pelo gov.br com e-mail pessoal) ou desvincular
    govbr = None
    if usuario and servicos().cfg.govbr_ativo:
        try:
            govbr = servicos().usuarios.tem_govbr(usuario)
        except Exception:
            govbr = None
    return {'usuario_email': usuario, 'usuario_nome': nome_usuario, 'usuario_admin': admin,
            'usuario_coordenacao': admin or bool(cursos_coordenados()),
            'login_simulado': servicos().cfg.login_simulado, 'usuario_govbr': govbr}


def ano_atual():
    return datetime.now().year


def registrar(app):
    app.jinja_env.globals.update(cor=cor, estatico=estatico, ano_atual=ano_atual, logo_ifc=logo_ifc)
    app.context_processor(_usuario)
    app.jinja_env.filters['data_br'] = data_br
    # Sem espaços e quebras sobrando em volta dos blocos {% ... %}
    app.jinja_env.trim_blocks = True
    app.jinja_env.lstrip_blocks = True
