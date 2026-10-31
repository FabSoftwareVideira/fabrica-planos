import json
from urllib.parse import quote

from ..armazenamento.csvsaida import CAMPOS_COLUNA
from ..avaliacao.prompt import LIMITE_PADRAO, LIMITES
from ..servicos.revisao import STATUS_REVISAO

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


def _plano(linhas, indice):
    """Nome e link do plano vizinho (anterior/próximo); None fora da lista."""
    if not 0 <= indice < len(linhas):
        return None
    nome = linhas[indice].get('Arquivo', '')
    return {'nome': nome, 'url': '/relatorio?arquivo=' + quote(nome)}


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


def contexto(linhas, indice, det, execucao, pode_revalidar=False, email=''):
    linha = linhas[indice]
    nome = linha.get('Arquivo', '')
    return {
        'email': email,
        'nome': nome,
        'linha': linha,
        'det': det,
        'indice': indice,
        'total': len(linhas),
        'pode_revalidar': pode_revalidar,
        'url_dashboard': '/dashboard#plano-' + str(indice),
        'anterior': _plano(linhas, indice - 1),
        'proximo': _plano(linhas, indice + 1),
        'url_pdf': ('/validacoes/' + execucao.id + '/pdf?arquivo=' + quote(nome)
                    if nome in execucao.pdfs() else ''),
        'campos': _campos(linha, (det or {}).get('secoes')),
        'resposta_ia': _resposta((det or {}).get('resposta_ia')),
    }


AVISOS_REVISAO = {
    'salva': ('success', 'check-circle', 'Parecer registrado. Ele passa a ser o status oficial do plano.'),
    'desfeita': ('success', 'check-circle', 'Revisão desfeita. O plano volta a mostrar a avaliação da IA.'),
    'incompleta': ('danger', 'times-circle', 'Escolha o parecer e explique no comentário o que precisa mudar '
                                             '(obrigatório quando o plano não é aprovado ou o parecer difere da IA).'),
}


def contexto_revisao(revisao, papel, ident, aviso=''):
    """Painel de revisão manual: o parecer vigente e, para quem tem papel no curso, o formulário."""
    return {
        'revisao': revisao,
        'papel_revisor': papel,
        'curso': (ident or {}).get('curso', ''),
        'opcoes_revisao': STATUS_REVISAO,
        'aviso_revisao': AVISOS_REVISAO.get(aviso),
    }
