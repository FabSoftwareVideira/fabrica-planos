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

2. Suba o validador e o Ollama:

```bash
docker compose up -d --build
```

3. Baixe o modelo no Ollama (uma vez; fica no volume `ollama-data`):

```bash
docker compose exec ollama ollama pull qwen2.5:7b
```

4. Teste:

```bash
curl -i -X POST http://localhost:8080/validar
```

Depois abra `http://IP_DO_SERVIDOR:8080/dashboard`.

## Conferir a extração de um plano

Mostra o texto extraído do PDF e como ele foi separado em seções (com `--prompt`, também o prompt enviado ao Ollama), sem chamar a IA:

```bash
docker compose exec app python -m app.depurar "2026-2 - Banco Dados II - Leila.pdf" --prompt
```

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

## Observações

- O Ollama roda como serviço `ollama` do próprio compose; o validador o alcança pela rede interna em `http://ollama:11434`. No host, ele fica em `OLLAMA_PORT` (padrão 11434), aceitando só conexões locais; para liberar na rede, use `OLLAMA_BIND=0.0.0.0` (o Ollama não tem autenticação). Não altere `OLLAMA_URL` ao trocar a porta. Os modelos ficam no volume `ollama-data` e sobrevivem a `docker compose down` (só `down -v` os apaga). Para usar GPU NVIDIA, descomente o bloco `deploy` do serviço no `docker-compose.yml`.
- A extração usa `pdfplumber`, que lê só a camada de texto. PDFs escaneados continuam precisando de OCR antes de entrar na pasta.
- Para trocar o modelo, altere `OLLAMA_MODEL` (e, se quiser, `OLLAMA_NUM_CTX`) no `.env`, baixe o modelo com `docker compose exec ollama ollama pull <modelo>` e rode `docker compose up -d`. Um `docker compose restart` não recarrega o `.env`.
