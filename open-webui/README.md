# Ollama

Projeto Docker Compose independente do validador. Ele executa o Ollama na GPU e cria a rede Docker compartilhada `ollama-shared`, pela qual o validador e outros projetos acessam a API em `http://ollama:11434`. Por ser separado, o Ollama não é reiniciado a cada deploy do validador.

## Deploy no Dokploy

1. Crie um recurso **Docker Compose** vinculado ao repositório GitHub `FabSoftwareVideira/fabrica-planos`.
2. Configure o arquivo Compose como `./open-webui/docker-compose.yml`.
3. Em **Environment**, cole o [`.env.example`](./.env.example) e ajuste se precisar (memória, CPUs, janela de contexto).
4. Baixe o modelo usado pelo validador no terminal do container `ollama`: `ollama pull qwen2.5:7b` (ou o definido em `OLLAMA_MODEL` no validador).

Não é preciso domínio: o Ollama não é publicado na internet. O volume `ollama-data` guarda os modelos entre recriações do container.

## Segurança

O Ollama não tem autenticação. A porta publicada no host aceita só conexões da própria máquina (`OLLAMA_BIND=127.0.0.1`), e na rede `ollama-shared` só devem entrar serviços confiáveis.
