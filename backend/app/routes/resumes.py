import io

import pypdf
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.db.database import supabase
from app.routes.auth import get_optional_user, get_current_user
from app.schemas.ranking import JobRankInput, UserPreferences
from app.services.cleaning import resolve_job_location
from app.services.embedding import generateEmbedding
from app.services.job_facts import extract_job_facts
from app.services.ranking import compute_match_score, score_jobs_with_llm

router = APIRouter()

VECTOR_RETRIEVAL_LIMIT = 10
VISITOR_JOB_LIMIT = 3
AUTHENTICATED_JOB_LIMIT = 10


def _normalize_text_array(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


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
    except Exception:
        response = (
            supabase.table("profiles")
            .select("target_role")
            .eq("id", user_id)
            .maybe_single()
            .execute()
        )

    data = response.data or {}
    return UserPreferences(
        target_role=data.get("target_role"),
        preferred_locations=_normalize_text_array(data.get("preferred_locations")),
        preferred_work_modes=_normalize_text_array(data.get("preferred_work_modes")),
        minimum_base_salary=data.get("minimum_base_salary"),
        salary_currency=data.get("salary_currency") or "USD",
    )


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
    response = supabase.rpc(
        "match_jobs",
        {
            "query_embedding": query_embedding,
            "match_limit": limit,
        },
    ).execute()

    return response.data or []


def fetch_full_jobs(job_ids: list[str]) -> dict[str, dict]:
    if not job_ids:
        return {}

    response = (
        supabase.table("jobs")
        .select("id, title, company, location, apply_url, description")
        .in_("id", job_ids)
        .execute()
    )
    return {str(job["id"]): job for job in response.data or []}


def score_job_matches(
    extracted_text: str,
    query_embedding: list[float],
    *,
    return_limit: int,
    preferences: UserPreferences | None = None,
) -> list[dict]:
    vector_matches = fetch_vector_job_matches(
        query_embedding, limit=VECTOR_RETRIEVAL_LIMIT
    )
    job_ids = [str(job["id"]) for job in vector_matches]
    full_jobs_by_id = fetch_full_jobs(job_ids)

    score_inputs: list[JobRankInput] = []
    display_jobs_by_id: dict[str, dict] = {}
    for vector_match in vector_matches:
        job_id = str(vector_match["id"])
        full_job = full_jobs_by_id.get(job_id, {})
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
        display_jobs_by_id[job_id] = display_job
        score_inputs.append(
            JobRankInput(
                job_id=job_id,
                title=display_job["title"],
                company=display_job["company"],
                location=display_job["location"],
                description=display_job["description"][:4000],
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
        scored_jobs.append(
            {
                "id": job["id"],
                "title": job["title"],
                "company": job["company"],
                "location": job["location"],
                "apply_url": job["apply_url"],
                "match_score": compute_match_score(score),
                "match_highlights": score.match_highlights,
                "match_concerns": score.match_concerns or [],
                "interview_likelihood": score.interview_likelihood,
                "skills_fit": score.skills_fit,
                "experience_fit": score.experience_fit,
                "seniority_fit": score.seniority_fit,
                "location_fit": score.location_fit,
                "pay_fit": score.pay_fit,
                "role_fit": score.role_fit,
                "preference_fit": score.preference_fit,
                "location_reason": score.location_reason,
                "location_evidence": score.location_evidence,
                "pay_reason": score.pay_reason,
                "pay_evidence": score.pay_evidence,
                "role_reason": score.role_reason,
                "role_evidence": score.role_evidence,
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
    embedding = generateEmbedding(extracted_text)
    jobs = score_job_matches(
        extracted_text, embedding, return_limit=VISITOR_JOB_LIMIT
    )

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

    supabase.storage.from_("resumes").upload(
        path=storage_path,
        file=file_bytes,
        file_options={"content-type": "application/pdf", "upsert": "true"},
    )
    preferences = fetch_user_preferences(user_id)
    embedding = generateEmbedding(extracted_text)
    match_query_embedding = generateEmbedding(
        build_match_query_text(extracted_text, preferences)
    )
    supabase.table("profiles").update(
        {
            "resume_text": extracted_text,
            "resume_embedding": embedding,
        }
    ).eq("id", user_id).execute()

    jobs = score_job_matches(
        extracted_text,
        match_query_embedding,
        return_limit=AUTHENTICATED_JOB_LIMIT,
        preferences=preferences,
    )

    supabase.table("job_matches").delete().eq("user_id", user_id).execute()
    if jobs:
        supabase.table("job_matches").insert(
            [
                {
                    "user_id": user_id,
                    "job_id": job["id"],
                    "match_score": job["match_score"],
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
                }
                for job in jobs
            ]
        ).execute()

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
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Resume processing failed: {str(e)}"
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
            }
        ).eq("id", user_id).execute()

        supabase.table("job_matches").delete().eq("user_id", user_id).execute()

        return {"success": True, "message": "Resume and associated matches deleted."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to delete resume: {str(e)}"
        ) from e
