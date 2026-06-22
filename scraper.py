import requests
import json
import hashlib
import os
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SEEN_FILE = Path("seen_jobs.json")

# Keywords que pontuam positivo (título ou descrição)
TITLE_KEYWORDS = [
    "cs operations", "cs ops", "cso", "cx operations", "cx ops",
    "customer success operations", "support operations", "support ops",
    "revenue operations", "revops", "customer experience operations",
    "zendesk", "hubspot", "crm operations", "customer operations",
]

DESC_KEYWORDS = [
    "zendesk", "hubspot", "ivr", "csat", "churn", "onboarding",
    "knowledge base", "cloudtalk", "intercom", "freshdesk",
    "customer success", "cs ops", "support ops",
]

# Palavras que eliminam a vaga (título)
EXCLUDE_TITLE = [
    "manager", "director", "vp ", "vice president", "head of",
    "senior manager", "us only", "united states only",
    "must be us", "must reside in us", "must be based in us",
]

# Palavras que eliminam a vaga (descrição/requisitos)
EXCLUDE_DESC = [
    "us citizen", "us citizenship", "green card", "must be authorized to work in the us",
    "must be located in the united states", "must reside in the us",
    "must be based in the united states", "only considering us",
    "eligible to work in the us", "us work authorization required",
    "us-based only", "united states only", "north america only",
    "canada or us only", "must be in the us",
]


# ── Seen jobs persistence ─────────────────────────────────────────────────────
def load_seen():
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()

def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(list(seen)))

def job_id(job):
    key = f"{job.get('title','')}{job.get('company','')}{job.get('url','')}"
    return hashlib.md5(key.encode()).hexdigest()


# ── Scoring ───────────────────────────────────────────────────────────────────
def score_job(title, description):
    t = title.lower()
    d = (description or "").lower()

    # Eliminação imediata
    for kw in EXCLUDE_TITLE:
        if kw in t:
            return -1, f"excluded_title:{kw}"

    for kw in EXCLUDE_DESC:
        if kw in d:
            return -1, f"excluded_desc:{kw}"

    score = 0
    matched = []

    for kw in TITLE_KEYWORDS:
        if kw in t:
            score += 3
            matched.append(kw)

    for kw in DESC_KEYWORDS:
        if kw in d:
            score += 1
            matched.append(kw)

    return score, matched


# ── Sources ───────────────────────────────────────────────────────────────────
def fetch_remoteok():
    jobs = []
    try:
        r = requests.get(
            "https://remoteok.com/api",
            headers={"User-Agent": "JobRadarBot/1.0"},
            timeout=15,
        )
        data = r.json()
        for item in data:
            if not isinstance(item, dict) or "position" not in item:
                continue
            jobs.append({
                "title": item.get("position", ""),
                "company": item.get("company", ""),
                "description": item.get("description", ""),
                "url": item.get("url", f"https://remoteok.com/remote-jobs/{item.get('id','')}"),
                "salary": item.get("salary_min") or item.get("salary"),
                "source": "Remote OK",
            })
    except Exception as e:
        print(f"remoteok error: {e}")
    return jobs


def fetch_himalayas():
    jobs = []
    searches = [
        "cs+operations", "cx+operations", "support+operations",
        "customer+success+operations", "revenue+operations",
    ]
    for q in searches:
        try:
            r = requests.get(
                f"https://himalayas.app/jobs/api?q={q}&remote=true",
                headers={"User-Agent": "JobRadarBot/1.0"},
                timeout=15,
            )
            data = r.json()
            for item in data.get("jobs", []):
                jobs.append({
                    "title": item.get("title", ""),
                    "company": item.get("companyName", ""),
                    "description": item.get("description", ""),
                    "url": item.get("applicationLink") or f"https://himalayas.app/jobs/{item.get('slug','')}",
                    "salary": item.get("salaryRange", ""),
                    "source": "Himalayas",
                })
            time.sleep(1)
        except Exception as e:
            print(f"himalayas error ({q}): {e}")
    return jobs


def fetch_weworkremotely():
    import xml.etree.ElementTree as ET
    jobs = []
    feeds = [
        "https://weworkremotely.com/categories/remote-customer-support-jobs.rss",
        "https://weworkremotely.com/categories/remote-management-and-finance-jobs.rss",
    ]
    for url in feeds:
        try:
            r = requests.get(url, headers={"User-Agent": "JobRadarBot/1.0"}, timeout=15)
            root = ET.fromstring(r.content)
            for item in root.findall(".//item"):
                title = item.findtext("title") or ""
                company_raw = title.split(" at ")[-1] if " at " in title else ""
                title_clean = title.split(" at ")[0] if " at " in title else title
                desc_raw = item.findtext("description") or ""
                # strip HTML tags simply
                import re
                desc = re.sub(r"<[^>]+>", " ", desc_raw)
                jobs.append({
                    "title": title_clean.strip(),
                    "company": company_raw.strip(),
                    "description": desc,
                    "url": item.findtext("link") or "",
                    "salary": "",
                    "source": "We Work Remotely",
                })
        except Exception as e:
            print(f"weworkremotely error: {e}")
    return jobs


def fetch_workingnomads():
    import xml.etree.ElementTree as ET
    import re
    jobs = []
    feeds = [
        "https://www.workingnomads.com/feed?category=customer-support",
        "https://www.workingnomads.com/feed?category=management",
    ]
    for url in feeds:
        try:
            r = requests.get(url, headers={"User-Agent": "JobRadarBot/1.0"}, timeout=15)
            root = ET.fromstring(r.content)
            for item in root.findall(".//item"):
                title = item.findtext("title") or ""
                desc_raw = item.findtext("description") or ""
                desc = re.sub(r"<[^>]+>", " ", desc_raw)
                jobs.append({
                    "title": title.strip(),
                    "company": "",
                    "description": desc,
                    "url": item.findtext("link") or "",
                    "salary": "",
                    "source": "Working Nomads",
                })
        except Exception as e:
            print(f"workingnomads error: {e}")
    return jobs


# ── Telegram ──────────────────────────────────────────────────────────────────
def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"telegram error: {e}")


def format_message(job, score):
    salary_line = ""
    if job.get("salary"):
        salary_line = f"\n💰 <b>{job['salary']}</b>"

    return (
        f"🎯 <b>{job['title']}</b>\n"
        f"🏢 {job.get('company', 'N/A')}\n"
        f"📡 {job['source']}{salary_line}\n"
        f"🔗 <a href=\"{job['url']}\">Ver vaga</a>\n"
        f"Score: {score}"
    )


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    seen = load_seen()
    print(f"[{datetime.now()}] Starting job radar. {len(seen)} jobs already seen.")

    all_jobs = []
    all_jobs += fetch_remoteok()
    all_jobs += fetch_himalayas()
    all_jobs += fetch_weworkremotely()
    all_jobs += fetch_workingnomads()

    print(f"Fetched {len(all_jobs)} total jobs across all sources.")

    new_count = 0
    sent_count = 0

    for job in all_jobs:
        jid = job_id(job)
        if jid in seen:
            continue

        seen.add(jid)
        new_count += 1

        score, reason = score_job(job["title"], job.get("description", ""))

        if score < 0:
            continue  # excluded

        if score < 2:
            continue  # not relevant enough

        msg = format_message(job, score)
        send_telegram(msg)
        sent_count += 1
        time.sleep(0.5)  # avoid telegram rate limit

    save_seen(seen)
    print(f"Done. {new_count} new jobs found, {sent_count} sent to Telegram.")

    if sent_count == 0:
        send_telegram("✅ Job Radar rodou agora — nenhuma vaga nova relevante encontrada.")
    else:
        send_telegram(f"✅ Job Radar concluído: <b>{sent_count} vagas novas</b> enviadas.")


if __name__ == "__main__":
    main()
