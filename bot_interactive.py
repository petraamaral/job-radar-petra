"""
Job Radar — Interactive Mode
============================
Extends scraper.py with Telegram inline buttons.
Each job message gets two buttons: Save to OakJobs | Ignore.

Requirements:
- Supabase project with migration 002_telegram_bot.sql applied
- Edge Function telegram-webhook deployed
- SUPABASE_URL and SUPABASE_SERVICE_KEY env vars added

Run this instead of scraper.py when you want button support.
The scraper logic (fetching, filtering, Groq scoring) is identical.
"""

import json
import os
import time
import requests
from datetime import datetime

# Import all shared logic from scraper.py
from scraper import (
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, GROQ_API_KEY,
    CANDIDATE_PROFILE, JOBSPY_QUERIES, LEVER_COMPANIES, RSS_SOURCES,
    load_seen, save_seen, make_job_id,
    passes_title_whitelist, quick_exclude, is_dead_link,
    is_broken_description, RELEVANCE_KEYWORDS, MAX_PER_COMPANY,
    analyze_with_groq, grade_emoji,
    fetch_jobspy, fetch_lever, fetch_rss, fetch_remoteok,
    strip_html,
)

SUPABASE_URL         = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")


# ── Supabase helpers ──────────────────────────────────────────────────────────

def supabase_insert(table: str, payload: dict) -> dict | None:
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print("  Supabase not configured — skipping insert")
        return None
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers={
            "apikey":        SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
            "Content-Type":  "application/json",
            "Prefer":        "return=representation",
        },
        json=payload,
        timeout=10,
    )
    if not r.ok:
        print(f"  Supabase error ({table}): {r.status_code} {r.text[:200]}")
        return None
    return r.json()[0] if r.json() else None


def save_pending_job(chat_id: str, job: dict, analysis: dict) -> str | None:
    """Save job to radar_pending_jobs and return the UUID."""
    result = supabase_insert("radar_pending_jobs", {
        "chat_id": chat_id,
        "title":   job.get("title", ""),
        "company": job.get("company", ""),
        "job_url": job.get("url", ""),
        "source":  job.get("source", ""),
        "salary":  job.get("salary") or analysis.get("salary", ""),
        "grade":   analysis.get("grade", ""),
        "description": job.get("description", ""),
        "analysis": json.dumps({
            "what_they_want": analysis.get("what_they_want", ""),
            "tools_required": analysis.get("tools_required", ""),
            "red_flags":      analysis.get("red_flags", ""),
            "composite":      analysis.get("composite", 0),
        }),
    })
    return result["id"] if result else None


# ── Telegram with buttons ─────────────────────────────────────────────────────

def send_telegram_with_buttons(text: str, job_id: str):
    """Send message with Save / Ignore inline buttons."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id":    TELEGRAM_CHAT_ID,
                "text":       text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "reply_markup": {
                    "inline_keyboard": [[
                        {
                            "text":          "💾 Salvar no OakJobs",
                            "callback_data": f"save:{job_id}",
                        },
                        {
                            "text":          "❌ Ignorar",
                            "callback_data": f"ignore:{job_id}",
                        },
                    ]]
                },
            },
            timeout=10,
        ).raise_for_status()
    except Exception as e:
        print(f"  telegram error: {e}")


def format_message(job: dict, analysis: dict) -> str:
    grade   = analysis["grade"]
    emoji   = grade_emoji(grade)
    wants   = analysis.get("what_they_want", "")
    tools   = analysis.get("tools_required", "")
    salary  = job.get("salary") or analysis.get("salary") or "not mentioned"
    tz      = analysis.get("timezone", "")
    flags   = analysis.get("red_flags", "")
    link    = job.get("url", "")
    link_tag = f'<a href="{link}">Ver vaga</a>' if link else "Link não disponível"
    dims = (
        f"Remote {analysis['remote_score']} · "
        f"Title {analysis['title_score']} · "
        f"Tools {analysis['tool_score']} · "
        f"Level {analysis['level_score']} · "
        f"TZ {analysis['timezone_score']}"
    )
    lines = [
        f"{emoji} <b>Grade {grade}</b> · <b>{job['title']}</b>",
        f"──────────────────────",
        f"🏢 {job.get('company') or 'N/A'}  |  📡 {job['source']}",
        f"──────────────────────",
    ]
    if wants:
        lines.append(f"📌 {wants}")
    if tools and tools.lower() != "not specified":
        lines.append(f"🛠 {tools}")
    if tz and tz.lower() != "not mentioned":
        lines.append(f"🕐 {tz}")
    lines += [
        f"──────────────────────",
        f"💰 {salary}",
        f"🔗 {link_tag}",
        f"──────────────────────",
        f"📊 {dims}",
    ]
    if flags:
        lines.append(f"⚠️ {flags}")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    seen = load_seen()
    print(f"[{datetime.now()}] Job Radar v3 Interactive. {len(seen)} vagas já vistas.")

    all_jobs = []

    print("Fetching via JobSpy...")
    for query in JOBSPY_QUERIES:
        fetched = fetch_jobspy(query)
        print(f"  '{query}': {len(fetched)} jobs")
        all_jobs += fetched
        time.sleep(3)

    print("Fetching Lever direct feeds...")
    for slug in LEVER_COMPANIES:
        fetched = fetch_lever(slug)
        if fetched:
            print(f"  {slug}: {len(fetched)} jobs")
        all_jobs += fetched

    print("Fetching RSS feeds...")
    for source in RSS_SOURCES:
        fetched = fetch_rss(source["url"], source["name"])
        print(f"  {source['name']}: {len(fetched)} jobs")
        all_jobs += fetched
    all_jobs += fetch_remoteok()

    print(f"Total coletado: {len(all_jobs)} vagas brutas.")

    sent_a = sent_b = 0
    sent_per_company = {}

    for job in all_jobs:
        jid = make_job_id(job)
        if jid in seen:
            continue
        seen.add(jid)

        if not passes_title_whitelist(job["title"]):
            continue
        if quick_exclude(job["title"]):
            continue
        if is_dead_link(job.get("url", "")):
            continue
        if is_broken_description(job.get("description", "")):
            continue

        combined = (job["title"] + " " + job.get("description", "")).lower()
        if not any(kw in combined for kw in RELEVANCE_KEYWORDS):
            continue

        company_key = job.get("company", "unknown").lower()
        if sent_per_company.get(company_key, 0) >= MAX_PER_COMPANY:
            continue

        time.sleep(2)
        analysis = analyze_with_groq(job)
        if not analysis:
            continue

        grade     = analysis["grade"]
        remote    = analysis["remote_type"]
        role_type = analysis["role_type"]
        print(f"  [{grade} | {role_type} | {remote}] {job['title']} @ {job.get('company','')}")

        if remote in ("us_only", "hybrid_us"):
            continue
        if role_type in ("sales", "technical", "management"):
            continue
        if grade not in ("A", "B"):
            continue

        # Save to Supabase pending table and get the job UUID
        job_id = save_pending_job(TELEGRAM_CHAT_ID, job, analysis)

        if job_id:
            # Send with buttons
            send_telegram_with_buttons(format_message(job, analysis), job_id)
        else:
            # Fallback: send without buttons if Supabase not configured
            from scraper import send_telegram
            send_telegram(format_message(job, analysis))

        sent_per_company[company_key] = sent_per_company.get(company_key, 0) + 1
        if grade == "A":
            sent_a += 1
        else:
            sent_b += 1
        time.sleep(0.5)

    save_seen(seen)

    total = sent_a + sent_b
    summary = (
        f"✅ <b>Job Radar v3 Interactive concluído</b>\n"
        f"🟢 Grade A: {sent_a}  🔵 Grade B: {sent_b}\n"
        f"📨 Total enviado: {total}"
        if total > 0
        else "✅ Job Radar v3 Interactive — nenhuma vaga A ou B hoje."
    )
    from scraper import send_telegram
    send_telegram(summary)
    print(f"Concluído. A={sent_a} B={sent_b}")


if __name__ == "__main__":
    main()
