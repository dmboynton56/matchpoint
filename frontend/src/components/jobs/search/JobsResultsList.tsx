import { SearchXIcon } from "lucide-react"

import { JobBrowseCard } from "@/components/jobs/search/JobBrowseCard"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { JobBrowseListing } from "@/types/job"

type JobsResultsListProps = {
  jobs: JobBrowseListing[]
  isLoading: boolean
  error: string | null
  onRetry?: () => void
}

function ResultsSkeleton() {
  return (
    <ul className="space-y-3" aria-hidden="true">
      {Array.from({ length: 5 }).map((_, index) => (
        <li
          key={index}
          className="h-24 animate-pulse rounded-xl border border-border bg-card/60"
        />
      ))}
    </ul>
  )
}

export function JobsResultsList({
  jobs,
  isLoading,
  error,
  onRetry,
}: JobsResultsListProps) {
  if (error) {
    return (
      <div className="rounded-xl border border-dashed border-destructive/30 bg-destructive/5 px-6 py-10 text-center">
        <p className="text-sm text-destructive">{error}</p>
        {onRetry ? (
          <Button variant="outline" size="sm" className="mt-4" onClick={onRetry}>
            Try again
          </Button>
        ) : null}
      </div>
    )
  }

  if (isLoading && jobs.length === 0) {
    return <ResultsSkeleton />
  }

  if (jobs.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-card/50 px-6 py-10 text-center">
        <SearchXIcon
          className="mx-auto mb-2 size-6 text-muted-foreground"
          aria-hidden="true"
        />
        <p className="text-sm text-muted-foreground">
          No jobs match your filters. Try widening your search or clearing a
          few filters.
        </p>
      </div>
    )
  }

  return (
    <ul
      className={cn("space-y-3 transition-opacity", isLoading && "opacity-60")}
      aria-busy={isLoading}
    >
      {jobs.map((job) => (
        <li key={job.id}>
          <JobBrowseCard job={job} />
        </li>
      ))}
    </ul>
  )
}
