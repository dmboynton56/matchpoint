from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from app.db.database import supabase
from app.routes.auth import get_current_user
import pypdf
import io

router = APIRouter()

@router.post("/resumes/upload")
async def upload_and_parse_resume(
    file: UploadFile = File(...), 
    current_user = Depends(get_current_user)
):
    # Validate file format
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    file_bytes = await file.read()
    user_id = current_user.id

    try:
        # Extract Plaintext from PDF (Text Extraction Service)
        pdf_reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        extracted_text = ""
        for page in pdf_reader.pages:
            extracted_text += page.extract_text() or ""
        
        if not extracted_text.strip():
            raise HTTPException(status_code=400, detail="Could not extract text from PDF.")

        # Store raw PDF binary in Supabase Storage Bucket
        storage_path = f"{user_id}/resume.pdf"
        
        # .upload() expects bytes, content_type tells browser how to render it
        supabase.storage.from_("resumes").upload(
            path=storage_path,
            file=file_bytes,
            file_options={"content-type": "application/pdf", "upsert": "true"}
        )

        # Save plaintext to database for OpenAI processing
        supabase.table("profiles").update({
            "resume_text": extracted_text,
            "updated_at": "now()"
        }).eq("id", user_id).execute()

        return {
            "message": "Resume uploaded and successfully parsed.",
            "text_preview": extracted_text[:200] + "..." # Return a snippet for UI verification
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Resume processing failed: {str(e)}")