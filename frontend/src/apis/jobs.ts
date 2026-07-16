import { apiFetch } from "./client"
import type { JobBrowseListing } from "@/types/job"
import type { JobSearchFilters } from "@/types/jobSearch"
import { filtersToSearchParams } from "@/lib/jobSearchParams"

export type JobsSearchResponse = {
  jobs: JobBrowseListing[]
  total: number
  page: number
  pageSize: number
}

/**
 * Browse/search the full job catalog for the `/jobs` page.
 *
 * GET /jobs/search query params mirror `JobSearchFilters` / `filtersToSearchParams`.
 */
export async function searchJobs(
  filters: JobSearchFilters
): Promise<JobsSearchResponse> {
  const params = filtersToSearchParams(filters)
  const qs = params.toString()
  return apiFetch<JobsSearchResponse>(`/jobs/search${qs ? `?${qs}` : ""}`)
}
