import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { toast } from "sonner"

import { getMyMatches } from "@/apis/matches"
import { AppliedJobButton } from "@/components/jobs/AppliedJobButton"
import { JobListingCard } from "@/components/jobs/JobListingCard"
import { AppShell } from "@/components/layout/AppShell"
import { RouteLoading } from "@/components/routing/RouteLoading"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/hooks/useAuth"
import { matchToJobMatch, sortByMatchScore } from "@/lib/matchToJobMatch"
import { hasApplyUrl, type JobListing } from "@/types/job"

export function AppliedJobsPage() {
  const { user, loading: authLoading } = useAuth()
  const [appliedJobs, setAppliedJobs] = useState<JobListing[]>([])
  const [appliedJobsLoading, setAppliedJobsLoading] = useState(false)

  useEffect(() => {
    if (authLoading || !user) return

    let cancelled = false

    void Promise.resolve()
      .then(() => {
        if (!cancelled) setAppliedJobsLoading(true)
        return getMyMatches({ applied: true })
      })
      .then((response) => {
        if (cancelled) return
        setAppliedJobs(sortByMatchScore(response.matches.map(matchToJobMatch)))
      })
      .catch((error) => {
        if (cancelled) return
        const message =
          error instanceof Error ? error.message : "Failed to load applied jobs"
        toast.error(message)
      })
      .finally(() => {
        if (!cancelled) setAppliedJobsLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [user, authLoading])

  if (authLoading || (user && appliedJobsLoading && appliedJobs.length === 0)) {
    return <RouteLoading />
  }

  const hasAppliedJobs = appliedJobs.length > 0

  const handleUnapplied = (jobId: string) => {
    setAppliedJobs((current) => current.filter((job) => job.id !== jobId))
  }

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <section className="space-y-2">
          <p className="text-xs font-semibold tracking-[0.22em] text-primary uppercase">
            Your applied jobs
          </p>
          <h1 className="font-heading text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
            Applied jobs
          </h1>
          <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base">
            {hasAppliedJobs
              ? `Showing ${appliedJobs.length} job${
                  appliedJobs.length === 1 ? "" : "s"
                } you've applied to.`
              : "Mark jobs as applied from your matches to see them here."}
          </p>
        </section>

        {hasAppliedJobs ? (
          <ul className="space-y-3">
            {appliedJobs.map((job) => (
              <li key={job.match_id ?? job.id}>
                <JobListingCard
                  job={job}
                  showApplyLink={hasApplyUrl(job)}
                  headerAddon={
                    job.id ? (
                      <AppliedJobButton
                        jobId={job.id}
                        onUnapplied={() => handleUnapplied(job.id)}
                      />
                    ) : null
                  }
                />
              </li>
            ))}
          </ul>
        ) : (
          <div className="rounded-xl border border-dashed border-border bg-card/50 px-6 py-10 text-center">
            <p className="text-sm text-muted-foreground">
              No applied jobs yet. Apply to a role from your matches and mark it
              as applied, or browse your job list.
            </p>
            <Button asChild className="mt-4">
              <Link to="/matches">View matches</Link>
            </Button>
          </div>
        )}
      </div>
    </AppShell>
  )
}
