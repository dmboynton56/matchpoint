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
        "message": "Backend running"
    }

@app.get("/first-job")
def get_first_job():
    csvPath = BASE_DIR / "job_board_data.csv"
    df = pd.read_csv(csvPath)

    first_job = df.iloc[0]
    cleanedPost = buildCleanedText(first_job)
    vector = generateEmbedding(cleanedPost)
    return {
        "title": first_job["title"],
        "company": first_job["company"],
        "vector_dimensions": len(vector),
        "sample_vector": vector[:5]
    }
