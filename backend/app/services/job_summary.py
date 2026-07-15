"""Generate and cache short browse summaries for job listings."""

from __future__ import annotations

import hashlib
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from app.db import turso
from app.services.embedding import client
from app.services.job_metadata import browse_metadata_missing, derive_browse_metadata

# Verified against /v1/models 2026-07-15: gpt-5.4-nano is real and the cheapest
# chat-capable tier ("gpt-4o-nano" does not exist; gpt-4o-mini costs more).
SUMMARY_MODEL = os.getenv("OPENAI_SUMMARY_MODEL", "gpt-5.4-nano")
SUMMARY_CHAR_LIMIT = int(os.getenv("OPENAI_SUMMARY_CHAR_LIMIT", "200"))
SUMMARY_INPUT_CHAR_LIMIT = int(os.getenv("OPENAI_SUMMARY_INPUT_CHAR_LIMIT", "3000"))
SUMMARY_TIMEOUT_SECONDS = float(os.getenv("OPENAI_SUMMARY_TIMEOUT_SECONDS", "8"))
SUMMARY_MAX_TOKENS = int(os.getenv("OPENAI_SUMMARY_MAX_TOKENS", "80"))
# Cap LLM calls per search request; jobs past the cap get a plain excerpt.
SUMMARY_MAX_PER_REQUEST = int(os.getenv("OPENAI_SUMMARY_MAX_PER_REQUEST", "12"))
SUMMARY_WORKERS = int(os.getenv("OPENAI_SUMMARY_WORKERS", "4"))

summary_client = client.with_options(
    timeout=SUMMARY_TIMEOUT_SECONDS,
    max_retries=int(os.getenv("OPENAI_SUMMARY_MAX_RETRIES", "1")),
)

_in_flight_summary_ids: set[str] = set()
_in_flight_summary_lock = threading.Lock()


SYSTEM_PROMPT = f"""
Write a concise job listing summary for a browse results card.
Return plain text only — no HTML, bullets, or markdown.
Keep it under {SUMMARY_CHAR_LIMIT} characters.
Focus on role scope and key requirements; omit boilerplate and benefits.
""".strip()


def description_hash(text: str) -> str:
    normalized = text.strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def fallback_summary(description: str | None, *, limit: int = SUMMARY_CHAR_LIMIT) -> str:
    text = (description or "").strip()
    if not text:
        return ""
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def generate_summary(description: str, *, title: str = "", company: str = "") -> str | None:
    if not description.strip():
        return None

    input_text = description.strip()[:SUMMARY_INPUT_CHAR_LIMIT]
    context = ""
    if title or company:
        context = f"Title: {title}\nCompany: {company}\n\n"

    try:
        completion = summary_client.chat.completions.create(
            model=SUMMARY_MODEL,
            # gpt-5.x rejects max_tokens; max_completion_tokens works everywhere.
            max_completion_tokens=SUMMARY_MAX_TOKENS,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"{context}Description:\n{input_text}",
                },
            ],
        )
        summary = (completion.choices[0].message.content or "").strip()
        if summary:
            if len(summary) > SUMMARY_CHAR_LIMIT:
                summary = summary[: SUMMARY_CHAR_LIMIT - 1].rstrip() + "…"
            return summary
    except Exception:
        return None
    return None


def _missing_summary(job: dict) -> bool:
    return not (job.get("summary") or "").strip()


def _claim_summary_ids(job_ids: list[str]) -> list[str]:
    """Claim uncached jobs for one background batch, preserving input order."""
    claimed: list[str] = []
    with _in_flight_summary_lock:
        for job_id in job_ids:
            if len(claimed) >= SUMMARY_MAX_PER_REQUEST:
                break
            if job_id in _in_flight_summary_ids:
                continue
            _in_flight_summary_ids.add(job_id)
            claimed.append(job_id)
    return claimed


def enrich_browse_listings(jobs: list[dict]) -> tuple[list[dict], list[str]]:
    """Attach fast browse enrichment and return IDs needing summaries.

    Missing summaries receive an in-memory description excerpt immediately.
    Their IDs are claimed for deferred generation, up to the per-request cap.
    Metadata derivation and persistence remain synchronous because they are
    local, regex-only operations.
    """
    if not jobs:
        return jobs, []

    needy = [
        job
        for job in jobs
        if _missing_summary(job) or browse_metadata_missing(job)
    ]
    if not needy:
        return jobs, []

    text_rows = turso.fetch_job_text([job["id"] for job in needy])
    by_id = {row["id"]: row for row in text_rows}

    metadata_updates: list[tuple[str, dict]] = []
    summary_candidates: list[str] = []

    for job in needy:
        row = by_id.get(job["id"])
        if not row:
            continue
        description = row.get("description") or ""

        if browse_metadata_missing(job):
            metadata = derive_browse_metadata(
                title=row.get("title") or "",
                location=row.get("location"),
                description=description,
            )
            if any(value is not None for value in metadata.values()):
                job.update(metadata)
                metadata_updates.append((job["id"], metadata))

        if _missing_summary(job) and description.strip():
            job["summary"] = fallback_summary(description)
            summary_candidates.append(job["id"])

    if metadata_updates:
        turso.batch_update_job_metadata(metadata_updates)

    return jobs, _claim_summary_ids(summary_candidates)


def generate_summaries_for_jobs(job_ids: list[str]) -> None:
    """Generate and batch-persist summaries claimed by the browse fast path."""
    # Defensively de-duplicate while retaining the search-result order.
    batch_ids = list(dict.fromkeys(job_ids))[:SUMMARY_MAX_PER_REQUEST]
    if not batch_ids:
        return

    try:
        text_rows = turso.fetch_job_text(batch_ids)

        def _generate(row: dict) -> str | None:
            try:
                return generate_summary(
                    row.get("description") or "",
                    title=row.get("title") or "",
                    company=row.get("company") or "",
                )
            except Exception:
                return None

        if not text_rows:
            return

        with ThreadPoolExecutor(
            max_workers=min(SUMMARY_WORKERS, len(text_rows))
        ) as pool:
            summaries = list(pool.map(_generate, text_rows))

        generated_at = datetime.now(timezone.utc).isoformat()
        updates: list[tuple[str, dict]] = []
        for row, summary in zip(text_rows, summaries):
            if not summary:
                continue
            description = row.get("description") or ""
            updates.append(
                (
                    row["id"],
                    {
                        "summary": summary,
                        "source_hash": description_hash(description),
                        "model": SUMMARY_MODEL,
                        "generated_at": generated_at,
                    },
                )
            )

        if updates:
            turso.batch_update_job_summaries(updates)
    finally:
        with _in_flight_summary_lock:
            _in_flight_summary_ids.difference_update(batch_ids)


def generate_and_attach_summary(job: dict) -> dict:
    """Generate summary for a single ingest job dict; mutates and returns it."""
    description = job.get("description") or ""
    if not description.strip():
        return job

    source_hash = description_hash(description)
    if job.get("summary_source_hash") == source_hash and job.get("summary"):
        return job

    summary = generate_summary(
        description,
        title=job.get("title") or "",
        company=job.get("company") or "",
    )
    job["summary_source_hash"] = source_hash
    job["summary_model"] = SUMMARY_MODEL
    job["summary_generated_at"] = datetime.now(timezone.utc).isoformat()
    if summary:
        job["summary"] = summary
    else:
        job["summary"] = fallback_summary(description)
    return job
