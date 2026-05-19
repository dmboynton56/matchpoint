import io

import pypdf
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.db.database import supabase
from app.routes.auth import get_optional_user

router = APIRouter()

VISITOR_JOB_LIMIT = 3
AUTHENTICATED_JOB_LIMIT = 20


def extract_text_from_pdf(file_bytes: bytes) -> str:
    pdf_reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    extracted_text = ""
    for page in pdf_reader.pages:
        extracted_text += page.extract_text() or ""

    if not extracted_text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from PDF.")

    return extracted_text


def fetch_job_matches(extracted_text: str, *, limit: int) -> list[dict]:
    # Placeholder until embedding-based matching is implemented.
    del extracted_text

    response = (
        supabase.table("jobs")
        .select("id, title, company, location, apply_url")
        .limit(limit)
        .execute()
    )

    jobs = response.data or []
    return [
        {
            "id": job["id"],
            "title": job["title"],
            "company": job["company"],
            "location": job.get("location"),
            "apply_url": job.get("apply_url"),
            "match_score": round(0.9 - (index * 0.05), 2),
        }
        for index, job in enumerate(jobs)
    ]


async def handle_visitor_upload(extracted_text: str) -> dict:
    jobs = fetch_job_matches(extracted_text, limit=VISITOR_JOB_LIMIT)

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

    supabase.table("profiles").update({
        "resume_text": extracted_text,
    }).eq("id", user_id).execute()

    jobs = fetch_job_matches(extracted_text, limit=AUTHENTICATED_JOB_LIMIT)

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
