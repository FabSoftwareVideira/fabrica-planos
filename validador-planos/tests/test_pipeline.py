import json
import logging

from app import csvsaida, detalhes, pipeline
from app.andamento import Andamento
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


def test_lote_grava_csv_registra_andamento_e_libera(tmp_path, monkeypatch, caplog):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(pipeline, 'extrair_texto', lambda caminho: 'Ementa: algo\n')
    resposta = json.dumps({'status_geral': 'OK', 'obs_geral': 'ok'})
    monkeypatch.setattr(pipeline, 'chamar_ollama', lambda url, payload: resposta)
    detalhes.salvar(cfg.detalhes_dir, 'removido.pdf', {'arquivo': 'removido.pdf'})
    andamento = Andamento()
    nomes = pipeline.listar_pdfs(cfg.planos_dir)
    assert andamento.iniciar(len(nomes))
    assert not andamento.iniciar(len(nomes))

    with caplog.at_level(logging.INFO, logger='app.pipeline'):
        pipeline.executar(cfg, andamento, nomes)

    linhas = csvsaida.ler_csv(cfg.csv_path)
    assert [l['Arquivo'] for l in linhas] == ['a.pdf', 'b.PDF']
    resumo = andamento.resumo()
    assert not resumo['rodando']
    assert resumo['processados'] == resumo['total'] == 2
    assert resumo['finalizado_em'] and not resumo['erro']
    det = detalhes.ler(cfg.detalhes_dir, 'a.pdf')
    assert det['texto'] == 'Ementa: algo\n'
    assert det['secoes']['ementa'] == 'algo'
    assert 'EMENTA:\nalgo' in det['prompt']
    assert det['resposta_ia'] == resposta
    assert detalhes.ler(cfg.detalhes_dir, 'removido.pdf') is None
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
    andamento = Andamento()
    andamento.iniciar(2)
    pipeline.executar(cfg, andamento, pipeline.listar_pdfs(cfg.planos_dir))
    linhas = csvsaida.ler_csv(cfg.csv_path)
    assert all(l['Status Geral'] == 'ERRO' for l in linhas)
    assert 'Ollama inacessível' in linhas[0]['Observação Geral']
    det = detalhes.ler(cfg.detalhes_dir, 'a.pdf')
    assert det['texto'] == 'texto' and det['erro'] == 'Ollama inacessível'


def test_erro_inesperado_libera_e_registra(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(pipeline, 'validar_plano', lambda cfg, nome: {'Status Geral': 'OK'})

    def disco_cheio(caminho, linhas):
        raise OSError('disco cheio')

    monkeypatch.setattr(csvsaida, 'escrever_csv', disco_cheio)
    andamento = Andamento()
    andamento.iniciar(2)
    try:
        pipeline.executar(cfg, andamento, ['a.pdf', 'b.PDF'])
    except OSError:
        pass
    resumo = andamento.resumo()
    assert not resumo['rodando']
    assert resumo['erro'] == 'disco cheio'
