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
  armazenamento/    arquivos em resultados/: CSV, detalhes por plano, validação atual, dono de cada PDF, usuários e revisões
  servicos/         casos de uso com estado: Validador (lote, fila, agendador) e PastaDePlanos (envio/exclusão)
  rotas/            Blueprints, um por área: publico, painel, validacoes, administracao, meus_planos
  paginas/          dados de cada página (contexto do template) e funções comuns aos templates
  templates/        HTML das páginas em Jinja: base.html (esqueleto), _macros.html e uma por página
  static/           CSS e JavaScript das páginas (css/, js/), servidos em /static com versão no endereço;
                    vendor/ tem o Design System gov.br, a fonte Rawline e o Font Awesome (scripts/atualizar_vendor.sh)
tests/              testes unitários (regras, seções, extração, pipeline, rotas, CSV)
resultados/         validação atual, cópia do CSV dela, usuários e revisões (criados automaticamente; ver "Resultado")
dev-resultados/     o mesmo, no modo de desenvolvimento (fora do git)
Dockerfile          imagem em dois estágios: desenvolvimento (Flask com recarga) e producao (gunicorn)
docker-compose.yml  produção: app, Caddy, oauth2-proxy e Ollama com GPU (é o que o deploy sobe)
docker-compose.dev.yml  desenvolvimento: só o app, sem login, com recarga automática (Ollama opcional)
.env.example, Caddyfile, .dockerignore
```

As camadas só dependem das de baixo: `rotas` → `servicos` → `avaliacao`/`armazenamento`, e `rotas` → `paginas` → `templates`. Cada rota monta o contexto com a função `contexto()` do módulo da página e chama `render_template`; o Jinja escapa os valores automaticamente. `/static` (CSS, JS, fontes e ícones) é público, no app e no Caddy, porque a página inicial também o usa. As rotas só traduzem HTTP (parâmetros, códigos de resposta) e chamam os serviços, que guardam as regras de negócio (quem pode substituir um PDF, fila, bloqueio durante o lote) e avisam problemas com exceções (`Ocupado`, `NaoEncontrado`, `Proibido`). Os serviços são criados uma vez em `criar_app()` e ficam em `app.extensions['servicos']`; nos testes, `criar_app(cfg, executar=...)` roda as avaliações na hora, sem thread.

Os PDFs ficam na pasta indicada por `PLANOS_HOST_DIR`, montada no container com escrita (o dashboard envia e exclui PDFs). Eles não entram na imagem nem no git.

## Interface (Padrão Digital de Governo)

As páginas seguem o [Padrão Digital de Governo](https://www.gov.br/ds/) (Design System gov.br, `@govbr-ds/core` 3.7): página inicial, dashboard, relatório e Meus planos. Na página inicial, o botão "Entrar com Google" mantém o visual pedido pelas diretrizes do Google.

- `templates/_ds.html` carrega o CSS do DS, a fonte e os ícones; `_cabecalho.html` e `_rodape.html` são o cabeçalho e o rodapé no padrão.
- O cabeçalho tem o menu com texto e ícone (Painel, Administração para administradores, Meus planos) e a conta de quem está logado; abaixo de 992px vira menu hambúrguer (`static/js/cabecalho.js`). O logotipo do IFC entra ao colocar o arquivo oficial em `app/static/img/logo-ifc.svg` (ou `.png`); sem ele, aparece a sigla IFC.
- `static/css/ds.css` tem os ajustes comuns às páginas migradas; cada página tem o seu CSS para o que é só dela.
- As bibliotecas ficam copiadas em `static/vendor` (sem CDN). Para trocar de versão, ajuste as versões no topo de `scripts/atualizar_vendor.sh`, rode o script (precisa de npm) e confira as páginas.
- Só o CSS do DS é usado; os componentes que dependem do JavaScript do DS (menus, upload) ficam de fora por enquanto.

## Dashboard

O dashboard (`/dashboard`) mostra os resultados a todos os servidores; o envio e a exclusão de PDFs ficam na página **Administração** (`/administracao`, só para `ADMIN_EMAILS`). As duas têm, logo abaixo do cabeçalho, a barra de status da validação: a última validação ou o andamento (plano atual e barra de progresso, fixa no topo enquanto valida) e, para administradores, o botão **Validar agora**. Ao terminar, abre os resultados novos no dashboard.

Na administração é possível:

- enviar PDFs (arrastando ou escolhendo arquivos; um PDF com o mesmo nome é substituído), abrir e excluir os da pasta, um a um ou todos de uma vez (**Excluir todos**, que não apaga o resultado da validação). Só entram arquivos `.pdf` de até `PDF_MAX_MB` MB (padrão 10) que abram e tenham texto selecionável; digitalizados (só imagem) são recusados com o aviso de que precisam de OCR.

No dashboard é possível:

- abrir o **Relatório** de cada plano avaliado: a avaliação de cada campo ao lado do texto extraído para ele, o texto completo do PDF, o prompt enviado e a resposta da IA. A barra do topo volta ao dashboard já no card do plano (ou `Esc`) e passa para o plano anterior/próximo (ou `←`/`→`). Planos validados antes desta versão só mostram o texto depois de uma nova validação;
- **revalidar um plano só** (botão ↻ no card, no relatório ou na lista de PDFs, útil depois que o docente corrige o PDF): a linha dele na validação atual é substituída (ou acrescentada, se for um PDF novo), sem rodar o lote;
- ver os resultados agrupados, com o resumo de cada grupo, escolhendo em **Agrupar por**: curso e período (padrão; ver "Curso e período"), só período, só curso, docente, situação (aprovados, pendentes…) ou sem agrupar. O agrupamento é feito no navegador e a escolha fica guardada nele;
- baixar o **zip com os PDFs de um grupo** (link no cabeçalho do grupo): leva os planos visíveis nele, respeitando os filtros (só coordenação de curso e administração);
- filtrar os resultados por texto (disciplina ou docente, sem diferenciar acentos), curso e período e status; os filtros ficam guardados enquanto a aba estiver aberta;
- baixar o CSV e o **zip com os PDFs** da validação atual (só coordenação de curso e administração; os demais abrem cada plano e PDF pelo card);
- ir direto ao parecer pelo botão **Revisar** do card, que aparece para a coordenação, o NDE e o NDB do curso do plano;
- ver quais planos já foram **revisados** pela coordenação, NDE ou NDB (selo "Revisado" e o parecer no card) e agrupar por revisão. Com revisão, vale o status do revisor (ver "Revisão manual").

Enquanto uma validação geral roda, envio e exclusão pelo administrador ficam bloqueados; o envio pelo professor (em "Meus planos") é aceito e avaliado em seguida. O acesso exige login com a conta Google `@ifc.edu.br` (ver "Login"). Qualquer servidor consulta resultados, relatórios e PDFs e entrega os próprios planos; o CSV e os zips ficam com quem tem papel de coordenação em algum curso e com os administradores; só os administradores (`ADMIN_EMAILS`) veem e usam **Validar agora**, ↻ Revalidar, envio e exclusão de quaisquer PDFs.

## Visão da coordenação

Em **Coordenação** (`/coordenacao`), quem tem o papel de coordenador vê a situação dos planos dos cursos que coordena, e a administração vê todos os cursos da validação atual. Cada coordenador tem a sua visão: com mais de um curso, escolhe qual ver. Para o curso e o período escolhidos (padrão: o período mais recente; com mais de um, também "Todos os períodos"), a página mostra:

- **Situação:** total de planos, aprovados, pendentes, reprovados e com erro, com a proporção de cada um. Com revisão vigente, vale o parecer do revisor;
- **Revisão:** quantos planos já foram revisados, quantos aguardam e em quantos o parecer difere da IA;
- **O que mais falta nos planos:** os campos que a avaliação automática não aprovou, em número de planos;
- **Por docente:** planos de cada docente, com a situação e quantos aguardam revisão; quem tem mais pendências aparece primeiro;
- **Planos:** a lista do curso e período, com os não aprovados e os que aguardam revisão primeiro, e os botões Revisar e Relatório. O **zip com os PDFs do curso** no período fica no topo.

## Curso e período

O cabeçalho do plano gerado pelo SIGAA identifica o componente, o curso e o período (`app/avaliacao/identificacao.py`):

| Oferta | Exemplo no PDF | Curso | Período |
|---|---|---|---|
| Graduação (semestral) | `CCC0723 - DESENVOLVIMENTO WEB I (60h) - Turma: 01 (2026.2)` | `CC` (2 primeiras letras do código) → Ciência da Computação | 2º semestre de 2026 |
| Técnico (anual) | `INC0713-1 - WEB DESIGN (60h) - Turma: 03 (2026)` e `Turma: [TÉCNICO EM INFORMÁTICA INTEGRADO AO ENSINO MÉDIO - IN07 (MT) - A (2026)]` | nome que vem entre colchetes | 2026 (anual) |

O docente vem do bloco "Matrícula Docente(s)" (`1773245 LUCILENE DAL MEDICO BAERLE - 60h`) e é usado no agrupamento por docente e na busca.

A dashboard agrupa os planos por curso e período (o mais recente primeiro; no mesmo ano, 2º semestre, 1º e os anuais) e mostra em cada card o código, a disciplina, a turma e a carga horária. Planos cujo cabeçalho não é reconhecido ficam em "Sem identificação de curso e período". O nome dos cursos de graduação vem da sigla, no dicionário `CURSOS` de `identificacao.py`: para outro curso, acrescente a sigla lá (sem ela, o grupo mostra só a sigla). A identificação é gravada nos detalhes de cada plano (`identificacao_plano`), mas a dashboard a lê de novo do texto já extraído: validações antigas e correções no leitor valem sem validar outra vez.

## Revisão manual (coordenação, NDE, NDB)

Quem é da coordenação, do NDE ou do NDB de um curso confere a avaliação da IA dos planos daquele curso:

- **Quem pode:** o administrador dá o papel em **Administração → Usuários**, na coluna **Revisão** (curso + Coordenação, NDE ou NDB). O curso é o do cabeçalho do plano (ver "Curso e período"); planos sem curso identificado não podem ser revisados. Sem login (`EXIGIR_LOGIN=0`, uso local), qualquer acesso revisa.
- **Como:** no relatório do plano, o painel **Revisão da coordenação / NDE / NDB** traz o parecer — Aprovado, Ajustes necessários ou Reprovado — e um comentário para o docente, obrigatório quando o plano não é aprovado ou o parecer difere da IA. Dá para alterar o parecer ou desfazer a revisão.
- **Efeito:** o parecer passa a ser o status oficial do plano: na dashboard (filtros, agrupamento, com o selo "Revisado" e a avaliação da IA ao lado) e em **Meus planos**, onde o professor vê o parecer, quem revisou e o comentário.
- **PDF novo reabre:** a revisão guarda o tamanho e a data do PDF revisado; se o PDF muda (o professor reenvia, o administrador substitui ou alguém copia outro para a pasta), ela deixa de valer e o plano volta a mostrar a avaliação da IA até uma nova revisão. Revalidar com a IA o mesmo PDF não desfaz a revisão.
- As revisões ficam em `resultados/revisoes.sqlite3` (uma por plano, a mais recente), à parte do resultado da validação: uma validação geral nova não as apaga.

## Meus planos (entrega pelo professor)

Em `/meus-planos` cada servidor entrega os próprios planos: o PDF enviado vai para a mesma pasta de planos do NDE (é a entrega oficial, no lugar da pasta do Drive) e a avaliação começa logo em seguida, só para ele. A página mostra os planos agrupados por curso e período, com a situação de cada um (na fila, avaliando, resultado com os campos a verificar e link para o relatório); o curso e o período são lidos já no envio, então o plano aparece no grupo certo antes mesmo de ser avaliado. Para corrigir, o professor ajusta no SIGAA e envia o PDF de novo com o mesmo nome, que substitui o anterior.

- O professor só substitui e exclui os planos que ele enviou; um nome já usado por outra pessoa (ou por um PDF que veio do Drive/administrador, sem dono) é recusado, pedindo para renomear.
- Quem enviou cada PDF fica em `resultados/donos.json` e aparece para o administrador na lista de PDFs da dashboard.
- As avaliações rodam uma por vez (a GPU é uma só): com outra em andamento, o plano espera na fila, que também vale para o ↻ Revalidar do administrador. A fila fica na memória; se o container reiniciar, os planos que esperavam são avaliados na próxima validação geral.

## Rotas

| Método | Rota | Resposta |
|---|---|---|
| POST | `/validar` | `200 {"status":"iniciado"}`, `409` se já houver validação em andamento, `422` se a pasta não tiver PDFs |
| POST | `/validar?arquivo=nome.pdf` | Revalida só esse plano e atualiza a validação atual; com outra validação rodando, entra na fila (`{"status":"na_fila","posicao":N}`); `404` se o PDF não estiver na pasta |
| GET | `/status` | Andamento: `rodando`, `total`, `processados`, `atual`, `iniciado_em`, `finalizado_em`, `erro`, `unico` (plano, numa revalidação) e `fila` (planos esperando) |
| GET | `/dashboard` | Página HTML com os resultados da validação atual |
| GET | `/coordenacao` | Visão da coordenação (`?curso=CC&periodo=2026.2`); quem não é coordenador nem administrador vai para o dashboard |
| GET | `/administracao` | Página HTML de gestão dos PDFs e validação; quem não é administrador vai para o dashboard |
| GET | `/administracao/usuarios` | Usuários (tabela paginada, 20 por página; filtros `q`, `situacao`, `papel`, `ordem`, `pagina`); só administradores |
| POST | `/administracao/usuarios/papel` | Dá (`acao=adicionar`) ou tira (`acao=remover`) do `email` o `papel` (`coordenador`, `nde` ou `ndb`) no `curso` (sigla); só administradores |
| POST | `/administracao/usuarios/ativo` | Ativa (`ativo=1`) ou desativa (`ativo=0`) o `email` do formulário e volta à tabela; administradores de `ADMIN_EMAILS` não podem ser desativados |
| GET | `/planos` | Lista dos PDFs da pasta (`nome`, `dono`, `tamanho`, `modificado`) |
| POST | `/planos` | Upload (multipart, campo `arquivos`, vários por vez, até `PDF_MAX_MB` por arquivo e 100 MB no total). Responde `salvos` e `recusados` (com o motivo); `409` durante a validação |
| DELETE | `/planos?arquivo=nome.pdf` | Exclui o PDF; `409` durante a validação |
| DELETE | `/planos/todos` | Exclui todos os PDFs da pasta (`{"excluidos": N}`); `409` durante a validação |
| GET | `/relatorio?arquivo=nome.pdf` | Relatório HTML do plano, com o painel de revisão; `404` se o plano não estiver na validação atual |
| POST | `/revisao` | Parecer (`arquivo`, `status` = `OK`, `PENDENTE` ou `REPROVADO`, `comentario`) ou, com `acao=desfazer`, desfaz a revisão; volta ao relatório. `403` para quem não tem papel no curso do plano |
| GET | `/validacoes` | Resumo da validação atual (lista com um item; vazia antes da primeira) |
| GET | `/validacoes/ID/csv` | CSV da validação (coordenação e administração) |
| GET | `/validacoes/ID/pdfs.zip` | Zip com os PDFs validados (coordenação e administração). Com `?arquivo=a.pdf&arquivo=b.pdf`, só esses (zip de um grupo) e `?nome=` entra no nome do arquivo baixado |
| GET | `/validacoes/ID/pdf?arquivo=nome.pdf` | O PDF como estava na validação |
| GET | `/pdf?arquivo=nome.pdf` | O PDF atual da pasta de planos |
| GET | `/` | Página inicial pública: apresentação do projeto e botão **Entrar com Google** |
| GET | `/health` | `{"status":"ok"}` |
| GET | `/meus-planos` | Página de entrega e acompanhamento dos planos de quem está logado |
| GET | `/meus-planos/lista` | Planos de quem está logado: `nome`, `enviado_em`, `situacao` (`na_fila` com `posicao`, `validando`, `avaliado` com `status`, `obs` e `problemas`, ou `aguardando`) |
| POST | `/meus-planos` | Entrega (multipart, campo `arquivos`); cada PDF salvo entra na fila de avaliação (`posicao`, 0 se já começou) |
| DELETE | `/meus-planos?arquivo=nome.pdf` | Exclui um plano próprio; `403` se for de outra pessoa, `409` durante a validação geral |

Com login exigido, toda rota (exceto `/` e `/health`) responde `401` sem o e-mail repassado pelo proxy, e `POST /validar`, `POST /planos`, `DELETE /planos` e `DELETE /planos/todos` respondem `403` para quem não está em `ADMIN_EMAILS`.

Validação automática todos os dias na hora `AGENDAMENTO_HORA` (padrão 5h, fuso `TZ`).

## Resultado

Só a validação atual é guardada, em `resultados/historico/AAAAMMDD-HHMMSS/`: o CSV (`validacao_planos.csv`), os detalhes de cada plano (`detalhes/`, usados no relatório), um resumo (`meta.json`) e uma cópia dos PDFs avaliados (`pdfs/`, para o zip e para abrir o PDF exatamente como foi avaliado). Uma validação geral nova substitui a anterior, que só é apagada quando a nova termina; uma interrompida por erro também vira a atual, com o que chegou a ser validado. Revalidar um plano atualiza a linha dele na validação atual. O agrupamento por curso, período e docente faz o papel de histórico, e as revisões manuais ficam à parte (`revisoes.sqlite3`).

`resultados/validacao_planos.csv` continua sendo gravado com a validação atual, para quem lê o arquivo direto. Ao subir esta versão, as validações anteriores que estavam guardadas são apagadas (fica a mais recente).

## Controle de execução

O estado da validação fica em memória no processo do gunicorn (`app/servicos/validador.py` e `andamento.py`), que roda com um único worker (`-w 1` no `Dockerfile`). Não aumente o número de workers: cada um teria seu próprio estado e duas validações poderiam rodar juntas. Se o container reiniciar no meio de um lote, a validação é perdida e o estado volta a livre; basta iniciar de novo.

## Rodar em desenvolvimento

Para testar na sua máquina, sem Caddy nem Google (com login simulado) e com recarga automática:

```bash
docker compose -f docker-compose.dev.yml up --build
```

Abra http://localhost:8000. Nesse modo:

- **Login simulado** (`LOGIN_SIMULADO=1`): no lugar do Google, "Entrar" leva a `/dev/login`, onde se escolhe uma persona ou se digita qualquer e-mail e nome. As personas cobrem os perfis: administração (`admin@ifc.edu.br`, que o compose põe em `ADMIN_EMAILS`), coordenação e NDE de CC, NDB de IN (já entram com o papel no curso), dois professores sem papel (para testar donos diferentes em "Meus planos") e uma estudante, recusada como no Google (só entram contas `@ifc.edu.br`). O botão **Trocar usuário**, no cabeçalho, volta à escolha. Por baixo, um cookie vira os mesmos cabeçalhos que o Caddy e o oauth2-proxy mandam em produção (`X-Usuario-Email` e o ID token), então login, cadastro, papéis e permissões passam pelo mesmo código. Fora do dev (`LOGIN_SIMULADO` não definido, como no `docker-compose.yml`) nada disso é registrado e o cookie é ignorado. Com `DEV_EXIGIR_LOGIN=0` não há login nenhum (todo acesso conta como administrador). A validação diária automática fica desligada.
- **Recarga automática:** a pasta do projeto é montada em `/app`, e o servidor do Flask (modo debug) reinicia ao salvar um arquivo `.py`; templates, CSS e JS valem no próximo recarregar da página. Não precisa reconstruir a imagem, só quando mudar o `requirements*.txt`.
- **Dados separados:** os PDFs vêm da pasta `planos/` do repositório (fora do git) e os resultados, usuários e revisões ficam em `dev-resultados/`, fora do git. O projeto do compose se chama `validador-planos-dev`, então não encosta nos containers nem nos volumes de produção.
- **Só a sua máquina acessa:** a porta é publicada em `127.0.0.1` (o depurador do Flask não pode ficar exposto na rede).
- **A IA é opcional.** Sem ela, a interface funciona e as validações terminam em ERRO ("Ollama inacessível"). Para validar de verdade, suba também o Ollama:
  - **na GPU NVIDIA** (recomendado): `docker compose -f docker-compose.dev.yml --profile ia up --build`. Precisa do Docker com acesso à GPU (no Windows, Docker Desktop com o driver NVIDIA; no Linux, o NVIDIA Container Toolkit); confira com `docker run --rm --gpus all ubuntu nvidia-smi -L`. Numa RTX 3060 (12 GB), o `qwen2.5:7b` roda 100% na GPU: cerca de 2 minutos no primeiro plano (carrega o modelo) e uns 7 s nos seguintes;
  - **na CPU**, sem GPU: `--profile ia-cpu` no lugar de `--profile ia` (lento: minutos por plano);
  - os modelos ficam no mesmo volume do `docker-compose.yml` (`validador-planos_ollama-data`): se a produção já rodou nesta máquina, o modelo não é baixado de novo. Senão, uma vez: `docker compose -f docker-compose.dev.yml exec ollama ollama pull qwen2.5:7b` (com `ollama-cpu` no lugar de `ollama` no perfil `ia-cpu`). Para um volume só do dev, use `DEV_OLLAMA_VOLUME=validador-planos-dev-modelos`;
  - o Ollama do dev fica em http://localhost:11434; o app o acessa pela rede do compose;
  - ou use um Ollama que já roda no seu computador, ou o do servidor por um túnel SSH (`ssh -p 50026 -N -L 11434:localhost:PORTA usuario@200.135.55.29`, com a `OLLAMA_PORT` do `.env` do servidor no lugar de PORTA): `DEV_OLLAMA_URL=http://host.docker.internal:11434`.

Variáveis opcionais (no ambiente ou num `.env`): `DEV_PORT` (padrão 8000), `DEV_ADMIN_EMAILS` (padrão `admin@ifc.edu.br`), `DEV_EXIGIR_LOGIN` (padrão 1), `DEV_PLANOS_DIR` (padrão `./planos`), `DEV_OLLAMA_URL`, `DEV_OLLAMA_MODEL`, `DEV_OLLAMA_NUM_CTX`, `DEV_OLLAMA_PORT` (padrão 11434) e `DEV_OLLAMA_VOLUME`. Comandos úteis:

```bash
docker compose -f docker-compose.dev.yml exec app pytest -q    # testes dentro do container
docker compose -f docker-compose.dev.yml logs -f app           # acompanhar o log
docker compose -f docker-compose.dev.yml down                  # parar
```

## Subir no servidor (Dokploy)

Em produção o validador roda no [Dokploy](https://dokploy.com), que gerencia os projetos e domínios da VPS. O `docker-compose.yml` é o de produção, cadastrado no Dokploy como recurso do tipo **Docker Compose**:

- o **Traefik do Dokploy** recebe o domínio, cuida do HTTPS (Let's Encrypt) e repassa ao serviço `caddy`, na porta 80, pela rede `dokploy-network`;
- o **Caddy** do projeto é interno, sem porta publicada no host: faz o login (`forward_auth` no `oauth2-proxy`) e repassa ao `app`, que fica só na rede do compose;
- os **PDFs e resultados** ficam em pastas fixas do servidor (`PLANOS_HOST_DIR` e `RESULTADOS_HOST_DIR`, padrão `/srv/validador-planos/...`), porque o Dokploy clona o repositório de novo a cada deploy;
- os **modelos do Ollama** ficam no volume `OLLAMA_VOLUME` (padrão `validador-planos_ollama-data`, o mesmo do deploy anterior ao Dokploy).

### Instalar e configurar (uma vez)

1. **Cliente OAuth no Google**, com a sua conta `@ifc.edu.br`, em [console.cloud.google.com](https://console.cloud.google.com): crie um projeto; em **Tela de permissão OAuth**, escolha o tipo **Interno** se estiver disponível (só contas da instituição conseguem entrar); em **Credenciais > Criar credenciais > ID do cliente OAuth**, tipo **Aplicativo da Web**, com o URI de redirecionamento `https://SEU_DOMINIO/oauth2/callback`. Guarde o ID e a chave secreta. Se o cliente já existe, só confira o URI (sem porta, se antes havia uma).

2. **Pastas de dados** no servidor (o container do app roda como root e grava nelas):

```bash
sudo mkdir -p /srv/validador-planos/planos /srv/validador-planos/resultados
```

3. **Instalar o Dokploy** (como root; ele precisa das portas 80, 443 e 3000 livres):

```bash
curl -sSL https://dokploy.com/install.sh | sh
```

Abra `http://IP_DO_SERVIDOR:3000`, crie a conta de administrador e ative a autenticação em dois fatores. Em **Settings > Web Server**, dê um domínio com HTTPS ao painel e, depois, bloqueie o acesso direto à porta 3000 (regras do `ufw` não valem para portas publicadas pelo Docker; veja a documentação do Dokploy).

4. **Criar o recurso**: em um projeto, **Create Service > Compose**, tipo **Docker Compose** (não **Stack**: no modo Swarm a reserva de GPU do Ollama não funciona). Em **Provider**, conecte o GitHub (GitHub App, o repositório é privado), escolha `FabSoftwareVideira/fabrica-planos`, branch `master` e o arquivo `./docker-compose.yml`. **Desligue o Autodeploy**: quem dispara o deploy é o GitHub Actions, depois dos testes (ver "Deploy automático").

5. **Environment**: cole o `.env.example` e ajuste os valores (cliente OAuth, `COOKIE_SECRET` gerado com `openssl rand -hex 16`, `ADMIN_EMAILS`, pastas, modelo).

6. **Domains**: adicione o domínio no serviço `caddy`, porta `80`, com HTTPS e certificado Let's Encrypt. Sem domínio próprio, `qualquer-nome.200-135-55-29.sslip.io` resolve para 200.135.55.29.

7. **Deploy** e, se o volume de modelos for novo, baixe o modelo uma vez (pelo terminal do container `ollama` no Dokploy, ou no servidor):

```bash
docker exec -it $(docker ps -qf name=ollama) ollama pull qwen2.5:7b
```

8. Abra `https://SEU_DOMINIO/dashboard`, entre com a conta Google institucional, envie os PDFs (se a pasta estiver vazia) e clique em **Validar agora**.

### Migrar do deploy anterior (Caddy com portas próprias e runner self-hosted)

O site fica fora do ar entre os passos 2 e 5, por alguns minutos.

1. **Backup** do clone antigo (`.env`, PDFs e resultados), na pasta onde está o `docker-compose.yml` em uso:

```bash
cd /home/fbizotto/projetos/fabrica-planos/validador-planos   # ou a raiz do clone, se o compose já estiver lá
tar czf ~/backup-validador-$(date +%F).tgz .env resultados ../planos
```

2. **Parar o deploy antigo**, liberando as portas 80 e 443 para o Dokploy (o volume com os modelos do Ollama não é apagado):

```bash
docker compose down
```

3. **Copiar os dados** para as pastas fixas (ajuste a origem dos PDFs se o `PLANOS_HOST_DIR` antigo apontava para outro lugar):

```bash
sudo mkdir -p /srv/validador-planos
sudo cp -a resultados ../planos /srv/validador-planos/
```

4. **Instalar o Dokploy e criar o recurso** (passos 3 a 6 acima). No Environment, reaproveite os valores do `.env` antigo; `APP_HOST` e `APP_PORT` não são mais usados (o domínio vai na aba Domains). Se o domínio antigo usava uma porta (ex.: `:8443`), atualize o URI de redirecionamento no Google para o domínio sem porta.

5. **Deploy** no Dokploy e teste o login, o dashboard e um relatório.

6. **Desligar o runner self-hosted**, que não é mais usado:

```bash
cd ~/actions-runner
sudo ./svc.sh stop && sudo ./svc.sh uninstall
./config.sh remove --token <TOKEN_DE_REMOCAO>   # token em Settings > Actions > Runners > o runner > Remove
```

Apague também a variável `DEPLOY_DIR` em **Settings > Secrets and variables > Actions > Variables**. O clone antigo pode ser apagado quando tudo estiver funcionando (o backup do passo 1 fica em `~`).

## Login

O Traefik do Dokploy repassa as requisições ao Caddy do projeto, que consulta o `oauth2-proxy` a cada uma (`forward_auth`). Sem sessão, o navegador vai para o login do Google; só entram contas de `EMAIL_DOMINIO` (padrão `ifc.edu.br`; alunos usam `@estudantes.ifc.edu.br` e são recusados). Com sessão, o Caddy repassa o e-mail ao app no cabeçalho `X-Usuario-Email`, depois de apagar qualquer valor vindo do navegador; o app só é alcançável pelo Caddy, na rede interna do compose.

- A sessão dura 7 dias (cookie `_planos_login`). **Sair**, no topo da dashboard, encerra a sessão no validador, não na conta Google.
- Para mudar os administradores, edite `ADMIN_EMAILS` no Environment do Dokploy e faça um novo deploy.
- O oauth2-proxy também devolve o ID token do Google (`OAUTH2_PROXY_SET_AUTHORIZATION_HEADER`), que o Caddy repassa em `X-Usuario-Token`; o app lê dele o nome da conta.

## Usuários

Todo servidor entra no cadastro (`resultados/usuarios.sqlite3`) no primeiro acesso, com o nome da conta Google; o nome e o último acesso são atualizados nos acessos seguintes. Em **Administração → Usuários** os administradores veem a tabela, buscam por nome ou e-mail, filtram por situação e papel (inclusive "Coordenação/NDE/NDB"), ativam ou desativam contas e, na coluna **Revisão**, dão ou tiram os papéis de coordenação, NDE e NDB em cada curso (ver "Revisão manual"). Os cursos oferecidos são os de `CURSOS` em `identificacao.py` e os que aparecem nos planos. Quem é desativado recebe "Acesso desativado" em qualquer página (403) até ser reativado; nada do que enviou é apagado. Os administradores de `ADMIN_EMAILS` aparecem como protegidos e não podem ser desativados.
- Fora do Docker (ex.: `flask --app app.web run` para desenvolver), use `EXIGIR_LOGIN=0`: sem login, todo acesso conta como administrador.

## Conferir a extração de um plano

Mostra o texto extraído do PDF e como ele foi separado em seções (com `--prompt`, também o prompt enviado ao Ollama), sem chamar a IA:

```bash
docker compose -f docker-compose.dev.yml exec app python -m app.depurar "2026-2 - Banco Dados II - Leila.pdf" --prompt
```

Em produção, rode `python -m app.depurar ...` no terminal do container `app`, pelo Dokploy.

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

Sem Python instalado, rode dentro do container de desenvolvimento: `docker compose -f docker-compose.dev.yml exec app pytest -q`.

## Observações

- O Ollama roda como serviço `ollama` do próprio compose; o validador o alcança pela rede interna em `http://ollama:11434`. No host, ele fica em `OLLAMA_PORT` (padrão 11434), aceitando só conexões locais; para liberar na rede, use `OLLAMA_BIND=0.0.0.0` (o Ollama não tem autenticação). Não altere `OLLAMA_URL` ao trocar a porta. Os modelos ficam no volume `OLLAMA_VOLUME` e sobrevivem a recriações dos containers. A GPU NVIDIA é reservada pelo bloco `deploy` do serviço no `docker-compose.yml`.
- O texto extraído é limpo antes da separação em seções: saem o rodapé do SIGAA ("Este documento foi emitido…", endereço, telefone), o cabeçalho institucional repetido a partir da 2ª página, títulos de bloco e cabeçalhos de tabela, e o bloco "Matrícula Docente(s)" de dentro da ementa (ele vai para a identificação).
- Horário de atendimento é decidido por regra, sem a IA: OK se a seção informa dia ou hora; INCOMPLETO se só indica onde consultar (quadro de horários, Planus, PTD, site); AUSENTE se vazia.
- A extração usa `pdfplumber`, que lê só a camada de texto. PDFs escaneados precisam de OCR antes de entrar na pasta: o upload os recusa e, se um deles for copiado direto para a pasta, a validação o marca como `ERRO` ("precisa passar por OCR") sem chamar a IA.
- Para trocar o modelo, baixe-o (`ollama pull <modelo>` no terminal do container `ollama`), altere `OLLAMA_MODEL` (e, se quiser, `OLLAMA_NUM_CTX`) no Environment do Dokploy e faça um novo deploy.

## Deploy automático (GitHub Actions + Dokploy)

O workflow `.github/workflows/ci-cd.yml` roda os testes (e constrói a imagem de produção e confere os dois compose) em todo push e pull request. Em push na `master` que passe nos testes, o job de deploy chama a API do Dokploy (`POST /api/compose.deploy`), que baixa o código, reconstrói as imagens e sobe os containers. O Autodeploy do próprio Dokploy fica desligado, para que só código testado vá para o ar. Para reimplantar sem commit, use **Actions > CI/CD > Run workflow** ou o botão **Deploy** no Dokploy.

O deploy reinicia o container `app`: uma validação em andamento naquele momento é perdida (ver "Controle de execução") e precisa ser iniciada de novo.

### Configurar uma vez

1. No Dokploy, gere uma chave da API em **Settings > Profile > API/CLI** (o nome do menu pode variar entre versões).
2. Copie o id do recurso: é o trecho final da URL da página do recurso no painel (`.../compose/<ID>`).
3. No GitHub, em **Settings > Secrets and variables > Actions > Secrets**, crie:
   - `DOKPLOY_URL`: endereço do painel, com `https://` (ex.: `https://painel.200-135-55-29.sslip.io`);
   - `DOKPLOY_API_KEY`: a chave do passo 1;
   - `DOKPLOY_COMPOSE_ID`: o id do passo 2.
4. Faça um push na `master` (ou **Run workflow**) e acompanhe o job em **Actions** e o build em **Deployments**, no Dokploy.

O painel do Dokploy precisa estar acessível pela internet (pelo domínio com HTTPS) para o GitHub Actions chamar a API.

### Cuidados

- A configuração do servidor fica no Environment do recurso, no Dokploy; não edite arquivos no servidor. Mudou uma variável (ex.: `ADMIN_EMAILS`)? Salve e faça um novo deploy.
- A chave da API dá controle sobre o Dokploy: guarde-a só nos secrets do GitHub e gere outra se ela vazar.
- Faça backup de `/srv/validador-planos/resultados` (usuários, revisões e a validação atual): o backup do Dokploy cobre os bancos que ele gerencia, não essas pastas.
