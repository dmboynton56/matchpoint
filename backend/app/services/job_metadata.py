"""Derive browse/search metadata from job title, location, and description."""

from __future__ import annotations

import re
from typing import Any

from app.services.job_facts import extract_job_facts

METADATA_FIELDS = (
    "workplace_type",
    "pay_min",
    "pay_max",
    "experience_level",
    "job_type",
)


def browse_metadata_missing(row: dict) -> bool:
    """True when a row has never had browse metadata derived (all fields NULL)."""
    return all(row.get(field) is None for field in METADATA_FIELDS)


EXPERIENCE_LEVEL_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("internship", ("intern", "internship", "co-op", "co op")),
    ("entry", ("entry level", "entry-level", "junior", "associate", "new grad", "early career")),
    ("mid", ("mid level", "mid-level", " intermediate")),
    ("senior", ("senior", "sr.", "sr ")),
    ("lead", ("lead", "staff", "principal", "manager", "head of")),
    ("executive", ("director", "vp ", "vice president", "chief", " cto", " cfo", " ceo")),
]

JOB_TYPE_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("internship", ("internship", " intern ", "co-op", "co op")),
    ("contract", ("contract", "contractor", "1099", "freelance")),
    ("part_time", ("part time", "part-time")),
    ("temporary", ("temporary", "temp role", "seasonal")),
    ("full_time", ("full time", "full-time", "fulltime")),
]


def infer_experience_level(title: str) -> str | None:
    lowered = f" {title.lower()} "
    for level, markers in EXPERIENCE_LEVEL_PATTERNS:
        if any(marker in lowered for marker in markers):
            return level
    return None


def infer_job_type(title: str, description: str | None) -> str | None:
    haystack = f" {title.lower()} {(description or '')[:1500].lower()} "
    for job_type, markers in JOB_TYPE_PATTERNS:
        if any(marker in haystack for marker in markers):
            return job_type
    return None


def _workplace_type_from_modes(work_modes: list[str]) -> str | None:
    if not work_modes:
        return None
    lowered = {mode.lower() for mode in work_modes}
    if "remote" in lowered and len(lowered) == 1:
        return "remote"
    if "hybrid" in lowered:
        return "hybrid"
    if lowered & {"on-site", "on site"}:
        return "on_site"
    if "remote" in lowered:
        return "remote"
    return None


def derive_browse_metadata(
    *, title: str, location: str | None, description: str | None
) -> dict:
    """Return Turso browse columns derived from job text."""
    facts = extract_job_facts(title=title, location=location, description=description)
    salary = facts.salary
    workplace_type = _workplace_type_from_modes(facts.work_modes)

    return {
        "workplace_type": workplace_type,
        "pay_min": salary.minimum if salary else None,
        "pay_max": salary.maximum if salary else None,
        "pay_currency": salary.currency if salary else None,
        "experience_level": infer_experience_level(title),
        "job_type": infer_job_type(title, description),
    }


def _title_marker_sql(markers: tuple[str, ...]) -> tuple[str, list[str]]:
    """Build OR'd title LIKE clauses for metadata fallback matching."""
    parts: list[str] = []
    params: list[str] = []
    for marker in markers:
        parts.append("LOWER(COALESCE(title, '')) LIKE ?")
        params.append(f"%{marker.strip().lower()}%")
    return f"({' OR '.join(parts)})", params


def experience_level_filter_sql(levels: list[str]) -> tuple[str, list[Any]]:
    """Match persisted column or infer from title when column is still NULL."""
    placeholders = ",".join(["?"] * len(levels))
    fallback_parts: list[str] = []
    fallback_params: list[Any] = []
    for level in levels:
        markers = next(
            (m for lvl, m in EXPERIENCE_LEVEL_PATTERNS if lvl == level),
            None,
        )
        if markers:
            fragment, params = _title_marker_sql(markers)
            fallback_parts.append(fragment)
            fallback_params.extend(params)

    fallback_sql = ""
    if fallback_parts:
        fallback_sql = (
            f" OR (experience_level IS NULL AND ({' OR '.join(fallback_parts)}))"
        )

    return (
        f"(experience_level IN ({placeholders}){fallback_sql})",
        [*levels, *fallback_params],
    )


def workplace_type_filter_sql(types: list[str]) -> tuple[str, list[Any]]:
    """Match persisted column or infer from location/description when NULL."""
    placeholders = ",".join(["?"] * len(types))
    fallback_parts: list[str] = []
    fallback_params: list[Any] = []

    workplace_markers = {
        "remote": ("%remote%", "%remote%"),
        "hybrid": ("%hybrid%", "%hybrid%"),
        "on_site": ("%on-site%", "%on-site%"),
    }

    for workplace in types:
        loc_marker, desc_marker = workplace_markers.get(
            workplace, (f"%{workplace.replace('_', ' ')}%", f"%{workplace.replace('_', ' ')}%")
        )
        fallback_parts.append(
            "(LOWER(COALESCE(location, '')) LIKE ? OR "
            "LOWER(COALESCE(description, '')) LIKE ?)"
        )
        fallback_params.extend([loc_marker, desc_marker])

    fallback_sql = ""
    if fallback_parts:
        fallback_sql = (
            f" OR (workplace_type IS NULL AND ({' OR '.join(fallback_parts)}))"
        )

    return (
        f"(workplace_type IN ({placeholders}){fallback_sql})",
        [*types, *fallback_params],
    )


def job_type_filter_sql(types: list[str]) -> tuple[str, list[Any]]:
    placeholders = ",".join(["?"] * len(types))
    fallback_parts: list[str] = []
    fallback_params: list[Any] = []

    for job_type in types:
        markers = next(
            (m for jt, m in JOB_TYPE_PATTERNS if jt == job_type),
            None,
        )
        if markers:
            title_sql, title_params = _title_marker_sql(markers)
            fallback_parts.append(
                f"(job_type IS NULL AND ({title_sql} OR LOWER(COALESCE(description, '')) LIKE ?))"
            )
            fallback_params.extend([*title_params, f"%{markers[0].strip()}%"])

    fallback_sql = ""
    if fallback_parts:
        fallback_sql = f" OR ({' OR '.join(fallback_parts)})"

    return (
        f"(job_type IN ({placeholders}){fallback_sql})",
        [*types, *fallback_params],
    )
