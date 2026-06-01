import json

from app.schemas.ranking import (
    JobRankInput,
    JobScore,
    ScoringResponse,
    UserPreferences,
    validate_scores,
)
from app.services.embedding import client


SYSTEM_PROMPT = """
Score each job independently for this resume.

Do not compare jobs to each other. Do not rank relatively. Do not force unique
scores. The same resume/job pair should receive roughly the same scores regardless
of what other jobs are included in the request.

Use JOB facts as grounded truth when they are present. Use USER_PREFERENCES only
for preference scoring; do not invent location, pay, or position preferences from
the resume unless they are explicitly present in USER_PREFERENCES.

Estimate interview_likelihood as the realistic chance this candidate would get
an interview from the job evidence and resume evidence. Score skills_fit,
experience_fit, seniority_fit, location_fit, pay_fit, role_fit, and
preference_fit from 0-1. If a preference or job fact is unknown, use a neutral fit
near 0.75 and explain that the evidence is missing. Use vector_similarity only as
weak context, not as the score.

Highlights must be 2-3 bullets, each 120 characters or fewer, citing resume and job
evidence. Concerns should be short and honest when there are clear gaps. Fill
location_reason/evidence, pay_reason/evidence, and role_reason/evidence with the
specific basis for the fit score, or note when the posting/preferences are unclear.
Never invent facts or omit job IDs.
""".strip()


def _build_user_message(
    resume_text: str,
    jobs: list[JobRankInput],
    *,
    preferences: UserPreferences | None = None,
    correction: str | None = None,
) -> str:
    job_ids = [job.job_id for job in jobs]
    jobs_json = json.dumps(
        [job.model_dump() for job in jobs],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    preferences_json = json.dumps(
        (preferences or UserPreferences()).model_dump(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    message = (
        f"RESUME: {resume_text}\n\n"
        f"USER_PREFERENCES: {preferences_json}\n\n"
        f"JOBS ({len(jobs)} total - score all): {jobs_json}\n\n"
        f"Return exactly {len(jobs)} scores with these job_id values, each once: {job_ids}"
    )
    if correction:
        message += f"\n\nCORRECTION: {correction}"
    return message


def _request_scores(
    resume_text: str,
    jobs: list[JobRankInput],
    *,
    preferences: UserPreferences | None = None,
    correction: str | None = None,
) -> ScoringResponse | None:
    completion = client.beta.chat.completions.parse(
        model="gpt-4o-mini",
        temperature=0.2,
        response_format=ScoringResponse,
        messages=[
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

    last_error: Exception | None = None
    correction: str | None = None

    for _ in range(4):
        parsed = _request_scores(
            resume_text,
            jobs,
            preferences=preferences,
            correction=correction,
        )
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
            parsed = _request_scores(
                resume_text,
                [job],
                preferences=preferences,
                correction=job_correction,
            )
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
