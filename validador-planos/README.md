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
- **revalidar um plano só** (botão ↻ no card, no relatório ou na lista de PDFs, útil depois que o docente corrige o PDF): a linha dele na última validação é substituída (ou acrescentada, se for um PDF novo), sem rodar o lote;
- filtrar os resultados por texto (disciplina ou docente, sem diferenciar acentos), status e campo com problema; os filtros ficam guardados enquanto a aba estiver aberta;
- consultar as últimas validações (seletor ao lado de **Resultados**) e baixar o CSV de cada uma e o **zip com os PDFs** da última.

Enquanto uma validação roda, envio e exclusão ficam bloqueados. A aplicação não tem autenticação própria: o acesso passa pelo Caddy (ver "Acesso externo"), que pede usuário e senha.

## Rotas

| Método | Rota | Resposta |
|---|---|---|
| POST | `/validar` | `200 {"status":"iniciado"}`, `409` se já houver validação em andamento, `422` se a pasta não tiver PDFs |
| POST | `/validar?arquivo=nome.pdf` | Revalida só esse plano e atualiza a última validação; `404` se o PDF não estiver na pasta, `409` se houver validação em andamento |
| GET | `/status` | Andamento: `rodando`, `total`, `processados`, `atual`, `iniciado_em`, `finalizado_em`, `erro` e `unico` (plano, numa revalidação) |
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

1. Copie a configuração e ajuste os valores (caminho dos PDFs, portas, `APP_HOST`, login):

```bash
cp .env.example .env
```

Gere o hash da senha e cole em `APP_SENHA_HASH`, entre aspas simples:

```bash
docker run --rm caddy:2 caddy hash-password --plaintext 'sua-senha'
```

2. Suba o validador, o Ollama e o Caddy:

```bash
docker compose up -d --build
```

3. Baixe o modelo no Ollama (uma vez; fica no volume `ollama-data`):

```bash
docker compose exec ollama ollama pull qwen2.5:7b
```

4. Abra `https://APP_HOST:APP_PORT/dashboard` (ex.: `https://planos.200-135-55-29.sslip.io:9090/dashboard`), entre com o login, envie os PDFs (se a pasta estiver vazia) e clique em **Validar agora**.

## Acesso externo

Só o serviço `caddy` publica portas: `APP_PORT` (a aplicação, com HTTPS e senha) e 80 (usada pelo Let's Encrypt para emitir e renovar o certificado; nela o Caddy só responde ao desafio e redireciona para HTTPS). O `app` e o Ollama ficam na rede interna do compose; o Ollama também em `127.0.0.1:OLLAMA_PORT` no host.

- `APP_HOST` é o nome que resolve para o IP público. Sem domínio próprio, `qualquer-nome.200-135-55-29.sslip.io` resolve para 200.135.55.29.
- O firewall da frente precisa encaminhar as portas 80 e `APP_PORT` para a máquina. Sem a 80 o certificado não é emitido; nesse caso, ou para testar localmente, deixe `APP_HOST` vazio e o Caddy serve HTTP puro em `APP_PORT`.
- Os certificados ficam no volume `caddy-data`. Ao trocar a senha, rode `docker compose up -d caddy`.

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
- O texto extraído é limpo antes da separação em seções: saem o rodapé do SIGAA ("Este documento foi emitido…", endereço, telefone), o cabeçalho institucional repetido a partir da 2ª página, títulos de bloco e cabeçalhos de tabela, e o bloco "Matrícula Docente(s)" de dentro da ementa (ele vai para a identificação).
- Horário de atendimento é decidido por regra, sem a IA: OK se a seção informa dia ou hora; INCOMPLETO se só indica onde consultar (quadro de horários, Planus, PTD, site); AUSENTE se vazia.
- A extração usa `pdfplumber`, que lê só a camada de texto. PDFs escaneados precisam de OCR antes de entrar na pasta: o upload os recusa e, se um deles for copiado direto para a pasta, a validação o marca como `ERRO` ("precisa passar por OCR") sem chamar a IA.
- Para trocar o modelo, altere `OLLAMA_MODEL` (e, se quiser, `OLLAMA_NUM_CTX`) no `.env`, baixe o modelo com `docker compose exec ollama ollama pull <modelo>` e rode `docker compose up -d`. Um `docker compose restart` não recarrega o `.env`.
