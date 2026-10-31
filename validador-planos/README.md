# Validador de Planos de Ensino

Aplicação em Python (Flask + gunicorn) que valida os PDFs de planos de ensino com o Ollama e publica um dashboard. Substitui o workflow de validação do n8n, com a mesma lógica de regras e o mesmo CSV (`;`, UTF-8 com BOM).

## Estrutura

```
app/
  web.py            entrada do gunicorn (app.web:app)
  fabrica.py        Application Factory: cria o Flask, os serviços e registra as rotas
  config.py         configuração lida do ambiente (.env)
  depurar.py        linha de comando para conferir a extração de um PDF
  avaliacao/        como um plano é avaliado: extração do PDF, seções, prompt, Ollama, regras e o pipeline
  armazenamento/    arquivos em resultados/: CSV, detalhes por plano, histórico e dono de cada PDF
  servicos/         casos de uso com estado: Validador (lote, fila, agendador) e PastaDePlanos (envio/exclusão)
  rotas/            Blueprints, um por área: publico, painel, validacoes, administracao, meus_planos
  paginas/          dados de cada página (contexto do template) e funções comuns aos templates
  templates/        HTML das páginas em Jinja: base.html (esqueleto), _macros.html e uma por página
  static/           CSS e JavaScript das páginas (css/, js/), servidos em /static com versão no endereço;
                    vendor/ tem o Design System gov.br, a fonte Rawline e o Font Awesome (scripts/atualizar_vendor.sh)
tests/              testes unitários (regras, seções, extração, pipeline, rotas, CSV)
resultados/         histórico das validações e cópia do CSV da última (criados automaticamente; ver "Histórico")
docker-compose.yml, Dockerfile, .env.example, Caddyfile
```

As camadas só dependem das de baixo: `rotas` → `servicos` → `avaliacao`/`armazenamento`, e `rotas` → `paginas` → `templates`. Cada rota monta o contexto com a função `contexto()` do módulo da página e chama `render_template`; o Jinja escapa os valores automaticamente. `/static` (CSS, JS, fontes e ícones) é público, no app e no Caddy, porque a página inicial também o usa. As rotas só traduzem HTTP (parâmetros, códigos de resposta) e chamam os serviços, que guardam as regras de negócio (quem pode substituir um PDF, fila, bloqueio durante o lote) e avisam problemas com exceções (`Ocupado`, `NaoEncontrado`, `Proibido`). Os serviços são criados uma vez em `criar_app()` e ficam em `app.extensions['servicos']`; nos testes, `criar_app(cfg, executar=...)` roda as avaliações na hora, sem thread.

Os PDFs ficam na pasta indicada por `PLANOS_HOST_DIR`, montada no container com escrita (o dashboard envia e exclui PDFs). Eles não entram na imagem nem no git.

## Interface (Padrão Digital de Governo)

As páginas seguem o [Padrão Digital de Governo](https://www.gov.br/ds/) (Design System gov.br, `@govbr-ds/core` 3.7): página inicial, dashboard, relatório e Meus planos. Na página inicial, o botão "Entrar com Google" mantém o visual pedido pelas diretrizes do Google.

- `templates/_ds.html` carrega o CSS do DS, a fonte e os ícones; `_cabecalho.html` e `_rodape.html` são o cabeçalho e o rodapé no padrão.
- `static/css/ds.css` tem os ajustes comuns às páginas migradas; cada página tem o seu CSS para o que é só dela.
- As bibliotecas ficam copiadas em `static/vendor` (sem CDN). Para trocar de versão, ajuste as versões no topo de `scripts/atualizar_vendor.sh`, rode o script (precisa de npm) e confira as páginas.
- Só o CSS do DS é usado; os componentes que dependem do JavaScript do DS (menus, upload) ficam de fora por enquanto.

## Dashboard

Em `/dashboard` é possível:

- iniciar a validação (botão **Validar agora**) e acompanhar o progresso (plano atual, barra de andamento); ao terminar, a página abre os resultados novos;
- enviar PDFs (arrastando ou escolhendo arquivos; um PDF com o mesmo nome é substituído), abrir e excluir os da pasta, um a um ou todos de uma vez (**Excluir todos**, que não apaga o histórico). Só entram arquivos `.pdf` de até `PDF_MAX_MB` MB (padrão 10) que abram e tenham texto selecionável; digitalizados (só imagem) são recusados com o aviso de que precisam de OCR;
- abrir o **Relatório** de cada plano avaliado: a avaliação de cada campo ao lado do texto extraído para ele, o texto completo do PDF, o prompt enviado e a resposta da IA. A barra do topo volta ao dashboard já no card do plano (ou `Esc`) e passa para o plano anterior/próximo (ou `←`/`→`). Planos validados antes desta versão só mostram o texto depois de uma nova validação;
- **revalidar um plano só** (botão ↻ no card, no relatório ou na lista de PDFs, útil depois que o docente corrige o PDF): a linha dele na última validação é substituída (ou acrescentada, se for um PDF novo), sem rodar o lote;
- ver os resultados agrupados, com o resumo de cada grupo, escolhendo em **Agrupar por**: curso e período (padrão; ver "Curso e período"), só período, só curso, docente, situação (aprovados, pendentes…) ou sem agrupar. O agrupamento é feito no navegador e a escolha fica guardada nele;
- baixar o **zip com os PDFs de um grupo** (link no cabeçalho do grupo): leva os planos visíveis nele, respeitando os filtros. Como o zip geral, só existe para a última validação;
- filtrar os resultados por texto (disciplina ou docente, sem diferenciar acentos), curso e período, status e campo com problema; os filtros ficam guardados enquanto a aba estiver aberta;
- consultar as últimas validações (seletor ao lado de **Resultados**) e baixar o CSV de cada uma e o **zip com os PDFs** da última.

Enquanto uma validação geral roda, envio e exclusão pelo administrador ficam bloqueados; o envio pelo professor (em "Meus planos") é aceito e avaliado em seguida. O acesso exige login com a conta Google `@ifc.edu.br` (ver "Login"). Qualquer servidor consulta resultados, relatórios, PDFs, CSV e zip e entrega os próprios planos; só os administradores (`ADMIN_EMAILS`) veem e usam **Validar agora**, ↻ Revalidar, envio e exclusão de quaisquer PDFs.

## Curso e período

O cabeçalho do plano gerado pelo SIGAA identifica o componente, o curso e o período (`app/avaliacao/identificacao.py`):

| Oferta | Exemplo no PDF | Curso | Período |
|---|---|---|---|
| Graduação (semestral) | `CCC0723 - DESENVOLVIMENTO WEB I (60h) - Turma: 01 (2026.2)` | `CC` (2 primeiras letras do código) → Ciência da Computação | 2º semestre de 2026 |
| Técnico (anual) | `INC0713-1 - WEB DESIGN (60h) - Turma: 03 (2026)` e `Turma: [TÉCNICO EM INFORMÁTICA INTEGRADO AO ENSINO MÉDIO - IN07 (MT) - A (2026)]` | nome que vem entre colchetes | 2026 (anual) |

O docente vem do bloco "Matrícula Docente(s)" (`1773245 LUCILENE DAL MEDICO BAERLE - 60h`) e é usado no agrupamento por docente e na busca.

A dashboard agrupa os planos por curso e período (o mais recente primeiro; no mesmo ano, 2º semestre, 1º e os anuais) e mostra em cada card o código, a disciplina, a turma e a carga horária. Planos cujo cabeçalho não é reconhecido ficam em "Sem identificação de curso e período". O nome dos cursos de graduação vem da sigla, no dicionário `CURSOS` de `identificacao.py`: para outro curso, acrescente a sigla lá (sem ela, o grupo mostra só a sigla). A identificação é gravada nos detalhes de cada plano (`identificacao_plano`), mas a dashboard a lê de novo do texto já extraído: validações antigas e correções no leitor valem sem validar outra vez.

## Meus planos (entrega pelo professor)

Em `/meus-planos` cada servidor entrega os próprios planos: o PDF enviado vai para a mesma pasta de planos do NDE (é a entrega oficial, no lugar da pasta do Drive) e a avaliação começa logo em seguida, só para ele. A página mostra os planos agrupados por curso e período, com a situação de cada um (na fila, avaliando, resultado com os campos a verificar e link para o relatório); o curso e o período são lidos já no envio, então o plano aparece no grupo certo antes mesmo de ser avaliado. Para corrigir, o professor ajusta no SIGAA e envia o PDF de novo com o mesmo nome, que substitui o anterior.

- O professor só substitui e exclui os planos que ele enviou; um nome já usado por outra pessoa (ou por um PDF que veio do Drive/administrador, sem dono) é recusado, pedindo para renomear.
- Quem enviou cada PDF fica em `resultados/donos.json` e aparece para o administrador na lista de PDFs da dashboard.
- As avaliações rodam uma por vez (a GPU é uma só): com outra em andamento, o plano espera na fila, que também vale para o ↻ Revalidar do administrador. A fila fica na memória; se o container reiniciar, os planos que esperavam são avaliados na próxima validação geral.

## Rotas

| Método | Rota | Resposta |
|---|---|---|
| POST | `/validar` | `200 {"status":"iniciado"}`, `409` se já houver validação em andamento, `422` se a pasta não tiver PDFs |
| POST | `/validar?arquivo=nome.pdf` | Revalida só esse plano e atualiza a última validação; com outra validação rodando, entra na fila (`{"status":"na_fila","posicao":N}`); `404` se o PDF não estiver na pasta |
| GET | `/status` | Andamento: `rodando`, `total`, `processados`, `atual`, `iniciado_em`, `finalizado_em`, `erro`, `unico` (plano, numa revalidação) e `fila` (planos esperando) |
| GET | `/dashboard?validacao=ID` | Página HTML com os controles e os resultados; sem `validacao`, a última |
| GET | `/planos` | Lista dos PDFs da pasta (`nome`, `dono`, `tamanho`, `modificado`) |
| POST | `/planos` | Upload (multipart, campo `arquivos`, vários por vez, até `PDF_MAX_MB` por arquivo e 100 MB no total). Responde `salvos` e `recusados` (com o motivo); `409` durante a validação |
| DELETE | `/planos?arquivo=nome.pdf` | Exclui o PDF; `409` durante a validação |
| DELETE | `/planos/todos` | Exclui todos os PDFs da pasta (`{"excluidos": N}`); `409` durante a validação |
| GET | `/relatorio?validacao=ID&arquivo=nome.pdf` | Relatório HTML do plano; sem `validacao`, a última; `404` se o plano não estiver nela |
| GET | `/validacoes` | Histórico: resumo de cada validação guardada, da mais recente para a mais antiga |
| GET | `/validacoes/ID/csv` | CSV da validação |
| GET | `/validacoes/ID/pdfs.zip` | Zip com os PDFs validados; só para a última validação (`404` nas demais). Com `?arquivo=a.pdf&arquivo=b.pdf`, só esses (zip de um grupo) e `?nome=` entra no nome do arquivo baixado |
| GET | `/validacoes/ID/pdf?arquivo=nome.pdf` | O PDF como estava na validação (só a última) |
| GET | `/pdf?arquivo=nome.pdf` | O PDF atual da pasta de planos |
| GET | `/` | Página inicial pública: apresentação do projeto e botão **Entrar com Google** |
| GET | `/health` | `{"status":"ok"}` |
| GET | `/meus-planos` | Página de entrega e acompanhamento dos planos de quem está logado |
| GET | `/meus-planos/lista` | Planos de quem está logado: `nome`, `enviado_em`, `situacao` (`na_fila` com `posicao`, `validando`, `avaliado` com `status`, `obs` e `problemas`, ou `aguardando`) |
| POST | `/meus-planos` | Entrega (multipart, campo `arquivos`); cada PDF salvo entra na fila de avaliação (`posicao`, 0 se já começou) |
| DELETE | `/meus-planos?arquivo=nome.pdf` | Exclui um plano próprio; `403` se for de outra pessoa, `409` durante a validação geral |

Com login exigido, toda rota (exceto `/` e `/health`) responde `401` sem o e-mail repassado pelo proxy, e `POST /validar`, `POST /planos`, `DELETE /planos` e `DELETE /planos/todos` respondem `403` para quem não está em `ADMIN_EMAILS`.

Validação automática todos os dias na hora `AGENDAMENTO_HORA` (padrão 5h, fuso `TZ`).

## Histórico

Cada validação fica em `resultados/historico/AAAAMMDD-HHMMSS/`, com o CSV (`validacao_planos.csv`), os detalhes de cada plano (`detalhes/`, usados no relatório) e um resumo (`meta.json`). Ficam as `HISTORICO_MAX` mais recentes (padrão 3); as mais antigas são apagadas ao fim de cada validação. Uma cópia dos PDFs (`pdfs/`) é guardada só na mais recente, para o zip e para abrir o PDF exatamente como foi avaliado; nas anteriores fica só o resultado. Uma validação interrompida por erro também entra no histórico, com o que chegou a ser validado.

`resultados/validacao_planos.csv` continua sendo gravado com a última validação, para quem lê o arquivo direto. Na primeira subida desta versão, o resultado anterior (esse CSV e a pasta `resultados/detalhes/`) é movido para o histórico.

## Controle de execução

O estado da validação fica em memória no processo do gunicorn (`app/servicos/validador.py` e `andamento.py`), que roda com um único worker (`-w 1` no `Dockerfile`). Não aumente o número de workers: cada um teria seu próprio estado e duas validações poderiam rodar juntas. Se o container reiniciar no meio de um lote, a validação é perdida e o estado volta a livre; basta iniciar de novo.

## Subir no servidor

1. Crie o cliente OAuth no Google (uma vez), com a sua conta `@ifc.edu.br`, em [console.cloud.google.com](https://console.cloud.google.com): crie um projeto; em **Tela de permissão OAuth**, escolha o tipo **Interno** se estiver disponível (só contas da instituição conseguem entrar); em **Credenciais > Criar credenciais > ID do cliente OAuth**, tipo **Aplicativo da Web**, com o URI de redirecionamento `https://APP_HOST/oauth2/callback` (acrescente `:APP_PORT` se não for 443). Guarde o ID e a chave secreta do cliente.

2. Copie a configuração e ajuste os valores (caminho dos PDFs, portas, `APP_HOST`, cliente OAuth, administradores):

```bash
cp .env.example .env
```

Gere a chave do cookie de sessão e cole em `COOKIE_SECRET`:

```bash
openssl rand -hex 16
```

3. Suba o validador, o Ollama, o Caddy e o oauth2-proxy:

```bash
docker compose up -d --build
```

4. Baixe o modelo no Ollama (uma vez; fica no volume `ollama-data`):

```bash
docker compose exec ollama ollama pull qwen2.5:7b
```

5. Abra `https://APP_HOST/dashboard` (ex.: `https://planos.200-135-55-29.sslip.io/dashboard`), entre com a conta Google institucional, envie os PDFs (se a pasta estiver vazia) e clique em **Validar agora**.

## Acesso externo

Só o serviço `caddy` publica portas: `APP_PORT` (a aplicação, com HTTPS e login) e 80 (usada pelo Let's Encrypt para emitir e renovar o certificado; nela o Caddy só responde ao desafio e redireciona para HTTPS). O `app` e o Ollama ficam na rede interna do compose; o Ollama também em `127.0.0.1:OLLAMA_PORT` no host.

- `APP_HOST` é o nome que resolve para o IP público. Sem domínio próprio, `qualquer-nome.200-135-55-29.sslip.io` resolve para 200.135.55.29.
- O firewall da frente precisa encaminhar as portas 80 e `APP_PORT` para a máquina. Sem a 80 o certificado não é emitido; nesse caso, ou para testar localmente, deixe `APP_HOST` vazio e o Caddy serve HTTP puro em `APP_PORT`.
- Os certificados ficam no volume `caddy-data`.

## Login

O Caddy consulta o `oauth2-proxy` a cada requisição (`forward_auth`). Sem sessão, o navegador vai para o login do Google; só entram contas de `EMAIL_DOMINIO` (padrão `ifc.edu.br`; alunos usam `@estudantes.ifc.edu.br` e são recusados). Com sessão, o Caddy repassa o e-mail ao app no cabeçalho `X-Usuario-Email`, depois de apagar qualquer valor vindo do navegador; o app só é alcançável pelo Caddy, na rede interna do compose.

- A sessão dura 7 dias (cookie `_planos_login`). **Sair**, no topo da dashboard, encerra a sessão no validador, não na conta Google.
- Para mudar os administradores, edite `ADMIN_EMAILS` e rode `docker compose up -d app`.
- Fora do Docker (ex.: `flask --app app.web run` para desenvolver), use `EXIGIR_LOGIN=0`: sem login, todo acesso conta como administrador.

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

## Deploy automático (GitHub Actions)

O workflow `.github/workflows/ci-cd.yml` roda os testes (e um `docker build`) em todo push e pull request que mexa em `validador-planos/`. Em push na `master` que passe nos testes, o job de deploy roda **no próprio servidor**, num runner self-hosted: atualiza o clone para o commit testado, executa `docker compose up -d --build` e confere se o app respondeu. Commits que só mexem no TCC ou nos workflows do n8n não disparam deploy. Para reimplantar sem commit, use **Actions > CI/CD > Run workflow**.

O deploy reinicia o container `app`: uma validação em andamento naquele momento é perdida (ver "Controle de execução") e precisa ser iniciada de novo.

### Configurar uma vez no servidor

O runner roda como o usuário `fbizotto`, dono do clone em `/home/fbizotto/projetos/fabrica-planos`, onde já estão `.env`, `planos/` e `resultados/`. Assim não é preciso mudar dono de pastas nem permissões da home.

1. **Conferir o acesso ao Docker** sem `sudo` (o runner não usa sudo):

```bash
docker ps
# se der "permission denied":
sudo usermod -aG docker fbizotto   # depois saia e entre de novo na sessão SSH
```

2. **Conferir o clone**: precisa estar limpo, sem alterações em arquivos versionados.

```bash
cd /home/fbizotto/projetos/fabrica-planos
git status --short --untracked-files=no   # não deve listar nada
```

3. **Instalar o runner**: no GitHub, **Settings > Actions > Runners > New self-hosted runner**, escolha **Linux / x64** e copie os comandos exibidos (a versão e o token mudam). No servidor:

```bash
mkdir -p ~/actions-runner && cd ~/actions-runner
# cole aqui o curl de download e o tar xzf exibidos pelo GitHub
./config.sh --url https://github.com/FabSoftwareVideira/fabrica-planos \
  --token <TOKEN_EXIBIDO> --name servidor-ifc --labels planos --unattended
sudo ./svc.sh install fbizotto
sudo ./svc.sh start
sudo ./svc.sh status   # deve aparecer "active (running)"
```

Como serviço, o runner volta sozinho depois de reiniciar o servidor. Em **Settings > Actions > Runners** ele deve aparecer como **Idle**.

4. **Variável do repositório**: em **Settings > Secrets and variables > Actions > Variables > New repository variable**, crie `DEPLOY_DIR` = `/home/fbizotto/projetos/fabrica-planos`.

5. Faça um push na `master` (ou **Actions > CI/CD > Run workflow**) e acompanhe em **Actions**.

### Cuidados

- Não edite arquivos versionados direto no servidor: o deploy para com erro se encontrar alterações locais, para não apagá-las. Configuração do servidor fica no `.env`, fora do git.
- Se o repositório virar público, restrinja o runner: em **Settings > Actions > General**, exija aprovação para workflows de forks, e nunca rode jobs de `pull_request` no runner self-hosted (o workflow já roda os testes de PR só nos runners do GitHub).
