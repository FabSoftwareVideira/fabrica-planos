import json
import os
import threading
from datetime import datetime

# Quem enviou cada PDF pela página "Meus planos": {nome do arquivo: {'email', 'enviado_em'}}, em
# resultados/donos.json. PDFs enviados pelo administrador ou copiados direto para a pasta não têm dono.

_trava = threading.Lock()


def _caminho(resultados_dir):
    return os.path.join(resultados_dir, 'donos.json')


def ler(resultados_dir):
    try:
        with open(_caminho(resultados_dir), encoding='utf-8') as arq:
            return json.load(arq)
    except (FileNotFoundError, ValueError):
        return {}


def _gravar(resultados_dir, donos):
    os.makedirs(resultados_dir, exist_ok=True)
    temporario = _caminho(resultados_dir) + '.tmp'
    with open(temporario, 'w', encoding='utf-8') as arq:
        json.dump(donos, arq, ensure_ascii=False, indent=1)
    os.replace(temporario, _caminho(resultados_dir))


def definir(resultados_dir, nome, email):
    with _trava:
        donos = ler(resultados_dir)
        donos[nome] = {'email': email, 'enviado_em': datetime.now().isoformat(timespec='seconds')}
        _gravar(resultados_dir, donos)


def remover(resultados_dir, nomes):
    with _trava:
        donos = ler(resultados_dir)
        if any(n in donos for n in nomes):
            _gravar(resultados_dir, {n: d for n, d in donos.items() if n not in nomes})
