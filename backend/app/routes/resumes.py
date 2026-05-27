import io

import pypdf
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.db.database import supabase
from app.routes.auth import get_optional_user, get_current_user
from app.schemas.ranking import JobRankInput
from app.services.embedding import generateEmbedding
from app.services.ranking import rank_jobs_with_llm

router = APIRouter()

VISITOR_JOB_LIMIT = 3
AUTHENTICATED_JOB_LIMIT = 10


def extract_text_from_pdf(file_bytes: bytes) -> str:
    pdf_reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    extracted_text = ""
    for page in pdf_reader.pages:
        extracted_text += page.extract_text() or ""

    if not extracted_text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from PDF.")

    return extracted_text


def fetch_vector_job_matches(query_embedding:list[float], *, limit: int) -> list[dict]:
    
    response = supabase.rpc("match_jobs", {
        "query_embedding": query_embedding,
        "match_limit": limit,
    }).execute()

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


def rank_job_matches(extracted_text: str, query_embedding: list[float], *, limit: int) -> list[dict]:
    vector_matches = fetch_vector_job_matches(query_embedding, limit=limit)
    job_ids = [str(job["id"]) for job in vector_matches]
    full_jobs_by_id = fetch_full_jobs(job_ids)

    rank_inputs: list[JobRankInput] = []
    display_jobs_by_id: dict[str, dict] = {}
    for vector_match in vector_matches:
        job_id = str(vector_match["id"])
        full_job = full_jobs_by_id.get(job_id, {})
        display_job = {
            "id": job_id,
            "title": full_job.get("title") or vector_match["title"],
            "company": full_job.get("company") or vector_match["company"],
            "location": full_job.get("location") or vector_match.get("location"),
            "apply_url": full_job.get("apply_url") or vector_match.get("apply_url"),
            "description": full_job.get("description") or "",
        }
        display_jobs_by_id[job_id] = display_job
        rank_inputs.append(
            JobRankInput(
                job_id=job_id,
                title=display_job["title"],
                company=display_job["company"],
                location=display_job["location"],
                description=display_job["description"][:4000],
                vector_similarity=float(vector_match.get("similarity") or 0),
            )
        )

    ranking_response = rank_jobs_with_llm(extracted_text, rank_inputs)
    ranked_jobs = []
    for ranking in ranking_response.rankings:
        job = display_jobs_by_id[ranking.job_id]
        ranked_jobs.append({
            "id": job["id"],
            "title": job["title"],
            "company": job["company"],
            "location": job["location"],
            "apply_url": job["apply_url"],
            "rank": ranking.rank,
            "match_score": ranking.match_score,
            "match_highlights": ranking.match_highlights,
        })

    return ranked_jobs


async def handle_visitor_upload(extracted_text: str) -> dict:
    jobs = rank_job_matches(extracted_text, limit=VISITOR_JOB_LIMIT)

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
    embedding = generateEmbedding(extracted_text)
    supabase.table("profiles").update({
        "resume_text": extracted_text,
        "resume_embedding": embedding
    }).eq("id", user_id).execute()

    jobs = rank_job_matches(extracted_text, embedding, limit=AUTHENTICATED_JOB_LIMIT)

    supabase.table("job_matches").delete().eq("user_id", user_id).execute()
    if jobs:
        supabase.table("job_matches").insert([
            {
                "user_id": user_id,
                "job_id": job["id"],
                "match_score": job["match_score"],
                "match_highlights": job["match_highlights"],
                "is_viewed": False,
                "is_favorited": False,
            }
            for job in jobs
        ]).execute()

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

        supabase.table("profiles").update({
            "resume_text": None,
        }).eq("id", user_id).execute()

        supabase.table("job_matches").delete().eq("user_id", user_id).execute()

        return {"success": True, "message": "Resume and associated matches deleted."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete resume: {str(e)}") from e
