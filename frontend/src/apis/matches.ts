import { apiFetch } from "./client"

export interface Job {
  id: string
  title: string
  company: string
  location: string | null
  apply_url: string | null
  description: string | null
  posted_at: string | null
}

export interface Match {
  match_id: string
  match_score: number
  match_notes: Array<{
    text: string
    is_warning: boolean
  }> | null
  match_highlights: string[] | null
  match_concerns: string[] | null
  interview_likelihood: number | null
  skills_fit: number | null
  experience_fit: number | null
  seniority_fit: number | null
  location_fit: number | null
  pay_fit: number | null
  role_fit: number | null
  preference_fit: number | null
  location_reason: string | null
  location_evidence: string | null
  pay_reason: string | null
  pay_evidence: string | null
  role_reason: string | null
  role_evidence: string | null
  job_facts: Record<string, unknown> | null
  is_viewed: boolean
  is_favorited: boolean
  matched_at: string
  job: Job
}

export interface MatchesResponse {
  count: number
  matches: Match[]
}

export interface MatchUpdateResponse {
  success: boolean
  match_id: string
  is_viewed?: boolean
  is_favorited?: boolean
  deleted?: boolean
}

export async function getMyMatches(filters?: {
  viewed?: boolean
  favorited?: boolean
}): Promise<MatchesResponse> {
  const params = new URLSearchParams()
  if (filters?.viewed !== undefined)
    params.set("viewed", String(filters.viewed))
  if (filters?.favorited !== undefined)
    params.set("favorited", String(filters.favorited))

  const qs = params.size ? `?${params}` : ""
  return apiFetch<MatchesResponse>(`/matches/me${qs}`)
}

// Mark a match as viewed
export async function markMatchViewed(
  matchId: string
): Promise<MatchUpdateResponse> {
  return apiFetch<MatchUpdateResponse>(`/matches/${matchId}/viewed`, {
    method: "PATCH",
  })
}

// Toggle the favorited state of a match
export async function toggleMatchFavorite(
  matchId: string
): Promise<MatchUpdateResponse> {
  return apiFetch<MatchUpdateResponse>(`/matches/${matchId}/favorite`, {
    method: "PATCH",
  })
}

// Delete a match from the user's list
export async function deleteMatch(
  matchId: string
): Promise<MatchUpdateResponse> {
  return apiFetch<MatchUpdateResponse>(`/matches/${matchId}`, {
    method: "DELETE",
  })
}
