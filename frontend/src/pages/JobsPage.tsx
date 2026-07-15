import { useEffect, useMemo, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { XIcon } from "lucide-react"

import { searchJobs } from "@/apis/jobs"
import { getProfilePreferences } from "@/auth/supabaseAuth"
import { ActiveFilterChips } from "@/components/jobs/search/ActiveFilterChips"
import { JobFilterBar } from "@/components/jobs/search/JobFilterBar"
import { JobSearchAssistant } from "@/components/jobs/search/JobSearchAssistant"
import { JobsPagination } from "@/components/jobs/search/JobsPagination"
import { JobsResultsList } from "@/components/jobs/search/JobsResultsList"
import { JobsSortSelect } from "@/components/jobs/search/JobsSortSelect"
import { AppShell } from "@/components/layout/AppShell"
import { Badge } from "@/components/ui/badge"
import { useAuth } from "@/hooks/useAuth"
import {
  filtersToSearchParams,
  parseFiltersFromSearchParams,
} from "@/lib/jobSearchParams"
import type { JobBrowseListing } from "@/types/job"
import { DEFAULT_JOB_SEARCH_FILTERS, type JobSearchFilters } from "@/types/jobSearch"

const SEARCH_DEBOUNCE_MS = 300

export function JobsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = useMemo(
    () => parseFiltersFromSearchParams(searchParams),
    [searchParams]
  )

  const [jobs, setJobs] = useState<JobBrowseListing[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [retryToken, setRetryToken] = useState(0)

  const { user } = useAuth()
  const [targetRole, setTargetRole] = useState<string | null>(null)
  const [suggestionDismissed, setSuggestionDismissed] = useState(false)

  const updateFilters = (next: JobSearchFilters) => {
    setSearchParams(filtersToSearchParams(next), { replace: true })
  }

  // Runs alongside (never before) the jobs fetch; the default latest-10 load
  // is never blocked on profile data.
  useEffect(() => {
    if (!user) {
      setTargetRole(null)
      return
    }
    let cancelled = false
    void getProfilePreferences(user.id).then((result) => {
      if (cancelled || !result.ok) return
      setTargetRole(result.data.target_role?.trim() || null)
    })
    return () => {
      cancelled = true
    }
  }, [user])

  const roleSuggestion =
    !suggestionDismissed && !filters.keywords.trim() && targetRole
      ? targetRole
      : null

  useEffect(() => {
    let cancelled = false

    const timer = setTimeout(() => {
      void Promise.resolve()
        .then(() => {
          if (cancelled) return undefined
          setIsLoading(true)
          setError(null)
          return searchJobs(filters)
        })
        .then((response) => {
          if (cancelled || !response) return
          setJobs(response.jobs)
          setTotal(response.total)
        })
        .catch((err) => {
          if (cancelled) return
          setError(
            err instanceof Error ? err.message : "Failed to load jobs."
          )
        })
        .finally(() => {
          if (!cancelled) setIsLoading(false)
        })
    }, SEARCH_DEBOUNCE_MS)

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [filters, retryToken])

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <section className="space-y-2">
          <p className="text-xs font-semibold tracking-[0.22em] text-primary uppercase">
            Browse jobs
          </p>
          <h1 className="font-heading text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
            Find your next role
          </h1>
          <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base">
            Search the full job catalog by keywords, location, and date
            posted — or let MatchPoint set up your filters from a sentence.
          </p>
        </section>

        <JobSearchAssistant
          onFiltersExtracted={(patch) =>
            updateFilters({
              ...DEFAULT_JOB_SEARCH_FILTERS,
              ...patch,
              sort: filters.sort,
              pageSize: filters.pageSize,
              page: 1,
            })
          }
        />

        <div className="space-y-3">
          {roleSuggestion && (
            <Badge variant="outline" className="gap-1 py-0.5 pr-1 font-normal">
              <button
                type="button"
                onClick={() =>
                  updateFilters({ ...filters, keywords: roleSuggestion, page: 1 })
                }
                className="hover:text-foreground"
              >
                Search &ldquo;{roleSuggestion}&rdquo; roles &rarr;
              </button>
              <button
                type="button"
                onClick={() => setSuggestionDismissed(true)}
                className="rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                aria-label="Dismiss search suggestion"
              >
                <XIcon className="size-3" aria-hidden="true" />
              </button>
            </Badge>
          )}
          <JobFilterBar filters={filters} onChange={updateFilters} />
          <ActiveFilterChips filters={filters} onChange={updateFilters} />
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm text-muted-foreground">
            {isLoading
              ? "Searching\u2026"
              : `${total} job${total === 1 ? "" : "s"} found`}
          </p>
          <JobsSortSelect
            value={filters.sort}
            onChange={(sort) => updateFilters({ ...filters, sort, page: 1 })}
          />
        </div>

        <JobsResultsList
          jobs={jobs}
          isLoading={isLoading}
          error={error}
          onRetry={() => setRetryToken((token) => token + 1)}
        />

        <JobsPagination
          page={filters.page}
          pageSize={filters.pageSize}
          total={total}
          onPageChange={(page) => updateFilters({ ...filters, page })}
          onPageSizeChange={(pageSize) =>
            updateFilters({ ...filters, pageSize, page: 1 })
          }
        />
      </div>
    </AppShell>
  )
}
