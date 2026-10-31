import threading
from datetime import datetime

# Estado da validação em memória. Substitui o arquivo validacao.lock do n8n: o gunicorn roda com
# um único processo (-w 1), então o estado vive nele. Se o processo cair, a validação cai junto e
# o estado volta a "livre" ao reiniciar, sem lock esquecido.


class Andamento:
    def __init__(self):
        self._trava = threading.Lock()
        self._estado = {
            'rodando': False,
            'total': 0,
            'processados': 0,
            'atual': '',
            'iniciado_em': None,
            'finalizado_em': None,
            'erro': '',
            'unico': '',  # nome do plano quando é a revalidação de um só
        }

    def iniciar(self, total, unico=''):
        """Marca a validação como iniciada. Devolve False se já houver uma em andamento."""
        with self._trava:
            if self._estado['rodando']:
                return False
            self._estado.update(
                rodando=True, total=total, processados=0, atual='',
                iniciado_em=_agora(), finalizado_em=None, erro='', unico=unico,
            )
            return True

    def validando(self, nome):
        with self._trava:
            self._estado['atual'] = nome

    def plano_concluido(self):
        with self._trava:
            self._estado['processados'] += 1

    def finalizar(self, erro=''):
        with self._trava:
            self._estado.update(rodando=False, atual='', finalizado_em=_agora(), erro=erro)

    @property
    def rodando(self):
        with self._trava:
            return self._estado['rodando']

    def resumo(self):
        with self._trava:
            return dict(self._estado)


def _agora():
    return datetime.now().isoformat(timespec='seconds')
