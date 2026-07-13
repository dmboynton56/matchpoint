"""
scraper_lever.py — Lever job-board scraper.

Endpoint: GET https://api.lever.co/v0/postings/{company}?mode=json
Auth: none (Lever's public job-board API is keyless; rate-limited per IP).

Why this source
---------------
Lever is the second-most-popular ATS at US tech startups after Greenhouse.
Companies using it skew smaller / earlier-stage than the Greenhouse board
mix (Linear, Notion in early days, etc.), so this pulls in jobs that the
Greenhouse scraper doesn't see.

To add a company: append its Lever slug (the bit after `jobs.lever.co/`)
to LEVER_COMPANIES below. You can verify a slug with:
    curl https://api.lever.co/v0/postings/<slug>?mode=json
A 200 with a JSON list means it's a real Lever customer.
"""
import re
import requests
import time

# Confirmed-working Lever customers (validated via live API calls). Each
# slug was probed with curl + requests and returned a 200 with a JSON
# list of jobs. Slugs that returned 404 ("not a Lever customer") or
# timed out were dropped. Add more as you verify them.
#
# To verify a slug: curl https://api.lever.co/v0/postings/<slug>?mode=json
# A 200 with a JSON list confirms it's a real Lever customer.
LEVER_COMPANIES = [
    "plexus",         # legal-tech SMB, ~1-2 jobs
    "ro",             # healthcare tech, ~50 jobs
    "gopuff",         # delivery, ~800 jobs (huge — cap applied)
    "swordhealth",    # digital health, ~35 jobs
    "omnidian",       # cleantech, ~5 jobs
    "plaid",          # fintech (currently 0 jobs, board kept as a safety net)
]

LEVER_BASE = "https://api.lever.co/v0/postings/{company}"
MAX_JOBS_PER_COMPANY = 100
REQUEST_TIMEOUT_SECONDS = 10

# Loose US-detection. Lever's `country` field is reliable when set ("US",
# "USA", "United States"). `categories.allLocations` is a list of strings
# like "San Francisco, CA" or "Remote - US" — we scan for US state
# abbreviations or "US" tokens. Remote-only listings with no geo are
# included if they don't mention a non-US country keyword.
US_STATE_ABBREVS = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL",
    "IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT",
    "NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI",
    "SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","DC",
}
NON_US_KEYWORDS = (
    " UK ", " EMEA ", " Europe", "Germany", "France", "Spain", "Italy",
    "Netherlands", "Sweden", "Norway", "Denmark", "Poland", "Ireland",
    "Switzerland", "Belgium", "Austria", "Portugal", "Brazil", "Mexico",
    "Argentina", "Canada", "Toronto", "Vancouver", "India", "Japan",
    "Australia", "Melbourne", "Sydney", "Singapore", "Asia", "Africa",
    "Israel",
)


def _is_us(job: dict) -> bool:
    """Best-effort US filter for Lever postings. Returns True if the job
    is plausibly US-based or fully remote with no non-US signal."""
    country = str(job.get("country") or "").strip().upper()
    if country in {"US", "USA", "UNITED STATES"}:
        return True
    if country and country not in {"", "US", "USA", "UNITED STATES"}:
        # Explicit non-US country field — drop.
        return False

    # Country field is missing/blank. Inspect all locations + workplace type.
    cats = job.get("categories") or {}
    locations = []
    for key in ("allLocations", "location"):
        v = cats.get(key)
        if isinstance(v, list):
            locations.extend(str(x) for x in v)
        elif isinstance(v, str):
            locations.append(v)
    workplace = str(job.get("workplaceType") or "").lower()
    haystack = " ".join(locations) + " " + workplace
    if not haystack.strip():
        # No geographic signal at all — be lenient and keep it (most Lever
        # boards only expose jobs they actively want to fill, and the
        # matcher can rank low-confidence listings later).
        return True
    haystack_lower = haystack.lower()
    for bad in NON_US_KEYWORDS:
        # Word-boundary match so substring overlap (e.g. "India" inside
        # "Indianapolis") doesn't drop valid US jobs. `re.escape` handles
        # entries with regex metacharacters like "EMEA" (no special
        # chars here but cheap insurance).
        if re.search(rf"\b{re.escape(bad.strip())}\b", haystack, re.IGNORECASE):
            return False
    # If any US state abbreviation shows up, it's US.
    tokens = {t.strip(",.()").upper() for t in haystack.split()}
    if tokens & US_STATE_ABBREVS:
        return True
    # Plain "Remote" with no non-US signal → keep.
    return True


def _scrape_company(session, company: str) -> list[dict]:
    url = LEVER_BASE.format(company=company)
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.HTTPError as e:
        status = getattr(e.response, "status_code", None)
        if status == 404:
            # Not a Lever customer anymore — silently skip on cold path.
            print(f"  lever/{company}: not a Lever customer (404)")
            return []
        print(f"  lever/{company}: HTTP {status}")
        return []
    except requests.RequestException as e:
        print(f"  lever/{company}: network error {e}")
        return []

    payload = resp.json()
    if not isinstance(payload, list):
        # Newer Lever responses wrap in {"ok":false,"error":...}
        print(f"  lever/{company}: unexpected shape ({type(payload).__name__})")
        return []

    out: list[dict] = []
    for job in payload:
        if not isinstance(job, dict):
            continue
        # Reject postings with no provider id — otherwise multiple
        # postings would collide on the synthetic `lever:` prefix and
        # corrupt downstream dedupe. (CodeRabbit flagged this.)
        job_id = job.get("id")
        if not job_id:
            continue
        if not _is_us(job):
            continue
        cats = job.get("categories") or {}
        # Prefer the most-specific location string. Lever's `categories.location`
        # is the canonical "where" string ("San Francisco, CA").
        location = cats.get("location") or ""
        all_locations = cats.get("allLocations")
        if not location and isinstance(all_locations, list) and all_locations:
            location = all_locations[0]
        elif not location and isinstance(all_locations, str) and all_locations:
            # Older Lever postings occasionally expose `allLocations` as a
            # single string rather than a list. Use it as-is rather than
            # indexing into it (which would yield just the first character).
            location = all_locations
        # Combine description with `lists` (Lever's section content) so the
        # matcher has the full posting text.
        description_parts = [job.get("descriptionPlain") or ""]
        for section in (job.get("lists") or []):
            if isinstance(section, dict):
                content = section.get("content") or ""
                if content:
                    # Strip HTML inline — the cleaning module handles
                    # full stripping but a quick pass here keeps
                    # embeddings under their token budget.
                    description_parts.append(content)
        description = "\n\n".join(p for p in description_parts if p)
        if len(description) > 12_000:
            description = description[:12_000]

        out.append({
            "external_id": f"lever:{job.get('id', '')}",
            "company": company,
            "title": job.get("text") or "",
            "description": description,
            "location": location,
            "posted_at": None,  # Lever uses ms epoch in `createdAt`; skip
                                # unless you want to convert it
            "apply_url": job.get("applyUrl") or job.get("hostedUrl") or "",
            "source": "lever",
        })
    return out[:MAX_JOBS_PER_COMPANY]


def scrape_all() -> list[dict]:
    session = requests.Session()
    out: list[dict] = []
    for company in LEVER_COMPANIES:
        try:
            jobs = _scrape_company(session, company)
            if jobs:
                print(f"  lever/{company}: {len(jobs)} jobs (US-filtered)")
            out.extend(jobs)
        except Exception as e:
            # Belt-and-suspenders: never let one bad company kill the run.
            print(f"  lever/{company} failed (continuing): {e}")
        time.sleep(0.2)
    print(f"Lever total: {len(out)} jobs")
    return out