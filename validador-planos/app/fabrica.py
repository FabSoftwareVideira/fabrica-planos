from dataclasses import dataclass

from flask import Flask

from . import rotas
from .paginas import comum as paginas
from .armazenamento.revisoes import Revisoes
from .armazenamento.usuarios import Usuarios
from .config import Config, carregar
from .servicos.planos import PastaDePlanos
from .servicos.revisao import Revisao
from .servicos.validador import Validador


@dataclass(frozen=True)
class Servicos:
    """Dependências compartilhadas pelas rotas (ver rotas/comum.py: servicos())."""
    cfg: Config
    validador: Validador
    planos: PastaDePlanos
    usuarios: Usuarios
    revisao: Revisao


def criar_app(cfg=None, executar=None):
    """Monta a aplicação: configuração, serviços e rotas. `executar` troca o modo de rodar as
    avaliações (padrão: numa thread; os testes passam uma função que roda na hora)."""
    cfg = cfg or carregar()
    validador = Validador(cfg, executar) if executar else Validador(cfg)
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # soma dos PDFs de um envio
    usuarios = Usuarios(cfg.usuarios_path)
    app.extensions['servicos'] = Servicos(cfg, validador, PastaDePlanos(cfg, validador), usuarios,
                                           Revisao(cfg, Revisoes(cfg.revisoes_path), usuarios))
    paginas.registrar(app)
    rotas.registrar(app)
    validador.preparar_historico()
    if cfg.agendar:
        validador.iniciar_agendador()
    return app
