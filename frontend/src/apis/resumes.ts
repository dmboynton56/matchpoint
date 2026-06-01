import { apiFetch, BASE_URL, getAuthHeaders } from "./client"
export interface ResumeUploadResponse {
  message: string
  is_authenticated: boolean
  requires_signup: boolean
  text_preview: string
  jobs: Array<{
    id: string
    title: string
    company: string
    location: string | null
    apply_url: string | null
    rank: number
    match_score: number
    interview_likelihood: number
    skills_fit: number
    experience_fit: number
    seniority_fit: number
    location_fit: number
    pay_fit: number
    role_fit: number
    preference_fit: number
    location_reason: string | null
    location_evidence: string | null
    pay_reason: string | null
    pay_evidence: string | null
    role_reason: string | null
    role_evidence: string | null
    match_highlights: string[]
    match_concerns: string[]
    job_facts: Record<string, unknown> | null
  }>
}

export interface ResumeDeleteResponse {
  success: boolean
  message: string
}

// Upload a resume to the db
export async function uploadResume(file: File): Promise<ResumeUploadResponse> {
  const form = new FormData()
  form.append("file", file)
  const res = await fetch(`${BASE_URL}/resumes/upload`, {
    method: "POST",
    headers: await getAuthHeaders({ body: form }),
    body: form,
    credentials: "include",
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body?.detail ?? `Upload failed: ${res.status}`)
  }

  return res.json() as Promise<ResumeUploadResponse>
}

// Delete the current user's resume
export async function deleteResume(): Promise<ResumeDeleteResponse> {
  return apiFetch<ResumeDeleteResponse>("/resumes/me", {
    method: "DELETE",
  })
}
