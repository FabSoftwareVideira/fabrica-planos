import pytest
import requests

from app.avaliacao import ollama


class _Resp:
    def __init__(self, status, corpo):
        self.status_code = status
        self.ok = status < 400
        self.text = corpo

    def json(self):
        return {'response': self.text}


def test_modelo_ausente_nao_repete_e_mostra_causa(monkeypatch):
    chamadas = []

    def falso_post(*args, **kwargs):
        chamadas.append(1)
        return _Resp(404, '{"error":"model \'qwen2.5:7b\' not found"}')

    monkeypatch.setattr(ollama.requests, 'post', falso_post)
    monkeypatch.setattr(ollama.time, 'sleep', lambda s: None)
    with pytest.raises(ollama.OllamaErro, match='not found'):
        ollama.chamar_ollama('http://ollama:11434', {})
    assert len(chamadas) == 1


def test_erro_do_servidor_repete(monkeypatch):
    respostas = [_Resp(500, 'falhou'), _Resp(200, '{"status_geral":"OK"}')]
    monkeypatch.setattr(ollama.requests, 'post', lambda *a, **k: respostas.pop(0))
    monkeypatch.setattr(ollama.time, 'sleep', lambda s: None)
    assert ollama.chamar_ollama('http://ollama:11434', {}) == '{"status_geral":"OK"}'


def test_ollama_fora_do_ar_informa(monkeypatch):
    def falso_post(*args, **kwargs):
        raise requests.ConnectionError('recusada')

    monkeypatch.setattr(ollama.requests, 'post', falso_post)
    monkeypatch.setattr(ollama.time, 'sleep', lambda s: None)
    with pytest.raises(ollama.OllamaErro, match='inacessível'):
        ollama.chamar_ollama('http://ollama:11434', {})
