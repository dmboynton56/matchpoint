import { apiFetch, BASE_URL } from "./client";

export interface ResumeUploadResponse {
  message: string;
  is_authenticated: boolean;
  requires_signup: boolean;
  text_preview: string;
  jobs: Array<{
    id: string;
    title: string;
    company: string;
    location: string | null;
    apply_url: string | null;
    match_score: number;
  }>;
}

export interface ResumeDeleteResponse {
  success: boolean;
  message: string;
}

// Upload a resume to the db
export async function uploadResume(file: File): Promise<ResumeUploadResponse> {
  const form = new FormData();
  form.append("file", file);

  const res = await fetch(`${BASE_URL}/resumes/upload`, {
    method: "POST",
    body: form,
    credentials: "include",
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail ?? `Upload failed: ${res.status}`);
  }

  return res.json() as Promise<ResumeUploadResponse>;
}

// Delete the current user's resume
export async function deleteResume(): Promise<ResumeDeleteResponse> {
  return apiFetch<ResumeDeleteResponse>("/resumes/me", {
    method: "DELETE",
  });
}