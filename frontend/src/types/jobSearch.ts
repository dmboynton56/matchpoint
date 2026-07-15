import {
  formatExperienceLevel,
  formatJobType,
  formatWorkplaceType,
  type ExperienceLevel,
  type JobType,
  type WorkplaceType,
} from "@/types/job"

/**
 * Filter contract shared by the `/jobs` browse page UI, the chat-style
 * search assistant, and `searchJobs()` in `@/apis/jobs`. This is the shape
 * the backend `GET /jobs/search` endpoint should accept (see suggested
 * query param mapping in `@/apis/jobs`).
 */
export type DatePosted = "any" | "24h" | "3d" | "7d" | "14d" | "30d"

export const DATE_POSTED_OPTIONS: { value: DatePosted; label: string }[] = [
  { value: "any", label: "Any time" },
  { value: "24h", label: "Past 24 hours" },
  { value: "3d", label: "Past 3 days" },
  { value: "7d", label: "Past week" },
  { value: "14d", label: "Past 2 weeks" },
  { value: "30d", label: "Past month" },
]

export type JobsSortOption = "relevance" | "newest"

export const JOBS_SORT_OPTIONS: { value: JobsSortOption; label: string }[] = [
  { value: "relevance", label: "Relevance" },
  { value: "newest", label: "Newest" },
]

const EXPERIENCE_LEVELS: ExperienceLevel[] = [
  "internship",
  "entry",
  "mid",
  "senior",
  "lead",
  "executive",
]
export const EXPERIENCE_LEVEL_OPTIONS = EXPERIENCE_LEVELS.map((value) => ({
  value,
  label: formatExperienceLevel(value),
}))

const JOB_TYPES: JobType[] = [
  "full_time",
  "part_time",
  "contract",
  "internship",
  "temporary",
]
export const JOB_TYPE_OPTIONS = JOB_TYPES.map((value) => ({
  value,
  label: formatJobType(value),
}))

const WORKPLACE_TYPES: WorkplaceType[] = ["remote", "hybrid", "on_site"]
export const WORKPLACE_TYPE_OPTIONS = WORKPLACE_TYPES.map((value) => ({
  value,
  label: formatWorkplaceType(value),
}))

/** Small curated set of common tech-hub locations for the location filter. */
export const LOCATION_OPTIONS = [
  "Remote",
  "San Francisco",
  "New York",
  "Denver",
  "Austin",
  "Seattle",
  "Boston",
  "Chicago",
  "Los Angeles",
]

export const LOCATION_MULTI_SELECT_OPTIONS = LOCATION_OPTIONS.map((value) => ({
  value,
  label: value,
}))

export type JobSearchFilters = {
  /** Free-text keyword search (title, company, description). */
  keywords: string
  locations: string[]
  experienceLevels: ExperienceLevel[]
  jobTypes: JobType[]
  workplaceTypes: WorkplaceType[]
  payMin: number | null
  payMax: number | null
  datePosted: DatePosted
  sort: JobsSortOption
  page: number
  pageSize: number
}

export const DEFAULT_PAGE_SIZE = 10

export const DEFAULT_JOB_SEARCH_FILTERS: JobSearchFilters = {
  keywords: "",
  locations: [],
  experienceLevels: [],
  jobTypes: [],
  workplaceTypes: [],
  payMin: null,
  payMax: null,
  datePosted: "any",
  sort: "relevance",
  page: 1,
  pageSize: DEFAULT_PAGE_SIZE,
}

/** True when any filter differs from the default (keywords, page/pageSize/sort excluded). */
export function hasActiveFilters(filters: JobSearchFilters): boolean {
  return (
    filters.keywords.trim().length > 0 ||
    filters.locations.length > 0 ||
    filters.experienceLevels.length > 0 ||
    filters.jobTypes.length > 0 ||
    filters.workplaceTypes.length > 0 ||
    filters.payMin != null ||
    filters.payMax != null ||
    filters.datePosted !== "any"
  )
}

export function clearAllFilters(filters: JobSearchFilters): JobSearchFilters {
  return {
    ...DEFAULT_JOB_SEARCH_FILTERS,
    sort: filters.sort,
    pageSize: filters.pageSize,
  }
}
