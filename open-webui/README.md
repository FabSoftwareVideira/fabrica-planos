# Ollama

O Ollama agora faz parte do Compose principal na raiz do repositório. Configure suas variáveis no `.env.example` da raiz e implante apenas `docker-compose.yml`; não crie um recurso Compose separado para esta pasta.

Para migrar uma implantação existente, pare/remova o recurso independente no Dokploy sem apagar seu volume de modelos. O Compose principal espera por padrão o volume `open-webui_ollama-data`; se o volume existente tiver outro nome, defina `OLLAMA_VOLUME_NAME` no ambiente do recurso principal. Em uma instalação nova, crie o volume antes do primeiro deploy. Consulte a seção “Ollama e acesso por outros projetos” do [README principal](../README.md) para detalhes.
