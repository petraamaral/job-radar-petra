import json
import hashlib
import os
import time
import re
import xml.etree.ElementTree as ET
import requests
from datetime import datetime
from pathlib import Path

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SERPAPI_KEY      = os.environ.get("SERPAPI_KEY", "")
GROQ_API_KEY     = os.environ.get("GROQ_API_KEY", "")
SEEN_FILE        = Path("seen_jobs.json")

CANDIDATE_PROFILE = """
Name: Petra Iglezias Amaral
Role target: CS Operations Specialist / CX Operations / Support Operations / Customer Success / Revenue Operations
Experience: 4+ years

Who she is: Ops professional who spots broken processes before anyone names them and builds the fix.
Uses AI as a core work tool — co-developed two production systems (WMS + CRM/FSM) using AI as
development partner, built a Python automation that scaled data coverage from 10% to 100% (still
running in production), and uses LLMs daily for analysis, scoring, and workflow automation.
Comfortable at the intersection of operations, data, and product thinking.

Soft skills that show up as outcomes: At 6 months at PagBrasil, proactively diagnosed a support
operation running on reactive firefighting, ran ticket volume analysis across categories, and
presented a full strategic transformation proposal (Impulso CS) to leadership — unprompted.
Also designed a cross-team innovation program (Sinergia PB) that ran three iterations, mixing
teams from CS, Fraud, Payments, and Integrations to solve multidisciplinary business problems.

Hard skills: Zendesk administration, HubSpot Service Hub (certified), Power BI (certified),
Metabase, Python scripting for automation, SQL for data querying and root cause analysis,
knowledge base architecture, multilingual onboarding (Portuguese/English/Spanish),
NPS/CSAT frameworks, ARR retention tracking, churn analysis,
familiar with Gainsight and ChurnZero health score frameworks, GDPR awareness.

Track record: 30+ concurrent accounts, zero churn, 9.4 CSAT, data coverage 10% to 100%
via Python automation still in production, fraud prevention solo 20 days zero chargebacks,
22% reduction in late deliveries via SQL root cause analysis at current role.

Work authorization: Brazilian national. NOT eligible for US work authorization.
Fully remote for any company worldwide EXCEPT US-only roles.
Open to Americas or EMEA timezones.
Salary: USD $2,500-$4,000/month or BRL R$3,500-4,500/month.
Languages: English (full professional), Portuguese (native), Spanish (conversational).
"""

# ── JobSpy queries ────────────────────────────────────────────────────────────
JOBSPY_QUERIES = [
    "Customer Success Operations Specialist",
    "CX Operations Analyst",
    "Customer Operations Specialist",
    "Support Operations Specialist",
    "Zendesk Administrator",
    "Customer Success Manager LATAM",
    "Revenue Operations Analyst",
    "Customer Success Associate",
]

# ── Lever companies (kept as high-quality fallback) ───────────────────────────
LEVER_COMPANIES = [
    "sophos", "truelayer", "flipp", "processstreet",
    "intercom", "front", "gladly", "kustomer",
    "helpscout", "dialpad", "aircall", "talkdesk",
    "planhat", "vitally", "churnzero", "gainsight",
    "mixpanel", "amplitude", "braze", "klaviyo",
    "gorgias", "dixa", "supportlogic",
    "rippling", "gusto", "ramp", "mercury",
    "stripe", "plaid", "nubank", "nuvemshop",
    "vtex", "cloudwalk", "pismo", "dock",
]

# ── RSS feeds (reliable fallback) ─────────────────────────────────────────────
RSS_SOURCES = [
    {
        "url": "https://remotive.com/remote-jobs/rss/customer-service",
        "name": "Remotive · Customer Service",
    },
    {
        "url": "https://remotive.com/remote-jobs/rss/business",
        "name": "Remotive · Business",
    },
    {
        "url": "https://weworkremotely.com/categories/remote-customer-support-jobs.rss",
        "name": "We Work Remotely · Support",
    },
    {
        "url": "https://weworkremotely.com/categories/remote-sales-and-marketing-jobs.rss",
        "name": "We Work Remotely · Sales & Marketing",
    },
]

# ── Filters ───────────────────────────────────────────────────────────────────
REQUIRE_TITLE_TERMS = [
    r"\bcustomer\b", r"\bclient\b", r"\bcs\b", r"\bcx\b",
    r"\bsupport\b", r"\bsuccess\b", r"\boperations\b", r"\bops\b",
    r"\bzendesk\b", r"\bonboarding\b", r"\bretention\b", r"\bchurn\b",
    r"\brevenue\b", r"\bservice\b", r"\bhelpdesk\b",
    r"\bsales ops\b", r"\brev ops\b", r"\brevops\b",
]

EXCLUDE_TITLE_QUICK = [
    r"\bdirector\b", r"\bvp\b", r"\bvice president\b", r"\bhead of\b",
    r"\bsenior manager\b", r"\bjr\b", r"\bregional manager\b",
    r"\bbenefits representative\b", r"\bpayroll\b", r"\baccountant\b",
    r"\bfinancial controller\b", r"\bfinancial analyst\b",
    r"\bsatellite\b", r"\bhealthcare\b", r"\bnurse\b", r"\bphysician\b",
    r"\bengineering manager\b", r"\bsoftware engineer\b", r"\bdevops\b",
    r"\bsales development\b", r"\bsdr\b", r"\bbdr\b",
    r"\bsales engineer\b", r"\bsolutions engineer\b",
    r"\bincident response\b", r"\bthreat\b", r"\bcybersecurity analyst\b",
    r"\badministrative assistant\b", r"\bexecutive assistant\b",
]

DEAD_LINK_DOMAINS = [
    "liveblog365.com", "infinityfree.me", "quickswoop", "halvolink",
    "hirevista", "skillorbit", "jobsearcher.com", "jooble.org",
    "trovit.com", "adzuna.com", "vacancyglobal.up.railway.app",
    "jobleads.com", "bebee.com", "lensa.com", "jobrapido",
    "learn4good.com", "jobtome.com", "kitjob.com",
    "mumbailocal.net", "applyjobs247", "jobhub.com",
    "jazzhr.com", "careerzynith", "globelife",
]

DEAD_VIA_SOURCES = [
    "jobhub", "jobleads", "bebee", "lensa", "learn4good",
    "jobrapido", "jooble", "adzuna", "trovit",
]

BROKEN_DESC_SIGNALS = [
    "internet explorer 11 is no longer supported",
    "please update to one of the following browsers",
    "check availabilitylogin", "lorem ipsum",
    "override the digital divide", "capitalise on low hanging fruit",
    "nanotechnology immersion", "testing 123", "will come and clean house",
    "please enable javascript", "sorry, internet explorer",
    "description too vague", "eigenst",
]

RELEVANCE_KEYWORDS = [
    "customer", "support", "success", "operations", "ops", "cx ", "cs ",
    "crm", "zendesk", "hubspot", "onboarding", "retention", "churn",
    "account", "service", "helpdesk", "client", "revenue",
]

MAX_PER_COMPANY = 3

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

def passes_title_whitelist(title):
    t = title.lower()
    return any(re.search(p, t) for p in REQUIRE_TITLE_TERMS)

def quick_exclude(title):
    t = title.lower()
    return any(re.search(p, t) for p in EXCLUDE_TITLE_QUICK)

def is_dead_link(url):
    return any(d in (url or "").lower() for d in DEAD_LINK_DOMAINS)

def is_broken_description(desc):
    d = (desc or "").lower()
    return any(s in d for s in BROKEN_DESC_SIGNALS)


# ── Groq scoring ──────────────────────────────────────────────────────────────

GRADE_THRESHOLDS = [(90, "A"), (80, "B"), (70, "C"), (60, "D")]

def score_to_grade(score):
    for threshold, grade in GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"

def grade_emoji(grade):
    return {"A": "🟢", "B": "🔵", "C": "🟡", "D": "🟠", "F": "🔴"}.get(grade, "⚪")

def groq_request(prompt, max_tokens=450):
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
        '  "role_type": "<cs_ops|sales|technical|management|other>",\n'
        '  "remote_type": "<global|us_only|hybrid_us|unclear>",\n'
        '  "remote_score": <0-100>,\n'
        '  "title_score": <0-100>,\n'
        '  "tool_score": <0-100>,\n'
        '  "level_score": <0-100>,\n'
        '  "timezone_score": <0-100>,\n'
        '  "what_they_want": "<2 sentences on actual duties — skip boilerplate. If vague write: Description too vague.>",\n'
        '  "tools_required": "<comma-separated tools explicitly mentioned, or: not specified>",\n'
        '  "salary": "<salary range explicitly stated IN THE JOB POSTING only — never use candidate salary. If not mentioned write: not mentioned>",\n'
        '  "timezone": "<timezone/region if mentioned, or: not mentioned>",\n'
        '  "red_flags": "<specific real concern from posting only — empty string if none>"\n'
        "}\n\n"
        "RULES:\n"
        "- role_type: cs_ops = Customer Success, CX Ops, Support Ops, CS Operations, Revenue Ops focused on retention/processes. "
        "sales = quota-carrying, outbound, cold calls, new logo, AE/AM with closing responsibilities. "
        "technical = engineering, developer, devops. management = people manager with direct reports. other = anything else.\n"
        "- remote_type: global = no location restriction. us_only = requires US residency/auth. hybrid_us = remote + occasional US onsite.\n"
        "- salary: ONLY extract salary explicitly stated in the job posting. Never output the candidate profile salary.\n"
        "- red_flags: flag if role requires language candidate does not speak, outbound/cold calling as primary duty, US work auth required, or quota as primary comp.\n"
        "- level_score: 4+ years is the candidate baseline. Penalize if 6+ years required or clearly junior."
    )

    try:
        r = groq_request(prompt, max_tokens=450)
        role_type = r.get("role_type", "other")
        composite = (
            r.get("remote_score",   0) * 0.30 +
            r.get("title_score",    0) * 0.25 +
            r.get("tool_score",     0) * 0.25 +
            r.get("level_score",    0) * 0.10 +
            r.get("timezone_score", 0) * 0.10
        )
        return {
            "role_type":      role_type,
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
            "salary":         r.get("salary", "not mentioned"),
            "timezone":       r.get("timezone", ""),
            "red_flags":      r.get("red_flags", ""),
        }
    except Exception as e:
        print(f"  groq error: {e}")
        return None


# ── Fetchers ──────────────────────────────────────────────────────────────────

def fetch_jobspy(query):
    """Primary source — scrapes Indeed, LinkedIn, ZipRecruiter, Google directly."""
    jobs = []
    try:
        from jobspy import scrape_jobs
        df = scrape_jobs(
            site_name=["indeed", "google"],
            search_term=query,
            is_remote=True,
            hours_old=48,
            results_wanted=30,
            description_format="markdown",
            verbose=0,
        )
        for _, row in df.iterrows():
            salary = ""
            try:
                import math
                min_a = row.get("min_amount")
                max_a = row.get("max_amount")
                interval = row.get("interval", "yearly") or "yearly"
                currency = row.get("currency", "USD") or "USD"
                if min_a and max_a and not (isinstance(min_a, float) and math.isnan(min_a)) and not (isinstance(max_a, float) and math.isnan(max_a)):
                    salary = f"{currency} {int(min_a):,}–{int(max_a):,}/{interval}"
                elif min_a and not (isinstance(min_a, float) and math.isnan(min_a)):
                    salary = f"{currency} {int(min_a):,}/{interval}"
            except Exception:
                salary = ""

            site = str(row.get("site", "unknown")).title()
            jobs.append({
                "title":          str(row.get("title", "")),
                "company":        str(row.get("company", "")),
                "description":    str(row.get("description", "")),
                "url":            str(row.get("job_url", "")),
                "salary":         salary,
                "source":         f"JobSpy · {site}",
                "source_quality": "direct",
            })
    except ImportError:
        print("  jobspy not installed — skipping")
    except Exception as e:
        print(f"  jobspy error ({query}): {e}")
    return jobs

def fetch_lever(company_slug):
    """High-quality ATS direct feed."""
    jobs = []
    try:
        url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
        r = requests.get(url, timeout=10)
        if not r.ok:
            return jobs
        for item in r.json():
            jobs.append({
                "title":          item.get("text", ""),
                "company":        company_slug.title(),
                "description":    strip_html(item.get("descriptionPlain", "") or item.get("description", "")),
                "url":            item.get("hostedUrl", ""),
                "salary":         "",
                "source":         f"Lever · {company_slug}",
                "source_quality": "ats_direct",
            })
        time.sleep(0.3)
    except Exception as e:
        print(f"  lever error ({company_slug}): {e}")
    return jobs

def fetch_rss(url, name):
    """RSS feeds as reliable fallback."""
    jobs = []
    try:
        r = requests.get(url, headers={"User-Agent": "JobRadarBot/2.0"}, timeout=15)
        content = r.content.decode("utf-8", errors="replace").encode("utf-8")
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            # Try removing control characters
            clean = re.sub(rb'[\x00-\x08\x0b\x0c\x0e-\x1f]', b'', content)
            try:
                root = ET.fromstring(clean)
            except ET.ParseError:
                # Last resort: strip anything non-ASCII and retry
                clean2 = re.sub(rb'[^\x09\x0a\x0d\x20-\x7e]', b'', content)
                root = ET.fromstring(clean2)
        for item in root.findall(".//item"):
            title_raw = item.findtext("title") or ""
            company   = title_raw.split(" at ")[-1].strip() if " at " in title_raw else ""
            title     = title_raw.split(" at ")[0].strip()  if " at " in title_raw else title_raw
            jobs.append({
                "title":          title,
                "company":        company,
                "description":    strip_html(item.findtext("description") or ""),
                "url":            item.findtext("link") or "",
                "salary":         "",
                "source":         name,
                "source_quality": "rss_direct",
            })
    except Exception as e:
        print(f"  rss error ({name}): {e}")
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
                f"${int(s_min):,}–${int(s_max):,}/year" if s_min and s_max
                else f"${int(s_min):,}/year" if s_min else ""
            )
            jobs.append({
                "title":          item.get("position", ""),
                "company":        item.get("company", ""),
                "description":    item.get("description", ""),
                "url":            item.get("url", ""),
                "salary":         salary,
                "source":         "Remote OK",
                "source_quality": "rss_direct",
            })
    except Exception as e:
        print(f"  remoteok error: {e}")
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
        print(f"  telegram error: {e}")

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

def process_jobs(all_jobs, seen):
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

        send_telegram(format_message(job, analysis))
        sent_per_company[company_key] = sent_per_company.get(company_key, 0) + 1
        if grade == "A":
            sent_a += 1
        else:
            sent_b += 1
        time.sleep(0.5)

    return sent_a, sent_b

def main():
    seen = load_seen()
    print(f"[{datetime.now()}] Job Radar v3 iniciado. {len(seen)} vagas já vistas.")

    all_jobs = []

    # 1. JobSpy — Indeed, ZipRecruiter, Google (primary source)
    print("Fetching via JobSpy...")
    for query in JOBSPY_QUERIES:
        fetched = fetch_jobspy(query)
        print(f"  '{query}': {len(fetched)} jobs")
        all_jobs += fetched
        time.sleep(3)

    # 2. Lever direct (high-quality ATS)
    print("Fetching Lever direct feeds...")
    for slug in LEVER_COMPANIES:
        fetched = fetch_lever(slug)
        if fetched:
            print(f"  {slug}: {len(fetched)} jobs")
        all_jobs += fetched

    # 3. RSS feeds
    print("Fetching RSS feeds...")
    for source in RSS_SOURCES:
        fetched = fetch_rss(source["url"], source["name"])
        print(f"  {source['name']}: {len(fetched)} jobs")
        all_jobs += fetched
    all_jobs += fetch_remoteok()

    print(f"Total coletado: {len(all_jobs)} vagas brutas.")

    sent_a, sent_b = process_jobs(all_jobs, seen)

    save_seen(seen)

    total = sent_a + sent_b
    summary = (
        f"✅ <b>Job Radar v3 concluído</b>\n"
        f"🟢 Grade A: {sent_a}  🔵 Grade B: {sent_b}\n"
        f"📨 Total enviado: {total}"
        if total > 0
        else "✅ Job Radar v3 concluído — nenhuma vaga A ou B hoje."
    )
    send_telegram(summary)
    print(f"Concluído. A={sent_a} B={sent_b}")

if __name__ == "__main__":
    main()
