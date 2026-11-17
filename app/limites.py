import threading
import time
from collections import deque

# Limite de requisições (rotas/publico.py: limitar). Janela deslizante em memória: o gunicorn roda com um só
# worker (o validador já depende disso), então um contador por processo vale para o sistema todo.
#
# Política: (nome, métodos, teste do caminho, contado por 'ip' ou 'usuario', limite, janela em segundos).
# Vale a primeira regra que casar. Os números ficam bem acima do uso normal; o objetivo é barrar robôs,
# loops e abusos (cada envio de plano dispara a IA, o recurso mais caro do servidor).

TODOS = None
LEITURA = frozenset({'GET', 'HEAD'})
ESCRITA = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})

LOGIN = ('/auth/govbr/login', '/auth/govbr/callback', '/auth/govbr/assinatura/', '/conta/govbr/vincular',
         '/assinatura/govbr/', '/entrar')
ENVIOS = ('/meus-planos', '/meus-planos/assinatura', '/validar', '/webhook/validar')
PUBLICAS = ('/', '/privacidade')

REGRAS = (
    ('login', TODOS, lambda c: c.startswith(LOGIN), 'ip', 20, 60),
    ('envio', ESCRITA, lambda c: c in ENVIOS, 'usuario', 30, 3600),
    ('exportacao', LEITURA, lambda c: c == '/coordenacao/assinados.zip', 'usuario', 10, 3600),
    ('pdf_publico', LEITURA, lambda c: c.startswith('/transparencia') and c.endswith('.pdf'), 'ip', 60, 60),
    ('publico', TODOS, lambda c: c in PUBLICAS or c.startswith('/transparencia'), 'ip', 120, 60),
    ('geral', TODOS, lambda c: True, 'usuario', 600, 60),
)
# Fora da contagem: arquivos estáticos, o healthcheck e a conferência do login que o Caddy faz a cada pedido
ISENTAS = ('/static/', '/health', '/auth/verificar')


def regra(metodo, caminho):
    """A regra que vale para o pedido, ou None se ele não é contado."""
    if caminho.startswith(ISENTAS):
        return None
    for r in REGRAS:
        nome, metodos, casa, por, limite, janela = r
        if (metodos is TODOS or metodo in metodos) and casa(caminho):
            return r
    return None  # pragma: no cover (a regra geral casa com tudo)


class Limitador:
    def __init__(self, relogio=time.monotonic):
        self.relogio = relogio
        self._pedidos = {}  # chave: deque com os instantes dos pedidos dentro da janela
        self._trava = threading.Lock()

    def conferir(self, chave, limite, janela):
        """0 se o pedido pode seguir (e ele é contado); senão, em quantos segundos tentar de novo."""
        agora = self.relogio()
        with self._trava:
            fila = self._pedidos.setdefault(chave, deque())
            while fila and fila[0] <= agora - janela:
                fila.popleft()
            if len(fila) >= limite:
                return max(1, int(fila[0] + janela - agora) + 1)
            fila.append(agora)
            if len(self._pedidos) > 10000:  # não deixa a memória crescer com chaves antigas
                self._limpar(agora)
            return 0

    def _limpar(self, agora):
        maior_janela = max(r[5] for r in REGRAS)
        for chave in [k for k, f in self._pedidos.items() if not f or f[-1] <= agora - maior_janela]:
            del self._pedidos[chave]
