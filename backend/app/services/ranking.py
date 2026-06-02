import json
import os
from concurrent.futures import ThreadPoolExecutor

from app.schemas.ranking import (
    JobRankInput,
    JobScore,
    ScoringResponse,
    UserPreferences,
    validate_scores,
)
from app.services.embedding import client

SCORING_MODEL = os.getenv("OPENAI_SCORING_MODEL", "gpt-5.4-nano")
SCORING_TIMEOUT_SECONDS = float(os.getenv("OPENAI_SCORING_TIMEOUT_SECONDS", "75"))
SCORING_MAX_RETRIES = int(os.getenv("OPENAI_SCORING_MAX_RETRIES", "0"))
SCORING_RESUME_CHAR_LIMIT = int(os.getenv("SCORING_RESUME_CHAR_LIMIT", "6000"))
SCORING_JOB_DESCRIPTION_CHAR_LIMIT = int(
    os.getenv("SCORING_JOB_DESCRIPTION_CHAR_LIMIT", "1000")
)
SCORING_BATCH_SIZE = int(os.getenv("SCORING_BATCH_SIZE", "5"))
SCORING_PARALLELISM = int(os.getenv("SCORING_PARALLELISM", "2"))
SCORING_REASONING_EFFORT = os.getenv("SCORING_REASONING_EFFORT", "none")

scoring_client = client.with_options(
    timeout=SCORING_TIMEOUT_SECONDS,
    max_retries=SCORING_MAX_RETRIES,
)


SYSTEM_PROMPT = """
Score each job independently for this resume.

Return compact, grounded structured data only. Do not compare jobs to each other,
rank relatively, or force unique scores. The same resume/job pair should receive
roughly the same scores regardless of what other jobs are included in the request.

Use JOB facts as grounded truth when they are present. Use USER_PREFERENCES only
for preference scoring; do not invent location, pay, or position preferences from
the resume unless they are explicitly present in USER_PREFERENCES.

Estimate interview_likelihood as the realistic chance this candidate would get
an interview from the job evidence and resume evidence. Score skills_fit,
experience_fit, seniority_fit, location_fit, pay_fit, role_fit, and
preference_fit from 0-1. If a preference or job fact is unknown, use a neutral fit
near 0.75 and explain that the evidence is missing. Use vector_similarity only as
weak context, not as the score.

For each job, return exactly three match_notes total. Notes may be positive,
negative, or mixed. They should explain the most decision-useful reasons behind
the scores, including location, pay, or role only when materially relevant. Set
is_warning=true only for a meaningful drawback the candidate should notice.
Do not add separate warning lists, evidence fields, or duplicate chip values.
Never invent facts or omit job IDs.
""".strip()


def _truncate_text(text: str, limit: int) -> str:
    normalized = text.strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "\n[truncated]"


def _build_user_message(
    resume_text: str,
    jobs: list[JobRankInput],
    *,
    preferences: UserPreferences | None = None,
    correction: str | None = None,
) -> str:
    job_ids = [job.job_id for job in jobs]
    compact_jobs = []
    for job in jobs:
        job_data = job.model_dump()
        job_data["description"] = _truncate_text(
            job.description,
            SCORING_JOB_DESCRIPTION_CHAR_LIMIT,
        )
        compact_jobs.append(job_data)

    jobs_json = json.dumps(
        compact_jobs,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    preferences_json = json.dumps(
        (preferences or UserPreferences()).model_dump(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    message = (
        f"RESUME: {_truncate_text(resume_text, SCORING_RESUME_CHAR_LIMIT)}\n\n"
        f"USER_PREFERENCES: {preferences_json}\n\n"
        f"JOBS ({len(jobs)} total - score all): {jobs_json}\n\n"
        f"Return exactly {len(jobs)} scores with these job_id values, each once: {job_ids}"
    )
    if correction:
        message += f"\n\nCORRECTION: {correction}"
    return message


_SCORING_RETRY_CORRECTION = (
    "The scoring request failed. Return a valid scoring response for every input job."
)


def _request_scores(
    resume_text: str,
    jobs: list[JobRankInput],
    *,
    preferences: UserPreferences | None = None,
    correction: str | None = None,
) -> ScoringResponse | None:
    request_params = {
        "model": SCORING_MODEL,
        "response_format": ScoringResponse,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _build_user_message(
                    resume_text,
                    jobs,
                    preferences=preferences,
                    correction=correction,
                ),
            },
        ],
    }
    if SCORING_MODEL.startswith("gpt-5"):
        request_params["reasoning_effort"] = SCORING_REASONING_EFFORT
    else:
        request_params["temperature"] = 0.2

    completion = scoring_client.beta.chat.completions.parse(
        **request_params,
    )
    return completion.choices[0].message.parsed


def _build_validation_correction(
    exc: ValueError, jobs: list[JobRankInput], response: ScoringResponse
) -> str:
    expected_ids = [job.job_id for job in jobs]
    actual_ids = [score.job_id for score in response.scores]
    return (
        f"Previous response failed validation: {exc}. "
        f"Return exactly {len(jobs)} scores with job_id values {expected_ids}. "
        f"You returned {len(actual_ids)} scores with job_id values {actual_ids}."
    )


def score_jobs_with_llm(
    resume_text: str,
    jobs: list[JobRankInput],
    *,
    preferences: UserPreferences | None = None,
) -> ScoringResponse:
    if not jobs:
        return ScoringResponse(scores=[])

    batch_size = max(1, SCORING_BATCH_SIZE)
    if len(jobs) > batch_size:
        chunks = [
            jobs[index : index + batch_size]
            for index in range(0, len(jobs), batch_size)
        ]
        max_workers = max(1, min(SCORING_PARALLELISM, len(chunks)))
        if max_workers > 1:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                responses = list(
                    executor.map(
                        lambda chunk: score_jobs_with_llm(
                            resume_text,
                            chunk,
                            preferences=preferences,
                        ),
                        chunks,
                    )
                )
        else:
            responses = [
                score_jobs_with_llm(resume_text, chunk, preferences=preferences)
                for chunk in chunks
            ]

        scores = [score for response in responses for score in response.scores]
        return validate_scores(ScoringResponse(scores=scores), jobs)

    last_error: Exception | None = None
    correction: str | None = None

    for _ in range(4):
        try:
            parsed = _request_scores(
                resume_text,
                jobs,
                preferences=preferences,
                correction=correction,
            )
        except Exception as exc:
            last_error = exc
            correction = _SCORING_RETRY_CORRECTION
            continue
        if parsed is None:
            last_error = ValueError("OpenAI scoring response was not parsed.")
            correction = "Return a valid scoring response for every input job."
            continue

        try:
            return validate_scores(parsed, jobs)
        except ValueError as exc:
            last_error = exc
            correction = _build_validation_correction(exc, jobs, parsed)

    scores: list[JobScore] = []
    for job in jobs:
        job_correction: str | None = None
        for _ in range(3):
            try:
                parsed = _request_scores(
                    resume_text,
                    [job],
                    preferences=preferences,
                    correction=job_correction,
                )
            except Exception as exc:
                last_error = exc
                job_correction = "Return one valid score for the single input job."
                continue
            if parsed is None:
                last_error = ValueError("OpenAI scoring response was not parsed.")
                job_correction = "Return one valid score for the single input job."
                continue

            try:
                scores.append(validate_scores(parsed, [job]).scores[0])
                break
            except ValueError as exc:
                last_error = exc
                job_correction = _build_validation_correction(exc, [job], parsed)
        else:
            raise RuntimeError(
                f"LLM scoring validation failed: {last_error}"
            ) from last_error

    return validate_scores(ScoringResponse(scores=scores), jobs)


def compute_match_score(score: JobScore) -> float:
    weighted_score = (
        score.interview_likelihood * 0.40
        + score.skills_fit * 0.20
        + score.experience_fit * 0.10
        + score.seniority_fit * 0.05
        + score.role_fit * 0.10
        + score.location_fit * 0.075
        + score.pay_fit * 0.05
        + score.preference_fit * 0.025
    )
    return round(max(0, min(1, weighted_score)), 4)
