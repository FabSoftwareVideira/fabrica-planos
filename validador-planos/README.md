# Validador de Planos de Ensino

Aplicação em Python (Flask + gunicorn) que valida os PDFs de planos de ensino com o Ollama e publica um dashboard. Substitui o workflow de validação do n8n, com a mesma lógica de regras e o mesmo CSV (`;`, UTF-8 com BOM).

## Estrutura

```
app/            código da aplicação
tests/          testes unitários (regras, seções, lock, CSV)
resultados/     CSV gerado e arquivo de lock (criado automaticamente)
docker-compose.yml, Dockerfile, .env.example
```

Os PDFs ficam na pasta indicada por `PLANOS_HOST_DIR`, montada somente leitura no container. Eles não entram na imagem nem no git.

## Rotas

| Método | Rota | Resposta |
|---|---|---|
| POST | `/validar` | `200 {"status":"iniciado"}`, `409` se já houver validação em andamento, `422` se a pasta não tiver PDFs |
| GET | `/dashboard` | Página HTML com os resultados da última validação |
| GET | `/pdf?arquivo=nome.pdf` | O PDF, só para nomes da pasta de planos |
| GET | `/health` | `{"status":"ok"}` |

Validação automática todos os dias na hora `AGENDAMENTO_HORA` (padrão 5h, fuso `TZ`).

## Lock

Ao iniciar, a validação grava a hora atual em `resultados/validacao.lock` e renova essa hora a cada plano. Enquanto a última atualização tiver menos de 15 minutos, novas chamadas recebem `409`. Ao terminar (ou falhar), o arquivo é zerado e a próxima chamada é aceita na hora.

## Subir no servidor

1. Copie a configuração e ajuste os valores (caminho dos PDFs, portas):

```bash
cp .env.example .env
```

2. Suba os containers:

```bash
docker compose up -d --build
```

3. Baixe o modelo no Ollama existente (uma vez; `ollama` é o nome do container):

```bash
docker exec ollama ollama pull qwen2.5:7b
```

4. Teste:

```bash
curl -i -X POST http://localhost:8080/validar
```

Depois abra `http://IP_DO_SERVIDOR:8080/dashboard`.

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

## Observações

- O validador não sobe um Ollama próprio: usa o que já roda no servidor, em `OLLAMA_URL` (padrão `http://host.docker.internal:11434`, a porta publicada no host). Se o firewall do host bloquear o tráfego dos containers para essa porta, libere-a para a rede do Docker.
- A extração usa `pdfplumber`, que lê só a camada de texto. PDFs escaneados continuam precisando de OCR antes de entrar na pasta.
- Para trocar o modelo, altere `OLLAMA_MODEL` no `.env` e reinicie o serviço `app`.
