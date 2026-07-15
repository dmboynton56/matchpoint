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
 *
 * Qualitative-coach v2: every bullet is classified as STRONG or WEAK.
 * STRONG bullets have no questions and no rewrite. WEAK bullets come
 * with one question per missing qualitative category. The user answers
 * the questions (or skips a category), the backend rewrites the bullet
 * grounded in the original + their answers + the cited job.
 */

/**
 * Six qualitative dimensions a strong resume bullet should cover.
 * The LLM picks which categories are missing from each bullet and
 * the user answers one question per missing category.
 */
export type CoachCategory =
  | "SPECIFICITY"
  | "SCOPE"
  | "OWNERSHIP"
  | "REPLACEMENT"
  | "CAUSE_EFFECT"
  | "ARTIFACT"

/**
 * Whether the bullet needs work (WEAK) or is already strong (STRONG).
 * Drives UI affordance and whether /coach/rewrite is even callable
 * for this bullet.
 */
export type CoachBulletVerdict = "STRONG" | "WEAK"

export interface CoachQuestion {
  /**
   * ASCII key used to send the answer back. Optional in the
   * schema -- the validator derives it from the category when
   * missing.
   */
  key?: string | null
  /**
   * Which qualitative dimension this question probes. Required.
   * The validator rejects duplicate categories within a bullet.
   */
  category: CoachCategory
  /** User-facing question. Short enough to be a label. */
  label: string
  /** Optional helper text shown under the input. */
  hint?: string | null
  type: "TEXT"
}

export interface BulletLocation {
  /** Section name from the parsed resume (e.g. "Work Experience"). */
  section: string
  /** Best-effort entry title (e.g. "AI Engineering Apprentice | Flatiron School"). */
  entry_title?: string | null
  /** First ~200 chars of the entry's text. UI shows this for context. */
  entry_text_snippet?: string | null
}

/**
 * Per-bullet payload from /coach/start. WEAK bullets carry one
 * question per missing category; STRONG bullets have empty
 * questions + a strength_reason.
 */
export interface CoachBullet {
  /** Stable identifier the LLM picks (e.g. "b1"). */
  bullet_id: string
  /** STRONG = no questions, WEAK = one question per missing category. */
  verdict: CoachBulletVerdict
  /** Verbatim sentence from the resume. The user can Ctrl-F to find it. */
  original_text: string
  /** Required when verdict is WEAK; ignored when STRONG. */
  weakness_reason?: string | null
  /** Required when verdict is STRONG; ignored when WEAK. */
  strength_reason?: string | null
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
  /** Empty for STRONG bullets; one per missing category for WEAK. */
  questions: CoachQuestion[]
}

export interface CoachStartResponse {
  /** Session identifier the UI sends back to /coach/rewrite. */
  session_id: string
  /** Skills returned alongside the bullet-coach list. */
  skills: Suggestion[]
  /** Up to 5 bullets -- mix of STRONG and WEAK. */
  bullets: CoachBullet[]
}

/**
 * Response from /coach/rewrite. The backend v2 returns flat
 * citation_* fields (not a nested citation object) and does NOT
 * include a `grounded` field -- the rewrite is already validated
 * by the time it gets here.
 */
export interface CoachRewriteResponse {
  /** Echo of the bullet the rewrite was generated for. */
  bullet_id: string
  /** Verbatim original text, copied from the start response. */
  original_text: string
  /** The LLM's suggested rewrite, grounded in the user's answers. */
  rewritten_text: string
  /** Flat citation fields (not a nested object). */
  citation_job_id: string
  citation_quote: string
  citation_job_title?: string | null
  citation_job_company?: string | null
  citation_apply_url?: string | null
}