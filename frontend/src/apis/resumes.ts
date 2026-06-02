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
    match_notes: Array<{
      text: string
      is_warning: boolean
    }> | null
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

export interface ResumeDetailsResponse {
  has_resume: boolean
  file_name: string | null
  uploaded_at: string | null
  signed_url: string | null
  expires_in: number
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

export async function getResumeDetails(): Promise<ResumeDetailsResponse> {
  return apiFetch<ResumeDetailsResponse>("/resumes/me")
}

// Delete the current user's resume
export async function deleteResume(): Promise<ResumeDeleteResponse> {
  return apiFetch<ResumeDeleteResponse>("/resumes/me", {
    method: "DELETE",
  })
}
