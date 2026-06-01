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
  return [...jobs].sort((a, b) => (b.match_score ?? 0) - (a.match_score ?? 0))
}

function matchToJobMatch(match: Match): JobMatch {
  return {
    id: match.job.id,
    title: match.job.title,
    company: match.job.company,
    location: match.job.location,
    apply_url: match.job.apply_url,
    match_score: match.match_score,
    match_notes: match.match_notes,
    match_highlights: match.match_highlights,
    match_concerns: match.match_concerns,
    interview_likelihood: match.interview_likelihood,
    skills_fit: match.skills_fit,
    experience_fit: match.experience_fit,
    seniority_fit: match.seniority_fit,
    location_fit: match.location_fit,
    pay_fit: match.pay_fit,
    role_fit: match.role_fit,
    preference_fit: match.preference_fit,
    location_reason: match.location_reason,
    location_evidence: match.location_evidence,
    pay_reason: match.pay_reason,
    pay_evidence: match.pay_evidence,
    role_reason: match.role_reason,
    role_evidence: match.role_evidence,
    job_facts: match.job_facts,
  }
}

export function JobsPage() {
  const location = useLocation()
  const { user, loading: authLoading } = useAuth()
  const state = location.state as JobsPageLocationState | null
  const stateJobs = useMemo(
    () => (state?.jobs ? sortByRank(state.jobs) : []),
    [state]
  )

  const [jobs, setJobs] = useState<JobMatch[]>(stateJobs)
  const [matchesLoading, setMatchesLoading] = useState(false)

  useEffect(() => {
    if (authLoading) return

    if (!user) return

    let cancelled = false

    void Promise.resolve()
      .then(() => {
        if (!cancelled) setMatchesLoading(true)
        return getMyMatches()
      })
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

  const displayedJobs = user ? jobs : stateJobs
  const hasMatches = displayedJobs.length > 0

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <section className="space-y-2">
          <p className="text-xs font-semibold tracking-[0.22em] text-primary uppercase">
            Your matches
          </p>
          <h1 className="font-heading text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
            Jobs tailored to you
          </h1>
          <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base">
            {hasMatches
              ? `Showing ${displayedJobs.length} role${
                  displayedJobs.length === 1 ? "" : "s"
                } ranked against your resume.`
              : "Upload your resume below to see personalized job matches."}
          </p>
        </section>

        {hasMatches ? (
          <ul className="space-y-3">
            {displayedJobs.map((job) => (
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
