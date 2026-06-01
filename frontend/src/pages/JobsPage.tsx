import { useEffect, useMemo, useState } from "react"
import { useLocation } from "react-router-dom"
import { toast } from "sonner"

import { getMyMatches, type Match } from "@/apis/matches"
import { JobListingCard } from "@/components/jobs/JobListingCard"
import { AppShell } from "@/components/layout/AppShell"
import { RouteLoading } from "@/components/routing/RouteLoading"
import UploadDropzone from "@/components/user/UploadDropzone"
import { useAuth } from "@/hooks/useAuth"
import type { JobMatch } from "@/types/job"

type JobsPageLocationState = {
  jobs?: JobMatch[]
}

function sortByRank(jobs: JobMatch[]): JobMatch[] {
  return [...jobs].sort((a, b) => (a.rank ?? 0) - (b.rank ?? 0))
}

function sortByMatchScore(jobs: JobMatch[]): JobMatch[] {
  return [...jobs].sort(
    (a, b) => (b.match_score ?? 0) - (a.match_score ?? 0)
  )
}

function matchToJobMatch(match: Match): JobMatch {
  return {
    id: match.job.id,
    title: match.job.title,
    company: match.job.company,
    location: match.job.location,
    apply_url: match.job.apply_url,
    match_score: match.match_score,
    match_highlights: match.match_highlights,
  }
}

export function JobsPage() {
  const location = useLocation()
  const { user, loading: authLoading } = useAuth()
  const state = location.state as JobsPageLocationState | null
  const stateJobs = useMemo(
    () => (state?.jobs ? sortByRank(state.jobs) : []),
    [state?.jobs]
  )

  const [jobs, setJobs] = useState<JobMatch[]>(stateJobs)
  const [matchesLoading, setMatchesLoading] = useState(false)

  useEffect(() => {
    if (authLoading) return

    if (!user) {
      setJobs(stateJobs)
      return
    }

    let cancelled = false
    setMatchesLoading(true)

    void getMyMatches()
      .then((response) => {
        if (cancelled) return
        setJobs(sortByMatchScore(response.matches.map(matchToJobMatch)))
      })
      .catch((error) => {
        if (cancelled) return
        const message =
          error instanceof Error ? error.message : "Failed to load matches"
        toast.error(message)
        if (stateJobs.length > 0) setJobs(stateJobs)
      })
      .finally(() => {
        if (!cancelled) setMatchesLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [user, authLoading, stateJobs])

  if (authLoading || (user && matchesLoading && jobs.length === 0)) {
    return <RouteLoading />
  }

  const hasMatches = jobs.length > 0

  return (
    <AppShell>
      <div className="space-y-6">
        <section className="space-y-2">
          <p className="text-xs font-semibold tracking-[0.22em] text-primary uppercase">
            Your matches
          </p>
          <h1 className="font-heading text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
            Jobs tailored to you
          </h1>
          <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base">
            {hasMatches
              ? `Showing ${jobs.length} role${jobs.length === 1 ? "" : "s"} ranked against your resume.`
              : "Upload your resume below to see personalized job matches."}
          </p>
        </section>

        {hasMatches ? (
          <ul className="space-y-3">
            {jobs.map((job) => (
              <li key={job.id}>
                <JobListingCard job={job} />
              </li>
            ))}
          </ul>
        ) : (
          <div className="rounded-xl border border-dashed border-border bg-card/50 px-6 py-10 text-center">
            <p className="text-sm text-muted-foreground">
              No matches yet. Upload a PDF resume to get started.
            </p>
            <UploadDropzone />
          </div>
        )}
      </div>
    </AppShell>
  )
}
