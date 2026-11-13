import logging
import os
from dataclasses import dataclass

from flask import Flask

from . import rotas
from .paginas import comum as paginas
from .armazenamento.revisoes import Revisoes
from .armazenamento.usuarios import Usuarios
from .banco import Banco
from .config import Config, carregar
from .servicos.assinatura import Assinaturas
from .servicos.backup import Backup
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
    assinaturas: Assinaturas
    backup: Backup


def criar_app(cfg=None, executar=None):
    """Monta a aplicação: configuração, serviços e rotas. `executar` troca o modo de rodar as
    avaliações (padrão: numa thread; os testes passam uma função que roda na hora)."""
    cfg = cfg or carregar()
    validador = Validador(cfg, executar) if executar else Validador(cfg)
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # soma dos PDFs de um envio
    banco = Banco(cfg.database_url)
    os.makedirs(cfg.resultados_dir, exist_ok=True)
    usuarios = Usuarios(banco)
    revisoes = Revisoes(banco)  # excluir um plano também apaga a revisão dele
    revisao = Revisao(cfg, revisoes, usuarios)
    assinaturas = Assinaturas(cfg, revisao)
    backup = Backup(cfg, validador, banco)
    app.extensions['servicos'] = Servicos(cfg, validador, PastaDePlanos(cfg, validador, revisoes, assinaturas),
                                           usuarios, revisao, assinaturas, backup)
    paginas.registrar(app)
    rotas.registrar(app)
    if cfg.login_simulado:  # só em desenvolvimento (docker-compose.dev.yml)
        from .rotas import login_simulado
        app.wsgi_app = login_simulado.Middleware(app.wsgi_app)
        app.register_blueprint(login_simulado.bp)
        logging.getLogger(__name__).warning('LOGIN SIMULADO ATIVO (/dev/login): use só em desenvolvimento')
    validador.preparar_historico()
    if cfg.agendar:
        validador.iniciar_agendador()
    if cfg.backup_agendar:
        backup.iniciar_agendador()
    return app
