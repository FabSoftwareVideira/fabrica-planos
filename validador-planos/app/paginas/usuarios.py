from datetime import datetime
from urllib.parse import urlencode

# Tela de usuários da administração (templates/usuarios.html): filtros, tabela e paginação.

POR_PAGINA = 20
SITUACOES = {'': 'Todas', 'ativos': 'Ativos', 'inativos': 'Desativados'}
PAPEIS = {'': 'Todos', 'admin': 'Administradores', 'consulta': 'Consulta'}
ORDENS = {'acesso': 'Último acesso', 'nome': 'Nome', 'email': 'E-mail', 'cadastro': 'Primeiro acesso'}


def _inteiro(valor, padrao=1):
    try:
        return max(1, int(valor))
    except (TypeError, ValueError):
        return padrao


def filtros(args):
    """Filtros válidos lidos da query string (valores desconhecidos viram o padrão)."""
    return {
        'q': (args.get('q') or '').strip()[:100],
        'situacao': args.get('situacao') if args.get('situacao') in SITUACOES else '',
        'papel': args.get('papel') if args.get('papel') in PAPEIS else '',
        'ordem': args.get('ordem') if args.get('ordem') in ORDENS else 'acesso',
        'pagina': _inteiro(args.get('pagina')),
    }


def endereco(f, **mudancas):
    """/administracao/usuarios com os filtros atuais (sem os padrões), trocando o que vier em mudancas."""
    valores = {**f, **mudancas}
    padroes = {'q': '', 'situacao': '', 'papel': '', 'ordem': 'acesso', 'pagina': 1}
    query = {k: v for k, v in valores.items() if k in padroes and v != padroes[k]}
    return '/administracao/usuarios' + ('?' + urlencode(query) if query else '')


def _paginas(atual, total):
    """Números a mostrar na paginação, com None no lugar dos trechos omitidos: 1 … 4 5 6 … 12."""
    mostrar = sorted({1, total, *range(max(1, atual - 1), min(total, atual + 1) + 1)})
    saida, anterior = [], 0
    for n in mostrar:
        if n - anterior > 1:
            saida.append(None)
        saida.append(n)
        anterior = n
    return saida


def _quando(iso):
    try:
        return datetime.fromisoformat(iso).strftime('%d/%m/%Y %H:%M')
    except (TypeError, ValueError):
        return ''


def contexto(usuarios, admins, f, eu='', aviso=''):
    itens, total = usuarios.listar(f['q'], f['situacao'], f['papel'], admins, f['ordem'], f['pagina'], POR_PAGINA)
    paginas = max(1, -(-total // POR_PAGINA))
    if f['pagina'] > paginas and total:  # página além do fim (ex.: após filtrar): mostra a última
        f = {**f, 'pagina': paginas}
        itens, total = usuarios.listar(f['q'], f['situacao'], f['papel'], admins, f['ordem'], f['pagina'], POR_PAGINA)
    for u in itens:
        u['admin'] = u['email'] in admins
        u['eu'] = u['email'] == eu
        u['ultimo'] = _quando(u['ultimo_acesso'])
        u['primeiro'] = _quando(u['primeiro_acesso'])
    inicio = (f['pagina'] - 1) * POR_PAGINA
    return {
        'usuarios': itens, 'total': total, 'contagem': usuarios.contar(), 'f': f, 'aviso': aviso,
        'pagina': f['pagina'], 'paginas': paginas, 'numeros': _paginas(f['pagina'], paginas),
        'de': inicio + 1 if total else 0, 'ate': inicio + len(itens),
        'situacoes': SITUACOES, 'papeis': PAPEIS, 'ordens': ORDENS,
        'endereco': lambda **m: endereco(f, **m),
        'filtrando': bool(f['q'] or f['situacao'] or f['papel']),
    }
