import { Link } from "react-router-dom"

import { AppShell } from "@/components/layout/AppShell"
import { Button } from "@/components/ui/button"

export function NotFoundPage() {
  return (
    <AppShell>
      <section
        className="flex min-h-[50vh] flex-col items-center justify-center px-4 text-center"
        aria-labelledby="not-found-heading"
      >
        <p className="text-xs font-semibold tracking-[0.22em] text-primary uppercase">
          Page not found
        </p>
        <p
          className="mt-4 font-heading text-8xl font-bold tracking-tight text-foreground/15 select-none sm:text-9xl"
          aria-hidden="true"
        >
          404
        </p>
        <h1
          id="not-found-heading"
          className="mt-2 font-heading text-2xl font-bold tracking-tight text-foreground sm:text-3xl"
        >
          This page doesn&apos;t exist
        </h1>
        <p className="mt-3 max-w-md text-sm leading-relaxed text-muted-foreground sm:text-base">
          The link may be broken or the page was removed. Head back home or
          browse your job matches.
        </p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <Button asChild>
            <Link to="/">Go home</Link>
          </Button>
          <Button variant="outline" asChild>
            <Link to="/jobs">View jobs</Link>
          </Button>
        </div>
      </section>
    </AppShell>
  )
}
