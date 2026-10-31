"""Ponto de entrada do gunicorn (app.web:app). A montagem fica em app/fabrica.py."""
import logging

from .fabrica import criar_app

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

app = criar_app()
