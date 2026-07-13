import requests
import json
import hashlib
import os
import time
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SERPAPI_KEY      = os.environ.get("SERPAPI_KEY", "")
GROQ_API_KEY     = os.environ.get("GROQ_API_KEY", "")
SEEN_FILE        = Path("seen_jobs.json")

CANDIDATE_PROFILE = """
Name: Petra Iglezias Amaral
Role target: CS Operations Specialist / CX Operations / Support Operations / Customer Success
Experience: 4+ years
Key skills: IVR design and deployment (CloudTalk), skills-based routing, Zendesk administration,
  knowledge base architecture, HubSpot Service Hub (certified), Power BI (certified), Metabase,
  Python scripting for automation, SQL for data querying, multilingual onboarding
  (Portuguese/English/Spanish), NPS/CSAT frameworks, ARR retention, churn analysis,
  familiar with Gainsight and ChurnZero health score frameworks.
Track record: 30+ concurrent accounts, zero churn, 9.4 CSAT, IVR built from scratch,
  data coverage scaled 10% to 100% via Python automation (still in production),
  fraud prevention solo coverage at international fintech with zero chargebacks.
Work authorization: Brazilian national. NOT eligible for US work authorization.
  Fully remote for any company worldwide EXCEPT US-only roles.
  Open to Americas or EMEA timezones.
Salary expectation: USD $2,500-$4,000/month or BRL R$3,500-4,500/month.
Languages: English (full professional), Portuguese (native), Spanish (conversational).
"""

# ── Queries SerpAPI ───────────────────────────────────────────────────────────
SERPAPI_QUERIES = [
    "Customer Operations Specialist remote worldwide",
    "CS Operations Specialist remote",
    "CX Operations Analyst remote",
    "Zendesk Administrator remote",
    "Customer Success Operations remote",
    "Support Operations Specialist remote",
]

# ── RSS sources — higher signal than Google Jobs ──────────────────────────────
RSS_SOURCES = [
    {
        "url": "https://remotive.com/remote-jobs/rss/customer-service",
        "name": "Remotive",
    },
    {
        "url": "https://weworkremotely.com/categories/remote-customer-support-jobs.rss",
        "name": "We Work Remotely",
    },
]

# ── Greenhouse companies to scan directly ─────────────────────────────────────
# Add more slugs from: boards.greenhouse.io/{slug}
GREENHOUSE_COMPANIES = [
    "sophos", "trustedhealthcom", "pagerduty", "intercom",
    "zapier", "gitlab", "hubspot", "drift", "freshworks",
    "klaviyo", "gorgias", "dixa", "supportlogic",
]

# ── Domains to block ──────────────────────────────────────────────────────────
DEAD_LINK_DOMAINS = [
    "liveblog365.com", "infinityfree.me", "quickswoop", "halvolink",
    "hirevista", "skillorbit", "jobsearcher.com", "jooble.org",
    "trovit.com", "adzuna.com", "vacancyglobal.up.railway.app",
    "jobleads.com", "bebee.com", "lensa.com", "jobrapido",
    "learn4good.com", "jobtome.com", "kitjob.com",
]

# ── Title exclusions ──────────────────────────────────────────────────────────
EXCLUDE_TITLE_QUICK = [
    r"\bdirector\b", r"\bvp\b", r"\bvice president\b", r"\bhead of\b",
    r"\bsenior manager\b", r"\bjr\b",
    r"\bsatellite\b", r"\bhealthcare\b", r"\bnurse\b", r"\bphysician\b",
    r"\bengineering manager\b", r"\bsoftware engineer\b", r"\bdevops\b",
    r"\bfinancial analyst\b", r"\baccountant\b", r"\bsupervisor\b",
]

# ── Broken description signals ────────────────────────────────────────────────
BROKEN_DESC_SIGNALS = [
    "internet explorer 11 is no longer supported",
    "please update to one of the following browsers",
    "check availabilitylogin", "lorem ipsum",
    "override the digital divide", "capitalise on low hanging fruit",
    "nanotechnology immersion", "testing 123", "will come and clean house",
    "please enable javascript", "sorry, internet explorer",
    "description too vague", "eigenst",  # catches German garbage
]

# ── Relevance keywords ────────────────────────────────────────────────────────
RELEVANCE_KEYWORDS = [
    "customer", "support", "success", "operations", "ops", "cx ", "cs ",
    "crm", "zendesk", "hubspot", "onboarding", "retention", "churn",
    "account", "service", "helpdesk", "client", "revenue",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

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
    return any(re.search(p, t) for p in EXCLUDE_TITLE_QUICK)

def is_dead_link(url):
    return any(d in (url or "").lower() for d in DEAD_LINK_DOMAINS)

def is_broken_description(desc):
    d = (desc or "").lower()
    return any(s in d for s in BROKEN_DESC_SIGNALS)

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


# ── Groq scoring (A-F across 5 dimensions) ───────────────────────────────────

GRADE_THRESHOLDS = [
    (90, "A"), (80, "B"), (70, "C"), (60, "D"),
]

def score_to_grade(score):
    for threshold, grade in GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"

def grade_emoji(grade):
    return {"A": "🟢", "B": "🔵", "C": "🟡", "D": "🟠", "F": "🔴"}.get(grade, "⚪")

def groq_request(prompt, max_tokens=400):
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "max_tokens": max_tokens,
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
        wait = int(r.headers.get("retry-after", 10))
        print(f"  Groq rate limit — waiting {wait}s...")
        time.sleep(wait + 1)
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers, json=payload, timeout=15,
        )
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])

def analyze_with_groq(job):
    if not GROQ_API_KEY:
        return None

    desc = strip_html(job.get("description", ""))[:1800]
    title = job.get("title", "")
    company = job.get("company", "")

    prompt = (
        "You are a job analyst. Score this job posting for a candidate using 5 dimensions.\n\n"
        f"CANDIDATE PROFILE:\n{CANDIDATE_PROFILE}\n\n"
        f"JOB POSTING:\nTitle: {title}\nCompany: {company}\nDescription: {desc}\n\n"
        "Respond ONLY with raw JSON, no markdown:\n"
        "{\n"
        '  "remote_type": "<global|us_only|hybrid_us|unclear>",\n'
        '  "remote_score": <0-100: 100=fully remote no country restriction, 0=onsite or US only>,\n'
        '  "title_score": <0-100: how well title matches CS Ops/CX Ops/Support Ops/Customer Success>,\n'
        '  "tool_score": <0-100: overlap between required tools and candidate skills>,\n'
        '  "level_score": <0-100: 100=perfect level match, 0=too senior or too junior>,\n'
        '  "timezone_score": <0-100: 100=Americas or EMEA, 50=unclear, 0=Asia-Pacific only>,\n'
        '  "what_they_want": "<2 sentences on actual day-to-day duties — skip boilerplate>",\n'
        '  "tools_required": "<comma-separated tools explicitly mentioned, or: not specified>",\n'
        '  "salary": "<salary range if mentioned, or: not mentioned>",\n'
        '  "timezone": "<timezone/region requirement if mentioned, or: not mentioned>",\n'
        '  "red_flags": "<specific real concern from posting only — empty string if none>"\n'
        "}\n\n"
        "RULES:\n"
        "- remote_type global = no location restriction. us_only = requires US residency/auth. hybrid_us = remote + occasional US onsite.\n"
        "- red_flags: NEVER flag work authorization unless posting explicitly requires US citizenship/greencard. Never flag salary unless under $1500/month.\n"
        "- level_score: 4+ years experience is the candidate baseline. Penalize if 6+ years required or if role is clearly junior."
    )

    try:
        r = groq_request(prompt, max_tokens=400)

        # Weighted composite score
        composite = (
            r.get("remote_score",   0) * 0.30 +
            r.get("title_score",    0) * 0.25 +
            r.get("tool_score",     0) * 0.25 +
            r.get("level_score",    0) * 0.10 +
            r.get("timezone_score", 0) * 0.10
        )

        return {
            "remote_type":    r.get("remote_type", "unclear"),
            "composite":      int(composite),
            "grade":          score_to_grade(int(composite)),
            "remote_score":   r.get("remote_score", 0),
            "title_score":    r.get("title_score", 0),
            "tool_score":     r.get("tool_score", 0),
            "level_score":    r.get("level_score", 0),
            "timezone_score": r.get("timezone_score", 0),
            "what_they_want": r.get("what_they_want", ""),
            "tools_required": r.get("tools_required", ""),
            "salary":         r.get("salary", ""),
            "timezone":       r.get("timezone", ""),
            "red_flags":      r.get("red_flags", ""),
        }
    except Exception as e:
        print(f"  groq error: {e}")
        return None


# ── Fetchers ──────────────────────────────────────────────────────────────────

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
                if isinstance(v, str) and any(c in v for c in ["$", "€", "£", "USD"]):
                    salary = v
                    break
            if not salary:
                for h in item.get("job_highlights", []):
                    for hi in h.get("items", []):
                        if any(c in hi for c in ["$", "€", "/month", "/year", "/hr"]):
                            salary = hi
                            break
            url = extract_apply_link(item)
            if is_dead_link(url):
                continue
            jobs.append({
                "title":       item.get("title", ""),
                "company":     item.get("company_name", ""),
                "description": item.get("description", ""),
                "url":         url,
                "salary":      salary,
                "source":      f"Google Jobs · via {item.get('via', 'N/A')}",
                "source_quality": "aggregator",
            })
        time.sleep(1)
    except Exception as e:
        print(f"serpapi error ({query}): {e}")
    return jobs

def fetch_rss(url, name):
    jobs = []
    try:
        r = requests.get(url, headers={"User-Agent": "JobRadarBot/2.0"}, timeout=15)
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
                "source":      name,
                "source_quality": "rss_direct",
            })
    except Exception as e:
        print(f"rss error ({name}): {e}")
    return jobs

def fetch_greenhouse(company_slug):
    jobs = []
    try:
        url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs"
        r = requests.get(url, timeout=15)
        if not r.ok:
            return jobs
        for item in r.json().get("jobs", []):
            jobs.append({
                "title":       item.get("title", ""),
                "company":     company_slug.title(),
                "description": strip_html(item.get("content", "")),
                "url":         item.get("absolute_url", ""),
                "salary":      "",
                "source":      f"Greenhouse · {company_slug}",
                "source_quality": "ats_direct",
            })
        time.sleep(0.5)
    except Exception as e:
        print(f"greenhouse error ({company_slug}): {e}")
    return jobs

def fetch_remoteok():
    jobs = []
    try:
        r = requests.get(
            "https://remoteok.com/api",
            headers={"User-Agent": "JobRadarBot/2.0"},
            timeout=15,
        )
        for item in r.json():
            if not isinstance(item, dict) or "position" not in item:
                continue
            s_min = item.get("salary_min")
            s_max = item.get("salary_max")
            salary = (
                f"${int(s_min):,}-${int(s_max):,}/year" if s_min and s_max
                else f"${int(s_min):,}/year" if s_min else ""
            )
            jobs.append({
                "title":       item.get("position", ""),
                "company":     item.get("company", ""),
                "description": item.get("description", ""),
                "url":         item.get("url", ""),
                "salary":      salary,
                "source":      "Remote OK",
                "source_quality": "rss_direct",
            })
    except Exception as e:
        print(f"remoteok error: {e}")
    return jobs


# ── Telegram ──────────────────────────────────────────────────────────────────

def send_telegram(text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        ).raise_for_status()
    except Exception as e:
        print(f"telegram error: {e}")

def format_message(job, analysis):
    grade   = analysis["grade"]
    emoji   = grade_emoji(grade)
    wants   = analysis.get("what_they_want", "")
    tools   = analysis.get("tools_required", "")
    salary  = job.get("salary") or analysis.get("salary") or "not mentioned"
    tz      = analysis.get("timezone", "")
    flags   = analysis.get("red_flags", "")
    link    = job.get("url", "")
    link_tag = f'<a href="{link}">Ver vaga</a>' if link else "Link não disponível"

    # Dimension breakdown
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
    print(f"[{datetime.now()}] Job Radar v2 iniciado. {len(seen)} vagas já vistas.")

    all_jobs = []

    # 1. ATS direct (highest signal)
    print("Fetching Greenhouse direct feeds...")
    for slug in GREENHOUSE_COMPANIES:
        fetched = fetch_greenhouse(slug)
        print(f"  {slug}: {len(fetched)} jobs")
        all_jobs += fetched

    # 2. RSS feeds (good signal)
    print("Fetching RSS feeds...")
    for source in RSS_SOURCES:
        fetched = fetch_rss(source["url"], source["name"])
        print(f"  {source['name']}: {len(fetched)} jobs")
        all_jobs += fetched
    all_jobs += fetch_remoteok()

    # 3. SerpAPI as fallback
    if SERPAPI_KEY:
        print("Fetching SerpAPI...")
        for q in SERPAPI_QUERIES:
            fetched = fetch_serpapi(q)
            print(f"  '{q}': {len(fetched)} jobs")
            all_jobs += fetched

    print(f"Total coletado: {len(all_jobs)} vagas brutas.")

    sent_a = sent_b = 0
    for job in all_jobs:
        jid = make_job_id(job)
        if jid in seen:
            continue
        seen.add(jid)

        if quick_exclude(job["title"]):
            continue
        if is_dead_link(job.get("url", "")):
            continue
        if is_broken_description(job.get("description", "")):
            continue

        combined = (job["title"] + " " + job.get("description", "")).lower()
        if not any(kw in combined for kw in RELEVANCE_KEYWORDS):
            continue

        time.sleep(2)
        analysis = analyze_with_groq(job)
        if not analysis:
            continue

        grade = analysis["grade"]
        remote = analysis["remote_type"]
        print(f"  [{grade} | {remote}] {job['title']} @ {job.get('company','')}")

        # Only A and B reach Telegram
        if remote in ("us_only", "hybrid_us"):
            continue
        if grade not in ("A", "B"):
            continue

        send_telegram(format_message(job, analysis))
        if grade == "A":
            sent_a += 1
        else:
            sent_b += 1
        time.sleep(0.5)

    save_seen(seen)

    total = sent_a + sent_b
    summary = (
        f"✅ <b>Job Radar v2 concluído</b>\n"
        f"🟢 Grade A: {sent_a}  🔵 Grade B: {sent_b}\n"
        f"📨 Total enviado: {total}"
        if total > 0
        else "✅ Job Radar v2 concluído — nenhuma vaga A ou B hoje."
    )
    send_telegram(summary)
    print(f"Concluído. A={sent_a} B={sent_b}")


if __name__ == "__main__":
    main()
