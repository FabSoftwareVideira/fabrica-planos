from . import (administracao, assinatura_govbr, coordenacao, disciplinas, govbr, meus_planos, painel, publico,
               transparencia, validacoes)

# Cada área do sistema é um Blueprint num arquivo próprio.
BLUEPRINTS = (publico.bp, govbr.bp, painel.bp, validacoes.bp, coordenacao.bp, disciplinas.bp, administracao.bp,
              meus_planos.bp, assinatura_govbr.bp, assinatura_govbr.retorno, transparencia.bp)


def registrar(app):
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
