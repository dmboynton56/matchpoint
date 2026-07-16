import { ExternalLink } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  formatExperienceLevel,
  formatJobType,
  formatPayRange,
  formatPostedAt,
  formatWorkplaceType,
  hasBrowseApplyUrl,
  type JobBrowseListing,
} from "@/types/job"
import { cn } from "@/lib/utils"

type JobBrowseCardProps = {
  job: JobBrowseListing
  className?: string
}

export function JobBrowseCard({ job, className }: JobBrowseCardProps) {
  const postedLabel = formatPostedAt(job.posted_at)
  const description = (job.summary ?? job.description)?.trim()
  const showApply = hasBrowseApplyUrl(job)

  const payLabel = formatPayRange(job.pay_min, job.pay_max, job.pay_currency)
  const badges = [
    payLabel ? { key: "pay", label: payLabel } : null,
    job.job_type
      ? { key: "job_type", label: formatJobType(job.job_type) }
      : null,
    job.experience_level
      ? { key: "experience_level", label: formatExperienceLevel(job.experience_level) }
      : null,
    job.workplace_type
      ? { key: "workplace_type", label: formatWorkplaceType(job.workplace_type) }
      : null,
  ].filter((badge): badge is { key: string; label: string } => badge != null)

  return (
    <article
      className={cn(
        "rounded-xl border border-border bg-card px-4 py-3 shadow-sm ring-1 ring-primary/20",
        className
      )}
    >
      <header className="min-w-0 space-y-1">
        <h2 className="text-sm leading-snug font-semibold tracking-tight text-foreground">
          {job.title}
        </h2>
        <p className="text-sm text-muted-foreground">{job.company}</p>
        {job.location ? (
          <p className="text-xs text-muted-foreground/90">{job.location}</p>
        ) : null}
        {postedLabel ? (
          <p className="text-xs text-muted-foreground/80">{postedLabel}</p>
        ) : null}
      </header>

      {badges.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {badges.map((badge) => (
            <Badge key={badge.key} variant="outline" className="text-muted-foreground">
              {badge.label}
            </Badge>
          ))}
        </div>
      ) : null}

      {description ? (
        <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
          {description}
        </p>
      ) : null}

      {showApply ? (
        <div className="mt-3 flex justify-end border-t border-border/60 pt-2.5">
          <Button
            asChild
            variant="outline"
            size="sm"
            className="h-8 gap-1.5 text-xs font-medium"
          >
            <a href={job.apply_url} target="_blank" rel="noopener noreferrer">
              Apply
              <ExternalLink className="size-3.5" aria-hidden="true" />
            </a>
          </Button>
        </div>
      ) : null}
    </article>
  )
}
