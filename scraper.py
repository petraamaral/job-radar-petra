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
    "manager", "director", "vp ", "vice president", "head of",
    "senior manager", "junior", "jr.", "analista", "marketing specialist",
]

EXCLUDE_DESC = [
    # Cidadania / autorização
    "us citizen", "us citizenship", "green card",
    "must be authorized to work in the us",
    "authorized to work in the united states",
    "work authorization in the us",
    "us work authorization",
    # Localização US restritiva
    "must be located in the united states",
    "must reside in the us",
    "must be based in the us",
    "must be based in the united states",
    "based anywhere in the us",
    "based in the us",
    "position is based in the us",
    "this position can be based anywhere in the us",
    "only considering us",
    "us-based only",
    "united states only",
    "located in the united states",
    "reside in the united states",
    "north america only",
    "canada or us only",
    "must be in the us",
    "open to us residents",
    "us residents only",
    # Vagas BR
    "r$", "reais", " clt ", "são paulo", "rio de janeiro",
    "belo horizonte", "pessoa negra", "afirmativa",
]


def load_seen():
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()

def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(list(seen)))

def job_id(job):
    key = f"{job.get('title','')}{job.get('company','')}{job.get('url','')}"
    return hashlib.md5(key.encode()).hexdigest()

def strip_html(text):
    return re.sub(r"<[^>]+>", " ", text or "")

def score_job(title, description):
    t = title.lower()
    d = (description or "").lower()

    for kw in EXCLUDE_TITLE:
        if kw in t:
            return -1
    for kw in EXCLUDE_DESC:
        if kw in d:
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
    # Tenta pegar o link direto da vaga nos apply_options
    for opt in item.get("apply_options", []):
        link = opt.get("link", "")
        if link and "google.com" not in link:
            return link
    # Fallback: related_links
    for rl in item.get("related_links", []):
        link = rl.get("link", "")
        if link and "google.com" not in link:
            return link
    # Último recurso: link do Google Jobs com job_id se disponível
    job_id_val = item.get("job_id", "")
    if job_id_val:
        return f"https://www.google.com/search?q={job_id_val}&udm=8"
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
            "api_key": SERPAPI_KEY,
        }
        r = requests.get("https://serpapi.com/search", params=params, timeout=20)
        data = r.json()

        for item in data.get("jobs_results", []):
            # Extrai salário
            salary = ""
            det = item.get("detected_extensions", {})
            for v in det.values():
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
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"telegram error: {e}")

def format_message(job, score):
    salary_line = f"💰 <b>{job['salary']}</b>" if job.get("salary") else "💰 Não informado"
    desc = short_description(job.get("description", ""))
    desc_line = f"📋 {desc}\n" if desc else ""

    return (
        f"🎯 <b>{job['title']}</b>\n"
        f"──────────────────────\n"
        f"🏢 Empresa: {job.get('company') or 'N/A'}\n"
        f"📡 Portal: {job['source']}\n"
        f"──────────────────────\n"
        f"{desc_line}"
        f"──────────────────────\n"
        f"{salary_line}\n"
        f"🔗 <a href=\"{job['url']}\">Ver vaga</a>\n"
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
        jid = job_id(job)
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
