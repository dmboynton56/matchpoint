import { JobListingCard } from "@/components/jobs/JobListingCard"
import { AppShell } from "@/components/layout/AppShell"
import { MOCK_JOBS } from "@/data/mockJobs"

export function JobsPage() {
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
            Personalized results from your resume will appear here once matching
            is wired up. Showing sample listings for now.
          </p>
        </section>

        <ul className="space-y-3">
          {MOCK_JOBS.map((job) => (
            <li key={job.id}>
              <JobListingCard job={job} />
            </li>
          ))}
        </ul>
      </div>
    </AppShell>
  )
}
