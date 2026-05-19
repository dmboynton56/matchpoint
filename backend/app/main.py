from fastapi import FastAPI
from pydantic import BaseModel
import pandas as pd
from pathlib import Path
from app.services.cleaning import (
    buildCleanedText
)
from app.services.embedding import (
    generateEmbedding
)
from app.db.database import (
    supabase
)
app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent
class JobRequest(BaseModel):
    company: str
    title: str
    description: str
    location: str
@app.get("/")
def root():
    return {
        "message": "Backend Started"
    }

@app.get("/jobs")
def insert_jobs_into_database():
    csvPath = BASE_DIR / "job_board_data_100.csv"
    df = pd.read_csv(csvPath)
    jobs = []
    for _, job in df.iterrows():
        cleanedPost = buildCleanedText(job)
        embedding = generateEmbedding(cleanedPost)
        data = {
            "external_id": str(job["external_id"]),
            "company": str(job["company"]),
            "title": str(job["title"]),
            "description": str(cleanedPost),
            "location": str(job["location"]),
            "posted_at": job["posted_at"],
            "apply_url": job["apply_url"],
            "embedding": embedding
        }
        response = supabase.table("jobs").upsert(data, on_conflict = "external_id").execute()
        
        jobs.append(response.data)

    return {
        "message": "Jobs inserted successfully",
        "data": jobs
    }