import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes.matches import router as matches_router
from app.routes.resumes import router as resumes_router
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


@app.get("/")
def root():
    return {
        "message": "Backend Started"
    }
