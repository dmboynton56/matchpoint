import { ExternalLink } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  formatMatchScore,
  getMatchHighlights,
  getMatchScoreTier,
  hasApplyUrl,
  matchScoreAccentClass,
  matchScoreBadgeClass,
  type JobListing,
} from "@/types/job"
import { cn } from "@/lib/utils"

type JobListingCardProps = {
  job: JobListing
  /** Show match % badge when `job.match_score` is set. */
  showMatchScore?: boolean
  /** Show “why this matched” bullets when highlights exist. */
  showHighlights?: boolean
  /** Show apply link when `job.apply_url` is set. */
  showApplyLink?: boolean
  /** Optional marketing tags (preview only; not from API). */
  showTags?: boolean
  className?: string
}

function MatchHighlightsList({ highlights }: { highlights: string[] }) {
  return (
    <ul className="mt-2 list-disc space-y-1 pl-4 text-xs leading-relaxed text-muted-foreground">
      {highlights.map((line) => (
        <li key={line}>{line}</li>
      ))}
    </ul>
  )
}

export function JobListingCard({
  job,
  showMatchScore = true,
  showHighlights = true,
  showApplyLink = true,
  showTags = false,
  className,
}: JobListingCardProps) {
  const tags = job.tags ?? []
  const highlights = getMatchHighlights(job)
  const showScore =
    showMatchScore && job.match_score != null && !Number.isNaN(job.match_score)
  const scoreTier =
    showScore && job.match_score != null
      ? getMatchScoreTier(job.match_score)
      : null
  const showHighlightList = showHighlights && highlights.length > 0
  const showApply = showApplyLink && hasApplyUrl(job)

  return (
    <article
      className={cn(
        "rounded-xl border border-border bg-card px-4 py-3 shadow-sm ring-1 ring-primary/20",
        scoreTier && "border-l-[3px]",
        scoreTier && matchScoreAccentClass(scoreTier),
        className
      )}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
        <header className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <h2 className="text-sm font-semibold leading-snug tracking-tight text-foreground">
              {job.title}
            </h2>
            {showScore && scoreTier ? (
              <Badge
                variant="secondary"
                className={cn(
                  "shrink-0 font-medium",
                  matchScoreBadgeClass(scoreTier)
                )}
              >
                {formatMatchScore(job.match_score!)}
              </Badge>
            ) : null}
          </div>
          <p className="text-sm text-muted-foreground">{job.company}</p>
          {job.location ? (
            <p className="text-xs text-muted-foreground/90">{job.location}</p>
          ) : null}
          {showHighlightList ? (
            <MatchHighlightsList highlights={highlights} />
          ) : null}
        </header>

        {showTags && tags.length > 0 ? (
          <div className="flex shrink-0 flex-wrap gap-1.5 sm:max-w-[40%] sm:justify-end">
            {tags.map((tag) => (
              <Badge key={tag} variant="outline" className="font-normal">
                {tag}
              </Badge>
            ))}
          </div>
        ) : null}
      </div>

      {showApply ? (
        <div className="mt-3 flex justify-end border-t border-border/60 pt-2.5">
          <Button
            asChild
            variant="outline"
            size="sm"
            className="h-8 gap-1.5 text-xs font-medium"
          >
            <a
              href={job.apply_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              Apply
              <ExternalLink className="size-3.5" aria-hidden="true" />
            </a>
          </Button>
        </div>
      ) : null}
    </article>
  )
}
