import io
import logging
from time import perf_counter

from openai import APITimeoutError
import pypdf
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.db import turso
from app.db.database import supabase
from app.routes.auth import get_optional_user, get_current_user
from pydantic import BaseModel, Field
from app.schemas.ranking import (
    JobRankInput,
    LocationPreferences,
    UserPreferences,
)
from app.services.cleaning import resolve_job_location
from app.services.embedding import generateEmbedding
from app.services.geo import (
    geocode_job_location,
    location_compatibility,
)
from app.services.job_facts import extract_job_facts
from app.services.ranking import (
    SCORING_JOB_DESCRIPTION_CHAR_LIMIT,
    compute_match_score,
    score_jobs_with_llm,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Pipeline tuning.
#
# The LLM sees VECTOR_RETRIEVAL_LIMIT jobs and returns at most
# AUTHENTICATED_JOB_LIMIT. Going LLM-in > LLM-out gives the model room
# to choose the best 10 from a wider pool — better matches for users
# whose top vector candidates aren't all true winners.
#
# VECTOR_RETRIEVAL_OVERFETCH compensates for the geolocation hard
# filter. We ask vector search for (limit * overfetch) so the LLM
# still sees the full `limit` candidates even when the location filter
# drops some. With overfetch=2 and a 30% country-match rate, a US
# candidate gets ~6 surviving of 20 fetched — still well above the
# 10-job return limit, so the filter doesn't starve the LLM of input.
# With overfetch=2 and no filter (existing user with no prefs), we
# fetch 40 and trim to 20 by similarity ranking before the LLM call.
VECTOR_RETRIEVAL_LIMIT = 20
VECTOR_RETRIEVAL_OVERFETCH = 2
# The country-filtered fetch needs a bigger pool than the global fetch:
# its job is to guarantee representation from the user's actual country
# even when national/global volume (SF, NYC, remote-US postings) would
# otherwise crowd it out on raw similarity. A same-sized limit as the
# global search means "top 40 in-country" can still miss real, relevant
# local jobs whose similarity is merely moderate rather than top-tier.
LOCAL_VECTOR_RETRIEVAL_OVERFETCH = 5
VISITOR_JOB_LIMIT = 3
AUTHENTICATED_JOB_LIMIT = 10
RESUME_SIGNED_URL_EXPIRES_SECONDS = 300


def _normalize_text_array(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _response_data(response, *, stage: str):
    if response is None:
        logger.warning("%s returned no response object", stage)
        return None
    return getattr(response, "data", None)


def _is_missing_preference_columns_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(
        phrase in message
        for phrase in ("does not exist", "column", "schema", "unknown field")
    )


def fetch_user_preferences(user_id: str) -> UserPreferences:
    try:
        response = (
            supabase.table("profiles")
            .select(
                "target_role, preferred_locations, preferred_work_modes, "
                "minimum_base_salary, salary_currency"
            )
            .eq("id", user_id)
            .maybe_single()
            .execute()
        )
    except Exception as exc:
        if not _is_missing_preference_columns_error(exc):
            logger.exception("fetch_user_preferences failed")
            raise
        response = (
            supabase.table("profiles")
            .select("target_role")
            .eq("id", user_id)
            .maybe_single()
            .execute()
        )

    data = _response_data(response, stage="fetch_user_preferences") or {}
    return UserPreferences(
        target_role=data.get("target_role"),
        preferred_locations=_normalize_text_array(data.get("preferred_locations")),
        preferred_work_modes=_normalize_text_array(data.get("preferred_work_modes")),
        minimum_base_salary=data.get("minimum_base_salary"),
        salary_currency=data.get("salary_currency") or "USD",
    )


def fetch_user_resume_text(user_id: str) -> str:
    response = (
        supabase.table("profiles")
        .select("resume_text")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    data = _response_data(response, stage="fetch_user_resume_text") or {}
    resume_text = data.get("resume_text")
    if not isinstance(resume_text, str) or not resume_text.strip():
        raise HTTPException(
            status_code=400,
            detail="Upload a resume before recalculating matches.",
        )
    return resume_text


def build_match_query_text(resume_text: str, preferences: UserPreferences | None) -> str:
    if not preferences:
        return resume_text

    preference_lines = []
    if preferences.target_role:
        preference_lines.append(f"Target role: {preferences.target_role}")
    if preferences.preferred_locations:
        preference_lines.append(
            f"Preferred locations: {', '.join(preferences.preferred_locations)}"
        )
    if preferences.preferred_work_modes:
        preference_lines.append(
            f"Preferred work modes: {', '.join(preferences.preferred_work_modes)}"
        )
    amount = preferences.minimum_base_salary
    currency = (preferences.salary_currency or "").strip()
    if amount is not None or currency:
        if amount is not None and currency:
            preference_lines.append(f"Minimum base salary: {currency} {amount:,}")
        elif amount is not None:
            preference_lines.append(f"Minimum base salary: {amount:,}")
        else:
            preference_lines.append(f"Minimum base salary currency: {currency}")

    if not preference_lines:
        return resume_text

    return "\n".join(preference_lines) + "\n\nResume:\n" + resume_text


def extract_text_from_pdf(file_bytes: bytes) -> str:
    pdf_reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    extracted_text = ""
    for page in pdf_reader.pages:
        extracted_text += page.extract_text() or ""

    if not extracted_text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from PDF.")

    return extracted_text


def fetch_vector_job_matches(query_embedding: list[float], *, limit: int) -> list[dict]:
    # Jobs live on Turso now; similarity is computed in Python over the
    # JSON-array TEXT embedding column (no pgvector in libSQL).
    return turso.vector_search(query_embedding, limit=limit)


def fetch_vector_job_matches_filtered(
    query_embedding: list[float], *, limit: int, country_codes: set[str]
) -> list[dict]:
    # Same as fetch_vector_job_matches, but restricted to jobs whose
    # geo_country_code is in `country_codes` before computing cosine
    # similarity. Guarantees the user's preferred country gets a fair
    # shot at retrieval instead of being diluted by the full corpus.
    return turso.vector_search_filtered(
        query_embedding, limit=limit, country_codes=country_codes
    )

def fetch_full_jobs(job_ids: list[str]) -> dict[str, dict]:
    if not job_ids:
        return {}
    # Pull the full job records (with description) from Turso.
    return turso.fetch_full_jobs(job_ids)


def _job_match_payload(job: dict) -> dict:
    return {
        "job_id": job["id"],
        "match_score": job["match_score"],
        "match_notes": job["match_notes"],
        "match_highlights": job["match_highlights"],
        "match_concerns": job["match_concerns"],
        "interview_likelihood": job["interview_likelihood"],
        "skills_fit": job["skills_fit"],
        "experience_fit": job["experience_fit"],
        "seniority_fit": job["seniority_fit"],
        "location_fit": job["location_fit"],
        "pay_fit": job["pay_fit"],
        "role_fit": job["role_fit"],
        "preference_fit": job["preference_fit"],
        "location_reason": job["location_reason"],
        "location_evidence": job["location_evidence"],
        "pay_reason": job["pay_reason"],
        "pay_evidence": job["pay_evidence"],
        "role_reason": job["role_reason"],
        "role_evidence": job["role_evidence"],
        "job_facts": job["job_facts"],
        "is_viewed": False,
        "is_favorited": False,
        "is_applied": False,
    }


def _persist_job_matches(user_id: str, jobs: list[dict]) -> None:
    payload = [_job_match_payload(job) for job in jobs]
    try:
        supabase.rpc(
            "replace_job_matches",
            {"p_user_id": user_id, "p_matches": payload},
        ).execute()
    except Exception:
        logger.exception("Failed to persist job matches for user %s", user_id)
        raise HTTPException(
            status_code=500,
            detail="Internal server error persisting job matches",
        )


def _log_upload_stage(stage: str, started_at: float) -> float:
    finished_at = perf_counter()
    logger.info(
        "Resume upload stage '%s' finished in %.2fs",
        stage,
        finished_at - started_at,
    )
    return finished_at


def recalculate_job_matches_for_user(
    user_id: str,
    resume_text: str | None = None,
    *,
    stage_prefix: str = "recalculate",
) -> list[dict]:
    started_at = perf_counter()
    if resume_text is None:
        resume_text = fetch_user_resume_text(user_id)
        started_at = _log_upload_stage(f"{stage_prefix}_fetch_resume", started_at)

    preferences = fetch_user_preferences(user_id)
    started_at = _log_upload_stage(f"{stage_prefix}_fetch_preferences", started_at)
    # Structured location prefs are an additional fetch; soft-fails on
    # missing columns (returns empty LocationPreferences → no filter).
    # This is the no-regression guarantee for users who haven't set
    # structured location preferences yet.
    location_preferences = fetch_user_location_preferences(user_id)
    started_at = _log_upload_stage(
        f"{stage_prefix}_fetch_location_preferences", started_at
    )
    match_query_embedding = generateEmbedding(
        build_match_query_text(resume_text, preferences)
    )
    started_at = _log_upload_stage(f"{stage_prefix}_match_query_embedding", started_at)

    jobs = score_job_matches(
        resume_text,
        match_query_embedding,
        return_limit=AUTHENTICATED_JOB_LIMIT,
        preferences=preferences,
        location_preferences=location_preferences,
    )
    started_at = _log_upload_stage(f"{stage_prefix}_job_scoring", started_at)

    _persist_job_matches(user_id, jobs)
    _log_upload_stage(f"{stage_prefix}_persist_job_matches", started_at)
    return jobs


def _location_compatibility_note(
    score: float,
    job_geo: dict,
    profile_location: dict | None,
) -> str:
    """Generate a short human-readable note explaining the score.

    Used as ``location_compatibility_note`` in JobFacts so the LLM and
    the front-end both get a readable string instead of having to
    interpret a bare number.
    """
    if not profile_location:
        return ""
    job_country = job_geo.get("geo_country_code")
    preferred = profile_location.get("preferred_country_codes") or []
    if score == 0.0:
        return (
            f"Filtered: job country {job_country!r} is not in the user's "
            f"preferred set ({preferred!r})."
        )
    if score == 0.5:
        return "Job location could not be geocoded; relying on LLM scoring."
    if score == 0.7:
        return "Country matched but job coordinates are missing."
    if score >= 1.0 and profile_location.get("location_mode") == "city_radius":
        return "Within the user's preferred radius."
    if score >= 1.0:
        return "Country matches user preference."
    return f"Partial match (score={score:.2f})."


def score_job_matches(
    extracted_text: str,
    query_embedding: list[float],
    *,
    return_limit: int,
    vector_retrieval_limit: int = VECTOR_RETRIEVAL_LIMIT,
    vector_retrieval_overfetch: int = VECTOR_RETRIEVAL_OVERFETCH,
    preferences: UserPreferences | None = None,
    location_preferences: LocationPreferences | None = None,
) -> list[dict]:
    # Fetch more from the vector index than the LLM batch size so the
    # geolocation hard filter can drop candidates without starving the
    # LLM of input. With overfetch=2 and a 50% filter rate, the LLM
    # still sees the full desired batch. With overfetch=2 and no
    # filter (the no-regression path for existing users), we trim
    # the extra fetch by similarity below.
    vector_match_fetch_limit = max(
        vector_retrieval_limit,
        vector_retrieval_limit * vector_retrieval_overfetch,
    )
    vector_matches = fetch_vector_job_matches(
        query_embedding, limit=vector_match_fetch_limit
    )

    # Retrieval is pure text similarity across the whole corpus, with
    # no awareness of geography. That means a user's preferred country
    # only ever acts as a re-ranking signal on whichever jobs happened
    # to win on similarity — a real location can get starved out of
    # the candidate pool entirely before location ever gets a vote.
    # Run a second, geo-scoped retrieval and merge it in so the user's
    # preferred country is guaranteed representation.
    normalized_country_codes = set()
    if location_preferences is not None:
        normalized_country_codes = {
            c.upper() for c in (location_preferences.preferred_country_codes or [])
        }
    if normalized_country_codes:
            local_fetch_limit = max(
                vector_match_fetch_limit,
                vector_retrieval_limit * LOCAL_VECTOR_RETRIEVAL_OVERFETCH,
            )
            local_matches = fetch_vector_job_matches_filtered(
                query_embedding,
                limit=local_fetch_limit,
                country_codes=normalized_country_codes,
            )
            seen_ids = {str(m["id"]) for m in vector_matches}
            for m in local_matches:
                if str(m["id"]) not in seen_ids:
                    vector_matches.append(m)
                    seen_ids.add(str(m["id"]))

    job_ids = [str(job["id"]) for job in vector_matches]
    full_jobs_by_id = fetch_full_jobs(job_ids)

    # If the user has no structured location preferences, treat this
    # as "no filter" so location_compatibility always returns 1.0 for
    # every job. The contract test in test_location_compatibility.py
    # locks this in.
    profile_location = (
        location_preferences.model_dump()
        if location_preferences is not None
        else None
    )
    # Seniority filter: drop jobs whose experience_level is outside
    # the user's target_seniority set. Default is
    # ["internship", "entry", "mid"] so a junior candidate doesn't
    # get matched against "Staff Engineer" or "Director" roles.
    # Jobs with experience_level IS NULL pass through (don't punish
    # what we don't know).
    target_seniority = (
        location_preferences.target_seniority
        if location_preferences is not None
        else []
    )
    target_seniority_set = {s.lower() for s in (target_seniority or [])}

    # First pass: collect every survivor of the location AND
    # seniority filter, in vector-search order (most-similar first).
    # We rank by a combined similarity + location score below; this
    # is just the candidate pool.
    # Tuple of (vector_match, full_job, job_geo, location_score).
    survivors: list[tuple[dict, dict, dict, float]] = []
    for vector_match in vector_matches:
        job_id = str(vector_match["id"])
        full_job = full_jobs_by_id.get(job_id, {})
        job_geo = {
            "geo_country_code": full_job.get("geo_country_code"),
            "geo_city": full_job.get("geo_city"),
            "geo_region": full_job.get("geo_region"),
            "geo_lat": full_job.get("geo_lat"),
            "geo_lon": full_job.get("geo_lon"),
            "geo_source": full_job.get("geo_source"),
        }
        location_score = location_compatibility(job_geo, profile_location)
        if location_score == 0.0:
            # Hard filter — wrong country. Drop entirely.
            continue
        # Seniority filter. Drop senior/lead/exec roles for users
        # who haven't opted in. The experience_level column comes
        # from job_metadata.derive_browse_metadata and is the same
        # source the browse UI uses, so this is consistent with
        # the rest of the product.
        experience_level = (full_job.get("experience_level") or "").lower() or None
        if (
            experience_level is not None
            and target_seniority_set
            and experience_level not in target_seniority_set
        ):
            continue
        survivors.append((vector_match, full_job, job_geo, location_score))

    # Second pass: rank by a combined score. The weights reflect the
    # current intent: similarity is still the dominant signal (the
    # user wants jobs that match their skills), but a strong local
    # job can outrank a more-similar distant one. Tunable via
    # LOCATION_RANK_WEIGHT below — raise to bias more toward local,
    # lower to bias more toward skills.
    LOCATION_RANK_WEIGHT = 0.30
    SIMILARITY_RANK_WEIGHT = 1.0 - LOCATION_RANK_WEIGHT
    for vector_match, full_job, _job_geo, _location_score in survivors:
        similarity = float(vector_match.get("similarity") or 0.0)
        full_job["_rank_score"] = (
            SIMILARITY_RANK_WEIGHT * similarity
            + LOCATION_RANK_WEIGHT * _location_score
        )
    survivors.sort(
        key=lambda t: t[1]["_rank_score"],
        reverse=True,
    )
    # Take the top N by combined rank. Beyond that, the LLM has
    # diminishing returns and the user gets diminishing variety.
    survivors = survivors[:vector_retrieval_limit]

    score_inputs: list[JobRankInput] = []
    display_jobs_by_id: dict[str, dict] = {}
    for vector_match, full_job, job_geo, location_score in survivors:
        job_id = str(vector_match["id"])
        raw_location = full_job.get("location") or vector_match.get("location") or ""
        resolved_location = resolve_job_location(
            raw_location,
            full_job.get("description") or "",
        )

        display_job = {
            "id": job_id,
            "title": full_job.get("title") or vector_match["title"],
            "company": full_job.get("company") or vector_match["company"],
            "location": resolved_location,
            "apply_url": full_job.get("apply_url") or vector_match.get("apply_url"),
            "description": full_job.get("description") or "",
        }
        facts = extract_job_facts(
            title=display_job["title"],
            location=display_job["location"],
            description=display_job["description"],
        )
        # Forward the score to the LLM. The teammate-owned prompt in
        # ranking.py will see this in the structured job_facts dict
        # and can use it as ground truth for its own location_fit
        # dimension instead of guessing from the raw location string.
        facts.location_compatibility_score = location_score
        facts.location_compatibility_note = (
            _location_compatibility_note(location_score, job_geo, profile_location)
        )
        display_jobs_by_id[job_id] = display_job
        score_inputs.append(
            JobRankInput(
                job_id=job_id,
                title=display_job["title"],
                company=display_job["company"],
                location=display_job["location"],
                description=display_job["description"][
                    :SCORING_JOB_DESCRIPTION_CHAR_LIMIT
                ],
                vector_similarity=float(vector_match.get("similarity") or 0),
                facts=facts,
            )
        )

    scoring_response = score_jobs_with_llm(
        extracted_text,
        score_inputs,
        preferences=preferences,
    )
    scored_jobs = []
    for score in scoring_response.scores:
        job = display_jobs_by_id[score.job_id]
        facts = next(
            (
                score_input.facts
                for score_input in score_inputs
                if score_input.job_id == score.job_id
            ),
            None,
        )
        # Override the LLM's location_fit with the calibrated value from
        # the route's location_compatibility() call. The LLM has no
        # visibility into the user's anchor city (only the country
        # preference and the resume text), so its location_fit values
        # are inconsistent: a Portland user sees NYC at 0.68 instead
        # of the distance-curve's 0.62, and Bellevue at 0.50 instead
        # of 0.93. The structured score is calibrated against the
        # user's actual preferences and is the source of truth.
        # The LLM still scores the other dimensions and writes the
        # notes — only the numeric location_fit is replaced.
        if facts is not None and facts.location_compatibility_score is not None:
            score.location_fit = facts.location_compatibility_score
        scored_jobs.append(
            {
                "id": job["id"],
                "title": job["title"],
                "company": job["company"],
                "location": job["location"],
                "apply_url": job["apply_url"],
                "match_score": compute_match_score(score),
                "match_notes": [
                    note.model_dump() for note in score.match_notes
                ],
                "match_highlights": [
                    note.text for note in score.match_notes if not note.is_warning
                ],
                "match_concerns": [
                    note.text for note in score.match_notes if note.is_warning
                ],
                "interview_likelihood": score.interview_likelihood,
                "skills_fit": score.skills_fit,
                "experience_fit": score.experience_fit,
                "seniority_fit": score.seniority_fit,
                "location_fit": score.location_fit,
                "pay_fit": score.pay_fit,
                "role_fit": score.role_fit,
                "preference_fit": score.preference_fit,
                "location_reason": None,
                "location_evidence": None,
                "pay_reason": None,
                "pay_evidence": None,
                "role_reason": None,
                "role_evidence": None,
                "job_facts": facts.model_dump() if facts else None,
            }
        )

    scored_jobs = sorted(
        scored_jobs,
        key=lambda job: job["match_score"],
        reverse=True,
    )
    for index, job in enumerate(scored_jobs, start=1):
        job["rank"] = index

    return scored_jobs[:return_limit]


async def handle_visitor_upload(extracted_text: str) -> dict:
    started_at = perf_counter()
    embedding = generateEmbedding(extracted_text)
    started_at = _log_upload_stage("visitor_embedding", started_at)
    jobs = score_job_matches(
        extracted_text,
        embedding,
        return_limit=VISITOR_JOB_LIMIT,
        vector_retrieval_limit=VISITOR_JOB_LIMIT,
    )
    _log_upload_stage("visitor_scoring", started_at)

    return {
        "message": "Resume parsed. Sign up to interact with your job matches.",
        "is_authenticated": False,
        "requires_signup": True,
        "text_preview": extracted_text[:200] + "...",
        "jobs": jobs,
    }


async def handle_authenticated_upload(
    current_user, file_bytes: bytes, extracted_text: str
) -> dict:
    user_id = current_user.id
    storage_path = f"{user_id}/resume.pdf"

    started_at = perf_counter()
    supabase.storage.from_("resumes").upload(
        path=storage_path,
        file=file_bytes,
        file_options={"content-type": "application/pdf", "upsert": "true"},
    )
    started_at = _log_upload_stage("storage_upload", started_at)
    embedding = generateEmbedding(extracted_text)
    started_at = _log_upload_stage("resume_embedding", started_at)
    # Upsert rather than update so the profile row is CREATED for
    # brand-new accounts. PostgREST's .update().eq() silently affects
    # 0 rows when the row doesn't exist yet, which means resume_text
    # and resume_embedding never land for the user even though the
    # upload reports success and the matches get persisted (matching
    # uses extracted_text directly, not the profile). The downstream
    # symptom is /suggestions/refresh failing on the next request
    # because _fetch_resume_text returns null. Same upsert pattern
    # the frontend uses in updateProfilePreferences / updateProfileTargetRole.
    # Note: supabase-py takes on_conflict as a keyword string
    # (snake_case), not a dict like the JS client.
    supabase.table("profiles").upsert(
        {
            "id": user_id,
            "resume_text": extracted_text,
            "resume_embedding": embedding,
        },
        on_conflict="id",
    ).execute()
    started_at = _log_upload_stage("profile_update", started_at)

    jobs = recalculate_job_matches_for_user(
        user_id,
        extracted_text,
        stage_prefix="upload",
    )

    return {
        "message": "Resume uploaded and successfully parsed.",
        "is_authenticated": True,
        "requires_signup": False,
        "text_preview": extracted_text[:200] + "...",
        "jobs": jobs,
    }


@router.post("/resumes/upload")
async def upload_and_parse_resume(
    file: UploadFile = File(...),
    current_user=Depends(get_optional_user),
):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    file_bytes = await file.read()

    try:
        extracted_text = extract_text_from_pdf(file_bytes)

        if current_user:
            return await handle_authenticated_upload(
                current_user, file_bytes, extracted_text
            )

        return await handle_visitor_upload(extracted_text)

    except HTTPException:
        raise
    except APITimeoutError as e:
        logger.exception("Resume processing timed out while calling OpenAI")
        raise HTTPException(
            status_code=504,
            detail=(
                "Resume processing timed out while calling OpenAI. "
                "Try again, or increase OPENAI_SCORING_TIMEOUT_SECONDS / reduce "
                "SCORING_*_CHAR_LIMIT values if this keeps happening locally."
            ),
        ) from e
    except Exception as e:
        logger.exception("Resume processing failed")
        raise HTTPException(
            status_code=500,
            detail="Internal server error processing resume",
        ) from e


@router.get("/resumes/me")
async def get_resume(
    current_user=Depends(get_current_user),
):
    user_id = current_user.id
    storage_path = f"{user_id}/resume.pdf"

    try:
        bucket = supabase.storage.from_("resumes")
        files = bucket.list(
            user_id,
            {"limit": 10, "offset": 0, "sortBy": {"column": "name", "order": "asc"}},
        )
        resume_file = next(
            (file for file in files if file.get("name") == "resume.pdf"),
            None,
        )

        if not resume_file:
            return {
                "has_resume": False,
                "file_name": None,
                "uploaded_at": None,
                "signed_url": None,
                "expires_in": RESUME_SIGNED_URL_EXPIRES_SECONDS,
            }

        signed_url_response = bucket.create_signed_url(
            storage_path, RESUME_SIGNED_URL_EXPIRES_SECONDS
        )
        signed_url = signed_url_response.get("signedUrl") or signed_url_response.get(
            "signedURL"
        )

        return {
            "has_resume": True,
            "file_name": resume_file.get("name"),
            "uploaded_at": resume_file.get("updated_at")
            or resume_file.get("created_at")
            or resume_file.get("last_accessed_at"),
            "signed_url": signed_url,
            "expires_in": RESUME_SIGNED_URL_EXPIRES_SECONDS,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to fetch resume metadata")
        raise HTTPException(
            status_code=500,
            detail="Internal server error fetching resume",
        ) from e


@router.delete("/resumes/me")
async def delete_resume(
    current_user=Depends(get_current_user),
):
    user_id = current_user.id
    storage_path = f"{user_id}/resume.pdf"

    try:
        supabase.storage.from_("resumes").remove([storage_path])

        supabase.table("profiles").update(
            {
                "resume_text": None,
                "resume_embedding": None,
            }
        ).eq("id", user_id).execute()

        supabase.table("job_matches").delete().eq("user_id", user_id).execute()

        return {"success": True, "message": "Resume and associated matches deleted."}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to delete resume")
        raise HTTPException(
            status_code=500,
            detail="Internal server error deleting resume",
        ) from e


# -----------------------------------------------------------------------------
# Structured location preferences
# -----------------------------------------------------------------------------
# Mirrors the `fetch_user_preferences` defensive pattern: if the new
# columns don't exist yet (pre-migration), we silently return an empty
# LocationPreferences so existing users see no regression. The matching
# route treats an empty location profile as "no filter" — see
# `location_compatibility`'s contract test for the no-regression cases.

_LOCATION_PREFERENCE_COLUMNS = (
    "location_mode, preferred_country_codes, preferred_city, "
    "preferred_lat, preferred_lon, preferred_radius_km, preferred_regions, "
    "target_seniority"
)


def _normalize_country_codes(value) -> list[str]:
    """Normalize country codes: uppercase, strip, dedupe, alpha-2 only.

    Anything that doesn't look like a 2-letter ISO code is dropped. This
    is a defensive filter — the front-end should be sending valid codes
    already, but a bad input from an old client should never crash the
    matching route.
    """
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, str):
            continue
        code = raw.strip().upper()
        if len(code) != 2 or not code.isalpha():
            continue
        if code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def fetch_user_location_preferences(user_id: str) -> LocationPreferences:
    """Return the user's structured location preferences.

    Soft-fails on missing columns (returns empty preferences) so this
    can be called from the matching route before the migration lands.
    An empty LocationPreferences has location_mode='country' and
    no country codes — `location_compatibility` returns 1.0 for every
    job in that state, so existing users see zero regression.
    """
    try:
        response = (
            supabase.table("profiles")
            .select(_LOCATION_PREFERENCE_COLUMNS)
            .eq("id", user_id)
            .maybe_single()
            .execute()
        )
    except Exception as exc:
        if not _is_missing_preference_columns_error(exc):
            logger.exception("fetch_user_location_preferences failed")
            raise
        return LocationPreferences()
    data = _response_data(response, stage="fetch_user_location_preferences") or {}
    return LocationPreferences(
        location_mode=data.get("location_mode") or "country",
        preferred_country_codes=_normalize_country_codes(
            data.get("preferred_country_codes")
        ),
        preferred_city=data.get("preferred_city"),
        preferred_lat=data.get("preferred_lat"),
        preferred_lon=data.get("preferred_lon"),
        preferred_radius_km=data.get("preferred_radius_km"),
        preferred_regions=_normalize_text_array(
            data.get("preferred_regions")
        ),
        target_seniority=_normalize_text_array(
            data.get("target_seniority")
        ),
    )


class LocationPreferencesUpdate(BaseModel):
    """Body of PATCH /profile/location-preferences.

    All fields optional so the client can update one without re-sending
    the others. ``None`` means "don't change"; an empty list / empty
    string means "explicitly clear." The route's semantics distinguish
    these two cases (None is preserved, falsy values clear the column).
    """

    location_mode: str | None = Field(default=None, max_length=32)
    preferred_country_codes: list[str] | None = None
    preferred_city: str | None = Field(default=None, max_length=160)
    preferred_lat: float | None = None
    preferred_lon: float | None = None
    preferred_radius_km: int | None = Field(default=None, ge=0, le=20000)
    preferred_regions: list[str] | None = None
    target_seniority: list[str] | None = None


@router.patch("/profile/location-preferences")
async def update_location_preferences(
    payload: LocationPreferencesUpdate,
    current_user=Depends(get_current_user),
):
    """Update the user's structured location preferences.

    Behavior:
        - Field present and non-None: written to the profile.
        - Field None: not written (preserved as-is).
        - preferred_city provided: server-side geocoded via the same
          Photon pipeline the jobs use, so the resulting lat/lon
          matches the format the read path expects.

    Returns the merged LocationPreferences so the client can confirm
    what landed. Matches are not recalculated here; the client
    triggers that separately.
    """
    user_id = current_user.id
    update: dict = {}

    if payload.location_mode is not None:
        if payload.location_mode not in {"country", "city_radius", "any"}:
            raise HTTPException(
                status_code=400,
                detail=(
                    "location_mode must be one of 'country', 'city_radius', "
                    "'any'."
                ),
            )
        update["location_mode"] = payload.location_mode

    if payload.preferred_country_codes is not None:
        update["preferred_country_codes"] = _normalize_country_codes(
            payload.preferred_country_codes
        )

    if payload.preferred_city is not None:
        city = payload.preferred_city.strip()
        update["preferred_city"] = city or None
        if city:
            # Server-side geocode the city so the stored lat/lon match
            # the format the read path uses for jobs. If Photon can't
            # resolve it we still save the city string and leave
            # lat/lon null — the user can edit and retry.
            geo = geocode_job_location(city)
            if geo.get("geo_lat") is not None and geo.get("geo_lon") is not None:
                update["preferred_lat"] = geo["geo_lat"]
                update["preferred_lon"] = geo["geo_lon"]
            else:
                update["preferred_lat"] = None
                update["preferred_lon"] = None

    if payload.preferred_lat is not None:
        update["preferred_lat"] = payload.preferred_lat
    if payload.preferred_lon is not None:
        update["preferred_lon"] = payload.preferred_lon
    if payload.preferred_radius_km is not None:
        update["preferred_radius_km"] = payload.preferred_radius_km

    if payload.preferred_regions is not None:
        update["preferred_regions"] = _normalize_text_array(
            payload.preferred_regions
        )

    if payload.target_seniority is not None:
        # Validate the values to avoid garbage in the column. The
        # candidate set comes from job_metadata.EXPERIENCE_LEVEL_PATTERNS;
        # we hard-code the allowed values here rather than import the
        # constant to keep the schema layer decoupled from the
        # inference layer.
        allowed = {
            "internship", "entry", "mid", "senior", "lead", "executive",
        }
        cleaned = [
            v.strip().lower() for v in payload.target_seniority
            if isinstance(v, str) and v.strip().lower() in allowed
        ]
        # If the user submitted only invalid values, fall back to the
        # safe default rather than wiping the column.
        if cleaned:
            update["target_seniority"] = cleaned

    if not update:
        return {"updated": False, "preferences": fetch_user_location_preferences(user_id).model_dump()}

    try:
        # Upsert keyed on the user id so a user who somehow has no
        # profile row yet still gets one created. Same defensive
        # pattern as the resume upload flow.
        result = supabase.table("profiles").upsert(
            {"id": user_id, **update}, on_conflict="id"
        ).execute()
        logger.debug(
            "[location-prefs] upsert OK fields=%s", sorted(update.keys())
        )
    except Exception as exc:
        logger.warning("[location-prefs] upsert failed user=%s exc=%s: %s",
                       user_id, type(exc).__name__, exc)
        if _is_missing_preference_columns_error(exc):
            raise HTTPException(
                status_code=503,
                detail=(
                    "Location preferences columns are not yet provisioned "
                    "on the profiles table. Apply the migration first."
                ),
            ) from exc
        logger.exception("update_location_preferences failed")
        raise HTTPException(
            status_code=500, detail="Failed to update location preferences."
        ) from exc

    merged = fetch_user_location_preferences(user_id)
    return {
        "updated": True,
        "preferences": merged.model_dump(),
    }


@router.get("/profile/location-preferences")
async def get_location_preferences(
    current_user=Depends(get_current_user),
):
    """Read the user's current location preferences."""
    user_id = current_user.id
    prefs = fetch_user_location_preferences(user_id)
    return {"preferences": prefs.model_dump()}


class GeocodeCityRequest(BaseModel):
    city: str = Field(..., min_length=1, max_length=160)


@router.post("/profile/geocode-city")
async def geocode_city_for_profile(
    payload: GeocodeCityRequest,
    current_user=Depends(get_current_user),
):
    """Server-side geocode a city string the user typed in the
    profile form. Returns the resolved lat/lon so the frontend
    can show "Detected: Portland, OR" before the user saves.

    The actual write to profiles happens in PATCH
    /profile/location-preferences. This endpoint is just the
    preview step.
    """
    geo = geocode_job_location(payload.city)
    if geo.get("geo_source") == "unresolved" or not geo.get("geo_lat"):
        raise HTTPException(
            status_code=404,
            detail=(
                f"Could not geocode {payload.city!r}. "
                "Try a more specific name (city, region) or "
                "an alternative spelling."
            ),
        )
    return {
        "city": payload.city,
        "country_code": geo.get("geo_country_code"),
        "region": geo.get("geo_region"),
        "lat": geo.get("geo_lat"),
        "lon": geo.get("geo_lon"),
    }

