import { FileUp } from "lucide-react"
import { Link } from "react-router-dom"

import { JobListingCard } from "@/components/jobs/JobListingCard"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  LANDING_PREVIEW_JOB_COUNT,
  MOCK_JOBS,
} from "@/data/mockJobs"
import { cn } from "@/lib/utils"

/** Blur ramps row-by-row so each listing stays its own card (border/bg), unlike one giant blurred layer + mask. */
function blurredRowClasses(rowIndex: number) {
  return cn(
    rowIndex === 0 && "blur-[4px] opacity-[0.85]",
    rowIndex === 1 && "blur-[6px] opacity-[0.78]",
    rowIndex >= 2 && "blur-[8px] opacity-[0.72]"
  )
}

function JobsPreviewPanel() {
  const previewJobs = MOCK_JOBS.slice(0, LANDING_PREVIEW_JOB_COUNT)
  const featured = previewJobs[0]
  const rest = previewJobs.slice(1)

  if (!featured) {
    return null
  }

  return (
    <Card className="mx-auto aspect-square w-full max-w-[min(100%,340px)] gap-0 overflow-hidden rounded-2xl py-0 shadow-[0_22px_70px_rgb(6_34_56/0.12)] ring-border sm:max-w-[380px] dark:shadow-[0_26px_90px_rgb(0_0_0/0.35)]">
      <CardContent className="relative flex min-h-0 flex-1 flex-col p-0">
        <div
          aria-hidden="true"
          className="pointer-events-none flex min-h-0 flex-1 flex-col justify-center gap-2.5 overflow-hidden px-3 py-3 select-none"
        >
          <div className="relative z-[1] shrink-0">
            <JobListingCard
              job={featured}
              showMatchScore={false}
              showHighlights={false}
              showApplyLink={false}
              className="px-3 py-2.5"
            />
          </div>
          {rest.map((job, rowIndex) => (
            <div
              key={job.id}
              className={cn(
                "origin-center saturate-[0.95]",
                blurredRowClasses(rowIndex)
              )}
            >
              <JobListingCard
                job={job}
                showMatchScore={false}
                showHighlights={false}
                showApplyLink={false}
                className="px-3 py-2.5"
              />
            </div>
          ))}
        </div>

        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center bg-background/30 px-5 backdrop-blur-[2px]">
          <div className="flex max-w-[14rem] flex-col items-center gap-3 text-center">
            <Button
              asChild
              size="lg"
              variant="secondary"
              className="pointer-events-auto h-11 gap-2 rounded-xl border border-accent/35 bg-accent px-6 text-base font-semibold text-accent-foreground shadow-md shadow-accent/15 hover:bg-accent/90"
            >
              <Link to="/jobs">
                <FileUp className="size-4 shrink-0" aria-hidden="true" />
                Upload resume
              </Link>
            </Button>
            <p className="pointer-events-none text-xs leading-snug text-muted-foreground">
              Upload your resume and see jobs catered to you.
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

export function Landing() {
  return (
    <section
      className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-14 px-5 py-10 pb-20 lg:flex-row lg:items-center lg:gap-16 lg:py-14 xl:gap-24"
      aria-labelledby="landing-hero-heading"
    >
      <div className="max-w-xl flex-1 lg:max-w-none lg:flex-[1.05]">
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary">
          AI job search
        </p>
        <h1
          id="landing-hero-heading"
          className="mt-4 font-heading text-4xl leading-[1.05] font-bold tracking-tight text-foreground uppercase sm:text-5xl lg:text-6xl xl:text-[3.35rem]"
        >
          Find your perfect jobs
        </h1>
        <p className="mt-6 max-w-lg text-lg leading-relaxed text-muted-foreground sm:text-xl">
          Upload once. MatchPoint reads your resume, pulls intent and skills, and
          surfaces roles worth your time.
        </p>
      </div>

      <div className="flex w-full flex-1 justify-center lg:max-w-none lg:justify-end xl:flex-[0.85]">
        <JobsPreviewPanel />
      </div>
    </section>
  )
}
