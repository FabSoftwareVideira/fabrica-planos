# Validador de Planos de Ensino

Aplicação web do IFC Videira que avalia os planos de ensino (PDFs do SIGAA) com IA local e mostra o resultado num painel.

- O texto de cada PDF é extraído e separado em seções (ementa, objetivos, metodologia, cronograma, referências…). Um modelo local no [Ollama](https://ollama.com) (padrão `qwen2.5:7b`) avalia cada campo, e regras fixas conferem o que não depende da IA, como a contagem de referências e o horário de atendimento.
- O **painel** mostra a situação de cada plano (aprovado, pendente ou com problemas), com filtros por curso, período e docente, e um relatório por plano com o texto extraído e a resposta da IA.
- Em **Meus planos**, cada professor entrega e acompanha os próprios planos. A **coordenação, o NDE e o NDB** de cada curso revisam a avaliação da IA, e o parecer deles passa a valer.
- Depois de aprovado na revisão, o professor **assina o plano com a conta gov.br** (em [assinador.iti.br](https://assinador.iti.br)) e envia o PDF assinado em **Meus planos**. O app confere a assinatura, que precisa ser de um certificado das autoridades em [`app/certificados/`](app/certificados/LEIA-ME.md), e se o conteúdo é o do plano aprovado.
- A **administração** envia PDFs, dispara validações (também roda todo dia, às 5h) e gerencia usuários e papéis.
- O acesso é feito com a conta **gov.br** ou com a conta Google institucional. Nos dois casos vale o e-mail `@ifc.edu.br`: no gov.br, ele precisa estar cadastrado e verificado na conta.

Feito em Python 3.12 com Flask e gunicorn, e páginas no [Padrão Digital de Governo](https://www.gov.br/ds/). Em produção, roda em Docker atrás de Caddy e oauth2-proxy (Google); o login gov.br é feito pelo próprio app.

## Como rodar

### Na sua máquina (desenvolvimento)

Precisa do Docker. O comando abaixo sobe o app com recarga automática e login simulado, sem precisar de conta Google:

```bash
docker compose -f docker-compose.dev.yml up --build
```

Abra http://localhost:8000 e, em **Entrar**, escolha um perfil de teste (administração, coordenação, NDE, professor…).

- Os PDFs vêm da pasta `planos/` e os resultados ficam em `dev-resultados/`. As duas pastas ficam fora do git.
- Sem a IA, a interface funciona, mas as validações terminam em ERRO. Para validar de verdade, suba também o Ollama, na GPU NVIDIA (`--profile ia`) ou na CPU (`--profile ia-cpu`, bem mais lento):

```bash
docker compose -f docker-compose.dev.yml --profile ia up --build
```

Na primeira vez, baixe o modelo:

```bash
docker compose -f docker-compose.dev.yml exec ollama ollama pull qwen2.5:7b
```

Para rodar os testes:

```bash
docker compose -f docker-compose.dev.yml exec app pytest -q
```

### No servidor (produção)

A produção roda no [Dokploy](https://dokploy.com), como recurso do tipo **Docker Compose**, usando o `docker-compose.yml` da raiz. Para configurar:

1. Crie um cliente OAuth no [Google Cloud](https://console.cloud.google.com) (tipo **Aplicativo da Web**), com o URI de redirecionamento `https://SEU_DOMINIO/oauth2/callback`. Para o login gov.br, peça a integração com o Login Único com o endereço de retorno `https://SEU_DOMINIO/auth/govbr/callback` e o de saída `https://SEU_DOMINIO/auth/gov/logout`, e preencha as variáveis `GOVBR_*` e `SEGREDO_SESSAO`. Com `LOGIN_GOOGLE=0`, fica só o gov.br.
2. No Dokploy, cadastre o repositório (branch `master`, arquivo `./docker-compose.yml`) e **desligue o Autodeploy**.
3. Em **Environment**, cole o `.env.example` e preencha os valores. Cada variável está explicada nele.
4. Em **Domains**, aponte o domínio para o serviço `caddy`, porta `80`, com HTTPS.
5. Coloque em `app/certificados/` o certificado da AC Raiz do Governo Federal do Brasil v1 (veja o [LEIA-ME](app/certificados/LEIA-ME.md)). Sem ele, os planos assinados são recusados.
6. Faça o deploy do projeto do Ollama conforme [`open-webui/README.md`](./open-webui/README.md) antes do validador.

#### Ollama e acesso por outros projetos

O Ollama fica em um projeto Compose independente na pasta [`open-webui/`](./open-webui/), implantável separadamente no Dokploy apontando para este repositório GitHub e usando o arquivo `./open-webui/docker-compose.yml`. Assim, o Ollama não é reiniciado junto com o validador.

Implante primeiro esse projeto: ele cria a rede `ollama-shared` e inicia o Ollama; depois implante o validador. As variáveis do Ollama estão em [`open-webui/.env.example`](./open-webui/.env.example), e os modelos ficam no volume persistente `ollama-data`.

O serviço `app` do validador também se conecta à rede compartilhada e acessa a API em `http://ollama:11434`. Outros projetos na mesma máquina podem usar o mesmo endereço anexando seus serviços à rede externa `ollama-shared`. Exemplo no Compose consumidor:

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

Os PDFs e os resultados ficam em pastas fixas do servidor (padrão `/srv/validador-planos/`), preparadas automaticamente a cada deploy. Faça backup de `/srv/validador-planos/resultados`, onde ficam os usuários, as revisões e a validação atual.

**Deploy automático:** a cada push na `master`, o GitHub Actions roda os testes e a auditoria de dependências e, se tudo passar, pede o deploy ao Dokploy. Para isso, configure em **Settings > Secrets and variables > Actions** os secrets `DOKPLOY_URL`, `DOKPLOY_API_KEY` e `DOKPLOY_COMPOSE_ID`.

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
