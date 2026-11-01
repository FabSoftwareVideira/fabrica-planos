import json
import os

# Detalhes de cada plano validado (texto extraído, seções, prompt e resposta da IA), gravados na
# pasta detalhes/ da execução (ver historico.py) para o relatório mostrar exatamente o que foi avaliado.


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


def remover(pasta, nome):
    try:
        os.remove(_caminho(pasta, nome))
    except FileNotFoundError:
        pass

