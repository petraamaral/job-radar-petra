import requests
import json
import hashlib
import os
import time
import re
from datetime import datetime
from pathlib import Path

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")
SEEN_FILE = Path("seen_jobs.json")

SERPAPI_QUERIES = [
    "CX Operations Specialist remote",
    "Support Operations Specialist remote",
    "Customer Success Operations remote",
]

TITLE_KEYWORDS = [
    "cs operations", "cs ops", "cx operations", "cx ops",
    "customer success operations", "support operations", "support ops",
    "revenue operations", "revops", "customer operations",
    "zendesk admin", "crm operations", "customer experience operations",
]

DESC_KEYWORDS = [
    "zendesk", "hubspot", "ivr", "csat", "churn", "onboarding",
    "knowledge base", "cloudtalk", "intercom", "freshdesk",
    "customer success", "cs ops", "support ops", "health score",
    "gainsight", "churnzero", "playbook",
]

EXCLUDE_TITLE = [
    "manager", "director", r"\bvp\b", "vice president", "head of",
    "senior manager", r"\bjunior\b", r"\bjr\b", "analista",
    "marketing specialist",
]

# Padrões regex precisos para US-only — evita falsos positivos com "West Coast US"
US_ONLY_PATTERNS = [
    r"\bmust be (authorized|authorised) to work in the (us|united states)\b",
    r"\bwork authorization (required )?(in|for) the (us|united states)\b",
    r"\bus (work )?authorization required\b",
    r"\bmust (reside|be (located|based)) in the (us|united states)\b",
    r"\bthis (position|role) (is |can be )?(only |exclusively )?based in the (us|united states)\b",
    r"\bonly (considering|open to|accepting) (candidates (in|from) )?(the )?(us|united states)\b",
    r"\b(us|united states)[- ]only\b",
    r"\beligible to work in the (us|united states)\b",
    r"\bmust (have|hold) (a )?(us|united states) (citizenship|work permit|visa)\b",
    r"\b(green card|us citizen(ship)?)\b",
    r"\bnorth america only\b",
    r"\b(canada or us|us or canada) only\b",
    r"\bus residents only\b",
    r"\bopen only to (us|united states) residents\b",
    r"\bauthorized to work in (the )?us\b",
]

BR_PATTERNS = [
    r"\br\$\s*\d",
    r"\bclt\b",
    r"\bvaga afirmativa\b",
    r"\bpessoas negras\b",
    r"\bsão paulo\b",
    r"\bbelo horizonte\b",
]


def load_seen():
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()

def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(list(seen)))

def make_job_id(job):
    key = f"{job.get('title','')}{job.get('company','')}{job.get('url','')}"
    return hashlib.md5(key.encode()).hexdigest()

def strip_html(text):
    return re.sub(r"<[^>]+>", " ", text or "")

def is_excluded(title, description):
    t = title.lower()
    d = (description or "").lower()

    # Título — alguns como regex, outros como substring simples
    for kw in EXCLUDE_TITLE:
        if re.search(kw, t):
            return True, f"title:{kw}"

    # US-only — regex preciso
    for pattern in US_ONLY_PATTERNS:
        if re.search(pattern, d, re.IGNORECASE):
            return True, f"us_only:{pattern[:40]}"

    # Vagas BR
    for pattern in BR_PATTERNS:
        if re.search(pattern, d, re.IGNORECASE):
            return True, f"br:{pattern}"

    return False, ""

def score_job(title, description):
    t = title.lower()
    d = (description or "").lower()

    excluded, reason = is_excluded(title, description)
    if excluded:
        return -1

    score = 0
    for kw in TITLE_KEYWORDS:
        if kw in t:
            score += 3
    for kw in DESC_KEYWORDS:
        if kw in d:
            score += 1
    return score

def short_description(text, max_chars=180):
    text = strip_html(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "..."

def extract_apply_link(item):
    for opt in item.get("apply_options", []):
        link = opt.get("link", "")
        if link and "google.com" not in link:
            return link
    for rl in item.get("related_links", []):
        link = rl.get("link", "")
        if link and "google.com" not in link:
            return link
    return ""


# ── SerpAPI ───────────────────────────────────────────────────────────────────
def fetch_serpapi(query):
    jobs = []
    if not SERPAPI_KEY:
        print("SERPAPI_KEY não definida, pulando Google Jobs.")
        return jobs
    try:
        params = {
            "engine": "google_jobs",
            "q": query,
            "hl": "en",
            "chips": "date_posted:month",  # só vagas do último mês
            "api_key": SERPAPI_KEY,
        }
        r = requests.get("https://serpapi.com/search", params=params, timeout=20)
        data = r.json()

        for item in data.get("jobs_results", []):
            salary = ""
            for v in item.get("detected_extensions", {}).values():
                if isinstance(v, str) and any(c in v for c in ["$", "€", "£", "USD", "EUR"]):
                    salary = v
                    break
            if not salary:
                for h in item.get("job_highlights", []):
                    for hi in h.get("items", []):
                        if any(c in hi for c in ["$", "€", "£", "/month", "/year", "/hr"]):
                            salary = hi
                            break

            jobs.append({
                "title": item.get("title", ""),
                "company": item.get("company_name", ""),
                "description": item.get("description", ""),
                "url": extract_apply_link(item),
                "salary": salary,
                "source": f"Google Jobs · via {item.get('via', 'N/A')}",
            })
        time.sleep(1)
    except Exception as e:
        print(f"serpapi error ({query}): {e}")
    return jobs


# ── Remote OK ─────────────────────────────────────────────────────────────────
def fetch_remoteok():
    jobs = []
    try:
        r = requests.get(
            "https://remoteok.com/api",
            headers={"User-Agent": "JobRadarBot/1.0"},
            timeout=15,
        )
        for item in r.json():
            if not isinstance(item, dict) or "position" not in item:
                continue
            s_min = item.get("salary_min")
            s_max = item.get("salary_max")
            salary = ""
            if s_min and s_max:
                salary = f"${int(s_min):,}–${int(s_max):,}/year"
            elif s_min:
                salary = f"${int(s_min):,}/year"
            jobs.append({
                "title": item.get("position", ""),
                "company": item.get("company", ""),
                "description": item.get("description", ""),
                "url": item.get("url", ""),
                "salary": salary,
                "source": "Remote OK",
            })
    except Exception as e:
        print(f"remoteok error: {e}")
    return jobs


# ── We Work Remotely ──────────────────────────────────────────────────────────
def fetch_weworkremotely():
    import xml.etree.ElementTree as ET
    jobs = []
    try:
        r = requests.get(
            "https://weworkremotely.com/categories/remote-customer-support-jobs.rss",
            headers={"User-Agent": "JobRadarBot/1.0"},
            timeout=15,
        )
        root = ET.fromstring(r.content)
        for item in root.findall(".//item"):
            title_raw = item.findtext("title") or ""
            company = title_raw.split(" at ")[-1].strip() if " at " in title_raw else ""
            title = title_raw.split(" at ")[0].strip() if " at " in title_raw else title_raw
            desc = strip_html(item.findtext("description") or "")
            jobs.append({
                "title": title,
                "company": company,
                "description": desc,
                "url": item.findtext("link") or "",
                "salary": "",
                "source": "We Work Remotely",
            })
    except Exception as e:
        print(f"weworkremotely error: {e}")
    return jobs


# ── Telegram ──────────────────────────────────────────────────────────────────
def send_telegram(text):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        r.raise_for_status()
    except Exception as e:
        print(f"telegram error: {e}")

def format_message(job, score):
    salary_line = f"💰 <b>{job['salary']}</b>" if job.get("salary") else "💰 Não informado"
    desc = short_description(job.get("description", ""))
    desc_line = f"📋 {desc}\n" if desc else ""
    link = job.get("url") or "N/A"
    link_tag = f'<a href="{link}">Ver vaga</a>' if link != "N/A" else "Link não disponível"

    return (
        f"🎯 <b>{job['title']}</b>\n"
        f"──────────────────────\n"
        f"🏢 Empresa: {job.get('company') or 'N/A'}\n"
        f"📡 Portal: {job['source']}\n"
        f"──────────────────────\n"
        f"{desc_line}"
        f"──────────────────────\n"
        f"{salary_line}\n"
        f"🔗 {link_tag}\n"
        f"⭐ Score: {score}"
    )


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    seen = load_seen()
    print(f"[{datetime.now()}] Job Radar iniciado. {len(seen)} vagas já vistas.")

    all_jobs = []
    for q in SERPAPI_QUERIES:
        all_jobs += fetch_serpapi(q)
    all_jobs += fetch_remoteok()
    all_jobs += fetch_weworkremotely()

    print(f"Total coletado: {len(all_jobs)} vagas brutas.")

    sent_count = 0
    for job in all_jobs:
        jid = make_job_id(job)
        if jid in seen:
            continue
        seen.add(jid)

        score = score_job(job["title"], job.get("description", ""))
        if score < 4:
            continue

        send_telegram(format_message(job, score))
        sent_count += 1
        time.sleep(0.5)

    save_seen(seen)
    print(f"Concluído. {sent_count} vagas enviadas.")

    summary = (
        f"✅ <b>Job Radar concluído</b>\n📨 {sent_count} vagas novas encontradas"
        if sent_count > 0
        else "✅ Job Radar concluído — nenhuma vaga nova relevante hoje."
    )
    send_telegram(summary)


if __name__ == "__main__":
    main()
