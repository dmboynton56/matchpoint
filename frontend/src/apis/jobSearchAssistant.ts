import { apiFetch } from "./client"
import { parseJobQueryLocally } from "@/lib/parseJobQuery"
import type { JobSearchFilters } from "@/types/jobSearch"

/**
 * Extracts filters from a free-text query via POST /jobs/search/parse,
 * falling back to the local regex parser if the backend call fails.
 */
export async function extractFiltersFromMessage(
  message: string
): Promise<Partial<JobSearchFilters>> {
  try {
    return await apiFetch<Partial<JobSearchFilters>>("/jobs/search/parse", {
      method: "POST",
      body: JSON.stringify({ message }),
    })
  } catch {
    return parseJobQueryLocally(message)
  }
}
