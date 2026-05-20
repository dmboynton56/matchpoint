from fastapi import FastAPI

from app.routes.resumes import router as resumes_router
from app.routes.matches import router as matches_router

app = FastAPI(title="Matchpoint API")

app.include_router(resumes_router)
app.include_router(matches_router)

@app.get("/")
def root():
    return {"message": "Backend running"}
