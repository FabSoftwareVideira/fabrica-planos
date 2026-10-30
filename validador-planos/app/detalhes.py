import json
import os

# Detalhes de cada plano validado (texto extraído, seções, prompt e resposta da IA), gravados em
# resultados/detalhes/<arquivo>.json para o relatório mostrar exatamente o que foi avaliado.


def _caminho(pasta, nome):
    return os.path.join(pasta, nome + '.json')


def salvar(pasta, nome, dados):
    os.makedirs(pasta, exist_ok=True)
    temporario = _caminho(pasta, nome) + '.tmp'
    with open(temporario, 'w', encoding='utf-8') as arq:
        json.dump(dados, arq, ensure_ascii=False, indent=1)
    os.replace(temporario, _caminho(pasta, nome))


def ler(pasta, nome):
    try:
        with open(_caminho(pasta, nome), encoding='utf-8') as arq:
            return json.load(arq)
    except (FileNotFoundError, ValueError):
        return None


def manter_somente(pasta, nomes):
    """Apaga os detalhes de planos que não fazem mais parte do resultado."""
    if not os.path.isdir(pasta):
        return
    manter = {nome + '.json' for nome in nomes}
    for arquivo in os.listdir(pasta):
        if arquivo.endswith('.json') and arquivo not in manter:
            os.remove(os.path.join(pasta, arquivo))
