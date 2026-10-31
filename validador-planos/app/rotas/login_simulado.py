import base64
import json
import logging
from urllib.parse import quote, unquote

from flask import Blueprint, redirect, render_template, request

from .comum import email, mesma_origem, servicos

# Login simulado, SÓ PARA DESENVOLVIMENTO (LOGIN_SIMULADO=1, ligado pelo docker-compose.dev.yml): em vez
# do Google, escolhe-se uma persona (ou qualquer e-mail) em /dev/login. O middleware transforma o cookie
# nos mesmos cabeçalhos que o Caddy e o oauth2-proxy mandam em produção (X-Usuario-Email e o ID token em
# X-Usuario-Token), então o app usa exatamente o mesmo caminho de login, cadastro e permissões.
# Sem LOGIN_SIMULADO=1 nada disto é registrado (ver fabrica.py).

log = logging.getLogger(__name__)

COOKIE = 'dev_usuario'

# (e-mail, nome, descrição, papéis nos cursos dados ao entrar). A administradora só é administradora se o
# e-mail estiver em ADMIN_EMAILS (o docker-compose.dev.yml põe admin@ifc.edu.br por padrão).
PERSONAS = [
    ('admin@ifc.edu.br', 'Ana Administradora', 'Administração: valida, envia e exclui PDFs, gerencia usuários', []),
    ('coordenacao.cc@ifc.edu.br', 'Carlos Coordenador', 'Coordenação de Ciência da Computação (revisa planos de CC)',
     [('CC', 'coordenador')]),
    ('nde.cc@ifc.edu.br', 'Nina do NDE', 'NDE de Ciência da Computação (revisa planos de CC)', [('CC', 'nde')]),
    ('ndb.in@ifc.edu.br', 'Bruno do NDB', 'NDB do Técnico em Informática (revisa planos de IN)', [('IN', 'ndb')]),
    ('professor@ifc.edu.br', 'Paulo Professor', 'Servidor sem papel: consulta e entrega os próprios planos', []),
    ('professora@ifc.edu.br', 'Patrícia Professora', 'Outra servidora sem papel (para testar donos diferentes)', []),
    ('aluno@estudantes.ifc.edu.br', 'Alice Aluna', 'Estudante: recusada, como no login com Google', []),
]


def _token(endereco, nome):
    """ID token no formato do Google (só a carga importa: o app não confere a assinatura)."""
    carga = base64.urlsafe_b64encode(json.dumps({'email': endereco, 'name': nome}).encode()).decode().rstrip('=')
    return f'Bearer simulado.{carga}.simulado'


def _ler_cookie(valor):
    endereco, _, nome = unquote(valor or '').partition('\n')
    return endereco.strip().lower(), nome.strip()


class Middleware:
    """Converte o cookie da persona escolhida nos cabeçalhos de login que o proxy mandaria."""

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        for parte in environ.get('HTTP_COOKIE', '').split(';'):
            chave, _, valor = parte.strip().partition('=')
            if chave == COOKIE and valor:
                endereco, nome = _ler_cookie(valor)
                if endereco:
                    environ['HTTP_X_USUARIO_EMAIL'] = endereco
                    environ['HTTP_X_USUARIO_TOKEN'] = _token(endereco, nome)
                break
        return self.app(environ, start_response)


bp = Blueprint('login_simulado', __name__)


def _destino():
    destino = request.values.get('rd', '') or '/dashboard'
    return destino if destino.startswith('/') and not destino.startswith('//') else '/dashboard'


def _pagina(erro='', status=200):
    s = servicos()
    personas = [{'email': e, 'nome': n, 'descricao': d, 'admin': e in s.cfg.admins} for e, n, d, _ in PERSONAS]
    return render_template('dev_login.html', personas=personas, erro=erro, rd=_destino(), atual=email(),
                           dominio=s.cfg.email_dominio, admins=sorted(s.cfg.admins)), status


@bp.get('/dev/login')
def pagina():
    return _pagina()


@bp.post('/dev/login')
def entrar():
    if not mesma_origem():
        return 'Origem inválida', 403
    s = servicos()
    endereco = (request.form.get('email') or '').strip().lower()
    nome = ' '.join((request.form.get('nome') or '').split())[:120]
    persona = next((p for p in PERSONAS if p[0] == endereco), None)
    if persona and not nome:
        nome = persona[1]
    # Mesma regra do oauth2-proxy (OAUTH2_PROXY_EMAIL_DOMAINS): só o domínio exato, sem subdomínios
    if not endereco.endswith('@' + s.cfg.email_dominio) or endereco.count('@') != 1:
        return _pagina(f'{endereco or "E-mail vazio"}: só entram contas @{s.cfg.email_dominio} '
                       '(no Google, o login seria recusado).', 403)
    if persona:  # a persona já entra com os papéis dela nos cursos
        s.usuarios.registrar_acesso(endereco, nome)
        for curso, papel in persona[3]:
            s.usuarios.adicionar_papel(endereco, curso, papel)
    log.info('Login simulado: %s', endereco)
    resposta = redirect(_destino(), 303)
    resposta.set_cookie(COOKIE, quote(endereco + '\n' + nome), httponly=True, samesite='Lax')
    return resposta


@bp.get('/oauth2/sign_out')
def sair():
    resposta = redirect(_destino() if request.args.get('rd') else '/', 303)
    resposta.delete_cookie(COOKIE)
    return resposta


@bp.get('/oauth2/start')
def iniciar():
    return redirect('/dev/login?rd=' + quote(_destino()), 303)
