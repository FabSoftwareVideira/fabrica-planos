from . import administracao, meus_planos, painel, publico, validacoes

# Cada área do sistema é um Blueprint num arquivo próprio.
BLUEPRINTS = (publico.bp, painel.bp, validacoes.bp, administracao.bp, meus_planos.bp)


def registrar(app):
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
