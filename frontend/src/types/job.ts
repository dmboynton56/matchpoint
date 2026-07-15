/**
 * A single job in match results from POST /resumes/upload (and future match APIs).
 * Field names mirror the FastAPI/Supabase response (snake_case).
 *
 * Match flags (`is_viewed`, `is_favorited`, `is_applied`) come from the matches API.
 */
export type MatchNote = {
  text: string
  is_warning: boolean
}

/** Employment type for a job listing (browse/search results). */
export type JobType =
  | "full_time"
  | "part_time"
  | "contract"
  | "internship"
  | "temporary"

/** Seniority level for a job listing (browse/search results). */
export type ExperienceLevel =
  | "internship"
  | "entry"
  | "mid"
  | "senior"
  | "lead"
  | "executive"

/** Where the work happens for a job listing (browse/search results). */
export type WorkplaceType = "remote" | "hybrid" | "on_site"

export type JobMatch = {
  id: string
  /** `job_matches.id` when loaded from the matches API. */
  match_id?: string
  is_favorited?: boolean
  is_applied?: boolean
  title: string
  company: string
  location: string | null
  apply_url: string | null
  rank?: number
  /** 0–1 similarity score from matching; null when not yet computed. */
  match_score: number | null
  interview_likelihood?: number | null
  skills_fit?: number | null
  experience_fit?: number | null
  seniority_fit?: number | null
  location_fit?: number | null
  pay_fit?: number | null
  role_fit?: number | null
  preference_fit?: number | null
  location_reason?: string | null
  location_evidence?: string | null
  pay_reason?: string | null
  pay_evidence?: string | null
  role_reason?: string | null
  role_evidence?: string | null
  match_notes?: MatchNote[] | null
  /** Short “why this matched” lines; optional until backend generates them. */
  match_highlights?: string[] | null
  match_concerns?: string[] | null
  job_facts?: Record<string, unknown> | null
  /**
   * Browse/search listing metadata below — not populated by the matches API
   * today. Optional + nullable so `JobListingCard` keeps working for both
   * personalized matches and the `/jobs` browse results once the backend
   * `GET /jobs/search` endpoint starts returning these fields.
   */
  job_type?: JobType | null
  experience_level?: ExperienceLevel | null
  workplace_type?: WorkplaceType | null
  pay_min?: number | null
  pay_max?: number | null
  pay_currency?: string | null
  posted_at?: string | null
}

/** UI-only extras for landing previews — not returned by the API. */
export type JobListing = JobMatch & {
  tags?: string[]
}

/**
 * Job row from Turso / `GET /jobs/search` — catalog fields only, no match
 * metadata. Mirrors `fetch_full_jobs()` in backend/app/db/turso.py.
 */
export type JobBrowseListing = {
  id: string
  title: string
  company: string
  location: string | null
  apply_url: string | null
  /** Cached short summary for browse cards; full description omitted from list API. */
  summary?: string | null
  description?: string | null
  posted_at: string | null
  job_type?: JobType | null
  experience_level?: ExperienceLevel | null
  workplace_type?: WorkplaceType | null
  pay_min?: number | null
  pay_max?: number | null
  pay_currency?: string | null
}

export function hasBrowseApplyUrl(
  job: JobBrowseListing
): job is JobBrowseListing & { apply_url: string } {
  return typeof job.apply_url === "string" && job.apply_url.length > 0
}

export type MatchScoreTier = "excellent" | "good" | "fair" | "low"

export function getMatchScoreTier(score: number): MatchScoreTier {
  if (score >= 0.9) return "excellent"
  if (score >= 0.75) return "good"
  if (score >= 0.6) return "fair"
  return "low"
}

const MATCH_SCORE_BADGE_CLASSES: Record<MatchScoreTier, string> = {
  excellent:
    "border-emerald-500/35 bg-emerald-500/12 text-emerald-700 dark:text-emerald-400",
  good: "border-primary/30 bg-primary/10 text-primary",
  fair: "border-amber-500/35 bg-amber-500/12 text-amber-800 dark:text-amber-400",
  low: "border-orange-500/30 bg-orange-500/10 text-orange-800 dark:text-orange-400",
}

const MATCH_SCORE_ACCENT_CLASSES: Record<MatchScoreTier, string> = {
  excellent: "border-l-emerald-500",
  good: "border-l-primary",
  fair: "border-l-amber-500",
  low: "border-l-orange-500/80",
}

export function matchScoreBadgeClass(tier: MatchScoreTier): string {
  return MATCH_SCORE_BADGE_CLASSES[tier]
}

export function matchScoreAccentClass(tier: MatchScoreTier): string {
  return MATCH_SCORE_ACCENT_CLASSES[tier]
}

export function formatMatchScore(score: number): string {
  const percent = Math.round(score * 100)
  return `${percent}% match`
}

const JOB_TYPE_LABELS: Record<JobType, string> = {
  full_time: "Full-time",
  part_time: "Part-time",
  contract: "Contract",
  internship: "Internship",
  temporary: "Temporary",
}

const EXPERIENCE_LEVEL_LABELS: Record<ExperienceLevel, string> = {
  internship: "Internship",
  entry: "Entry level",
  mid: "Mid level",
  senior: "Senior",
  lead: "Lead",
  executive: "Executive",
}

const WORKPLACE_TYPE_LABELS: Record<WorkplaceType, string> = {
  remote: "Remote",
  hybrid: "Hybrid",
  on_site: "On-site",
}

export function formatJobType(value: JobType): string {
  return JOB_TYPE_LABELS[value]
}

export function formatExperienceLevel(value: ExperienceLevel): string {
  return EXPERIENCE_LEVEL_LABELS[value]
}

export function formatWorkplaceType(value: WorkplaceType): string {
  return WORKPLACE_TYPE_LABELS[value]
}

/** e.g. "$110k – $140k", "$110k+", "Up to $140k", or null when both bounds are missing. */
export function formatPayRange(
  min: number | null | undefined,
  max: number | null | undefined,
  currency: string | null | undefined = "USD"
): string | null {
  if (min == null && max == null) return null

  const symbol = currency === "USD" || !currency ? "$" : `${currency} `
  const formatAmount = (value: number) =>
    value >= 1000 ? `${symbol}${Math.round(value / 1000)}k` : `${symbol}${value}`

  if (min != null && max != null) {
    return min === max
      ? formatAmount(min)
      : `${formatAmount(min)} – ${formatAmount(max)}`
  }
  if (min != null) return `${formatAmount(min)}+`
  return `Up to ${formatAmount(max!)}`
}

/** e.g. "Posted 3 days ago", "Posted today". Returns null when unparseable. */
export function formatPostedAt(postedAt: string | null | undefined): string | null {
  if (!postedAt) return null
  const postedDate = new Date(postedAt)
  if (Number.isNaN(postedDate.getTime())) return null

  const diffMs = Date.now() - postedDate.getTime()
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

  if (diffDays <= 0) return "Posted today"
  if (diffDays === 1) return "Posted 1 day ago"
  if (diffDays < 30) return `Posted ${diffDays} days ago`
  const diffMonths = Math.floor(diffDays / 30)
  if (diffMonths < 12) return `Posted ${diffMonths} month${diffMonths === 1 ? "" : "s"} ago`
  const diffYears = Math.floor(diffMonths / 12)
  return `Posted ${diffYears} year${diffYears === 1 ? "" : "s"} ago`
}

export function hasApplyUrl(
  job: JobMatch
): job is JobMatch & { apply_url: string } {
  return typeof job.apply_url === "string" && job.apply_url.length > 0
}

export function getMatchHighlights(job: JobMatch): string[] {
  return job.match_highlights?.filter((line) => line.trim().length > 0) ?? []
}

export function getMatchConcerns(job: JobMatch): string[] {
  return job.match_concerns?.filter((line) => line.trim().length > 0) ?? []
}

function normalizeMatchNotes(job: JobMatch): MatchNote[] {
  const notes =
    job.match_notes
      ?.filter((note) => note.text.trim().length > 0)
      .map((note) => ({
        text: note.text.trim(),
        is_warning: Boolean(note.is_warning),
      })) ?? []

  if (notes.length > 0) return notes

  return [
    ...getMatchHighlights(job).map((text) => ({
      text,
      is_warning: false,
    })),
    ...getMatchConcerns(job).map((text) => ({
      text,
      is_warning: true,
    })),
  ]
}

export function splitMatchNotes(job: JobMatch): {
  highlights: MatchNote[]
  warnings: MatchNote[]
} {
  const notes = normalizeMatchNotes(job)
  const highlights = notes.filter((note) => !note.is_warning).slice(0, 3)
  const warnings = notes.filter((note) => note.is_warning)

  return { highlights, warnings }
}

/** @deprecated Use splitMatchNotes instead */
export function getMatchNotes(job: JobMatch): MatchNote[] {
  const { highlights, warnings } = splitMatchNotes(job)
  return [...highlights, ...warnings]
}

/** Response body from POST /resumes/upload (Phil's resume route). */
export type ResumeUploadResponse = {
  message: string
  is_authenticated: boolean
  requires_signup: boolean
  text_preview: string
  jobs: JobMatch[]
}
