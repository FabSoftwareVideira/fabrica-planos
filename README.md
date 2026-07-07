# Validação Automática de Planos de Ensino (TCC)

Sistema semiautomático que valida planos de ensino em PDF usando n8n e IA local (Ollama), verificando se todos os campos obrigatórios estão preenchidos corretamente. Os resultados vão para uma planilha Google Sheets e podem ser visualizados em um dashboard HTML.

## Como funciona

```
Google Drive (pasta com PDFs)
        │
        ▼
n8n: baixa e extrai o texto de cada PDF
        │
        ▼
Separa o texto por seções (ementa, objetivos, metodologia, ...)
        │
        ▼
Ollama (llama3.2, local/GPU): avalia cada campo → OK / INCOMPLETO / AUSENTE
        │
        ▼
Google Sheets (uma linha por plano) ──► Dashboard HTML (/webhook/dashboard)
```

### Critérios avaliados

Identificação (instituição, componente, docente) · Ementa · Objetivos geral e específicos · Conteúdo programático · Metodologia · Procedimentos de avaliação (incl. interdisciplinaridade) · Cronograma · Avaliações · Horário de atendimento · Referências (mín. 3 básicas + 5 complementares) · Coerência entre objetivos, metodologia e avaliação.

## Arquivos

| Arquivo | O que é |
|---------|---------|
| `3go4m2xSKi3p5P0g-My_workflow.json` | Workflow principal de validação (roda todo dia às 5h ou manualmente) |
| `dashboard-planos.json` | Workflow do dashboard HTML via webhook |
| `docker-compose.yml` | Stack n8n + Ollama (com GPU NVIDIA) |

## Requisitos

- Docker Desktop
- GPU NVIDIA (opcional, mas ~10x mais rápido; sem GPU remova o bloco `deploy` do `docker-compose.yml`)
- Conta Google com um projeto no Google Cloud Console

## Setup

### 1. Subir os containers

```bash
docker compose up -d
docker exec vslongo-workflows-ollama-1 ollama pull llama3.2
```

- n8n: http://localhost:5678 (criar conta local no primeiro acesso)
- Ollama: acessível pelos workflows em `http://ollama:11434`

### 2. Google Cloud Console

1. Criar credencial **OAuth 2.0 Client ID** em APIs e Serviços → Credenciais
2. Adicionar o redirect URI: `http://localhost:5678/rest/oauth2-credential/callback`
3. Ativar as APIs **Google Drive** e **Google Sheets**
4. Na Tela de consentimento OAuth, **publicar o app** (senão o token expira a cada 7 dias)

### 3. Importar os workflows no n8n

1. Add workflow → ⋮ → **Import from file** (para os dois JSONs)
2. Reconectar as credenciais Google nos nós do Drive e do Sheets
3. No nó **Registrar no Sheets** e no nó **Ler Validações**: selecionar a planilha (usar "From list" para evitar erro de ID)
4. A planilha precisa de uma aba chamada `Validações`

### 4. Usar

- **Validar**: abrir o workflow principal → **Test workflow** (ou esperar o agendamento das 5h)
- **Dashboard**: ativar o workflow do dashboard (toggle) e abrir http://localhost:5678/webhook/dashboard

## Solução de problemas

| Problema | Causa/Solução |
|----------|---------------|
| `redirect_uri_mismatch` no login Google | Adicionar o callback do passo 2 no Cloud Console |
| `403 access_denied` | App em modo teste: adicionar seu e-mail em "Usuários de teste" ou publicar o app |
| `invalid grant / refresh token` | Token expirou (app em modo teste) → reconectar credencial e publicar o app |
| Ollama lento / timeout | Verificar GPU: `docker exec vslongo-workflows-ollama-1 ollama ps` deve mostrar `100% GPU` |
| Esqueceu a senha do n8n | `docker exec vslongo-workflows-n8n-1 n8n user-management:reset` (workflows são preservados) |
| Só 1 plano processado | Code nodes devem usar `$input.all()`, nunca `$input.first()` |

## Análise dos resultados (monografia)

A planilha gera o dado por critério necessário para comparar o sistema com a avaliação humana (padrão ouro): coeficiente Kappa, acurácia, precisão, recall, F1-score e matriz de confusão. Esse cálculo é feito offline, fora do pipeline.
