from pydantic import BaseModel, Field


class JobRankInput(BaseModel):
    job_id: str
    title: str
    company: str
    location: str | None = None
    description: str = Field(max_length=4000)
    vector_similarity: float


class JobRanking(BaseModel):
    job_id: str
    rank: int = Field(ge=1)
    match_score: float = Field(ge=0, le=1)
    match_highlights: list[str] = Field(min_length=2, max_length=3)


class RankingResponse(BaseModel):
    rankings: list[JobRanking]


def validate_rankings(
    response: RankingResponse, input_jobs: list[JobRankInput]
) -> RankingResponse:
    expected_ids = {job.job_id for job in input_jobs}
    actual_ids = {ranking.job_id for ranking in response.rankings}
    if actual_ids != expected_ids:
        missing = sorted(expected_ids - actual_ids)
        extra = sorted(actual_ids - expected_ids)
        raise ValueError(
            f"Ranking IDs must match input jobs. Missing: {missing}. Extra: {extra}."
        )

    expected_ranks = list(range(1, len(input_jobs) + 1))
    rankings_by_rank = sorted(response.rankings, key=lambda ranking: ranking.rank)
    actual_ranks = [ranking.rank for ranking in rankings_by_rank]
    if actual_ranks != expected_ranks:
        raise ValueError(
            f"Ranks must be unique and cover 1-{len(input_jobs)}. Got: {actual_ranks}."
        )

    for previous, current in zip(rankings_by_rank, rankings_by_rank[1:]):
        if previous.match_score <= current.match_score:
            raise ValueError("Scores must strictly decrease by rank.")

    for ranking in rankings_by_rank:
        for highlight in ranking.match_highlights:
            if len(highlight) > 120:
                raise ValueError("Match highlights must be 120 characters or fewer.")

    return RankingResponse(rankings=rankings_by_rank)
