"""
sources/adzuna.py — Adzuna Jobs API adapter.

Docs: https://developer.adzuna.com/docs/search

Endpoint: GET https://api.adzuna.com/v1/api/jobs/{country}/{page}
Auth: app_id + app_key as query params (Adzuna uses key-in-URL — secure enough
on free tier since keys are scoped read-only and rate-limited).

Required env:
    ADZUNA_APP_ID
    ADZUNA_APP_KEY

The pipeline calls `fetch()` once per day. We request a few pages to
diversify beyond the first ~50 results. Adzuna's free dev tier is 250 calls
per month, so we keep this conservative — 3 pages × 50 = 150 jobs per day,
~4,500/month which would burn the free quota. Default to 1 page (50 jobs)
so we stay under the cap; bump via ADZUNA_PAGES_PER_RUN if you've upgraded.
"""
from __future__ import annotations

import logging
import os
import time

import requests

from ._common import (
    DEFAULT_ADZUNA_QUERIES,
    _env_or_warn,
    _pick_query,
    _rotation_index,
    _truncate,
    iso_or_none,
    strip_html,
)

logger = logging.getLogger(__name__)

SOURCE_NAME = "adzuna"

ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs/us/search/{page}"
DEFAULT_COUNTRY = "us"
DEFAULT_RESULTS_PER_PAGE = 50
# 1 page × 50 results stays well under the free-tier 250 calls/month budget.
# Override with ADZUNA_PAGES_PER_RUN on a paid plan.
DEFAULT_PAGES = 1
REQUEST_TIMEOUT_SECONDS = 10
USER_AGENT = "matchpoint-pipeline/1.0 (+https://matchpoint.example)"


def _is_us_location(location: dict | None) -> bool:
    """Adzuna returns `location.area` as a list like ['US', 'California',
    'San Francisco']. The first element is the country code. We accept US
    listings only — non-US results still slip through `where=US` in practice
    because some postings carry ambiguous area arrays."""
    if not location:
        return True  # be lenient if the field is missing
    area = location.get("area") or []
    if not area:
        return True
    first = str(area[0]).upper()
    return first in {"US", "USA", "UNITED STATES"}


def _normalize(raw: dict) -> dict | None:
    """Shape one Adzuna result into the pipeline's job-dict contract."""
    external_id = raw.get("id")
    if external_id is None:
        return None
    title = (raw.get("title") or "").strip()
    company = (raw.get("company") or {}).get("display_name") or ""
    if not title or not company:
        return None

    description = raw.get("description") or ""
    # Adzuna descriptions are usually plain text but occasionally contain
    # HTML; strip_html is a safe no-op on plain text.
    description = strip_html(description)
    # Cap at 12k chars to keep OpenAI embedding input reasonable.
    description = _truncate(description, 12_000)

    location = raw.get("location") or {}
    location_text = location.get("display_name") or ""

    apply_url = raw.get("redirect_url") or ""
    posted_at = iso_or_none(raw.get("created"))

    return {
        "external_id": f"adzuna:{external_id}",
        "company": company,
        "title": title,
        "description": description,
        "location": location_text,
        "posted_at": posted_at,
        "apply_url": apply_url,
        "source": SOURCE_NAME,
    }


def fetch() -> list[dict]:
    """Fetch up to N pages of US jobs from Adzuna. Soft-fail by raising on
    any HTTP / network error so the caller (run_pipeline) can decide to skip
    this source. Returns [] when keys are unconfigured — that means the
    source is intentionally disabled, not broken."""
    app_id = _env_or_warn("ADZUNA_APP_ID")
    app_key = _env_or_warn("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        logger.info("[adzuna] ADZUNA_APP_ID/ADZUNA_APP_KEY not set — skipping")
        return []

    try:
        pages = int(__import__("os").getenv("ADZUNA_PAGES_PER_RUN", str(DEFAULT_PAGES)))
    except ValueError:
        pages = DEFAULT_PAGES
    pages = max(1, min(pages, 5))  # hard cap at 5 to bound latency

    results_per_page = DEFAULT_RESULTS_PER_PAGE

    # Day-of-week rotation: pick one focused query for today's pool instead
    # of paging through the same broad "all US jobs" result set every day.
    # Override the rotation list with ADZUNA_QUERIES (comma-separated) if
    # you want a different mix.
    custom = os.getenv("ADZUNA_QUERIES", "").strip()
    if custom:
        queries = [q.strip() for q in custom.split(",") if q.strip()]
    else:
        queries = DEFAULT_ADZUNA_QUERIES
    rotation_index = _rotation_index()
    todays_query = _pick_query(queries, rotation_index)
    logger.info(
        "[adzuna] rotation day=%d query=%r (queries=%d)",
        rotation_index, todays_query, len(queries),
    )

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    out: list[dict] = []
    for page in range(1, pages + 1):
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": results_per_page,
            # Bias toward recent postings to match the 7-day purge window.
            "max_days_old": 7,
            # Rotated per day-of-week for variety.
            "what": todays_query,
            "where": "US",
            "content-type": "application/json",
        }
        url = ADZUNA_BASE.format(page=page)
        try:
            resp = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
            resp.raise_for_status()
        except requests.HTTPError as e:
            # 4xx other than 429 is almost always a config problem — log and
            # raise so the pipeline surfaces it once instead of retrying.
            status = getattr(e.response, "status_code", None)
            body = getattr(e.response, "text", "")[:200]
            logger.error("[adzuna] HTTP %s on page %d: %s", status, page, body)
            raise
        except requests.RequestException as e:
            logger.error("[adzuna] network error on page %d: %s", page, e)
            raise

        payload = resp.json()
        raw_results = payload.get("results") or []
        if not raw_results:
            logger.info("[adzuna] page %d returned 0 results — stopping early", page)
            break

        kept = 0
        for raw in raw_results:
            if not _is_us_location(raw.get("location")):
                continue
            normalized = _normalize(raw)
            if normalized is None:
                continue
            out.append(normalized)
            kept += 1

        logger.info(
            "[adzuna] page %d: %d raw → %d kept (total so far: %d)",
            page, len(raw_results), kept, len(out),
        )

        # Be polite; Adzuna is a free tier.
        if page < pages:
            time.sleep(0.25)

    return out