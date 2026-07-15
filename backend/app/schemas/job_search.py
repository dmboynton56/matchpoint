"""Pydantic schemas for job browse search and NLU filter parsing."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DatePosted = Literal["any", "24h", "3d", "7d", "14d", "30d"]
JobsSortOption = Literal["relevance", "newest"]
ExperienceLevel = Literal[
    "internship", "entry", "mid", "senior", "lead", "executive"
]
JobType = Literal["full_time", "part_time", "contract", "internship", "temporary"]
WorkplaceType = Literal["remote", "hybrid", "on_site"]


class JobBrowseListing(BaseModel):
    id: str
    title: str
    company: str
    location: str | None = None
    apply_url: str | None = None
    posted_at: str | None = None
    summary: str | None = None
    job_type: JobType | None = None
    experience_level: ExperienceLevel | None = None
    workplace_type: WorkplaceType | None = None
    pay_min: int | None = None
    pay_max: int | None = None
    pay_currency: str | None = None


class JobsSearchResponse(BaseModel):
    jobs: list[JobBrowseListing]
    total: int
    page: int
    pageSize: int


class JobSearchParseRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class ParsedJobSearchFilters(BaseModel):
    """Structured output from the NLU parser — all fields optional."""

    keywords: str | None = None
    locations: list[str] | None = None
    experienceLevels: list[ExperienceLevel] | None = None
    jobTypes: list[JobType] | None = None
    workplaceTypes: list[WorkplaceType] | None = None
    payMin: int | None = None
    payMax: int | None = None
    datePosted: DatePosted | None = None
