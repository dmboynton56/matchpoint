"""Extract JobSearchFilters from natural-language queries via structured LLM output."""

from __future__ import annotations

import os

from app.schemas.job_search import ParsedJobSearchFilters
from app.services.embedding import client

PARSER_MODEL = os.getenv("OPENAI_JOB_SEARCH_PARSER_MODEL", "gpt-5.4-nano")
PARSER_TIMEOUT_SECONDS = float(os.getenv("OPENAI_JOB_SEARCH_PARSER_TIMEOUT_SECONDS", "30"))

parser_client = client.with_options(
    timeout=PARSER_TIMEOUT_SECONDS,
    max_retries=int(os.getenv("OPENAI_JOB_SEARCH_PARSER_MAX_RETRIES", "1")),
)

SYSTEM_PROMPT = """
Extract job search filters from the user's message.
Return only fields explicitly implied by the message — omit everything else.

Rules:
- keywords: role/skills/topic terms only (not locations, levels, or pay)
- locations: city names or "Remote" when the user wants remote work as a place
- experienceLevels: one or more of internship, entry, mid, senior, lead, executive
- jobTypes: one or more of full_time, part_time, contract, internship, temporary
- workplaceTypes: remote, hybrid, on_site — only when explicitly about work arrangement
- payMin / payMax: annual USD integers when salary is mentioned
- datePosted: one of any, 24h, 3d, 7d, 14d, 30d when recency is mentioned

When the user says "remote" as a location preference, put "Remote" in locations
(not workplaceTypes) unless they clearly mean hybrid/on-site arrangement.
Use exact enum strings from the schema.
""".strip()


def parse_job_search_message(message: str) -> ParsedJobSearchFilters:
    completion = parser_client.beta.chat.completions.parse(
        model=PARSER_MODEL,
        response_format=ParsedJobSearchFilters,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message.strip()},
        ],
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        return ParsedJobSearchFilters()
    return parsed


def parsed_filters_to_dict(parsed: ParsedJobSearchFilters) -> dict:
    """Drop null/empty fields; use camelCase keys for the frontend contract."""
    data = parsed.model_dump(exclude_none=True)
    cleaned: dict = {}
    for key, value in data.items():
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, list) and not value:
            continue
        cleaned[key] = value
    return cleaned
