import { supabase } from "@/auth/supabaseAuth"

export const BASE_URL = import.meta.env.VITE_API_URL ?? ""

export async function getAuthHeaders(init?: RequestInit): Promise<Headers> {
  const headers = new Headers(init?.headers)
  const {
    data: { session },
  } = await supabase.auth.getSession()

  if (session?.access_token) {
    headers.set("Authorization", `Bearer ${session.access_token}`)
  }

  if (!headers.has("Content-Type") && !(init?.body instanceof FormData)) {
    headers.set("Content-Type", "application/json")
  }

  return headers
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: await getAuthHeaders(init),
    credentials: "include",
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body?.detail ?? `Request failed: ${res.status}`)
  }

  return res.json() as Promise<T>
}
