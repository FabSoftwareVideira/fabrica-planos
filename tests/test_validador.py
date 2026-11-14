"""Testes unitários da coordenação das avaliações (app/servicos/validador.py) e do estado em memória
(app/servicos/andamento.py). A IA não é chamada: pipeline.executar/revalidar são trocados por falsos."""
from datetime import datetime

import pytest

from app.avaliacao import pipeline
from app.config import Config
from app.servicos import validador as modulo
from app.servicos.andamento import Andamento
from app.servicos.validador import Validador


class Adiado:
    """No lugar da thread: guarda as tarefas para o teste rodar uma a uma, quando quiser."""

    def __init__(self):
        self.tarefas = []

    def __call__(self, tarefa):
        self.tarefas.append(tarefa)

    def rodar_proxima(self):
        self.tarefas.pop(0)()


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    planos = tmp_path / 'planos'
    planos.mkdir()
    cfg = Config(planos_dir=str(planos), resultados_dir=str(tmp_path / 'res'), ollama_url='', modelo='m',
                 num_ctx=1, hora_agendada=5, agendar=False)
    avaliados = []

    def revalidar(cfg_, andamento, nome):
        avaliados.append(nome)
        andamento.finalizar()

    def executar(cfg_, andamento, nomes):
        avaliados.append(tuple(nomes))
        andamento.finalizar()
    monkeypatch.setattr(pipeline, 'revalidar', revalidar)
    monkeypatch.setattr(pipeline, 'executar', executar)
    adiado = Adiado()
    return Validador(cfg, adiado), adiado, planos, avaliados


# Andamento -------------------------------------------------------------------------------------------

def test_andamento_inicia_uma_vez_e_conta_os_planos():
    a = Andamento()
    assert not a.rodando and a.resumo()['iniciado_em'] is None
    assert a.iniciar(2) and not a.iniciar(1)  # já há uma em andamento
    a.validando('a.pdf')
    a.plano_concluido()
    estado = a.resumo()
    assert estado['rodando'] and estado['atual'] == 'a.pdf' and estado['processados'] == 1 and estado['total'] == 2
    a.finalizar(erro='falhou')
    estado = a.resumo()
    assert not estado['rodando'] and estado['atual'] == '' and estado['erro'] == 'falhou' and estado['finalizado_em']
    assert a.iniciar(1, unico='b.pdf') and a.resumo()['unico'] == 'b.pdf' and a.resumo()['erro'] == ''


def test_resumo_e_uma_copia():
    a = Andamento()
    a.resumo()['rodando'] = True
    assert not a.rodando


# Lote --------------------------------------------------------------------------------------------------

def test_lote_sem_planos(ambiente):
    v, adiado, _, _ = ambiente
    assert v.iniciar_lote() == 'sem_planos' and not adiado.tarefas


def test_lote_avalia_todos_os_pdfs_e_recusa_outro_ao_mesmo_tempo(ambiente):
    v, adiado, planos, avaliados = ambiente
    (planos / 'b.pdf').write_bytes(b'%PDF-')
    (planos / 'a.pdf').write_bytes(b'%PDF-')
    (planos / 'nota.txt').write_text('x')
    assert v.iniciar_lote() is None
    assert v.iniciar_lote() == 'ocupado'
    assert v.em_avaliacao('qualquer.pdf')  # durante o lote, todos estão em avaliação
    adiado.rodar_proxima()
    assert avaliados == [('a.pdf', 'b.pdf')] and not v.andamento.rodando


# Fila --------------------------------------------------------------------------------------------------

def test_fila_avalia_um_por_vez_na_ordem(ambiente):
    v, adiado, planos, avaliados = ambiente
    for nome in ('a.pdf', 'b.pdf', 'c.pdf'):
        (planos / nome).write_bytes(b'%PDF-')
    assert v.enfileirar('a.pdf') == 0  # começou na hora
    assert v.enfileirar('b.pdf') == 1 and v.enfileirar('c.pdf') == 2
    assert v.enfileirar('b.pdf') == 1  # não entra duas vezes
    assert v.fila() == ['b.pdf', 'c.pdf'] and v.status()['fila'] == ['b.pdf', 'c.pdf']
    assert v.em_avaliacao('a.pdf') and not v.em_avaliacao('b.pdf')
    adiado.rodar_proxima()  # termina a.pdf e começa b.pdf
    assert v.status()['unico'] == 'b.pdf' and v.fila() == ['c.pdf']
    adiado.rodar_proxima()
    adiado.rodar_proxima()
    assert avaliados == ['a.pdf', 'b.pdf', 'c.pdf'] and v.fila() == [] and not adiado.tarefas


def test_fila_pula_plano_excluido_enquanto_esperava(ambiente):
    v, adiado, planos, avaliados = ambiente
    for nome in ('a.pdf', 'b.pdf', 'c.pdf'):
        (planos / nome).write_bytes(b'%PDF-')
    v.enfileirar('a.pdf')
    v.enfileirar('b.pdf')
    v.enfileirar('c.pdf')
    (planos / 'b.pdf').unlink()
    adiado.rodar_proxima()
    adiado.rodar_proxima()
    assert avaliados == ['a.pdf', 'c.pdf']


def test_remover_da_fila(ambiente):
    v, _, planos, _ = ambiente
    for nome in ('a.pdf', 'b.pdf'):
        (planos / nome).write_bytes(b'%PDF-')
    v.enfileirar('a.pdf')
    v.enfileirar('b.pdf')
    with v.trava:
        v.remover_da_fila('b.pdf')
        v.remover_da_fila('nao-esta.pdf')
    assert v.fila() == []


def test_falha_na_avaliacao_nao_trava_a_fila(ambiente, monkeypatch):
    v, adiado, planos, _ = ambiente
    for nome in ('a.pdf', 'b.pdf'):
        (planos / nome).write_bytes(b'%PDF-')

    def quebra(cfg_, andamento, nome):
        andamento.finalizar(erro='x')
        raise RuntimeError('IA fora do ar')
    monkeypatch.setattr(pipeline, 'revalidar', quebra)
    v.enfileirar('a.pdf')
    v.enfileirar('b.pdf')
    with pytest.raises(RuntimeError):
        adiado.rodar_proxima()
    assert v.status()['unico'] == 'b.pdf'  # a próxima começou mesmo assim


# Inicialização -----------------------------------------------------------------------------------------

def test_preparar_historico_apaga_o_lock_antigo(ambiente):
    v, _, _, _ = ambiente
    import os
    os.makedirs(v.cfg.resultados_dir)
    lock = os.path.join(v.cfg.resultados_dir, 'validacao.lock')
    open(lock, 'w').close()
    v.preparar_historico()
    assert not os.path.exists(lock)


def test_preparar_historico_nao_derruba_o_app(ambiente, monkeypatch, caplog):
    v, _, _, _ = ambiente
    from app.armazenamento import historico

    def falha(*args):
        raise OSError('disco cheio')
    monkeypatch.setattr(historico, 'migrar_legado', falha)
    v.preparar_historico()
    assert 'Falha ao preparar o histórico' in caplog.text


class _Fim(Exception):
    pass


def test_agendador_dispara_o_lote_na_hora_marcada(ambiente, monkeypatch, caplog):
    v, adiado, _, _ = ambiente
    caplog.set_level('INFO')
    esperas = []

    class Relogio(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 14, 6, 30)  # depois das 5h: o próximo é amanhã

    def dormir(segundos):
        esperas.append(segundos)
        if len(esperas) > 1:
            raise _Fim
    monkeypatch.setattr(modulo, 'datetime', Relogio)
    monkeypatch.setattr(modulo.time, 'sleep', dormir)
    with pytest.raises(_Fim):
        v._agendador()
    assert esperas[0] == 22.5 * 3600
    assert 'não iniciada: sem_planos' in caplog.text  # sem PDFs, só registra
