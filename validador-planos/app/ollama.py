import json
import re
import time

import requests

from .prompt import FORMAT_SCHEMA

TENTATIVAS = 3
ESPERA_SEGUNDOS = 5


def montar_payload(modelo, prompt, num_ctx):
    return {
        'model': modelo,
        'prompt': prompt,
        'stream': False,
        'format': FORMAT_SCHEMA,
        'keep_alive': '30m',
        'options': {'num_ctx': num_ctx, 'num_predict': 1500, 'temperature': 0.1},
    }


def chamar_ollama(ollama_url, payload, timeout=180):
    ultimo_erro = None
    for tentativa in range(TENTATIVAS):
        try:
            resp = requests.post(ollama_url + '/api/generate', json=payload, timeout=timeout)
            resp.raise_for_status()
            return resp.json().get('response', '')
        except requests.RequestException as erro:
            ultimo_erro = erro
            if tentativa < TENTATIVAS - 1:
                time.sleep(ESPERA_SEGUNDOS)
    raise ultimo_erro


def extrair_json(raw):
    m = re.search(r'\{[\s\S]*\}', raw or '')
    valor = json.loads(m.group(0) if m else (raw or ''))
    if 'status_geral' not in valor:
        raise ValueError('JSON sem status_geral')
    return valor
