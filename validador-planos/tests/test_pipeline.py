import json
import logging

from app import csvsaida, lock, pipeline
from app.config import Config


def _cfg(tmp_path):
    planos = tmp_path / 'planos'
    planos.mkdir()
    (planos / 'a.pdf').write_bytes(b'%PDF fake')
    (planos / 'b.PDF').write_bytes(b'%PDF fake')
    return Config(
        planos_dir=str(planos), resultados_dir=str(tmp_path / 'res'),
        ollama_url='http://ollama:11434', modelo='qwen2.5:14b', num_ctx=12288,
        hora_agendada=5, agendar=False,
    )


def test_lote_grava_csv_registra_andamento_e_libera_lock(tmp_path, monkeypatch, caplog):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(pipeline, 'extrair_texto', lambda caminho: 'Ementa: algo\n')
    resposta = json.dumps({'status_geral': 'OK', 'obs_geral': 'ok'})
    monkeypatch.setattr(pipeline, 'chamar_ollama', lambda url, payload: resposta)
    lock.atualizar(cfg.lock_path)

    with caplog.at_level(logging.INFO, logger='app.pipeline'):
        pipeline.executar(cfg)

    linhas = csvsaida.ler_csv(cfg.csv_path)
    assert [l['Arquivo'] for l in linhas] == ['a.pdf', 'b.PDF']
    assert not lock.ocupado(cfg.lock_path)
    mensagens = caplog.text
    assert 'Validação iniciada: 2 plano(s), modelo qwen2.5:14b' in mensagens
    assert '[1/2] Validando a.pdf' in mensagens
    assert 'Validação concluída: 2 plano(s)' in mensagens


def test_falha_no_ollama_vira_erro_no_csv(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(pipeline, 'extrair_texto', lambda caminho: 'texto')

    def sem_conexao(url, payload):
        raise RuntimeError('Ollama inacessível')

    monkeypatch.setattr(pipeline, 'chamar_ollama', sem_conexao)
    pipeline.executar(cfg)
    linhas = csvsaida.ler_csv(cfg.csv_path)
    assert all(l['Status Geral'] == 'ERRO' for l in linhas)
    assert 'Ollama inacessível' in linhas[0]['Observação Geral']
