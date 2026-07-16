"""Derive browse/search metadata from job title, location, and description."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.services.job_facts import extract_job_facts

METADATA_FIELDS = (
    "workplace_type",
    "pay_min",
    "pay_max",
    "experience_level",
    "job_type",
)

WORKPLACE_FALLBACK_MARKERS: dict[str, tuple[str, ...]] = {
    "remote": ("remote",),
    "hybrid": ("hybrid",),
    "on_site": ("on-site", "on site"),
}


def metadata_derived_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def browse_metadata_missing(row: dict) -> bool:
    """True when browse metadata has never been derived for this row."""
    return row.get("metadata_derived_at") is None


EXPERIENCE_LEVEL_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("internship", ("intern", "internship", "co-op", "co op")),
    ("entry", ("entry level", "entry-level", "junior", "associate", "new grad", "early career")),
    ("mid", ("mid level", "mid-level", "intermediate")),
    ("senior", ("senior", "sr.", "sr")),
    ("lead", ("lead", "staff", "principal", "manager", "head of")),
    ("executive", ("director", "vp", "vice president", "chief", "cto", "cfo", "ceo")),
]

JOB_TYPE_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("internship", ("internship", "intern", "co-op", "co op")),
    ("contract", ("contract", "contractor", "1099", "freelance")),
    ("part_time", ("part time", "part-time")),
    ("temporary", ("temporary", "temp role", "seasonal")),
    ("full_time", ("full time", "full-time", "fulltime")),
]


def _marker_matches(haystack: str, marker: str) -> bool:
    normalized = marker.strip()
    if not normalized:
        return False
    pattern = rf"(?<!\w){re.escape(normalized)}(?!\w)"
    return re.search(pattern, haystack, re.IGNORECASE) is not None


def infer_experience_level(title: str) -> str | None:
    for level, markers in EXPERIENCE_LEVEL_PATTERNS:
        if any(_marker_matches(title, marker) for marker in markers):
            return level
    return None


def infer_job_type(title: str, description: str | None) -> str | None:
    haystack = f"{title} {(description or '')[:1500]}"
    for job_type, markers in JOB_TYPE_PATTERNS:
        if any(_marker_matches(haystack, marker) for marker in markers):
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


def _like_marker_sql(column: str, marker: str) -> tuple[str, list[str]]:
    """Build boundary-safe LIKE clauses for one marker on a text column."""
    normalized = marker.strip().lower()
    if not normalized:
        return "0", []
    col = f"LOWER(COALESCE({column}, ''))"
    patterns = [
        f"% {normalized} %",
        f"{normalized} %",
        f"% {normalized}",
        normalized,
    ]
    parts = [f"{col} LIKE ?" for _ in patterns]
    return f"({' OR '.join(parts)})", patterns


def _title_marker_sql(markers: tuple[str, ...]) -> tuple[str, list[str]]:
    """Build OR'd title LIKE clauses for metadata fallback matching."""
    parts: list[str] = []
    params: list[str] = []
    for marker in markers:
        fragment, marker_params = _like_marker_sql("title", marker)
        if fragment != "0":
            parts.append(fragment)
            params.extend(marker_params)
    if not parts:
        return "0", []
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
            if fragment != "0":
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

    for workplace in types:
        aliases = WORKPLACE_FALLBACK_MARKERS.get(
            workplace, (workplace.replace("_", " "),)
        )
        alias_parts: list[str] = []
        for alias in aliases:
            alias_parts.append(
                "(LOWER(COALESCE(location, '')) LIKE ? OR "
                "LOWER(COALESCE(description, '')) LIKE ?)"
            )
            pattern = f"%{alias}%"
            fallback_params.extend([pattern, pattern])
        fallback_parts.append(f"({' OR '.join(alias_parts)})")

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
            marker_parts: list[str] = []
            marker_params: list[str] = []
            for marker in markers:
                title_sql, title_params = _like_marker_sql("title", marker)
                desc_sql, desc_params = _like_marker_sql("description", marker)
                if title_sql != "0" or desc_sql != "0":
                    marker_parts.append(f"({title_sql} OR {desc_sql})")
                    marker_params.extend([*title_params, *desc_params])
            if marker_parts:
                fallback_parts.append(
                    f"(job_type IS NULL AND ({' OR '.join(marker_parts)}))"
                )
                fallback_params.extend(marker_params)

    fallback_sql = ""
    if fallback_parts:
        fallback_sql = f" OR ({' OR '.join(fallback_parts)})"

    return (
        f"(job_type IN ({placeholders}){fallback_sql})",
        [*types, *fallback_params],
    )
