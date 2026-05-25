import json

from app.schemas.ranking import JobRankInput, RankingResponse, validate_rankings
from app.services.embedding import client


SYSTEM_PROMPT = """
Rank all N jobs 1-N for this resume.

Criteria: skills/experience, seniority, tech overlap, domain, location if stated,
and career fit. Scores must be 0-1 and strictly decrease by rank. Highlights must
be 2-3 bullets, each 120 characters or fewer, citing resume and job evidence and
noting gaps honestly. Use vector_similarity as a weak tiebreaker only. Never invent
facts or omit job IDs.
""".strip()


def _build_user_message(resume_text: str, jobs: list[JobRankInput]) -> str:
    jobs_json = json.dumps(
        [job.model_dump() for job in jobs],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"RESUME: {resume_text}\n\nJOBS ({len(jobs)} total - rank all): {jobs_json}"


def rank_jobs_with_llm(
    resume_text: str, jobs: list[JobRankInput]
) -> RankingResponse:
    if not jobs:
        return RankingResponse(rankings=[])

    last_error: Exception | None = None
    for _ in range(2):
        completion = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            temperature=0.2,
            response_format=RankingResponse,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_message(resume_text, jobs)},
            ],
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            last_error = ValueError("OpenAI ranking response was not parsed.")
            continue

        try:
            return validate_rankings(parsed, jobs)
        except ValueError as exc:
            last_error = exc

    raise RuntimeError(f"LLM ranking validation failed: {last_error}") from last_error
