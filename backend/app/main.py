from fastapi import FastAPI

from app.routes.resumes import router as resumes_router

app = FastAPI(title="Matchpoint API")

app.include_router(resumes_router)


@app.get("/")
def root():
    return {"message": "Backend running"}
