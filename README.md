# MatchPoint

MatchPoint is an AI-powered job search app that helps you find roles aligned with your resume and preferences. Upload a PDF resume, get ranked job matches with fit signals and highlights, manage your profile preferences, and track applications as you apply.

Built during our apprenticeship in [Flatiron School's Accelerated AI Engineering Immersive Work-Integrated Program](https://flatironschool.com/courses/work-integrated-programs/).

## Live deployments


| Service  | URL                                                                                          |
| -------- | -------------------------------------------------------------------------------------------- |
| Frontend | [https://matchpoint-web-gamma.vercel.app/jobs](https://matchpoint-web-gamma.vercel.app/jobs) |
| Backend  | [https://matchpoint-lake.vercel.app/](https://matchpoint-lake.vercel.app/)                   |


## Team

- [Drew Boynton](https://www.linkedin.com/in/drewboynton/)
- [Mason Kling](https://www.linkedin.com/in/mason-kling/)
- [Jason Chen](https://www.linkedin.com/in/jason-chen-ucmerced/)
- [Phillip Cantu](https://www.linkedin.com/in/phillipcantu/)

## Tech stack

- **Frontend:** React, TypeScript, Vite, Tailwind CSS, shadcn/ui, Supabase Auth
- **Backend:** FastAPI, Python, OpenAI (embeddings & match scoring), Supabase (Postgres, storage, RLS)
- **Infrastructure:** Vercel (frontend & backend), Supabase, GitHub Actions (daily job pipeline)

## Features

- Resume upload and parsing for personalized job matching
- Ranked job listings with match scores, fit signals, and match notes
- User profiles with target role, locations, work mode, and salary preferences
- Auth via email/password and Google (Supabase)
- Post-apply follow-up flow (track applied, favorites, hide jobs — UI in progress)

## Local development

### Prerequisites

- Node.js with npm
- Python 3
- Docker (for local Supabase)

### Setup

1. Clone the repo and `cd` into it.

**Backend**

1. `cd backend`, create a virtual environment, and `pip install -r requirements.txt`.
2. From the project root, ensure Docker is running, then `npx supabase start`.
3. Copy `backend/.env.example` to `backend/.env` and fill in values.
4. Run the API:
  ```bash
   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
  ```

**Frontend**

1. In a second terminal, `cd frontend`, `npm install`, copy `frontend/.env.example` to `frontend/.env` and fill in values.
2. Start the dev server:
  ```bash
   npm run dev
  ```

The app runs at [http://localhost:5173](http://localhost:5173) by default.