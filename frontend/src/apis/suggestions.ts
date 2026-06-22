import type {
  CoachBullet,
  CoachRewriteResponse,
  CoachStartResponse,
  Suggestion,
} from "@/types/suggestions"

import { apiFetch } from "./client"

export interface ResumeSuggestionsResponse {
  id: string
  cache_key: string
  created_at: string
  suggestions: Suggestion[]
}

export interface ResumeSuggestionsRefreshResponse {
  cache_key: string
  count: number
  suggestions: Suggestion[]
  /** True when fewer than MIN_SUGGESTIONS survived grounding. */
  below_minimum: boolean
}

/** GET /suggestions/me — returns the latest cached row, or 404. */
export async function getMySuggestions(): Promise<ResumeSuggestionsResponse> {
  return apiFetch<ResumeSuggestionsResponse>("/suggestions/me")
}

/** POST /suggestions/refresh — always re-runs the LLM. */
export async function refreshSuggestions(): Promise<ResumeSuggestionsRefreshResponse> {
  return apiFetch<ResumeSuggestionsRefreshResponse>("/suggestions/refresh", {
    method: "POST",
  })
}

/**
 * POST /suggestions/coach/start — start a coach session.
 * Returns a session_id, the skill suggestions, and up to 4 weak
 * bullets with questions. The UI sends the session_id back with
 * each rewrite call.
 */
export async function startCoachSession(): Promise<CoachStartResponse> {
  return apiFetch<CoachStartResponse>("/suggestions/coach/start", {
    method: "POST",
  })
}

/**
 * POST /suggestions/coach/rewrite — request a rewrite for one
 * bullet. The user has filled in the bullet's questions; this
 * sends their answers back and returns the rewritten bullet.
 */
export async function rewriteBullet(input: {
  session_id: string
  bullet_id: string
  answers: Record<string, string>
}): Promise<CoachRewriteResponse> {
  return apiFetch<CoachRewriteResponse>("/suggestions/coach/rewrite", {
    method: "POST",
    body: JSON.stringify(input),
  })
}

/** Re-export the bullet type so consumers don't need to dig into the types module. */
export type { CoachBullet }