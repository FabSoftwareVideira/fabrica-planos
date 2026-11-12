from . import administracao, assinatura_govbr, coordenacao, govbr, meus_planos, painel, publico, validacoes

# Cada área do sistema é um Blueprint num arquivo próprio.
BLUEPRINTS = (publico.bp, govbr.bp, painel.bp, validacoes.bp, coordenacao.bp, administracao.bp, meus_planos.bp,
              assinatura_govbr.bp)


def registrar(app):
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
