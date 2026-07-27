import json
import os
from concurrent.futures import ThreadPoolExecutor

from app.schemas.ranking import (
    JobRankInput,
    JobScore,
    MATCH_NOTE_MAX_CHARS,
    ScoringResponse,
    UserPreferences,
    validate_scores,
)
from app.services.embedding import client
from app.services.match_notes import normalize_match_notes

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
MATCH_SCORE_WEIGHTS = {
    "skills_fit": 0.25,
    "experience_fit": 0.18,
    "role_fit": 0.17,
    "seniority_fit": 0.10,
    "location_fit": 0.10,
    "pay_fit": 0.075,
    "preference_fit": 0.075,
    "interview_likelihood": 0.05,
}

scoring_client = client.with_options(
    timeout=SCORING_TIMEOUT_SECONDS,
    max_retries=SCORING_MAX_RETRIES,
)


SYSTEM_PROMPT = f"""
Score each job independently for this resume.

Return compact, grounded structured data only. Do not compare jobs to each other,
rank relatively, or force unique scores. The same resume/job pair should receive
roughly the same scores regardless of what other jobs are included in the request.

Use JOB facts as grounded truth when they are present. Use USER_PREFERENCES only
for preference scoring; do not invent location, pay, or position preferences from
the resume unless they are explicitly present in USER_PREFERENCES.

When the job's `facts` object includes `location_compatibility_score` (a float
between 0 and 1), use that value directly as your `location_fit` score. It has
already been calibrated to the candidate's location preferences and the job's
distance from the candidate's anchor city (or country centroid if no city is
set). The accompanying `location_compatibility_note` explains the score in plain
English and is suitable for use in the regular comment. Do not re-derive
`location_fit` from the raw location string — the structured number is the
grounded truth.

Estimate interview_likelihood as a separate realistic chance this candidate
would get an interview from the job evidence and resume evidence. It is not the
overall match score. Score skills_fit, experience_fit, seniority_fit,
location_fit, pay_fit, role_fit, and preference_fit from 0-1 as match-quality
signals. If a preference or job fact is unknown, use a neutral fit near 0.75 and
explain that the evidence is missing. Use vector_similarity only as weak
context, not as the score.

Seniority calibration: when the job's title or `facts.experience_level`
indicates a level clearly above what the resume supports (e.g. the resume
shows apprentice or early-career and the job is Senior, Staff, Principal,
or Director), score `seniority_fit` low (0.1-0.3) and include a warning
that flags the gap. The route has already pre-filtered jobs whose
experience_level is outside the user's target_seniority, so jobs that
reach you should generally be in-range; trust the structured signal
over the title alone when scoring seniority.

Return exactly three match_notes with is_warning=false plus zero or more
match_notes with is_warning=true. Regular comments and warnings serve different
purposes and must not duplicate the same point. Every match note must be
{MATCH_NOTE_MAX_CHARS} characters or fewer so it fits on one UI line.

Regular comments (is_warning=false, exactly three):
- Explain why the job is worth considering: skills overlap, role alignment,
  relevant experience, partial preference fit, or neutral score context.
- Prefer positive or balanced framing. Do not use regular comments for
  dealbreakers, relocation requirements, pay shortfalls, or seniority gaps.

Warnings (is_warning=true, zero or more):
- Required when any material drawback applies, including:
  onsite/relocation mismatch vs candidate location or stated preferences,
  pay below the candidate's stated minimum, seniority gap (e.g. apprentice to
  manager), or missing critical requirements.
- If a note describes a drawback the candidate should actively weigh before
  applying, it MUST be is_warning=true and MUST NOT appear as a regular comment.
- Example regular: "Strong React/TypeScript overlap with the stack."
- Example warning: "Role is SF on-site; resume shows Denver with no relocation
  or onsite preference stated."

Warnings must not replace regular comments. Omit warnings only when no material
drawbacks apply. Do not add separate warning lists, evidence fields, or duplicate
chip values. Never invent facts or omit job IDs.
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


def _normalize_scoring_response(response: ScoringResponse) -> ScoringResponse:
    return ScoringResponse(
        scores=[
            score.model_copy(update={"match_notes": normalize_match_notes(score)})
            for score in response.scores
        ]
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
            return validate_scores(_normalize_scoring_response(parsed), jobs)
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
                scores.append(
                    validate_scores(_normalize_scoring_response(parsed), [job]).scores[0]
                )
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
    weighted_score = sum(
        getattr(score, field) * weight
        for field, weight in MATCH_SCORE_WEIGHTS.items()
    )
    return round(max(0, min(1, weighted_score)), 4)
