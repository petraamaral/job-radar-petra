# Job Radar — Petra

Busca diária de vagas CS Ops remotas via Google Jobs (SerpAPI) + RSS de backup. Manda no Telegram só o que é relevante.

## Setup

### 1. Criar repo no GitHub
Repo privado: `job-radar-petra`. Sobe todos os arquivos desta pasta.

### 2. Adicionar 3 secrets
Settings → Secrets and variables → Actions → New repository secret:

| Secret | Valor |
|--------|-------|
| `TELEGRAM_TOKEN` | Token do BotFather |
| `TELEGRAM_CHAT_ID` | Teu chat ID numérico |
| `SERPAPI_KEY` | Tua API key da SerpAPI |

### 3. Testar agora
Actions → Job Radar → Run workflow

Roda automaticamente todo dia às 9h BRT.

## Formato da mensagem

```
🎯 CS Operations Specialist
──────────────────────
🏢 Empresa: Acme Corp
📡 Portal: Google Jobs · via LinkedIn
──────────────────────
📋 Resumo curto da vaga...
──────────────────────
💰 $2,500–$3,500/month
🔗 Ver vaga
⭐ Score: 9
```

## Ajustar filtros

Edita `scraper.py`:

- `SERPAPI_QUERIES` — as buscas no Google Jobs (3 = 90 créditos/mês, dentro do free tier de 250)
- `TITLE_KEYWORDS` — +3 pontos por match no título
- `DESC_KEYWORDS` — +1 ponto por match na descrição  
- `EXCLUDE_TITLE` — elimina a vaga pelo título (manager, director, etc.)
- `EXCLUDE_DESC` — elimina pelo texto (US only, cidadania, vagas BR, etc.)
- Score mínimo para envio: linha `if score < 4` — sobe para filtrar mais, desce para ver mais

## Testar localmente

```bash
pip install -r requirements.txt
TELEGRAM_TOKEN="..." TELEGRAM_CHAT_ID="..." SERPAPI_KEY="..." python scraper.py
```
