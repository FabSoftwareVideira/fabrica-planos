# Imagem em dois modos (ver README, "Rodar em desenvolvimento" e "Subir no servidor"):
#   desenvolvimento  servidor do Flask com recarga automática; o código vem montado do host
#   producao         gunicorn com o código copiado na imagem (último estágio: o padrão do docker build)

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt


FROM base AS desenvolvimento

# pytest para rodar os testes dentro do container
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt

# O código não é copiado: docker-compose.dev.yml monta a pasta do projeto em /app, e o Flask
# recarrega a cada arquivo salvo (Python, templates, CSS e JS).
CMD ["flask", "--app", "app.web", "run", "--debug", "--host", "0.0.0.0", "--port", "8000"]


FROM base AS producao

COPY app ./app

# Um único worker: a fila e o lock ficam dentro do processo.
CMD ["gunicorn", "-w", "1", "--threads", "4", "-b", "0.0.0.0:8000", "--access-logfile", "-", "app.web:app"]
