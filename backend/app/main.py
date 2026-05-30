import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd
from pathlib import Path
from app.routes.matches import router as matches_router
from app.routes.resumes import router as resumes_router
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

cors_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
if frontend_url := os.environ.get("FRONTEND_URL", "").strip().rstrip("/"):
    cors_origins.append(frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(matches_router)
app.include_router(resumes_router)

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
    required_fields = [
        "external_id",
        "company",
        "title",
        "location"
    ]
    job = df.iloc[0]

    print("ORIGINAL:")
    print(job["description"])

    print("\n\nCLEANED:")
    print(buildCleanedText(job))
    # for _, job in df.iterrows():
    #     missing = False
    #     for field in required_fields:
    #         if pd.isna(job.get(field)):
    #             missing = True
    #             break
    #     if missing:
    #         print(
    #             f"Skipping job: missing required fields"
    #         )
    #         continue
    #     cleanedPost = buildCleanedText(job)
    #     try:
    #         embedding = generateEmbedding(cleanedPost)
    #     except Exception as e:
    #         print(e)
    #         continue
        
    #     data = {
    #         "external_id": str(job["external_id"]),
    #         "company": str(job["company"]),
    #         "title": str(job["title"]),
    #         "description": str(cleanedPost),
    #         "location": str(job["location"]),
    #         "posted_at": job.get("posted_at"),
    #         "apply_url": job.get("apply_url"),
    #         "embedding": embedding
    #     }
    #     response = supabase.table("jobs").upsert(data, on_conflict = "external_id").execute()
        
    #     jobs.append(response.data)

    # return {
    #     "message": "Jobs inserted successfully",
    #     "data": jobs
    # }
