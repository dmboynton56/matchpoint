import {
  AlertTriangle,
  BriefcaseBusiness,
  DollarSign,
  ExternalLink,
  MapPin,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  formatMatchScore,
  getMatchConcerns,
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

function MatchConcernsList({ concerns }: { concerns: string[] }) {
  return (
    <ul className="mt-2 space-y-1 text-xs leading-relaxed text-amber-800 dark:text-amber-300">
      {concerns.map((line) => (
        <li key={line} className="flex gap-1.5">
          <AlertTriangle
            className="mt-0.5 size-3 shrink-0"
            aria-hidden="true"
          />
          <span>{line}</span>
        </li>
      ))}
    </ul>
  )
}

function fitTone(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "border-muted-foreground/25 bg-muted text-muted-foreground"
  }
  if (value >= 0.8) {
    return "border-emerald-500/35 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
  }
  if (value >= 0.6) {
    return "border-primary/30 bg-primary/10 text-primary"
  }
  if (value >= 0.4) {
    return "border-amber-500/35 bg-amber-500/10 text-amber-800 dark:text-amber-400"
  }
  return "border-orange-500/30 bg-orange-500/10 text-orange-800 dark:text-orange-400"
}

function formatFit(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "Unknown"
  return `${Math.round(value * 100)}%`
}

function FitSignals({ job }: { job: JobListing }) {
  const signals = [
    { label: "Location", value: job.location_fit, Icon: MapPin },
    { label: "Pay", value: job.pay_fit, Icon: DollarSign },
    { label: "Role", value: job.role_fit, Icon: BriefcaseBusiness },
  ]

  if (signals.every((signal) => signal.value == null)) return null

  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {signals.map(({ label, value, Icon }) => (
        <Badge
          key={label}
          variant="outline"
          className={cn("gap-1 text-[11px] font-medium", fitTone(value))}
        >
          <Icon className="size-3" aria-hidden="true" />
          {label} {formatFit(value)}
        </Badge>
      ))}
    </div>
  )
}

function EvidenceLine({
  label,
  reason,
  evidence,
}: {
  label: string
  reason?: string | null
  evidence?: string | null
}) {
  if (!reason && !evidence) return null

  return (
    <p className="text-xs leading-relaxed text-muted-foreground">
      <span className="font-medium text-foreground">{label}:</span> {reason}
      {evidence ? (
        <span className="text-muted-foreground/80"> ({evidence})</span>
      ) : null}
    </p>
  )
}

function FitEvidence({ job }: { job: JobListing }) {
  const hasEvidence =
    job.location_reason ||
    job.location_evidence ||
    job.pay_reason ||
    job.pay_evidence ||
    job.role_reason ||
    job.role_evidence

  if (!hasEvidence) return null

  return (
    <div className="mt-2 space-y-1">
      <EvidenceLine
        label="Location"
        reason={job.location_reason}
        evidence={job.location_evidence}
      />
      <EvidenceLine
        label="Pay"
        reason={job.pay_reason}
        evidence={job.pay_evidence}
      />
      <EvidenceLine
        label="Role"
        reason={job.role_reason}
        evidence={job.role_evidence}
      />
    </div>
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
  const concerns = getMatchConcerns(job)
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
            <h2 className="text-sm leading-snug font-semibold tracking-tight text-foreground">
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
          <FitSignals job={job} />
          {showHighlightList ? (
            <MatchHighlightsList highlights={highlights} />
          ) : null}
          <FitEvidence job={job} />
          {concerns.length > 0 ? (
            <MatchConcernsList concerns={concerns} />
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
