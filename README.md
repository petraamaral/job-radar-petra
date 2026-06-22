# Job Radar — Petra

Scraper de vagas remotas para CS Ops. Roda diariamente via GitHub Actions e manda vagas relevantes no Telegram.

## Fontes monitoradas
- Remote OK (API)
- Himalayas (API)
- We Work Remotely (RSS)
- Working Nomads (RSS)

## Como configurar

### 1. Criar repositório no GitHub
- Cria um repo novo, pode ser privado: `job-radar-petra`
- Sobe todos os arquivos desta pasta

### 2. Adicionar secrets no GitHub
Vai em **Settings → Secrets and variables → Actions → New repository secret** e adiciona:

| Secret | Valor |
|--------|-------|
| `TELEGRAM_TOKEN` | Token do bot (BotFather) |
| `TELEGRAM_CHAT_ID` | Teu chat ID numérico |

### 3. Ativar o workflow
- Vai em **Actions** no GitHub
- Clica em **Job Radar**
- Clica em **Enable workflow** se estiver desativado
- Para testar agora: clica em **Run workflow**

## Como funciona o scoring

Cada vaga recebe pontos:
- +3 por keyword no **título** (cs operations, cx ops, support operations, etc.)
- +1 por keyword na **descrição** (zendesk, hubspot, churn, onboarding, etc.)
- Score < 2 = descartada silenciosamente
- Score -1 = excluída (US only, manager, director, VP, exige cidadania)

## Mensagem no Telegram

```
🎯 CS Operations Specialist
🏢 Acme Corp
📡 Himalayas
💰 $2,500–$3,500/month
🔗 Ver vaga
Score: 7
```

## Ajustar keywords

Edita o arquivo `scraper.py`:
- `TITLE_KEYWORDS` — palavras que pontuam no título
- `DESC_KEYWORDS` — palavras que pontuam na descrição
- `EXCLUDE_TITLE` — eliminam a vaga pelo título
- `EXCLUDE_DESC` — eliminam a vaga pela descrição (US only, cidadania, etc.)

## Rodar localmente (teste)

```bash
pip install -r requirements.txt
TELEGRAM_TOKEN="seu_token" TELEGRAM_CHAT_ID="seu_chat_id" python scraper.py
```
