"""
sources/_common.py — helpers shared by every third-party job source.

Each source module exposes a single `fetch() -> list[dict]` that returns rows
shaped exactly like the Greenhouse scraper so the rest of the pipeline
(run_pipeline, cleaning, embedding, upsert) doesn't care where a job came
from. The keys are:

    external_id   str  — stable per-source id; becomes the dedupe key
    company       str
    title         str
    description   str  — raw text or HTML; cleaning.py handles both
    location      str
    posted_at     str | None  — ISO 8601 when the source provides one
    apply_url     str
    source        str  — "adzuna" | "greenhouse"

A source is allowed to return [] on no results and MUST raise on transient
network / auth failures — `run_pipeline` wraps each source in its own
try/except so one failing API never blocks the others.
"""
from __future__ import annotations

import html
import os
from html.parser import HTMLParser
from typing import Any


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _env_or_warn(name: str) -> str | None:
    """Return the env var, or None if missing. Sources call this and return
    [] when their key isn't configured so an unconfigured source is a no-op
    rather than a crash."""
    val = _env(name)
    return val or None


def strip_html(text: str) -> str:
    """Strip HTML tags while preserving plain-text comparison operators.

    Naive char-by-char scanning flips on every `<` and stays there until
    the next `>`, which silently drops plain text like "experience < 2 years"
    or "ratio > 1.5". Real HTMLParser only treats syntactically plausible
    tags as markup, so standalone `<` / `>` in plain text pass through
    untouched. We use stdlib `html.parser` so we don't pull in BeautifulSoup
    per-row (the existing pipeline already uses BS elsewhere; this keeps
    the source modules dependency-light).
    """
    if not text:
        return ""

    class _TextExtractor(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self._chunks: list[str] = []

        def handle_data(self, data: str) -> None:
            self._chunks.append(data)

        def get_text(self) -> str:
            return " ".join(" ".join(self._chunks).split())

    # Unescape entities before parsing so `&amp;` doesn't trip the parser.
    parser = _TextExtractor()
    parser.feed(html.unescape(text))
    parser.close()
    return parser.get_text()


def iso_or_none(value: Any) -> str | None:
    """Best-effort ISO 8601 normalization. Adzuna uses "2024-05-13T..."."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # Replace trailing Z with +00:00 so Python's fromisoformat is happy on
    # older versions. Python 3.11+ handles Z natively, but Vercel's runtime
    # is 3.9 and we don't want a version-skew crash in a cold-start path.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return s


def _truncate(text: str | None, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit]


# -----------------------------------------------------------------------------
# 7-day query rotation
# -----------------------------------------------------------------------------
# Free-tier aggregators return mostly the same job boards each day, so
# burning N pages of a single broad query yields heavy overlap. Rotating
# through a list of focused queries (one per day) gets you genuinely
# different result sets at the same API cost.
#
# To change the rotation, edit ADZUNA_QUERIES. To force a specific day
# instead of the day-of-week index, set QUERY_ROTATION_OFFSET (advanced).
DEFAULT_ADZUNA_QUERIES: list[str] = [
    "software engineer",
    "data engineer",
    "backend developer",
    "frontend developer",
    "full stack engineer",
    "devops engineer",
    "machine learning engineer",
]


def _pick_query(queries: list[str], index: int) -> str:
    """Pick the index-th query from a list. Wraps on empty."""
    if not queries:
        return ""
    return queries[index % len(queries)]


def _rotation_index() -> int:
    """Day-of-week (0=Mon ... 6=Sun) plus optional offset for skewing the
    rotation. Override via QUERY_ROTATION_OFFSET env var if you want
    Tuesday's pool to use index 4 instead of index 1, etc."""
    from datetime import datetime, timezone

    offset_raw = __import__("os").getenv("QUERY_ROTATION_OFFSET", "0")
    try:
        offset = int(offset_raw)
    except ValueError:
        offset = 0
    return (datetime.now(timezone.utc).weekday() + offset) % 7