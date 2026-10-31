import json
import logging
from datetime import datetime

from app.armazenamento import csvsaida, detalhes, historico
from app.avaliacao import pipeline
from app.config import Config
from app.servicos.andamento import Andamento


def _cfg(tmp_path, historico_max=3):
    planos = tmp_path / 'planos'
    planos.mkdir()
    (planos / 'a.pdf').write_bytes(b'%PDF fake')
    (planos / 'b.PDF').write_bytes(b'%PDF fake')
    return Config(
        planos_dir=str(planos), resultados_dir=str(tmp_path / 'res'),
        ollama_url='http://ollama:11434', modelo='qwen2.5:14b', num_ctx=12288,
        hora_agendada=5, agendar=False, historico_max=historico_max,
    )


def _executar(cfg):
    andamento = Andamento()
    nomes = pipeline.listar_pdfs(cfg.planos_dir)
    andamento.iniciar(len(nomes))
    pipeline.executar(cfg, andamento, nomes)
    return andamento


def test_lote_grava_historico_registra_andamento_e_libera(tmp_path, monkeypatch, caplog):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(pipeline, 'extrair_texto', lambda caminho: 'Ementa: algo\n')
    resposta = json.dumps({'status_geral': 'OK', 'obs_geral': 'ok'})
    monkeypatch.setattr(pipeline, 'chamar_ollama', lambda url, payload: resposta)
    andamento = Andamento()
    nomes = pipeline.listar_pdfs(cfg.planos_dir)
    assert andamento.iniciar(len(nomes))
    assert not andamento.iniciar(len(nomes))

    with caplog.at_level(logging.INFO, logger='app.avaliacao.pipeline'):
        pipeline.executar(cfg, andamento, nomes)

    resumo = andamento.resumo()
    assert not resumo['rodando']
    assert resumo['processados'] == resumo['total'] == 2
    assert resumo['finalizado_em'] and not resumo['erro']

    [execucao] = historico.listar(cfg.historico_dir)
    assert [l['Arquivo'] for l in csvsaida.ler_csv(execucao.csv_path)] == ['a.pdf', 'b.PDF']
    assert csvsaida.ler_csv(cfg.csv_path) == csvsaida.ler_csv(execucao.csv_path)  # cópia da última
    assert execucao.pdfs() == ['a.pdf', 'b.PDF']
    meta = execucao.meta()
    assert (meta['total'], meta['processados'], meta['erro']) == (2, 2, '')
    assert meta['ok'] + meta['pendentes'] + meta['problemas'] == 2
    assert meta['modelo'] == 'qwen2.5:14b'

    det = detalhes.ler(execucao.detalhes_dir, 'a.pdf')
    assert det['texto'] == 'Ementa: algo\n'
    assert det['secoes']['ementa'] == 'algo'
    assert 'EMENTA:\nalgo' in det['prompt']
    assert det['resposta_ia'] == resposta
    mensagens = caplog.text
    assert 'iniciada: 2 plano(s), modelo qwen2.5:14b' in mensagens
    assert '[1/2] Validando a.pdf' in mensagens
    assert 'Validação concluída: 2 plano(s)' in mensagens


def test_historico_guarda_as_ultimas_e_pdfs_so_da_mais_recente(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, historico_max=2)
    monkeypatch.setattr(pipeline, 'extrair_texto', lambda caminho: 'Ementa: algo\n')
    monkeypatch.setattr(pipeline, 'chamar_ollama', lambda url, payload: '{"status_geral": "OK"}')
    horas = iter(range(10, 13))
    criar = historico.criar
    monkeypatch.setattr(historico, 'criar', lambda raiz, agora=None: criar(raiz, datetime(2026, 10, 30, next(horas))))
    for _ in range(3):
        _executar(cfg)

    execucoes = historico.listar(cfg.historico_dir)
    assert [e.id for e in execucoes] == ['20261030-120000', '20261030-110000']  # a primeira saiu
    assert execucoes[0].pdfs() == ['a.pdf', 'b.PDF']
    assert execucoes[1].pdfs() == []
    assert detalhes.ler(execucoes[1].detalhes_dir, 'a.pdf') is not None  # resultado antigo continua


def test_falha_no_ollama_vira_erro_no_csv(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(pipeline, 'extrair_texto', lambda caminho: 'texto')

    def sem_conexao(url, payload):
        raise RuntimeError('Ollama inacessível')

    monkeypatch.setattr(pipeline, 'chamar_ollama', sem_conexao)
    _executar(cfg)
    [execucao] = historico.listar(cfg.historico_dir)
    linhas = csvsaida.ler_csv(execucao.csv_path)
    assert all(l['Status Geral'] == 'ERRO' for l in linhas)
    assert 'Ollama inacessível' in linhas[0]['Observação Geral']
    det = detalhes.ler(execucao.detalhes_dir, 'a.pdf')
    assert det['texto'] == 'texto' and det['erro'] == 'Ollama inacessível'


def test_erro_inesperado_libera_e_registra_execucao_interrompida(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    chamadas = []

    def validar(cfg, nome, detalhes_dir):
        chamadas.append(nome)
        if len(chamadas) == 2:
            raise OSError('disco cheio')
        return {'Arquivo': nome, 'Status Geral': 'OK'}

    monkeypatch.setattr(pipeline, 'validar_plano', validar)
    andamento = Andamento()
    andamento.iniciar(2)
    try:
        pipeline.executar(cfg, andamento, ['a.pdf', 'b.PDF'])
    except OSError:
        pass
    resumo = andamento.resumo()
    assert not resumo['rodando']
    assert resumo['erro'] == 'disco cheio'
    [execucao] = historico.listar(cfg.historico_dir)
    meta = execucao.meta()
    assert (meta['erro'], meta['processados'], meta['total']) == ('disco cheio', 1, 2)
    assert [l['Arquivo'] for l in csvsaida.ler_csv(execucao.csv_path)] == ['a.pdf']


def test_pdf_sem_texto_vira_erro_sem_chamar_a_ia(tmp_path, monkeypatch):
    from conftest import PDF_SEM_TEXTO
    cfg = _cfg(tmp_path)
    (tmp_path / 'planos' / 'a.pdf').write_bytes(PDF_SEM_TEXTO)

    def nao_chamar(url, payload):
        raise AssertionError('a IA não deveria ser chamada')

    monkeypatch.setattr(pipeline, 'chamar_ollama', nao_chamar)
    pasta = str(tmp_path / 'det')
    linha = pipeline.validar_plano(cfg, 'a.pdf', pasta)
    assert linha['Status Geral'] == 'ERRO'
    assert 'OCR' in linha['Observação Geral']
    assert 'OCR' in detalhes.ler(pasta, 'a.pdf')['erro']


def test_migra_resultado_da_versao_sem_historico(tmp_path):
    res = tmp_path / 'res'
    linha = csvsaida.linha_resultado('a.pdf', '/x', {'status_geral': 'OK'})
    csvsaida.escrever_csv(str(res / 'validacao_planos.csv'), [linha])
    detalhes.salvar(str(res / 'detalhes'), 'a.pdf', {'texto': 'antigo'})

    raiz = str(res / 'historico')
    historico.migrar_legado(raiz, str(res / 'validacao_planos.csv'), str(res / 'detalhes'), csvsaida.ler_csv)
    historico.migrar_legado(raiz, str(res / 'validacao_planos.csv'), str(res / 'detalhes'), csvsaida.ler_csv)

    [execucao] = historico.listar(raiz)
    assert execucao.meta()['ok'] == 1
    assert detalhes.ler(execucao.detalhes_dir, 'a.pdf') == {'texto': 'antigo'}
    assert execucao.pdfs() == []


def test_revalidar_um_plano_atualiza_a_ultima_validacao(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(pipeline, 'extrair_texto', lambda caminho: 'Ementa: algo\n')
    monkeypatch.setattr(pipeline, 'chamar_ollama', lambda url, payload: '{"status_geral": "OK", "obs_geral": "v1"}')
    _executar(cfg)
    (tmp_path / 'planos' / 'c.pdf').write_bytes(b'%PDF novo')
    monkeypatch.setattr(pipeline, 'chamar_ollama', lambda url, payload: '{"status_geral": "OK", "obs_geral": "v2"}')

    for nome in ('a.pdf', 'c.pdf'):  # um que já estava e um novo
        andamento = Andamento()
        andamento.iniciar(1, unico=nome)
        pipeline.revalidar(cfg, andamento, nome)
        assert andamento.resumo()['unico'] == nome and not andamento.resumo()['rodando']

    [execucao] = historico.listar(cfg.historico_dir)
    linhas = csvsaida.ler_csv(execucao.csv_path)
    assert [(l['Arquivo'], l['Observação Geral']) for l in linhas] == [('a.pdf', 'v2'), ('b.PDF', 'v1'), ('c.pdf', 'v2')]
    assert csvsaida.ler_csv(cfg.csv_path) == linhas
    assert execucao.meta()['total'] == 3 and execucao.meta()['revalidado_em']
    assert 'c.pdf' in execucao.pdfs()


def test_revalidar_sem_historico_cria_validacao(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(pipeline, 'extrair_texto', lambda caminho: 'Ementa: algo\n')
    monkeypatch.setattr(pipeline, 'chamar_ollama', lambda url, payload: '{"status_geral": "OK"}')
    andamento = Andamento()
    andamento.iniciar(1, unico='a.pdf')
    pipeline.revalidar(cfg, andamento, 'a.pdf')
    [execucao] = historico.listar(cfg.historico_dir)
    assert [l['Arquivo'] for l in csvsaida.ler_csv(execucao.csv_path)] == ['a.pdf']
