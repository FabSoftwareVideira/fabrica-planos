import json
from urllib.parse import quote

from ..armazenamento.csvsaida import CAMPOS_COLUNA
from ..avaliacao.prompt import LIMITE_PADRAO, LIMITES
from .comum import data_br

# Relatório de um plano (templates/relatorio.html): monta os dados de cada campo e da navegação.

EXPLICACOES = {
    'coerencia': 'Avalia em conjunto os objetivos, a metodologia e os procedimentos de avaliação.',
    'referencias': 'Avaliada por contagem automática (mín. 3 básicas e 5 complementares), sem a IA.',
}


def _resposta(raw):
    try:
        return json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return raw


def _plano(linhas, indice, validacao):
    """Nome e link do plano vizinho (anterior/próximo); None fora da lista."""
    if not 0 <= indice < len(linhas):
        return None
    nome = linhas[indice].get('Arquivo', '')
    return {'nome': nome, 'url': '/relatorio?validacao=' + validacao + '&arquivo=' + quote(nome)}


def _campos(linha, sec):
    campos = []
    for rotulo, chave in CAMPOS_COLUNA:
        campos.append({
            'rotulo': rotulo,
            'status': linha.get(rotulo, ''),
            'obs': linha.get(rotulo + ' Obs', ''),
            'explicacao': EXPLICACOES.get(chave, ''),
            # Sem detalhes (validação antiga) não há contagem nem texto extraído.
            'contagem': ((sec.get('ref_basicas', 0), sec.get('ref_complementares', 0))
                         if sec is not None and chave == 'referencias' else None),
            'mostrar_texto': sec is not None and chave != 'coerencia',
            'texto': (sec or {}).get(chave, '') or '',
            'limite': LIMITES.get(chave, LIMITE_PADRAO),
        })
    return campos


def contexto(linhas, indice, det, execucao, eh_ultima=True, pode_revalidar=False):
    linha = linhas[indice]
    nome = linha.get('Arquivo', '')
    # Para a última validação o dashboard dispensa o ?validacao=, como no link do menu.
    url_dashboard = ('/dashboard' + ('' if eh_ultima else '?validacao=' + execucao.id) + '#plano-' + str(indice))
    return {
        'nome': nome,
        'linha': linha,
        'det': det,
        'indice': indice,
        'total': len(linhas),
        'eh_ultima': eh_ultima,
        'pode_revalidar': pode_revalidar,
        'data': data_br((execucao.meta() or {}).get('finalizado_em')),
        'url_dashboard': url_dashboard,
        'anterior': _plano(linhas, indice - 1, execucao.id),
        'proximo': _plano(linhas, indice + 1, execucao.id),
        'url_pdf': ('/validacoes/' + execucao.id + '/pdf?arquivo=' + quote(nome)
                    if nome in execucao.pdfs() else ''),
        'campos': _campos(linha, (det or {}).get('secoes')),
        'resposta_ia': _resposta((det or {}).get('resposta_ia')),
    }
