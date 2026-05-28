import { apiFetch, BASE_URL } from "./client";
import { supabase } from "../auth/supabaseAuth";

const RESUMES_BUCKET = "resumes";
const RESUME_FILENAME = "resume.pdf";

export function getResumeStoragePath(userId: string): string {
  return `${userId}/${RESUME_FILENAME}`;
}
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
    rank: number;
    match_score: number;
    match_highlights: string[];
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
  const {
    data: { session },
  } = await supabase.auth.getSession()
  const res = await fetch(`${BASE_URL}/resumes/upload`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${session?.access_token}`,
    },
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

export async function resumeExists(userId: string): Promise<boolean> {
  const { data, error } = await supabase.storage
    .from(RESUMES_BUCKET)
    .list(userId, { limit: 1, search: RESUME_FILENAME });

  if (error) {
    return false;
  }

  return (data ?? []).some((file) => file.name === RESUME_FILENAME);
}

export async function getResumeSignedUrl(
  userId: string,
  expiresInSeconds = 60
): Promise<string> {
  const path = getResumeStoragePath(userId);
  const { data, error } = await supabase.storage
    .from(RESUMES_BUCKET)
    .createSignedUrl(path, expiresInSeconds);

  if (error || !data?.signedUrl) {
    throw new Error(error?.message ?? "Could not generate resume URL.");
  }

  return data.signedUrl;
}
