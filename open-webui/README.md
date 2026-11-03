# Open WebUI

Projeto Docker Compose independente do validador. Ele executa o Open WebUI e o Ollama na GPU e cria a rede Docker compartilhada `ollama-shared`. Para implantá-lo no Dokploy:

1. Crie outro recurso **Docker Compose** vinculado ao repositório GitHub `FabSoftwareVideira/fabrica-planos`.
2. Configure o arquivo Compose como `./open-webui/docker-compose.yml`.
3. Configure as variáveis de `.env.example`. `OPEN_WEBUI_SECRET_KEY` deve ser uma chave aleatória persistente (por exemplo, `openssl rand -hex 32`). O Compose cria volumes persistentes para o WebUI e para os modelos do Ollama.
4. Implante este projeto antes do Compose do validador. O Compose cria a rede Docker `ollama-shared` automaticamente se ela ainda não existir.
5. Configure o domínio do Dokploy para o serviço `open-webui`, porta `8080`, com HTTPS.
6. Baixe o modelo necessário pelo terminal do container `ollama`, por exemplo `ollama pull qwen2.5:7b`.

Para criar a primeira conta administrativa, defina temporariamente `OPEN_WEBUI_ENABLE_SIGNUP=true`, registre a conta e depois volte para `false` e faça novo deploy. Os dados e as contas ficam no volume `open-webui-data`.

O Ollama deste projeto usa `http://ollama:11434`; serviços de outros Compose também podem acessar esse endereço ao se conectarem à mesma rede externa. A porta publicada no host, por padrão, só aceita conexões locais. O Ollama não oferece autenticação, portanto conecte à rede compartilhada apenas serviços confiáveis. Como o volume usa o nome padrão do novo projeto, os modelos armazenados no volume antigo não são reaproveitados e precisam ser baixados novamente.
