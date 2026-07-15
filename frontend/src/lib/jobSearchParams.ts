import {
  DATE_POSTED_OPTIONS,
  DEFAULT_JOB_SEARCH_FILTERS,
  EXPERIENCE_LEVEL_OPTIONS,
  JOBS_SORT_OPTIONS,
  JOB_TYPE_OPTIONS,
  WORKPLACE_TYPE_OPTIONS,
  type DatePosted,
  type JobSearchFilters,
  type JobsSortOption,
} from "@/types/jobSearch"
import type { ExperienceLevel, JobType, WorkplaceType } from "@/types/job"

/**
 * Serializes/parses `JobSearchFilters` to/from the `/jobs` URL query string,
 * so search state is shareable and back/forward navigation works — e.g.
 * `/jobs?q=ml&location=Denver,San+Francisco&level=entry&posted=7d&page=2`.
 */

function parseEnumList<T extends string>(
  raw: string | null,
  validValues: readonly T[]
): T[] {
  if (!raw) return []
  const validSet = new Set<string>(validValues)
  return raw
    .split(",")
    .map((value) => value.trim())
    .filter((value) => validSet.has(value)) as T[]
}

function parseEnum<T extends string>(
  raw: string | null,
  validValues: readonly T[],
  fallback: T
): T {
  if (raw && (validValues as readonly string[]).includes(raw)) return raw as T
  return fallback
}

function parseNumber(raw: string | null): number | null {
  if (!raw) return null
  const parsed = Number(raw)
  return Number.isFinite(parsed) ? parsed : null
}

const EXPERIENCE_LEVEL_VALUES = EXPERIENCE_LEVEL_OPTIONS.map((o) => o.value)
const JOB_TYPE_VALUES = JOB_TYPE_OPTIONS.map((o) => o.value)
const WORKPLACE_TYPE_VALUES = WORKPLACE_TYPE_OPTIONS.map((o) => o.value)
const DATE_POSTED_VALUES = DATE_POSTED_OPTIONS.map((o) => o.value)
const SORT_VALUES = JOBS_SORT_OPTIONS.map((o) => o.value)

export function parseFiltersFromSearchParams(
  params: URLSearchParams
): JobSearchFilters {
  const page = Math.max(1, Number(params.get("page")) || 1)
  const pageSize = Number(params.get("page_size")) || DEFAULT_JOB_SEARCH_FILTERS.pageSize

  return {
    keywords: params.get("q") ?? "",
    locations: params.get("location")?.split(",").filter(Boolean) ?? [],
    experienceLevels: parseEnumList<ExperienceLevel>(
      params.get("level"),
      EXPERIENCE_LEVEL_VALUES
    ),
    jobTypes: parseEnumList<JobType>(params.get("type"), JOB_TYPE_VALUES),
    workplaceTypes: parseEnumList<WorkplaceType>(
      params.get("workplace"),
      WORKPLACE_TYPE_VALUES
    ),
    payMin: parseNumber(params.get("pay_min")),
    payMax: parseNumber(params.get("pay_max")),
    datePosted: parseEnum<DatePosted>(
      params.get("posted"),
      DATE_POSTED_VALUES,
      "any"
    ),
    sort: parseEnum<JobsSortOption>(params.get("sort"), SORT_VALUES, "relevance"),
    page,
    pageSize,
  }
}

export function filtersToSearchParams(filters: JobSearchFilters): URLSearchParams {
  const params = new URLSearchParams()

  if (filters.keywords.trim()) params.set("q", filters.keywords.trim())
  if (filters.locations.length > 0) params.set("location", filters.locations.join(","))
  if (filters.experienceLevels.length > 0)
    params.set("level", filters.experienceLevels.join(","))
  if (filters.jobTypes.length > 0) params.set("type", filters.jobTypes.join(","))
  if (filters.workplaceTypes.length > 0)
    params.set("workplace", filters.workplaceTypes.join(","))
  if (filters.payMin != null) params.set("pay_min", String(filters.payMin))
  if (filters.payMax != null) params.set("pay_max", String(filters.payMax))
  if (filters.datePosted !== "any") params.set("posted", filters.datePosted)
  if (filters.sort !== "relevance") params.set("sort", filters.sort)
  if (filters.page > 1) params.set("page", String(filters.page))
  if (filters.pageSize !== DEFAULT_JOB_SEARCH_FILTERS.pageSize)
    params.set("page_size", String(filters.pageSize))

  return params
}
