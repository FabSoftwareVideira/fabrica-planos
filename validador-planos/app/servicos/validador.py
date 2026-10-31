import logging
import os
import threading
import time
from datetime import datetime, timedelta

from ..armazenamento import csvsaida, historico
from ..avaliacao import pipeline
from .andamento import Andamento

log = logging.getLogger(__name__)


def _em_thread(tarefa):
    threading.Thread(target=tarefa, daemon=True).start()


class Validador:
    """Coordena as avaliações: o lote com todos os PDFs, a revalidação de um plano e a fila.

    Uma avaliação roda por vez (a GPU é uma só); ao terminar, a próxima da fila começa. O estado
    (andamento e fila) vive na memória do processo, por isso o gunicorn roda com um único worker.
    `executar` recebe a tarefa já montada; o padrão a roda numa thread (os testes a rodam na hora).
    """

    def __init__(self, cfg, executar=_em_thread):
        self.cfg = cfg
        self.andamento = Andamento()
        # Serializa o início das avaliações e as alterações na pasta de planos: não se mexe nos PDFs
        # enquanto um lote está sendo validado. Também protege a fila.
        self.trava = threading.Lock()
        self._fila = []
        self._executar = executar

    # Disparo ------------------------------------------------------------------------------------

    def _disparar(self, alvo, *args):
        """Roda a avaliação e, ao terminar, começa o próximo plano da fila. Chamar fora da trava."""
        def tarefa():
            try:
                alvo(*args)
            finally:
                self.proximo_da_fila()
        self._executar(tarefa)

    def iniciar_lote(self):
        """Valida todos os PDFs da pasta. Devolve None se iniciou, ou o motivo ('ocupado' / 'sem_planos')."""
        with self.trava:
            nomes = pipeline.listar_pdfs(self.cfg.planos_dir)
            if not nomes:
                return 'sem_planos'
            if not self.andamento.iniciar(len(nomes)):
                return 'ocupado'
        self._disparar(pipeline.executar, self.cfg, self.andamento, nomes)
        return None

    # Fila ---------------------------------------------------------------------------------------

    def enfileirar(self, nome):
        """Põe o plano na fila (uma vez só) e o começa se nada estiver rodando. Devolve a posição na
        fila (0 se já começou)."""
        with self.trava:
            if nome not in self._fila:
                self._fila.append(nome)
        self.proximo_da_fila()
        with self.trava:
            return self._fila.index(nome) + 1 if nome in self._fila else 0

    def proximo_da_fila(self):
        with self.trava:
            nome = self._tirar_proximo()
        if nome:
            self._disparar(pipeline.revalidar, self.cfg, self.andamento, nome)

    def _tirar_proximo(self):
        """Com a trava: tira da fila e marca como iniciado o próximo plano, se nada estiver rodando."""
        while self._fila:
            nome = self._fila[0]
            if not os.path.isfile(os.path.join(self.cfg.planos_dir, nome)):  # excluído enquanto esperava
                self._fila.pop(0)
                continue
            if not self.andamento.iniciar(1, unico=nome):
                return None
            return self._fila.pop(0)
        return None

    def remover_da_fila(self, nome):
        """Com a trava (quem chama já a segura)."""
        if nome in self._fila:
            self._fila.remove(nome)

    def fila(self):
        with self.trava:
            return list(self._fila)

    def status(self):
        return {**self.andamento.resumo(), 'fila': self.fila()}

    def em_avaliacao(self, nome):
        """True se um lote estiver rodando ou se este plano estiver sendo avaliado agora."""
        estado = self.andamento.resumo()
        return estado['rodando'] and (not estado['unico'] or estado['unico'] == nome)

    # Inicialização ------------------------------------------------------------------------------

    def preparar_historico(self):
        # Ao subir não há validação rodando: dá para migrar o resultado da versão anterior e limpar sobras.
        cfg = self.cfg
        try:
            historico.migrar_legado(cfg.historico_dir, cfg.csv_path, os.path.join(cfg.resultados_dir, 'detalhes'),
                                    csvsaida.ler_csv)
            historico.podar(cfg.historico_dir)  # versões anteriores guardavam várias validações
            lock_antigo = os.path.join(cfg.resultados_dir, 'validacao.lock')  # da versão com lock em arquivo
            if os.path.exists(lock_antigo):
                os.remove(lock_antigo)
        except OSError:
            log.exception('Falha ao preparar o histórico de validações')

    def iniciar_agendador(self):
        threading.Thread(target=self._agendador, daemon=True).start()

    def _agendador(self):
        """Dispara o lote todo dia na hora configurada, se não houver outra avaliação em andamento."""
        while True:
            agora = datetime.now()
            alvo = agora.replace(hour=self.cfg.hora_agendada, minute=0, second=0, microsecond=0)
            if alvo <= agora:
                alvo += timedelta(days=1)
            time.sleep((alvo - agora).total_seconds())
            motivo = self.iniciar_lote()
            if motivo:
                log.info('Validação agendada não iniciada: %s', motivo)
