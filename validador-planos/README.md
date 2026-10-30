# Validador de Planos de Ensino

Aplicação em Python (Flask + gunicorn) que valida os PDFs de planos de ensino com o Ollama e publica um dashboard. Substitui o workflow de validação do n8n, com a mesma lógica de regras e o mesmo CSV (`;`, UTF-8 com BOM).

## Estrutura

```
app/            código da aplicação
tests/          testes unitários (regras, seções, extração, rotas, CSV)
resultados/     CSV gerado e detalhes/ (texto extraído, prompt e resposta da IA por plano), criados automaticamente
docker-compose.yml, Dockerfile, .env.example
```

Os PDFs ficam na pasta indicada por `PLANOS_HOST_DIR`, montada no container com escrita (o dashboard envia e exclui PDFs). Eles não entram na imagem nem no git.

## Dashboard

Em `/dashboard` é possível:

- iniciar a validação (botão **Validar agora**) e acompanhar o progresso (plano atual, barra de andamento); ao terminar, a página recarrega com os resultados;
- enviar PDFs (arrastando ou escolhendo arquivos; um PDF com o mesmo nome é substituído), abrir e excluir os da pasta;
- abrir o **Relatório** de cada plano avaliado (nova aba): a avaliação de cada campo ao lado do texto extraído para ele, o texto completo do PDF, o prompt enviado e a resposta da IA. Planos validados antes desta versão só mostram o texto depois de uma nova validação.

Enquanto uma validação roda, envio e exclusão ficam bloqueados. Não há autenticação: qualquer um que alcance a porta `APP_PORT` pode enviar e excluir PDFs.

## Rotas

| Método | Rota | Resposta |
|---|---|---|
| POST | `/validar` | `200 {"status":"iniciado"}`, `409` se já houver validação em andamento, `422` se a pasta não tiver PDFs |
| GET | `/status` | Andamento: `rodando`, `total`, `processados`, `atual`, `iniciado_em`, `finalizado_em`, `erro` |
| GET | `/dashboard` | Página HTML com os controles e os resultados da última validação |
| GET | `/planos` | Lista dos PDFs da pasta (`nome`, `tamanho`, `modificado`) |
| POST | `/planos` | Upload (multipart, campo `arquivos`, vários por vez, até 100 MB no total); `409` durante a validação |
| DELETE | `/planos?arquivo=nome.pdf` | Exclui o PDF; `409` durante a validação |
| GET | `/relatorio?arquivo=nome.pdf` | Relatório HTML do plano na última validação; `404` se ele não estiver no resultado |
| GET | `/pdf?arquivo=nome.pdf` | O PDF, só para nomes da pasta de planos |
| GET | `/health` | `{"status":"ok"}` |

Validação automática todos os dias na hora `AGENDAMENTO_HORA` (padrão 5h, fuso `TZ`).

## Controle de execução

O estado da validação fica em memória no processo do gunicorn (`app/andamento.py`), que roda com um único worker (`-w 1` no `Dockerfile`). Não aumente o número de workers: cada um teria seu próprio estado e duas validações poderiam rodar juntas. Se o container reiniciar no meio de um lote, a validação é perdida e o estado volta a livre; basta iniciar de novo.

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

4. Abra `http://IP_DO_SERVIDOR:8080/dashboard`, envie os PDFs (se a pasta estiver vazia) e clique em **Validar agora**.

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
