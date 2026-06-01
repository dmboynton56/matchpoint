from pydantic import BaseModel, Field


class SalaryFacts(BaseModel):
    minimum: int | None = Field(default=None, ge=0)
    maximum: int | None = Field(default=None, ge=0)
    currency: str | None = None
    period: str | None = None
    evidence: str | None = Field(default=None, max_length=240)


class JobFacts(BaseModel):
    work_modes: list[str] = Field(default_factory=list, max_length=4)
    locations: list[str] = Field(default_factory=list, max_length=12)
    salary: SalaryFacts | None = None
    role_family: str | None = Field(default=None, max_length=80)


class UserPreferences(BaseModel):
    target_role: str | None = Field(default=None, max_length=160)
    preferred_locations: list[str] = Field(default_factory=list, max_length=8)
    preferred_work_modes: list[str] = Field(default_factory=list, max_length=4)
    minimum_base_salary: int | None = Field(default=None, ge=0)
    salary_currency: str = Field(default="USD", max_length=8)


class JobRankInput(BaseModel):
    job_id: str
    title: str
    company: str
    location: str | None = None
    description: str = Field(max_length=4000)
    vector_similarity: float
    facts: JobFacts | None = None


class JobScore(BaseModel):
    job_id: str
    interview_likelihood: float = Field(ge=0, le=1)
    skills_fit: float = Field(ge=0, le=1)
    experience_fit: float = Field(ge=0, le=1)
    seniority_fit: float = Field(ge=0, le=1)
    location_fit: float = Field(ge=0, le=1)
    pay_fit: float = Field(ge=0, le=1)
    role_fit: float = Field(ge=0, le=1)
    preference_fit: float = Field(ge=0, le=1)
    match_highlights: list[str] = Field(min_length=2, max_length=3)
    match_concerns: list[str] | None = Field(default=None, max_length=3)
    location_reason: str | None = Field(default=None, max_length=180)
    location_evidence: str | None = Field(default=None, max_length=180)
    pay_reason: str | None = Field(default=None, max_length=180)
    pay_evidence: str | None = Field(default=None, max_length=180)
    role_reason: str | None = Field(default=None, max_length=180)
    role_evidence: str | None = Field(default=None, max_length=180)


class ScoringResponse(BaseModel):
    scores: list[JobScore]


def validate_scores(
    response: ScoringResponse, input_jobs: list[JobRankInput]
) -> ScoringResponse:
    expected_ids = {job.job_id for job in input_jobs}
    actual_ids = {score.job_id for score in response.scores}
    if len(response.scores) != len(input_jobs) or len(actual_ids) != len(response.scores):
        raise ValueError("Scoring response must include each input job exactly once.")

    if actual_ids != expected_ids:
        missing = sorted(expected_ids - actual_ids)
        extra = sorted(actual_ids - expected_ids)
        raise ValueError(
            f"Scored job IDs must match input jobs. Missing: {missing}. Extra: {extra}."
        )

    for score in response.scores:
        for highlight in score.match_highlights:
            if not highlight.strip():
                raise ValueError("Match highlights cannot be blank.")
            if len(highlight) > 120:
                raise ValueError("Match highlights must be 120 characters or fewer.")
        for concern in score.match_concerns or []:
            if not concern.strip():
                raise ValueError("Match concerns cannot be blank.")
            if len(concern) > 120:
                raise ValueError("Match concerns must be 120 characters or fewer.")
        for field_name in (
            "location_reason",
            "location_evidence",
            "pay_reason",
            "pay_evidence",
            "role_reason",
            "role_evidence",
        ):
            value = getattr(score, field_name)
            if value is not None and not value.strip():
                raise ValueError(f"{field_name} cannot be blank when provided.")

    return response
