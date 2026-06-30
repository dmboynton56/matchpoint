import { ArrowDown, Brain, ListChecks, ScanSearch } from "lucide-react"

import Header from "@/components/layout/Header"
import UploadDropzone from "@/components/user/UploadDropzone"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

const FEATURES = [
  {
    icon: ScanSearch,
    title: "Intent extraction",
    description:
      "We read between the lines of your resume to understand the work you actually want next.",
  },
  {
    icon: Brain,
    title: "Skill matching",
    description:
      "Your real skills get mapped against live roles, so the fit is based on substance, not keywords.",
  },
  {
    icon: ListChecks,
    title: "Curated roles",
    description:
      "Skip the endless scroll. You get a focused shortlist of openings worth applying to.",
  },
]

export function LandingPage() {
  return (
    <div className="flex min-h-svh flex-col bg-background text-foreground">
      <Header />

      <main className="flex-1">
        <section
          id="upload"
          aria-labelledby="landing-hero-heading"
          className="mx-auto flex w-full max-w-6xl flex-col gap-14 px-5 py-12 lg:flex-row lg:items-center lg:gap-20 lg:py-20"
        >
          <div className="max-w-xl flex-1">
            <p className="text-xs font-semibold tracking-[0.22em] text-primary uppercase">
              AI job search
            </p>
            <h1
              id="landing-hero-heading"
              className="mt-5 font-heading text-5xl leading-[1.02] font-bold tracking-tight uppercase sm:text-6xl lg:text-7xl"
            >
              Find your{" "}
              <span className="relative inline-block whitespace-nowrap">
                perfect
                <span
                  aria-hidden="true"
                  className="absolute inset-x-0 -bottom-1 h-2 rounded-full bg-accent/70"
                />
              </span>{" "}
              jobs
            </h1>
            <p className="mt-7 max-w-md text-lg leading-relaxed text-muted-foreground sm:text-xl">
              Upload once. MatchPoint reads your resume, pulls intent and skills,
              and surfaces roles worth your time.
            </p>

            <div className="mt-9 flex items-center gap-3 text-sm text-muted-foreground">
              <span className="flex size-9 items-center justify-center rounded-full bg-primary/10 text-primary">
                <ArrowDown className="size-4" aria-hidden="true" />
              </span>
              <span>Drop your resume to get started — it takes seconds.</span>
            </div>
          </div>

          <div className="w-full flex-1 lg:max-w-xl">
            <div className="rounded-3xl border border-border bg-card p-6 shadow-2xl shadow-primary/10 ring-1 ring-foreground/5 sm:p-8">
              <UploadDropzone />
            </div>
          </div>
        </section>

        <section
          aria-labelledby="features-heading"
          className="bg-primary text-primary-foreground"
        >
          <div className="mx-auto w-full max-w-6xl px-5 py-16 lg:py-20">
            <div className="max-w-2xl">
              <p className="text-xs font-semibold tracking-[0.22em] text-primary-foreground/70 uppercase">
                Why MatchPoint
              </p>
              <h2
                id="features-heading"
                className="mt-4 font-heading text-3xl font-bold tracking-tight uppercase sm:text-4xl"
              >
                Less searching, more matching
              </h2>
            </div>

            <div className="mt-10 grid gap-5 md:grid-cols-3">
              {FEATURES.map((feature) => {
                const Icon = feature.icon
                return (
                  <Card
                    key={feature.title}
                    className="bg-card/95 ring-0 backdrop-blur"
                  >
                    <CardHeader>
                      <span className="mb-3 flex size-11 items-center justify-center rounded-xl bg-accent/15 text-accent">
                        <Icon className="size-5" aria-hidden="true" />
                      </span>
                      <CardTitle className="text-lg uppercase">
                        {feature.title}
                      </CardTitle>
                      <CardDescription className="mt-1 leading-relaxed">
                        {feature.description}
                      </CardDescription>
                    </CardHeader>
                  </Card>
                )
              })}
            </div>
          </div>
        </section>

        <section className="mx-auto w-full max-w-6xl px-5 py-16 text-center lg:py-20">
          <h2 className="font-heading text-3xl font-bold tracking-tight uppercase sm:text-4xl">
            Ready to find roles worth your time?
          </h2>
          <p className="mx-auto mt-4 max-w-md text-lg text-muted-foreground">
            One resume upload is all it takes to see your matches.
          </p>
          <Button asChild size="xl" className="mt-8">
            <a href="#upload">
              <ArrowDown className="size-4" aria-hidden="true" />
              Upload your resume
            </a>
          </Button>
        </section>
      </main>
    </div>
  )
}

export default LandingPage
