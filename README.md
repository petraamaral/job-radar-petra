# Job Radar

A self-hosted job search bot that runs daily, scores listings A–F, and delivers only the best matches to your Telegram.

Built to solve a real problem: manually checking six job boards every morning is wasted time when a script can do it better.

## What it does

- Scans **Greenhouse ATS directly** (company career pages, no aggregator noise)
- Reads **RSS feeds** from We Work Remotely and Remotive
- Falls back to **Google Jobs via SerpAPI** for broader coverage
- Filters dead links, stale aggregator spam, and irrelevant titles before touching the LLM
- Scores each listing across **5 dimensions** using Groq (llama-3.1-8b-instant):
  - Remote fit (30%) — no location restriction, no US auth required
  - Title match (25%) — role aligns with target profile
  - Tool overlap (25%) — required tools match candidate skills
  - Experience level (10%) — not too senior, not too junior
  - Timezone (10%) — Americas or EMEA
- Converts the weighted score to a **letter grade (A–F)**
- Sends only **Grade A and B** listings to Telegram
- Runs daily via **GitHub Actions** — zero infrastructure needed

## Why this instead of job boards

Job boards surface the same listings across dozens of aggregators, mixed with dead links, ghost jobs, and postings from companies that stopped hiring months ago. This bot goes to the source (ATS APIs and verified RSS feeds) and filters aggressively before scoring, so what reaches you is actually worth reading.

## Setup

### 1. Fork or clone this repo

```bash
git clone https://github.com/yourusername/job-radar
```

### 2. Customize your profile

Edit `scraper.py` — find `CANDIDATE_PROFILE` near the top and replace with your own background, target roles, salary range, and work authorization.

Also update `GREENHOUSE_COMPANIES` with companies you want to track directly.

### 3. Add GitHub Secrets

Settings → Secrets and variables → Actions → New repository secret:

| Secret | Description |
|--------|-------------|
| `TELEGRAM_TOKEN` | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Your numeric chat ID |
| `GROQ_API_KEY` | Free at console.groq.com |
| `SERPAPI_KEY` | Optional — free tier at serpapi.com (100 searches/month) |

### 4. Run manually to test

Actions → Job Radar → Run workflow

Runs automatically every day at 09:00 BRT (12:00 UTC).

## Message format

```
🟢 Grade A · Customer Operations Specialist
──────────────────────
🏢 Acme Corp  |  📡 Greenhouse · acmecorp
──────────────────────
📌 Own the post-sale customer lifecycle, drive adoption and retention across a portfolio of 200+ SMB accounts.
🛠 Zendesk, HubSpot, SQL, Metabase
🕐 Americas timezone
──────────────────────
💰 $3,000–$4,000/month
🔗 Ver vaga
──────────────────────
📊 Remote 100 · Title 90 · Tools 85 · Level 80 · TZ 100
```

## Customize

| Variable | What it controls |
|----------|-----------------|
| `SERPAPI_QUERIES` | Search queries sent to Google Jobs |
| `GREENHOUSE_COMPANIES` | Company slugs to scan via Greenhouse API |
| `RSS_SOURCES` | RSS feeds to monitor |
| `EXCLUDE_TITLE_QUICK` | Regex patterns to skip by title |
| `DEAD_LINK_DOMAINS` | Aggregator domains to block |
| Grade filter in `main()` | Change `("A", "B")` to include C if you want more volume |

## Tech stack

- Python 3.11
- Groq API (llama-3.1-8b-instant) — free tier
- SerpAPI Google Jobs — optional, free tier (100 req/month)
- Greenhouse public API — no key needed
- GitHub Actions — free for public repos
- Telegram Bot API — free

## Part of OakJobs

This bot is the sourcing layer for [OakJobs](https://github.com/yourusername/oakjobs) — an open-source personal ATS that tracks your applications, integrates Gmail, and scores fit with AI. Job Radar finds the listings; OakJobs manages everything after you apply.
