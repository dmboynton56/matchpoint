import { Badge } from "@/components/ui/badge"
import type { MockJob } from "@/data/mockJobs"
import { cn } from "@/lib/utils"

type JobListingCardProps = {
  job: MockJob
  showTags?: boolean
  className?: string
}

export function JobListingCard({
  job,
  showTags = true,
  className,
}: JobListingCardProps) {
  return (
    <article
      className={cn(
        "rounded-xl border border-border bg-card px-4 py-3 shadow-sm ring-1 ring-primary/20",
        className
      )}
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
        <div className="min-w-0 space-y-1">
          <h2 className="text-sm font-semibold leading-snug tracking-tight text-foreground">
            {job.title}
          </h2>
          <p className="text-sm text-muted-foreground">{job.company}</p>
          <p className="text-xs text-muted-foreground/90">{job.location}</p>
        </div>
        {showTags && job.tags.length > 0 ? (
          <div className="flex shrink-0 flex-wrap gap-1.5">
            {job.tags.map((tag) => (
              <Badge key={tag} variant="outline" className="font-normal">
                {tag}
              </Badge>
            ))}
          </div>
        ) : null}
      </div>
    </article>
  )
}
