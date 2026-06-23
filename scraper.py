import requests
import json
import hashlib
import os
import time
import re
from datetime import datetime
from pathlib import Path

TELEGRAM_TOKEN  = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SERPAPI_KEY     = os.environ.get("SERPAPI_KEY", "")
GROQ_API_KEY    = os.environ.get("GROQ_API_KEY", "")
SEEN_FILE       = Path("seen_jobs.json")

# ── Candidate profile sent to Groq ────────────────────────────────────────────
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

# SerpAPI queries — 3/day = 90 credits/month (free tier: 250)
SERPAPI_QUERIES = [
    "CX Operations Specialist remote",
    "Support Operations Specialist remote",
    "Customer Success Operations remote",
]

# Pre-filter: obvious title exclusions before calling Groq (saves tokens)
EXCLUDE_TITLE_QUICK = [
    r"\bdirector\b", r"\bvp\b", r"\bvice president\b", r"\bhead of\b",
    r"\bsenior manager\b", r"\bjunior\b", r"\bjr\b",
]


# ── Storage ───────────────────────────────────────────────────────────────────
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

def short_description(text, max_chars=200):
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


# ── Groq analysis ─────────────────────────────────────────────────────────────
def analyze_with_groq(job):
    """
    Returns dict:
      remote_type: "global" | "us_only" | "hybrid_us" | "unclear"
      fit_score: 0–100
      fit_reason: one sentence
      red_flags: one sentence or empty string
    """
    if not GROQ_API_KEY:
        # Fallback: pass everything through with neutral score
        return {"remote_type": "unclear", "fit_score": 50,
                "fit_reason": "Groq not configured.", "red_flags": ""}

    desc_truncated = strip_html(job.get("description", ""))[:1500]

    prompt = f"""You are a job analyst. Analyze this job posting for a specific candidate.

CANDIDATE PROFILE:
{CANDIDATE_PROFILE}

JOB POSTING:
Title: {job.get('title', '')}
Company: {job.get('company', '')}
Description: {desc_truncated}

Respond ONLY with a JSON object, no extra text:
{{
  "remote_type": "<global|us_only|hybrid_us|unclear>",
  "fit_score": <integer 0-100>,
  "fit_reason": "<one sentence max 120 chars explaining the main fit or mismatch>",
  "red_flags": "<one sentence max 120 chars about concerns, or empty string if none>"
}}

remote_type rules:
- global: open to candidates worldwide or explicitly says remote worldwide/international
- us_only: requires US residency, US work authorization, or US citizenship
- hybrid_us: remote but requires occasional on-site in the US
- unclear: location requirements not stated

fit_score rules:
- 80-100: strong match, skills align directly with requirements
- 60-79: good match, most skills align with minor gaps
- 40-59: partial match, some relevant skills but notable gaps
- 0-39: poor match, role is outside candidate's profile"""

    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "max_tokens": 200,
                "temperature": 0.1,
            },
            timeout=15,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        result = json.loads(content)
        # Validate required fields
        return {
            "remote_type": result.get("remote_type", "unclear"),
            "fit_score":   int(result.get("fit_score", 50)),
            "fit_reason":  result.get("fit_reason", ""),
            "red_flags":   result.get("red_flags", ""),
        }
    except Exception as e:
        print(f"groq error: {e}")
        return {"remote_type": "unclear", "fit_score": 50,
                "fit_reason": "Analysis unavailable.", "red_flags": ""}


# ── Sources ───────────────────────────────────────────────────────────────────
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
            "chips": "date_posted:month",
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
            salary = ""
            if s_min and s_max:
                salary = f"${int(s_min):,}–${int(s_max):,}/year"
            elif s_min:
                salary = f"${int(s_min):,}/year"
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
            desc      = strip_html(item.findtext("description") or "")
            jobs.append({
                "title":       title,
                "company":     company,
                "description": desc,
                "url":         item.findtext("link") or "",
                "salary":      "",
                "source":      "We Work Remotely",
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
                "chat_id":                  TELEGRAM_CHAT_ID,
                "text":                     text,
                "parse_mode":               "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        r.raise_for_status()
    except Exception as e:
        print(f"telegram error: {e}")

def fit_emoji(score):
    if score >= 80: return "🟢"
    if score >= 60: return "🟡"
    if score >= 40: return "🟠"
    return "🔴"

def format_message(job, analysis):
    score    = analysis["fit_score"]
    reason   = analysis["fit_reason"]
    flags    = analysis["red_flags"]
    salary   = f"💰 <b>{job['salary']}</b>" if job.get("salary") else "💰 Não informado"
    desc     = short_description(job.get("description", ""))
    desc_ln  = f"📋 {desc}\n" if desc else ""
    flags_ln = f"⚠️ {flags}\n" if flags else ""
    link     = job.get("url") or ""
    link_tag = f'<a href="{link}">Ver vaga</a>' if link else "Link não disponível"

    return (
        f"🎯 <b>{job['title']}</b>\n"
        f"──────────────────────\n"
        f"🏢 Empresa: {job.get('company') or 'N/A'}\n"
        f"📡 Portal: {job['source']}\n"
        f"──────────────────────\n"
        f"{desc_ln}"
        f"──────────────────────\n"
        f"{salary}\n"
        f"🔗 {link_tag}\n"
        f"──────────────────────\n"
        f"{fit_emoji(score)} Fit: <b>{score}%</b> — {reason}\n"
        f"{flags_ln}"
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

        # Quick title filter before calling Groq
        if quick_exclude(job["title"]):
            print(f"  Excluded (title): {job['title']}")
            continue

        # Groq analysis
        analysis = analyze_with_groq(job)
        print(f"  [{analysis['remote_type']} | {analysis['fit_score']}%] {job['title']}")

        # Discard US-only and low-fit
        if analysis["remote_type"] in ("us_only", "hybrid_us"):
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
