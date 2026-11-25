import json
from datetime import datetime

from flask import Blueprint, Response, redirect, render_template, request

from ..armazenamento.usuarios import NOME_MAX, PAPEIS_CURSO
from .comum import cursos_coordenados, eh_admin, email, mesma_origem, nome, servicos, texto

# Meu perfil (templates/conta.html): o nome que o sistema mostra (editável), o e-mail e os papéis, a conta
# gov.br vinculada e o nível dela, as disciplinas do usuário e os dados pessoais guardados (LGPD).
bp = Blueprint('conta', __name__, url_prefix='/conta')

NIVEIS = {'bronze': 'Bronze', 'prata': 'Prata', 'ouro': 'Ouro'}
AVISOS = {'nome': 'Nome atualizado.', 'nome_login': 'Voltou a valer o nome da sua conta de login.'}


def _dados(usuario):
    """Tudo o que a página mostra (e o que "Baixar meus dados" entrega)."""
    s = servicos()
    cadastro = s.usuarios.obter(usuario) or {}
    cursos = s.disciplinas.cursos()
    papeis = [{'curso': curso, 'nome_curso': cursos.get(curso, curso), 'papel': PAPEIS_CURSO.get(papel, papel)}
              for curso, papel in s.usuarios.papeis(usuario)]
    govbr = s.usuarios.govbr_de(usuario) if s.cfg.govbr_ativo else None
    disciplinas = [{'periodo': o['periodo'], 'curso': o['curso'], 'codigo': o['codigo'], 'disciplina': o['nome'],
                    'turma': o['turma']} for o in s.disciplinas.ofertas.listar(docente=usuario)]
    return {
        'email': usuario,
        'nome': cadastro.get('nome') or nome(),
        'nome_login': cadastro.get('nome_login') or nome(),
        'nome_proprio': bool(cadastro.get('nome_proprio')),
        'perfil': 'Administrador' if eh_admin() else 'Coordenação' if cursos_coordenados() else 'Consulta',
        'primeiro_acesso': cadastro.get('primeiro_acesso', ''),
        'ultimo_acesso': cadastro.get('ultimo_acesso', ''),
        'papeis': papeis,
        'govbr': govbr,
        'disciplinas': disciplinas,
    }


@bp.get('')
def pagina():
    usuario = email()
    if not usuario:
        return texto('Login necessário.', 401)
    dados = _dados(usuario)
    por_periodo = {}
    for d in dados['disciplinas']:
        por_periodo[d['periodo']] = por_periodo.get(d['periodo'], 0) + 1
    return render_template('conta.html', dados=dados, niveis=NIVEIS, nome_max=NOME_MAX,
                           por_periodo=sorted(por_periodo.items(), reverse=True),
                           govbr_ativo=servicos().cfg.govbr_ativo, aviso=AVISOS.get(request.args.get('aviso', '')),
                           erro=request.args.get('erro', '') == 'nome')


@bp.post('/nome')
def salvar_nome():
    usuario = email()
    if not usuario or not mesma_origem():
        return texto('Requisição recusada.', 403)
    if request.form.get('acao') == 'login':
        servicos().usuarios.definir_nome(usuario, '')
        return redirect('/conta?aviso=nome_login', 303)
    novo = ' '.join((request.form.get('nome') or '').split())
    if len(novo) < 3:
        return redirect('/conta?erro=nome', 303)
    servicos().usuarios.definir_nome(usuario, novo)
    return redirect('/conta?aviso=nome', 303)


@bp.get('/meus-dados.json')
def meus_dados():
    """Os dados pessoais que o sistema guarda sobre quem pede (LGPD, art. 18: acesso e portabilidade). O CPF da
    conta gov.br não é guardado (só um resumo criptográfico), por isso não aparece."""
    usuario = email()
    if not usuario:
        return texto('Login necessário.', 401)
    dados = {'gerado_em': datetime.now().isoformat(timespec='seconds'), **_dados(usuario)}
    resp = Response(json.dumps(dados, ensure_ascii=False, indent=2), mimetype='application/json')
    resp.headers['Content-Disposition'] = 'attachment; filename=meus-dados-planos-de-ensino.json'
    return resp
