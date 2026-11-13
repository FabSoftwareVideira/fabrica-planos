# Validador de Planos de Ensino

Aplicação web do IFC Videira que avalia os planos de ensino (PDFs do SIGAA) com IA local e mostra o resultado num painel.

- O texto de cada PDF é extraído e separado em seções (ementa, objetivos, metodologia, cronograma, referências…). Um modelo local no [Ollama](https://ollama.com) (padrão `qwen2.5:7b`) avalia cada campo, e regras fixas conferem o que não depende da IA, como a contagem de referências e o horário de atendimento.
- O **painel** mostra a situação de cada plano (aprovado, pendente ou com problemas), com filtros por curso, período e docente, e um relatório por plano com o texto extraído e a resposta da IA.
- Em **Meus planos**, cada professor entrega e acompanha os próprios planos. Quem envia é o **professor responsável** pelo plano: o nome que aparece no painel é o do cadastro dele, não o escrito no PDF. No envio, o app só confere se o docente do PDF tem o nome dele, ou parecido (sobrenomes a mais, acentos, uma letra diferente, iniciais); se for de outra pessoa, o PDF é recusado. A **coordenação, o NDE e o NDB** de cada curso revisam a avaliação da IA, e o parecer deles passa a valer. O coordenador do curso pode revisar qualquer plano dele, inclusive o que ele mesmo enviou.
- Depois de aprovado na revisão, o professor **assina o plano com a conta gov.br**: em **Meus planos**, pelo botão **Assinar com gov.br** (API de Assinatura Eletrônica do gov.br, quando configurada) ou assinando em [assinador.iti.br](https://assinador.iti.br) e enviando o PDF assinado. O app confere a assinatura, que precisa ser de um certificado das autoridades em [`app/certificados/`](app/certificados/LEIA-ME.md), e se o conteúdo é o do plano aprovado. Depois de assinado, o plano não é substituído pelo professor: a coordenação do curso precisa liberar um novo envio.
- A **administração** dispara validações (também roda todo dia, às 5h), exclui planos sem dono, oculta planos do painel e gerencia usuários e papéis. Ela não envia planos: isso é dos professores.
- O acesso é feito com a conta **gov.br** ou com a conta Google institucional. Nos dois casos vale o e-mail `@ifc.edu.br`. Se a conta gov.br tem um e-mail pessoal, a pessoa entra uma vez com o Google institucional e clica em **Vincular gov.br** no cabeçalho: dali em diante o login gov.br encontra o usuário pelo CPF. O app guarda só um HMAC do CPF, feito com `SEGREDO_SESSAO`; se esse segredo mudar, os vínculos precisam ser refeitos. Quem entra pelo gov.br com o e-mail institucional verificado fica vinculado automaticamente.

Feito em Python 3.12 com Flask e gunicorn, e páginas no [Padrão Digital de Governo](https://www.gov.br/ds/). Em produção, roda em Docker atrás de Caddy e oauth2-proxy (Google); o login gov.br é feito pelo próprio app.

## Como rodar

### Na sua máquina (desenvolvimento)

Precisa do Docker. O comando abaixo sobe o app com recarga automática e login simulado, sem precisar de conta Google:

```bash
docker compose -f docker-compose.dev.yml up --build
```

Abra http://localhost:8000 e, em **Entrar**, escolha um perfil de teste (administração, coordenação, NDE, professor…).

- Os PDFs vêm da pasta `planos/` e os resultados ficam em `dev-resultados/`. As duas pastas ficam fora do git.
- **Assinar com gov.br** funciona sem o gov.br: no dev a assinatura é simulada (`GOVBR_ASSINATURA_AMBIENTE=simulada`), com uma autoridade de teste criada na hora. Só vale junto do login simulado; para desligar, `DEV_ASSINATURA_AMBIENTE=` (vazio).
- Sem a IA, a interface funciona, mas as validações terminam em ERRO. Para validar de verdade, suba também o Ollama, na GPU NVIDIA (`--profile ia`) ou na CPU (`--profile ia-cpu`, bem mais lento):

```bash
docker compose -f docker-compose.dev.yml --profile ia up --build
```

Na primeira vez, baixe o modelo:

```bash
docker compose -f docker-compose.dev.yml exec ollama ollama pull qwen2.5:7b
```

Para rodar os testes (precisam de um PostgreSQL, que é o serviço `postgres` do compose de desenvolvimento; cada teste usa um esquema próprio, apagado ao final):

```bash
docker compose -f docker-compose.dev.yml exec -e TEST_DATABASE_URL=postgresql://planos:planos@postgres:5432/planos app pytest -q
```

#### Banco de dados

Usuários, papéis em cursos e revisões ficam no PostgreSQL (variável `DATABASE_URL`; serviço `postgres` nos dois composes). Os demais dados continuam em arquivos.

### No servidor (produção)

A produção roda no [Dokploy](https://dokploy.com), como recurso do tipo **Docker Compose**, usando o `docker-compose.yml` da raiz. Para configurar:

1. Crie um cliente OAuth no [Google Cloud](https://console.cloud.google.com) (tipo **Aplicativo da Web**), com o URI de redirecionamento `https://SEU_DOMINIO/oauth2/callback`. Para o login gov.br, peça a integração com o Login Único com o endereço de retorno `https://SEU_DOMINIO/auth/govbr/callback` e o de saída `https://SEU_DOMINIO/auth/gov/logout`, e preencha as variáveis `GOVBR_*` e `SEGREDO_SESSAO`. Com `LOGIN_GOOGLE=0`, fica só o gov.br.
2. No Dokploy, cadastre o repositório (branch `master`, arquivo `./docker-compose.yml`) e **desligue o Autodeploy**.
3. Em **Environment**, cole o `.env.example` e preencha os valores. Cada variável está explicada nele.
4. Em **Domains**, aponte o domínio para o serviço `caddy`, porta `80`, com HTTPS.
5. Coloque em `app/certificados/` o certificado da AC Raiz do Governo Federal do Brasil v1 (veja o [LEIA-ME](app/certificados/LEIA-ME.md)). Sem ele, os planos assinados são recusados.
6. Para o botão **Assinar com gov.br**, peça ao gov.br as credenciais da **API de Assinatura Eletrônica** (separadas das do login), com o endereço de retorno `https://SEU_DOMINIO/assinatura/govbr/callback`, e preencha as variáveis `GOVBR_ASSINATURA_*` (veja o `.env.example`). Sem elas, o professor assina em assinador.iti.br e envia o PDF, como antes. Assinar exige conta gov.br **prata ou ouro**. Em homologação, a conta de teste é criada em sso.staging.acesso.gov.br, o código de SMS pode ser `12345`, e a cadeia de teste do ITI é aceita a partir da própria resposta da API; em produção, só valem os certificados de `app/certificados/`.
7. Faça o deploy do projeto do Ollama conforme [`open-webui/README.md`](./open-webui/README.md) antes do validador.

#### Ollama e acesso por outros projetos

O Ollama fica em um projeto Compose independente na pasta [`open-webui/`](./open-webui/), implantável separadamente no Dokploy apontando para este repositório GitHub e usando o arquivo `./open-webui/docker-compose.yml`. Assim, o Ollama não é reiniciado junto com o validador.

Implante primeiro esse projeto: ele cria a rede `ollama-shared` e inicia o Ollama; depois implante o validador. As variáveis do Ollama estão em [`open-webui/.env.example`](./open-webui/.env.example), e os modelos ficam no volume persistente `ollama-data`.

O serviço `app` do validador também se conecta à rede compartilhada e acessa a API em `http://ollama:11434`. O Caddy o acessa pelo alias `fabrica-planos-web-interno` na rede privada, evitando confusão com outros serviços chamados `app` na rede do Dokploy. Outros projetos na mesma máquina podem usar o Ollama anexando seus serviços à rede externa `ollama-shared`. Exemplo no Compose consumidor:

```yaml
services:
  minha-aplicacao:
    environment:
      OLLAMA_BASE_URL: http://ollama:11434
    networks:
      - validador-ia

networks:
  validador-ia:
    name: ollama-shared
    external: true
```

Essa rede dá acesso à API do Ollama sem abrir a porta `11434` para a internet. Por padrão, a porta publicada no host só aceita conexões locais. Como o Ollama não oferece autenticação, só conecte à rede serviços confiáveis. Mantenha este projeto em execução para garantir que a rede exista; outros Compose a declaram como externa e não a removem.

Os PDFs, os resultados e os backups ficam em pastas fixas do servidor (padrão `/srv/validador-planos/`), preparadas automaticamente a cada deploy.

#### Backup e restauração

O sistema faz um backup automático todo dia às `BACKUP_HORA` (padrão **3h**, antes da validação das 5h) e guarda os últimos `BACKUP_MANTER` backups automáticos (padrão **7**). Os arquivos ficam em `BACKUPS_HOST_DIR` (padrão `/srv/validador-planos/backups`) e podem ser criados, baixados, restaurados e excluídos em **Administração > Backup**.

Cada backup é um ZIP com:

- `planos/`: os PDFs da pasta de planos;
- `resultados/`: `validacao_planos.csv`, `donos.json`, `ocultos.json`, `liberacoes.json`, `assinaturas.json`, o histórico das validações e os PDFs assinados;
- `banco.sql`: dump do PostgreSQL (usuários e revisões), feito com `pg_dump` e restaurado com `psql`;
- `manifesto.json`: formato, data, origem e contagens do backup.

A restauração substitui **todos** os dados atuais pelos do ZIP. Antes de substituir, o próprio sistema cria um backup do estado atual, com a origem “Antes de restaurar”, então dá para desfazer. A restauração é recusada enquanto houver uma validação em andamento. Os backups manuais e os de antes de restaurar não são apagados automaticamente.

Backups antigos sem `banco.sql` restauram apenas os arquivos; os dados atuais do PostgreSQL não são substituídos.

O backup fica na mesma VPS: ele protege contra exclusões e erros de operação, mas não contra a perda do servidor. Copie periodicamente os arquivos de `/srv/validador-planos/backups` para outro local (outra máquina, storage externo ou cópia offline). Para restaurar sem a interface (por exemplo, com o app fora do ar), descompacte o ZIP e copie as pastas por cima dos dados:

```bash
unzip -o /srv/validador-planos/backups/AAAAMMDD-HHMMSS-manual.zip -d /tmp/restaurar
rsync -a --delete /tmp/restaurar/planos/ /srv/validador-planos/planos/
rsync -a --delete /tmp/restaurar/resultados/ /srv/validador-planos/resultados/
docker compose exec -T postgres psql -U planos -d planos -v ON_ERROR_STOP=1 --single-transaction < /tmp/restaurar/banco.sql
```

O serviço `preparar-pastas` ajusta o dono das três pastas a cada deploy. As variáveis `BACKUP_HORA`, `BACKUP_MANTER`, `BACKUP_AGENDAR` e `BACKUPS_HOST_DIR` estão explicadas no `.env.example`.

**Deploy automático:** a cada push na `master`, o GitHub Actions roda os testes e a auditoria de dependências e, se tudo passar, pede o deploy ao Dokploy. Para isso, configure em **Settings > Secrets and variables > Actions** os secrets `DOKPLOY_URL`, `DOKPLOY_API_KEY` e `DOKPLOY_COMPOSE_ID`.

## Alto contraste

Todas as páginas têm, acima do cabeçalho, uma barra de utilidades com links de acesso rápido (Extensão e Estágios, SIGAA e Portal do Campus) e o botão **Alto contraste**. Ele alterna o tema em todas as páginas: fundo preto, texto branco e realces em amarelo, como no portal do IFC. A escolha é salva em `localStorage` (chave `contraste`) e reaplicada nas próximas visitas, antes do CSS carregar, para a página não piscar no tema claro.

## Como contribuir

1. Crie uma branch a partir da `master` e rode o projeto em modo de desenvolvimento (veja acima).
2. Organização do código em `app/`:
   - `rotas/` traduz as requisições HTTP;
   - `servicos/` guarda as regras de negócio;
   - `avaliacao/` faz a extração e a avaliação dos planos;
   - `armazenamento/` grava os arquivos de resultado;
   - `paginas/`, `templates/` e `static/` montam a interface.
3. Acrescente testes em `tests/` para o que mudar e confira se todos passam (`pytest -q`).
4. Abra um pull request. O CI roda os testes, o `pip-audit`, o build da imagem e a validação dos arquivos compose; tudo precisa passar antes do merge.

## Colaboradores

- [Fábrica de Software - IFC Videira](http://github.com/FabSoftwareVideira/)
- [Fabricio Bizotto](https://github.com/fabricioifc/)
- [Vinicius Slongo](https://github.com/vslongo/)
