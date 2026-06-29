import requests
import json
import hashlib
import os
import time
import re
from datetime import datetime
from pathlib import Path

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SERPAPI_KEY      = os.environ.get("SERPAPI_KEY", "")
GROQ_API_KEY     = os.environ.get("GROQ_API_KEY", "")
SEEN_FILE        = Path("seen_jobs.json")

CANDIDATE_PROFILE = """
Name: Petra Iglezias Amaral
Role target: CS Operations Specialist / CX Operations / Support Operations
Experience: 4+ years
Key skills: IVR design and deployment (CloudTalk), skills-based routing, Zendesk administration,
  knowledge base architecture, HubSpot Service Hub (certified), Power BI (certified), Metabase,
  Python scripting for automation and web scraping, SQL for data querying, multilingual onboarding
  (Portuguese/English/Spanish), NPS/CSAT frameworks, ARR retention, churn analysis,
  familiar with Gainsight and ChurnZero health score frameworks, GDPR awareness.
Track record: 30+ concurrent accounts managed, zero churn, 9.4 CSAT, IVR built from scratch,
  data coverage scaled 10% to 100% via Python automation (tool still in production),
  fraud prevention solo coverage at international fintech with zero chargebacks.
Work authorization: Brazilian national. NOT eligible for US work authorization.
  Can work fully remotely for any company worldwide EXCEPT US-only roles.
  Open to Americas or EMEA timezones.
Salary expectation: USD $2,500–$4,000/month remote.
"""

SERPAPI_QUERIES = [
    "Support Operations Specialist remote",
    "Customer Operations Specialist remote",
    "Revenue Operations Analyst remote",
    "Zendesk Administrator remote",
    "CX Operations Analyst remote",
    "Customer Success Operations remote",
]

EXCLUDE_TITLE_QUICK = [
    r"\bdirector\b", r"\bvp\b", r"\bvice president\b", r"\bhead of\b",
    r"\bsenior manager\b", r"\bjunior\b", r"\bjr\b",
]

RELEVANCE_KEYWORDS = [
    "customer", "support", "success", "operations", "ops", "cx ", "cs ",
    "crm", "zendesk", "hubspot", "onboarding", "retention", "churn",
    "account", "service", "helpdesk", "client", "revenue",
]

# Spam aggregator domains — links never work
DEAD_LINK_DOMAINS = [
    "liveblog365.com", "infinityfree.me", "quickswoop", "halvolink",
    "hirevista", "skillorbit", "jobsearcher.com", "jooble.org",
    "trovit.com", "adzuna.com",
]

# Broken description signals — not real job posts
BROKEN_DESC_SIGNALS = [
    "internet explorer 11 is no longer supported",
    "please update to one of the following browsers",
    "check availabilitylogin",
    "override the digital divide with additional clickthroughs",
    "capitalise on low hanging fruit",
    "nanotechnology immersion",
    "testing 123",
    "lorem ipsum",
    "will come and clean house",
    "sorry, internet explorer",
    "please enable javascript",
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

def quick_exclude(title):
    t = title.lower()
    for pattern in EXCLUDE_TITLE_QUICK:
        if re.search(pattern, t):
            return True
    return False

def is_dead_link(url):
    url_lower = (url or "").lower()
    return any(domain in url_lower for domain in DEAD_LINK_DOMAINS)

def is_broken_description(desc):
    d = (desc or "").lower()
    return any(signal in d for signal in BROKEN_DESC_SIGNALS)

def short_description(text, max_chars=200):
    text = strip_html(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "..."

def extract_apply_link(item):
    for opt in item.get("apply_options", []):
        link = opt.get("link", "")
        if link and "google.com" not in link and not is_dead_link(link):
            return link
    for rl in item.get("related_links", []):
        link = rl.get("link", "")
        if link and "google.com" not in link and not is_dead_link(link):
            return link
    return ""


def groq_request(prompt):
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "max_tokens": 350,
        "temperature": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers, json=payload, timeout=15,
    )
    if r.status_code == 429:
        retry_after = int(r.headers.get("retry-after", 10))
        print(f"  Groq rate limit, waiting {retry_after}s...")
        time.sleep(retry_after + 1)
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers, json=payload, timeout=15,
        )
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])


def analyze_with_groq(job):
    if not GROQ_API_KEY:
        return {
            "remote_type": "skip", "fit_score": 0,
            "what_they_want": "", "tools_required": "",
            "salary": "", "timezone": "",
            "fit_gap": "", "red_flags": "",
        }

    desc_truncated = strip_html(job.get("description", ""))[:1800]
    title = job.get("title", "")
    company = job.get("company", "")

    prompt = (
        "You are a job analyst. Extract structured data from a job posting and evaluate fit for a candidate.\n\n"
        f"CANDIDATE PROFILE:\n{CANDIDATE_PROFILE}\n\n"
        f"JOB POSTING:\nTitle: {title}\nCompany: {company}\nDescription: {desc_truncated}\n\n"
        "Respond ONLY with a JSON object — no markdown:\n"
        "{\n"
        '  "remote_type": "<global|us_only|hybrid_us|unclear>",\n'
        '  "fit_score": <integer 0-100>,\n'
        '  "what_they_want": "<2 sentences on actual day-to-day duties only — skip company boilerplate. If no duties visible write: Description too vague.>",\n'
        '  "tools_required": "<comma-separated tools/skills explicitly mentioned, or: not specified>",\n'
        '  "salary": "<salary range if mentioned, or: not mentioned>",\n'
        '  "timezone": "<timezone/region requirement if mentioned, or: not mentioned>",\n'
        '  "fit_gap": "<what candidate has vs what is missing — max 100 chars>",\n'
        '  "red_flags": "<specific real concern from posting only — empty string if none>"\n'
        "}\n\n"
        "RULES:\n"
        "- remote_type global = no location restriction. us_only = requires US residency/auth/citizenship. hybrid_us = remote + occasional US onsite. unclear = not stated.\n"
        "- red_flags: never flag work authorization unless posting explicitly requires it. Never flag salary unless posting states under $2000/month.\n"
        "- fit_score: 80-100 strong, 60-79 good, 40-59 partial, 0-39 poor."
    )

    try:
        result = groq_request(prompt)
        return {
            "remote_type":   result.get("remote_type", "unclear"),
            "fit_score":     int(result.get("fit_score", 50)),
            "what_they_want": result.get("what_they_want", ""),
            "tools_required": result.get("tools_required", ""),
            "salary":        result.get("salary", ""),
            "timezone":      result.get("timezone", ""),
            "fit_gap":       result.get("fit_gap", ""),
            "red_flags":     result.get("red_flags", ""),
        }
    except Exception as e:
        print(f"  groq error: {e}")
        return {
            "remote_type": "skip", "fit_score": 0,
            "what_they_want": "", "tools_required": "",
            "salary": "", "timezone": "",
            "fit_gap": "", "red_flags": "",
        }


def fetch_serpapi(query):
    jobs = []
    if not SERPAPI_KEY:
        return jobs
    try:
        r = requests.get("https://serpapi.com/search", params={
            "engine": "google_jobs",
            "q": query,
            "hl": "en",
            "chips": "date_posted:month",
            "api_key": SERPAPI_KEY,
        }, timeout=20)
        for item in r.json().get("jobs_results", []):
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
                "title":       item.get("title", ""),
                "company":     item.get("company_name", ""),
                "description": item.get("description", ""),
                "url":         extract_apply_link(item),
                "salary":      salary,
                "source":      f"Google Jobs · via {item.get('via', 'N/A')}",
            })
        time.sleep(1)
    except Exception as e:
        print(f"serpapi error ({query}): {e}")
    return jobs


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
            salary = f"${int(s_min):,}–${int(s_max):,}/year" if s_min and s_max else (f"${int(s_min):,}/year" if s_min else "")
            jobs.append({
                "title":       item.get("position", ""),
                "company":     item.get("company", ""),
                "description": item.get("description", ""),
                "url":         item.get("url", ""),
                "salary":      salary,
                "source":      "Remote OK",
            })
    except Exception as e:
        print(f"remoteok error: {e}")
    return jobs


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
            company   = title_raw.split(" at ")[-1].strip() if " at " in title_raw else ""
            title     = title_raw.split(" at ")[0].strip()  if " at " in title_raw else title_raw
            jobs.append({
                "title":       title,
                "company":     company,
                "description": strip_html(item.findtext("description") or ""),
                "url":         item.findtext("link") or "",
                "salary":      "",
                "source":      "We Work Remotely",
            })
    except Exception as e:
        print(f"weworkremotely error: {e}")
    return jobs


def send_telegram(text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10,
        ).raise_for_status()
    except Exception as e:
        print(f"telegram error: {e}")

def fit_emoji(score):
    if score >= 80: return "🟢"
    if score >= 60: return "🟡"
    if score >= 40: return "🟠"
    return "🔴"

def format_message(job, analysis):
    score    = analysis["fit_score"]
    wants    = analysis.get("what_they_want", "")
    tools    = analysis.get("tools_required", "")
    salary_a = analysis.get("salary", "")
    timezone = analysis.get("timezone", "")
    gap      = analysis.get("fit_gap", "")
    flags    = analysis.get("red_flags", "")

    # Salary: prefer job listing salary, fall back to Groq extracted
    salary_display = job.get("salary") or salary_a or "Não informado"

    link     = job.get("url") or ""
    link_tag = f'<a href="{link}">Ver vaga</a>' if link else "Link não disponível"

    lines = [
        f"🎯 <b>{job['title']}</b>",
        f"──────────────────────",
        f"🏢 {job.get('company') or 'N/A'}  |  📡 {job['source']}",
        f"──────────────────────",
    ]

    if wants:
        lines.append(f"📌 <b>O que fazem:</b> {wants}")
    if tools and tools.lower() != "not specified":
        lines.append(f"🛠 <b>Ferramentas:</b> {tools}")
    if timezone and timezone.lower() != "not mentioned":
        lines.append(f"🕐 <b>Timezone:</b> {timezone}")

    lines.append(f"──────────────────────")
    lines.append(f"💰 {salary_display}")
    lines.append(f"🔗 {link_tag}")
    lines.append(f"──────────────────────")
    lines.append(f"{fit_emoji(score)} Fit: <b>{score}%</b>")

    if gap:
        lines.append(f"✅ {gap}")
    if flags:
        lines.append(f"⚠️ {flags}")

    return "\n".join(lines)


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

        # 1. Title filter
        if quick_exclude(job["title"]):
            print(f"  Excluded (title): {job['title']}")
            continue

        # 2. Dead link filter
        if is_dead_link(job.get("url", "")):
            print(f"  Excluded (dead link): {job['title']}")
            continue

        # 3. Broken description filter
        if is_broken_description(job.get("description", "")):
            print(f"  Excluded (broken desc): {job['title']}")
            continue

        # 4. Relevance pre-filter
        combined = (job["title"] + " " + job.get("description", "")).lower()
        if not any(kw in combined for kw in RELEVANCE_KEYWORDS):
            print(f"  Skipped (not relevant): {job['title']}")
            continue

        # 5. Groq analysis
        time.sleep(2)
        analysis = analyze_with_groq(job)
        print(f"  [{analysis['remote_type']} | {analysis['fit_score']}%] {job['title']}")

        if analysis["remote_type"] in ("us_only", "hybrid_us", "skip"):
            continue
        if analysis["fit_score"] < 45:
            continue

        send_telegram(format_message(job, analysis))
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
