from pydantic import BaseModel, Field

MATCH_NOTE_MAX_CHARS = 90


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
    # Geolocation hard-filter signal. Populated by the matching route
    # before the LLM sees the job; 0.0 means the route has already
    # filtered the job out. The LLM reads these to ground its
    # location_fit score in a real number instead of guessing from
    # the raw location string. Both are None when the user has no
    # structured location preferences (the no-regression path).
    location_compatibility_score: float | None = Field(default=None, ge=0, le=1)
    location_compatibility_note: str | None = Field(default=None, max_length=160)


class UserPreferences(BaseModel):
    target_role: str | None = Field(default=None, max_length=160)
    preferred_locations: list[str] = Field(default_factory=list, max_length=8)
    preferred_work_modes: list[str] = Field(default_factory=list, max_length=4)
    minimum_base_salary: int | None = Field(default=None, ge=0)
    salary_currency: str = Field(default="USD", max_length=8)


class LocationPreferences(BaseModel):
    """Structured user preferences for the matching route.

    Geolocation fields: the route hard-filters jobs by
    ``preferred_country_codes`` when ``location_mode == "country"`` and
    soft-filters by ``preferred_radius_km`` around the anchor city.
    ``location_mode == "any"`` disables the filter entirely.

    Seniority fields: the route filters jobs whose ``experience_level``
    is NOT in ``target_seniority`` (matched against the `jobs`
    table's `experience_level` column). Default is
    ``["internship", "entry", "mid"]`` so a junior candidate doesn't
    get matched against "Staff Engineer" or "Director" roles. A user
    can override by setting this to include "senior" or "lead".

    All fields are optional. Empty values mean "no preference" — the
    route does not filter on them.
    """

    location_mode: str | None = Field(default="country", max_length=32)
    preferred_country_codes: list[str] = Field(
        default_factory=list, max_length=8
    )
    preferred_city: str | None = Field(default=None, max_length=160)
    preferred_lat: float | None = None
    preferred_lon: float | None = None
    preferred_radius_km: int | None = Field(default=None, ge=0, le=20000)
    preferred_regions: list[str] = Field(default_factory=list, max_length=8)
    target_seniority: list[str] = Field(
        default_factory=lambda: ["internship", "entry", "mid"],
        max_length=8,
    )


class JobRankInput(BaseModel):
    job_id: str
    title: str
    company: str
    location: str | None = None
    description: str = Field(max_length=4000)
    vector_similarity: float
    facts: JobFacts | None = None


class MatchNote(BaseModel):
    text: str = Field(max_length=MATCH_NOTE_MAX_CHARS)
    is_warning: bool = False


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
    match_notes: list[MatchNote] = Field(min_length=3, max_length=6)


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
        for note in score.match_notes:
            if not note.text.strip():
                raise ValueError("Match notes cannot be blank.")

        regular_notes = [note for note in score.match_notes if not note.is_warning]
        if len(regular_notes) != 3:
            raise ValueError(
                "Each job must include exactly three non-warning match notes."
            )

    return response
