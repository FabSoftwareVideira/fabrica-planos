import os
from datetime import datetime, timedelta, timezone

# Lock de execução: o arquivo guarda a hora da última atualização.
# Ele conta como ocupado enquanto essa hora tiver menos de 15 minutos.
JANELA = timedelta(minutes=15)


def _ler(caminho):
    try:
        with open(caminho, encoding='utf-8') as arq:
            return arq.read().strip()
    except FileNotFoundError:
        return ''


def ocupado(caminho, agora=None):
    conteudo = _ler(caminho)
    if not conteudo:
        return False
    try:
        ultimo = datetime.fromisoformat(conteudo.replace('Z', '+00:00'))
    except ValueError:
        return False
    if ultimo.tzinfo is None:
        ultimo = ultimo.replace(tzinfo=timezone.utc)
    agora = agora or datetime.now(timezone.utc)
    return agora - ultimo < JANELA


def atualizar(caminho, agora=None):
    agora = agora or datetime.now(timezone.utc)
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, 'w', encoding='utf-8') as arq:
        arq.write(agora.isoformat())


def liberar(caminho):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, 'w', encoding='utf-8') as arq:
        arq.write('')
