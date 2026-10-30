# Validador de Planos de Ensino

Aplicação em Python (Flask + gunicorn) que valida os PDFs de planos de ensino com o Ollama e publica um dashboard. Substitui o workflow de validação do n8n, com a mesma lógica de regras e o mesmo CSV (`;`, UTF-8 com BOM).

## Estrutura

```
app/            código da aplicação
tests/          testes unitários (regras, seções, extração, rotas, CSV)
resultados/     histórico das validações e cópia do CSV da última (criados automaticamente; ver "Histórico")
docker-compose.yml, Dockerfile, .env.example
```

Os PDFs ficam na pasta indicada por `PLANOS_HOST_DIR`, montada no container com escrita (o dashboard envia e exclui PDFs). Eles não entram na imagem nem no git.

## Dashboard

Em `/dashboard` é possível:

- iniciar a validação (botão **Validar agora**) e acompanhar o progresso (plano atual, barra de andamento); ao terminar, a página abre os resultados novos;
- enviar PDFs (arrastando ou escolhendo arquivos; um PDF com o mesmo nome é substituído), abrir e excluir os da pasta, um a um ou todos de uma vez (**Excluir todos**, que não apaga o histórico). Só entram arquivos `.pdf` de até `PDF_MAX_MB` MB (padrão 10) que abram e tenham texto selecionável; digitalizados (só imagem) são recusados com o aviso de que precisam de OCR;
- abrir o **Relatório** de cada plano avaliado: a avaliação de cada campo ao lado do texto extraído para ele, o texto completo do PDF, o prompt enviado e a resposta da IA. A barra do topo volta ao dashboard já no card do plano (ou `Esc`) e passa para o plano anterior/próximo (ou `←`/`→`). Planos validados antes desta versão só mostram o texto depois de uma nova validação;
- consultar as últimas validações (seletor ao lado de **Resultados**) e baixar o CSV de cada uma e o **zip com os PDFs** da última.

Enquanto uma validação roda, envio e exclusão ficam bloqueados. Não há autenticação: qualquer um que alcance a porta `APP_PORT` pode enviar e excluir PDFs.

## Rotas

| Método | Rota | Resposta |
|---|---|---|
| POST | `/validar` | `200 {"status":"iniciado"}`, `409` se já houver validação em andamento, `422` se a pasta não tiver PDFs |
| GET | `/status` | Andamento: `rodando`, `total`, `processados`, `atual`, `iniciado_em`, `finalizado_em`, `erro` |
| GET | `/dashboard?validacao=ID` | Página HTML com os controles e os resultados; sem `validacao`, a última |
| GET | `/planos` | Lista dos PDFs da pasta (`nome`, `tamanho`, `modificado`) |
| POST | `/planos` | Upload (multipart, campo `arquivos`, vários por vez, até `PDF_MAX_MB` por arquivo e 100 MB no total). Responde `salvos` e `recusados` (com o motivo); `409` durante a validação |
| DELETE | `/planos?arquivo=nome.pdf` | Exclui o PDF; `409` durante a validação |
| DELETE | `/planos/todos` | Exclui todos os PDFs da pasta (`{"excluidos": N}`); `409` durante a validação |
| GET | `/relatorio?validacao=ID&arquivo=nome.pdf` | Relatório HTML do plano; sem `validacao`, a última; `404` se o plano não estiver nela |
| GET | `/validacoes` | Histórico: resumo de cada validação guardada, da mais recente para a mais antiga |
| GET | `/validacoes/ID/csv` | CSV da validação |
| GET | `/validacoes/ID/pdfs.zip` | Zip com os PDFs validados; só para a última validação (`404` nas demais) |
| GET | `/validacoes/ID/pdf?arquivo=nome.pdf` | O PDF como estava na validação (só a última) |
| GET | `/pdf?arquivo=nome.pdf` | O PDF atual da pasta de planos |
| GET | `/health` | `{"status":"ok"}` |

Validação automática todos os dias na hora `AGENDAMENTO_HORA` (padrão 5h, fuso `TZ`).

## Histórico

Cada validação fica em `resultados/historico/AAAAMMDD-HHMMSS/`, com o CSV (`validacao_planos.csv`), os detalhes de cada plano (`detalhes/`, usados no relatório) e um resumo (`meta.json`). Ficam as `HISTORICO_MAX` mais recentes (padrão 3); as mais antigas são apagadas ao fim de cada validação. Uma cópia dos PDFs (`pdfs/`) é guardada só na mais recente, para o zip e para abrir o PDF exatamente como foi avaliado; nas anteriores fica só o resultado. Uma validação interrompida por erro também entra no histórico, com o que chegou a ser validado.

`resultados/validacao_planos.csv` continua sendo gravado com a última validação, para quem lê o arquivo direto. Na primeira subida desta versão, o resultado anterior (esse CSV e a pasta `resultados/detalhes/`) é movido para o histórico.

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
- A extração usa `pdfplumber`, que lê só a camada de texto. PDFs escaneados precisam de OCR antes de entrar na pasta: o upload os recusa e, se um deles for copiado direto para a pasta, a validação o marca como `ERRO` ("precisa passar por OCR") sem chamar a IA.
- Para trocar o modelo, altere `OLLAMA_MODEL` (e, se quiser, `OLLAMA_NUM_CTX`) no `.env`, baixe o modelo com `docker compose exec ollama ollama pull <modelo>` e rode `docker compose up -d`. Um `docker compose restart` não recarrega o `.env`.
