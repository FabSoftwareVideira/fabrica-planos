# OpenHands

Projeto Docker Compose independente do validador. Ele executa o OpenHands Agent Canvas e o Ollama na GPU, e cria a rede Docker compartilhada `ollama-shared` para outros projetos.

## Deploy no Dokploy

1. Crie outro recurso **Docker Compose** vinculado ao repositório GitHub `FabSoftwareVideira/fabrica-planos`.
2. Configure o arquivo Compose como `./open-webui/docker-compose.yml`.
3. Configure `LOCAL_BACKEND_API_KEY` e `OH_SECRET_KEY` com valores aleatórios fortes e persistentes (por exemplo, gere cada um com `openssl rand -hex 32`).
4. Configure o domínio do Dokploy para o serviço `openhands`, porta `8000`, com HTTPS.
5. Baixe o modelo desejado no terminal do container `ollama`, por exemplo `ollama pull qwen2.5-coder:14b`.

Os volumes `openhands-data`, `openhands-projects` e `ollama-data` persistem as configurações, os arquivos de projeto e os modelos. O conteúdo de `/projects` fica acessível ao agente.

## Configurar o Ollama

No OpenHands, abra **Settings → LLM → Add LLM Profile → Advanced** e configure:

- **Model:** `openai/qwen2.5-coder:14b` (ou outro modelo disponível no Ollama)
- **Provider Connection:** crie ou selecione uma conexão com Base URL `http://ollama:11434/v1` e uma API key fictícia, como `local-llm`

Modelos locais usados com agentes precisam de uma janela de contexto grande; o Compose configura 32k por padrão. Reduza `OLLAMA_CONTEXT_LENGTH` se faltar VRAM. O validador e outros projetos podem usar o mesmo Ollama na rede externa `ollama-shared`.

## Segurança

O agente pode executar comandos e modificar arquivos dentro do ambiente de trabalho. Proteja o domínio com autenticação ou VPN e só monte em `/projects` repositórios nos quais o agente possa trabalhar. Não monte o socket do Docker nem habilite modo privilegiado, salvo se aceitar conscientemente o risco adicional.
