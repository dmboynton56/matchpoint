from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.db import turso
from app.schemas.job_search import (
    JobBrowseListing,
    JobSearchParseRequest,
    JobsSearchResponse,
)
from app.services.job_search_parser import (
    parse_job_search_message,
    parsed_filters_to_dict,
)
from app.services.job_summary import (
    enrich_browse_listings,
    generate_summaries_for_jobs,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _parse_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _parse_int(raw: str | None) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


@router.get("/jobs/search", response_model=JobsSearchResponse)
def search_jobs_endpoint(
    background_tasks: BackgroundTasks,
    q: str = Query("", description="Keyword search"),
    location: str | None = Query(None, description="Comma-separated locations"),
    level: str | None = Query(None, description="Comma-separated experience levels"),
    type: str | None = Query(None, description="Comma-separated job types"),
    workplace: str | None = Query(None, description="Comma-separated workplace types"),
    pay_min: str | None = Query(None),
    pay_max: str | None = Query(None),
    posted: str = Query("any", description="Date posted window"),
    sort: str = Query("relevance"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    rows, total = turso.search_jobs(
        keywords=q,
        locations=_parse_csv(location),
        experience_levels=_parse_csv(level),
        job_types=_parse_csv(type),
        workplace_types=_parse_csv(workplace),
        pay_min=_parse_int(pay_min),
        pay_max=_parse_int(pay_max),
        date_posted=posted,
        sort=sort if sort in {"relevance", "newest"} else "relevance",
        page=page,
        page_size=page_size,
    )

    rows, pending_summary_ids = enrich_browse_listings(rows)
    if pending_summary_ids:
        background_tasks.add_task(
            generate_summaries_for_jobs, pending_summary_ids
        )

    jobs = [JobBrowseListing.model_validate(row) for row in rows]
    return JobsSearchResponse(
        jobs=jobs,
        total=total,
        page=page,
        pageSize=page_size,
    )


@router.post("/jobs/search/parse")
def parse_search_filters(body: JobSearchParseRequest):
    try:
        parsed = parse_job_search_message(body.message)
        return parsed_filters_to_dict(parsed)
    except Exception as exc:
        logger.exception("Job search parse failed")
        raise HTTPException(
            status_code=502,
            detail="Failed to parse search query.",
        ) from exc
