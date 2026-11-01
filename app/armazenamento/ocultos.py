import json
import os
import threading
from datetime import datetime

# Planos que o administrador ocultou do painel: {nome do arquivo: {'por', 'em'}}, em resultados/ocultos.json.
# O PDF e a avaliação continuam guardados; o plano só deixa de aparecer no dashboard e na visão da
# coordenação. É o que o administrador faz com os planos de outros usuários, que ele não pode excluir.

_trava = threading.Lock()


def _caminho(resultados_dir):
    return os.path.join(resultados_dir, 'ocultos.json')


def ler(resultados_dir):
    try:
        with open(_caminho(resultados_dir), encoding='utf-8') as arq:
            return json.load(arq)
    except (FileNotFoundError, ValueError):
        return {}


def _gravar(resultados_dir, ocultos):
    os.makedirs(resultados_dir, exist_ok=True)
    temporario = _caminho(resultados_dir) + '.tmp'
    with open(temporario, 'w', encoding='utf-8') as arq:
        json.dump(ocultos, arq, ensure_ascii=False, indent=1)
    os.replace(temporario, _caminho(resultados_dir))


def ocultar(resultados_dir, nome, email):
    with _trava:
        ocultos = ler(resultados_dir)
        ocultos[nome] = {'por': email, 'em': datetime.now().isoformat(timespec='seconds')}
        _gravar(resultados_dir, ocultos)


def mostrar(resultados_dir, nomes):
    """Volta a mostrar esses planos no painel (também ao excluí-los ou ao chegar uma versão nova do PDF)."""
    with _trava:
        ocultos = ler(resultados_dir)
        if any(n in ocultos for n in nomes):
            _gravar(resultados_dir, {n: o for n, o in ocultos.items() if n not in nomes})
