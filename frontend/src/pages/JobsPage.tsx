import { useLocation } from "react-router-dom"
import UploadDropzone from "@/components/user/UploadDropzone"
import { JobListingCard } from "@/components/jobs/JobListingCard"
import { AppShell } from "@/components/layout/AppShell"
import type { JobMatch } from "@/types/job"

type JobsPageLocationState = {
  jobs?: JobMatch[]
}

function sortByRank(jobs: JobMatch[]): JobMatch[] {
  return [...jobs].sort((a, b) => (a.rank ?? 0) - (b.rank ?? 0))
}

export function JobsPage() {
  const location = useLocation()
  const state = location.state as JobsPageLocationState | null
  const jobs = state?.jobs ? sortByRank(state.jobs) : []
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
