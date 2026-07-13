import requests
from bs4 import BeautifulSoup
import time

COMPANIES = [
    "stripe", "airbnb", "robinhood", "datadog", "figma",
    "discord", "dropbox", "asana", "hubspotjobs", "vercel",
    "crunchyroll", "reddit", "brex", "cloudflare", "canonical",
    "spacex", "flexport", "gusto", "netlify", "contentful",
    "mercury", "fivetran", "lattice", "cultureamp", "checkr",
    "dashlane", "intercom", "elastic", "webflow", "twitch",
    "cockroachlabs", "databricks", "postman", "braze",
    "okta", "block", "andurilindustries", "chime", "algolia",
    "trustpilot", "wizinc", "aurorainnovation", "tebra", "rithum",
    "coinbase", "linkedin", "tripadvisor", "pinterest", "affirm",
    "instacart", "boxinc", "mongodb", "samsara", "planetlabs",
    "scaleai", "anthropic", "coursera", "duolingo", "udemy",
    "nuro", "wayve", "epirus", "astranis", "ginkgobioworks",
    "fireblocks", "carta", "remote", "newrelic", "tanium",
    "gitlab"
]

MAX_JOBS_PER_COMPANY = 100


def scrape_all() -> list[dict]:
    session = requests.Session()
    all_jobs = []

    for company in COMPANIES:
        try:
            url = (
                f"https://boards-api.greenhouse.io/v1/boards/"
                f"{company}/jobs?content=true&state=live"
            )
            response = session.get(url, timeout=10)
            response.raise_for_status()

            jobs = response.json().get("jobs", [])
            print(f"{company}: {len(jobs)} total jobs available")

            added = 0
            for job in jobs:
                if added >= MAX_JOBS_PER_COMPANY:
                    break

                description_html = job.get("content", "")
                description_text = BeautifulSoup(
                    description_html, "html.parser"
                ).get_text(" ", strip=True)

                all_jobs.append({
                    "external_id": str(job.get("id", "")),
                    "company": company,
                    "title": job.get("title", ""),
                    "description": description_text,
                    "location": (job.get("location", {}) or {}).get("name", ""),
                    "posted_at": job.get("updated_at", "") or None,
                    "apply_url": job.get("absolute_url", ""),
                    "source": "greenhouse",
                })
                added += 1

            print(f"collected {added} jobs")
            time.sleep(0.2)  # be polite to the API

        except Exception as e:
            print(f"Failed for {company}: {e}")

    print(f"\nTotal jobs scraped: {len(all_jobs)}")
    return all_jobs
