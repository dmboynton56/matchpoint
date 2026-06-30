export type SuggestionKind = "SKILL"

export interface Citation {
  job_id: string
  quote: string
  /**
   * Job-context enrichment, populated by the backend from the user's
   * top matches. Optional in the schema, so older rows or jobs
   * without an apply_url will surface as null/undefined.
   */
  job_title?: string | null
  job_company?: string | null
  apply_url?: string | null
}

export interface LearningLink {
  label: string
  url: string
}

export interface Suggestion {
  kind: SuggestionKind
  text: string
  evidence: Citation[]
  /** Optional. A well-known link to a course, cert, or docs page for the skill. */
  learning_link?: LearningLink | null
  /** Optional. 1-2 short sentences on why this matters in the user's top matches. */
  why_it_matters?: string | null
}

/**
 * Bullet-coach types — used by the conversational rewrite flow.
 * Backend returns these in /suggestions/coach/start and accepts
 * them back in /suggestions/coach/rewrite.
 */
export type CoachQuestionType = "TEXT"

export interface CoachQuestion {
  /** ASCII key used to send the answer back. */
  key: string
  /** User-facing question. Short enough to be a label. */
  label: string
  /** Optional helper text shown under the input. */
  hint?: string | null
  type: CoachQuestionType
}

export interface BulletLocation {
  /** Section name from the parsed resume (e.g. "Work Experience"). */
  section: string
  /** Best-effort entry title (e.g. "AI Engineering Apprentice | Flatiron School"). */
  entry_title?: string | null
  /** First ~200 chars of the entry's text. UI shows this for context. */
  entry_text_snippet?: string | null
}

export interface CoachBullet {
  /** Stable identifier the LLM picks (e.g. "b1"). */
  bullet_id: string
  /** Verbatim sentence from the resume. The user can Ctrl-F to find it. */
  original_text: string
  /** One-sentence explanation of why this bullet is weak. */
  weakness_reason: string
  /** Section/entry the LLM believes this bullet came from. */
  location: BulletLocation
  /** Job ID the citation quote came from. */
  citation_job_id: string
  /** Verbatim substring of the cited job's description. */
  citation_quote: string
  /** Optional job context, same as Citation. */
  citation_job_title?: string | null
  citation_job_company?: string | null
  citation_apply_url?: string | null
  /** 2-4 targeted questions. */
  questions: CoachQuestion[]
}

export interface CoachStartResponse {
  /** Session identifier the UI sends back to /coach/rewrite. */
  session_id: string
  /** Skills returned alongside the bullet-coach list. */
  skills: Suggestion[]
  /** Up to 4 weak bullets. */
  bullets: CoachBullet[]
}

export interface CoachRewriteCitation {
  job_id: string
  quote: string
  job_title?: string | null
  job_company?: string | null
  apply_url?: string | null
}

export interface CoachRewriteResponse {
  /** Echo of the bullet the rewrite was generated for. */
  bullet_id: string
  /** Verbatim original text, copied from the start response. */
  original_text: string
  /** The LLM's suggested rewrite, grounded in the user's answers. */
  rewritten_text: string
  /** Citation the rewrite draws on. Same shape as the start response. */
  citation: CoachRewriteCitation
  /** True when the rewrite passed the grounding validator. */
  grounded: boolean
  /** Empty when grounded is true; otherwise human-readable reasons. */
  grounding_failures: string[]
}