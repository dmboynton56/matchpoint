"""
scraper_ashby.py — Ashby job-board scraper.

Endpoint: GET https://api.ashbyhq.com/posting-api/job-board/{company}
Auth: none (Ashby's public job-board endpoint is keyless; rate-limited per IP).

Why this source
---------------
Ashby is the third major ATS used by US tech startups, especially
post-2020. Companies on Ashby are typically Series A–C tech companies
that outgrew spreadsheets but aren't large enough for Workday. Examples
confirmed working below: PostHog, Linear, Notion, Ramp, Lovable, Supabase.

To add a company: append its Ashby slug (the bit after `jobs.ashbyhq.com/`)
to ASHBY_COMPANIES below. Verify a slug with:
    curl https://api.ashbyhq.com/posting-api/job-board/<slug>
A 200 with a JSON body containing `jobs: [...]` confirms it.
"""
import re
import requests
import time

# Confirmed-working Ashby customers (validated via live API calls). Each
# slug was probed with curl + requests and returned 200 with a non-empty
# jobs list. Slugs that returned 404 or had zero jobs were dropped. Add
# more as you verify them — to verify, run:
#     curl https://api.ashbyhq.com/posting-api/job-board/<slug>
# A 200 with a JSON body containing `jobs: [...]` confirms it.
ASHBY_COMPANIES = [
    # Original 6 (smaller/dedicated list)
    "posthog",        # 19 jobs — analytics, open source
    "linear",         # 24 jobs — issue tracking
    "notion",         # 141 jobs — productivity
    "ramp",           # 128 jobs — fintech
    "lovable",        # 70 jobs — AI app builder
    "supabase",       # 51 jobs — open-source BaaS
    # Added per curated list
    "baseten",        # 72 jobs — AI infra
    "browserbase",    # 6 jobs — browser infra
    "modal",          # 33 jobs — serverless compute
    "warp",           # 21 jobs — terminal
    "vanta",          # 110 jobs — compliance/SOC2
    "replit",         # 99 jobs — cloud IDE
    "cursor",         # 113 jobs — AI code editor
    "decagon",        # 113 jobs — AI customer service
    "sierra",         # 158 jobs — AI agents
    "zip",            # 132 jobs — procurement
    "perplexity",     # 81 jobs — AI search
    "cohere",         # 129 jobs — LLMs
    "watershed",      # 42 jobs — climate ESG
    "ashby",          # 64 jobs — ATS itself
    "pylon",          # 13 jobs — B2B support
    "harvey",         # 335 jobs — legal AI
    "bland",          # 12 jobs — AI phone calls
    "abridge",        # 46 jobs — medical AI
    "mercor",         # 62 jobs — AI talent marketplace
    "homebase",       # 21 jobs — SMB HR / payroll
    "braintrust",     # 26 jobs — AI eval
    "krea",           # 18 jobs — AI image gen
    "llamaindex",     # 16 jobs — LLM framework
    # Skipped — 404 / not on Ashby as of validation:
    #   tailscale, codeium, anysphere (slugs don't exist)
    #   sourcegraph, modernhealth, coda (migrated to other ATSes)
]

ASHBY_BASE = "https://api.ashbyhq.com/posting-api/job-board/{company}"
MAX_JOBS_PER_COMPANY = 100
REQUEST_TIMEOUT_SECONDS = 10

# US state abbreviations for parsing `location` strings like "San Francisco, CA".
US_STATE_ABBREVS = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL",
    "IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT",
    "NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI",
    "SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","DC",
}
NON_US_KEYWORDS = re.compile(
    r"\b(UK|EMEA|Europe|Germany|France|Spain|Italy|Netherlands|Sweden|"
    r"Norway|Denmark|Poland|Ireland|Switzerland|Belgium|Austria|"
    r"Portugal|Brazil|Mexico|Argentina|Canada|Toronto|Vancouver|"
    r"India|Japan|Australia|Melbourne|Sydney|Singapore|Asia|Africa|"
    r"Israel|Tel Aviv|London|Paris|Berlin|Amsterdam|Dublin|Barcelona|"
    r"Munich|Zurich|Madrid|Milan|Rome|Stockholm|Copenhagen|Oslo|"
    r"Helsinki|Warsaw|Budapest|Prague|Lisbon|Sao Paulo|Buenos Aires)\b",
    re.IGNORECASE,
)


def _country_from_address(job: dict) -> str:
    """Ashby returns the country nested under address.postalAddress.addressCountry
    when set, e.g. "USA". Returns "" if missing or non-dict."""
    addr = job.get("address")
    if not isinstance(addr, dict):
        return ""
    postal = addr.get("postalAddress")
    if not isinstance(postal, dict):
        return ""
    return str(postal.get("addressCountry") or "").strip()


def _is_us(job: dict) -> bool:
    country = _country_from_address(job).upper()
    if country in {"US", "USA", "UNITED STATES"}:
        return True
    if country and country not in {"", "US", "USA", "UNITED STATES"}:
        return False

    # Country missing — scan `location` string for US state abbrev or
    # non-US city/country keyword.
    location = str(job.get("location") or "")
    secondary = job.get("secondaryLocations") or []
    secondary_text = " ".join(str(s) for s in secondary if s)
    haystack = (location + " " + secondary_text).strip()
    if not haystack:
        # No location info at all — keep (Ashby only exposes live postings;
        # matcher will rank them).
        return True
    if NON_US_KEYWORDS.search(haystack):
        return False
    tokens = {t.strip(",.()").upper() for t in haystack.replace(",", " ").split()}
    if tokens & US_STATE_ABBREVS:
        return True
    return True


def _scrape_company(session, company: str) -> list[dict]:
    url = ASHBY_BASE.format(company=company)
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        if resp.status_code == 404:
            print(f"  ashby/{company}: not an Ashby customer (404)")
            return []
        resp.raise_for_status()
    except requests.HTTPError as e:
        status = getattr(e.response, "status_code", None)
        print(f"  ashby/{company}: HTTP {status}")
        return []
    except requests.RequestException as e:
        print(f"  ashby/{company}: network error {e}")
        return []

    payload = resp.json()
    if not isinstance(payload, dict):
        print(f"  ashby/{company}: unexpected shape ({type(payload).__name__})")
        return []
    raw_jobs = payload.get("jobs") or []
    if not isinstance(raw_jobs, list):
        return []

    out: list[dict] = []
    for job in raw_jobs:
        if not isinstance(job, dict):
            continue
        if not job.get("isListed", True):
            # Ashby supports draft / unlisted postings; skip those.
            continue
        if not _is_us(job):
            continue

        description = job.get("descriptionPlain") or job.get("descriptionHtml") or ""
        if len(description) > 12_000:
            description = description[:12_000]

        out.append({
            "external_id": f"ashby:{job.get('id', '')}",
            "company": company,
            "title": job.get("title") or "",
            "description": description,
            "location": job.get("location") or "",
            "posted_at": job.get("publishedAt"),
            "apply_url": job.get("applyUrl") or job.get("jobUrl") or "",
            "source": "ashby",
        })
    return out[:MAX_JOBS_PER_COMPANY]


def scrape_all() -> list[dict]:
    session = requests.Session()
    out: list[dict] = []
    for company in ASHBY_COMPANIES:
        try:
            jobs = _scrape_company(session, company)
            if jobs:
                print(f"  ashby/{company}: {len(jobs)} jobs (US-filtered)")
            out.extend(jobs)
        except Exception as e:
            print(f"  ashby/{company} failed (continuing): {e}")
        time.sleep(0.2)
    print(f"Ashby total: {len(out)} jobs")
    return out