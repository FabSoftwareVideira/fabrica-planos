import json
import os
import threading
from datetime import datetime

# Liberações de reenvio de planos já assinados: {nome do arquivo: {'por', 'em'}}, em
# resultados/liberacoes.json. Depois de assinado, o professor só substitui o plano se a coordenação do
# curso liberar; a liberação vale para um envio (o app a apaga quando o PDF novo é gravado).

_trava = threading.Lock()


def _caminho(resultados_dir):
    return os.path.join(resultados_dir, 'liberacoes.json')


def ler(resultados_dir):
    try:
        with open(_caminho(resultados_dir), encoding='utf-8') as arq:
            return json.load(arq)
    except (FileNotFoundError, ValueError):
        return {}


def _gravar(resultados_dir, liberacoes):
    os.makedirs(resultados_dir, exist_ok=True)
    temporario = _caminho(resultados_dir) + '.tmp'
    with open(temporario, 'w', encoding='utf-8') as arq:
        json.dump(liberacoes, arq, ensure_ascii=False, indent=1)
    os.replace(temporario, _caminho(resultados_dir))


def liberar(resultados_dir, nome, email):
    """Permite que o professor envie uma nova versão do plano assinado."""
    with _trava:
        liberacoes = ler(resultados_dir)
        liberacoes[nome] = {'por': email, 'em': datetime.now().isoformat(timespec='seconds')}
        _gravar(resultados_dir, liberacoes)


def liberado(resultados_dir, nome):
    return nome in ler(resultados_dir)


def cancelar(resultados_dir, nome):
    remover(resultados_dir, [nome])


def remover(resultados_dir, nomes):
    """Apaga as liberações desses planos (ao enviar a versão nova, ao excluir o plano ou ao cancelar)."""
    with _trava:
        liberacoes = ler(resultados_dir)
        if any(n in liberacoes for n in nomes):
            _gravar(resultados_dir, {n: l for n, l in liberacoes.items() if n not in nomes})
