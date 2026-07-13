# Job Radar

A self-hosted job search bot that runs daily, scores listings A–F, and delivers only the best matches to your Telegram.

Built to solve a real problem: manually checking six job boards every morning is wasted time when a script can do it better.

## Two modes

**Simple mode** (this repo) — runs via GitHub Actions cron, sends Grade A and B listings to Telegram. Zero infrastructure beyond GitHub. No interactivity.

**Interactive mode** (coming soon) — persistent process on Render with Telegram webhook. Adds "Save to OakJobs" buttons that insert listings directly into your application pipeline. Requires Render + Supabase.

## What it does

- Scrapes **Indeed, ZipRecruiter, and Google Jobs** concurrently via [JobSpy](https://github.com/speedyapply/JobSpy)
- Scans **Lever ATS directly** for companies you care about (no aggregator noise)
- Reads **RSS feeds** from We Work Remotely and Remotive as reliable fallback
- Filters dead links, broken descriptions, and irrelevant titles before touching the LLM
- Classifies each listing by `role_type` using Groq — `sales` and `technical` roles are discarded before scoring
- Scores remaining listings across **5 dimensions** using Groq (llama-3.1-8b-instant):
  - Remote fit (30%) — no location restriction, no US auth required
  - Title match (25%) — role aligns with target profile
  - Tool overlap (25%) — required tools match candidate skills
  - Experience level (10%) — not too senior, not too junior
  - Timezone (10%) — Americas or EMEA
- Converts the weighted score to a **letter grade (A–F)**
- Sends only **Grade A and B** listings to Telegram
- Caps at **3 listings per company** per run to avoid flooding
- Runs daily via **GitHub Actions** — zero infrastructure needed

## Why this instead of job boards

Job boards surface the same listings across dozens of aggregators, mixed with dead links, ghost jobs, and postings from companies that stopped hiring months ago. This bot goes to the source and filters aggressively before scoring, so what reaches you is actually worth reading.

## Setup

### 1. Fork or clone this repo

```bash
git clone https://github.com/yourusername/job-radar
```

### 2. Customize your profile

Edit `scraper.py` — find `CANDIDATE_PROFILE` near the top and replace with your own background, target roles, salary range, and work authorization.

Also update `LEVER_COMPANIES` with companies you want to track directly and `JOBSPY_QUERIES` with your target role titles.

### 3. Add GitHub Secrets

Settings → Secrets and variables → Actions → New repository secret:

| Secret | Description |
|--------|-------------|
| `TELEGRAM_TOKEN` | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Your numeric chat ID |
| `GROQ_API_KEY` | Free at console.groq.com |

SerpAPI is no longer required. JobSpy scrapes directly.

### 4. Run manually to test

Actions → Job Radar → Run workflow

Runs automatically every day at 09:00 BRT (12:00 UTC).

## Message format

```
🟢 Grade A · Customer Operations Specialist
──────────────────────
🏢 Acme Corp  |  📡 JobSpy · Indeed
──────────────────────
📌 Own the post-sale customer lifecycle, drive adoption and retention across a portfolio of SMB accounts.
🛠 Zendesk, HubSpot, SQL
🕐 Americas timezone
──────────────────────
💰 USD 3,000–4,000/yearly
🔗 Ver vaga
──────────────────────
📊 Remote 100 · Title 90 · Tools 85 · Level 80 · TZ 100
```

## Customize

| Variable | What it controls |
|----------|-----------------|
| `JOBSPY_QUERIES` | Search queries sent to Indeed/ZipRecruiter/Google |
| `LEVER_COMPANIES` | Company slugs to scan via Lever API |
| `RSS_SOURCES` | RSS feeds to monitor |
| `EXCLUDE_TITLE_QUICK` | Regex patterns to skip by title |
| `REQUIRE_TITLE_TERMS` | Whitelist — title must match at least one term |
| `DEAD_LINK_DOMAINS` | Domains to block |
| `MAX_PER_COMPANY` | Max listings per company per run (default: 3) |
| Grade filter in `main()` | Change `("A", "B")` to include C for more volume |

## Tech stack

- **[JobSpy](https://github.com/speedyapply/JobSpy)** (MIT) — job scraping from Indeed, ZipRecruiter, Google Jobs, LinkedIn
- **Groq API** (llama-3.1-8b-instant) — role classification and scoring, free tier
- **Lever public API** — direct ATS feed, no key needed
- **GitHub Actions** — free for public repos
- **Telegram Bot API** — free

## Credits

Job scraping powered by [JobSpy](https://github.com/speedyapply/JobSpy) by speedyapply (MIT License). This project would not be possible without their work on reverse-engineering job board APIs.

## Part of OakJobs

This bot is the sourcing layer for [OakJobs](https://github.com/yourusername/oakjobs) — an open-source personal ATS that tracks your applications, integrates Gmail, and scores fit with AI. Job Radar finds the listings; OakJobs manages everything after you apply.
