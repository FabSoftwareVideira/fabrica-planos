import json
import os
import threading
from datetime import datetime

# Planos assinados pelos professores (servicos/assinatura.py): o PDF assinado em resultados/assinados/ e o
# registro em resultados/assinaturas.json: {nome do arquivo: {'email', 'signatario', 'assinado_em',
# 'enviado_em', 'versao', 'aprovado_em'}}. `versao` é a do PDF aprovado (tamanho e data, como na revisão).

_trava = threading.Lock()


def _caminho(resultados_dir):
    return os.path.join(resultados_dir, 'assinaturas.json')


def pasta(resultados_dir):
    return os.path.join(resultados_dir, 'assinados')


def caminho_pdf(resultados_dir, nome):
    return os.path.join(pasta(resultados_dir), nome)


def ler(resultados_dir):
    try:
        with open(_caminho(resultados_dir), encoding='utf-8') as arq:
            return json.load(arq)
    except (FileNotFoundError, ValueError):
        return {}


def _gravar(resultados_dir, registros):
    os.makedirs(resultados_dir, exist_ok=True)
    temporario = _caminho(resultados_dir) + '.tmp'
    with open(temporario, 'w', encoding='utf-8') as arq:
        json.dump(registros, arq, ensure_ascii=False, indent=1)
    os.replace(temporario, _caminho(resultados_dir))


def gravar(resultados_dir, nome, pdf, dados):
    """Guarda o PDF assinado (substituindo uma assinatura anterior do plano) e o registro."""
    registro = dict(dados, enviado_em=datetime.now().isoformat(timespec='seconds'))
    with _trava:
        os.makedirs(pasta(resultados_dir), exist_ok=True)
        destino = caminho_pdf(resultados_dir, nome)
        with open(destino + '.enviando', 'wb') as arq:
            arq.write(pdf)
        os.replace(destino + '.enviando', destino)
        registros = ler(resultados_dir)
        registros[nome] = registro
        _gravar(resultados_dir, registros)
    return registro


def remover(resultados_dir, nomes):
    with _trava:
        for nome in nomes:
            try:
                os.remove(caminho_pdf(resultados_dir, nome))
            except FileNotFoundError:
                pass
        registros = ler(resultados_dir)
        if any(n in registros for n in nomes):
            _gravar(resultados_dir, {n: r for n, r in registros.items() if n not in nomes})
