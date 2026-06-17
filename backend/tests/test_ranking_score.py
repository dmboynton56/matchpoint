import os

from app.schemas.ranking import JobScore, MatchNote

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from app.services.ranking import compute_match_score


def _score(**overrides) -> JobScore:
    payload = {
        "job_id": "job-1",
        "interview_likelihood": 0.5,
        "skills_fit": 0.5,
        "experience_fit": 0.5,
        "seniority_fit": 0.5,
        "location_fit": 0.5,
        "pay_fit": 0.5,
        "role_fit": 0.5,
        "preference_fit": 0.5,
        "match_notes": [
            MatchNote(text="Skills overlap with role requirements."),
            MatchNote(text="Experience maps to core responsibilities."),
            MatchNote(text="Preferences mostly align with job facts."),
        ],
    }
    payload.update(overrides)
    return JobScore(**payload)


def test_match_score_keeps_strong_fit_high_with_modest_interview_likelihood():
    score = _score(
        interview_likelihood=0.35,
        skills_fit=0.9,
        experience_fit=0.86,
        seniority_fit=0.82,
        location_fit=0.9,
        pay_fit=0.8,
        role_fit=0.88,
        preference_fit=0.82,
    )

    assert compute_match_score(score) == 0.8404


def test_match_score_stays_low_for_weak_fit_even_with_average_interview_signal():
    score = _score(
        interview_likelihood=0.55,
        skills_fit=0.35,
        experience_fit=0.3,
        seniority_fit=0.4,
        location_fit=0.45,
        pay_fit=0.5,
        role_fit=0.32,
        preference_fit=0.4,
    )

    assert compute_match_score(score) == 0.3759
