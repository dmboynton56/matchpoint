import { BriefcaseBusiness, SendHorizontal } from "lucide-react"

import { Button } from "@/components/ui/button"

export function App() {
  return (
    <main className="flex min-h-svh flex-col bg-background text-foreground">
      <header className="flex h-16 items-center px-5 sm:px-8">
        <a
          href="/"
          className="inline-flex items-center gap-2 text-sm font-semibold tracking-normal text-foreground"
        >
          <span className="flex size-8 items-center justify-center rounded-md border border-border bg-card text-primary shadow-sm">
            <BriefcaseBusiness className="size-4" aria-hidden="true" />
          </span>
          MatchPoint
        </a>
      </header>

      <div className="flex flex-1 items-center justify-center px-4 pt-10 pb-24 sm:px-6">
        <section className="w-full max-w-3xl">
          <h1 className="text-center text-2xl font-medium tracking-normal text-foreground sm:text-3xl">
            What kind of jobs are you looking for?
          </h1>

          <form className="mt-10" aria-label="Job search">
            <div className="flex min-h-16 items-center gap-3 rounded-[2rem] border border-border bg-card px-4 py-3 shadow-[0_18px_60px_rgb(16_24_32/0.11)] transition-colors focus-within:border-ring focus-within:ring-4 focus-within:ring-ring/20 sm:gap-4 sm:px-5 dark:shadow-[0_18px_70px_rgb(0_0_0/0.34)]">
              <label htmlFor="job-search" className="sr-only">
                Search jobs
              </label>
              <input
                className="h-10 min-w-0 flex-1 bg-transparent text-base text-foreground outline-none placeholder:text-muted-foreground"
                id="job-search"
                name="job-search"
                placeholder="Enter search"
                type="text"
                autoComplete="off"
              />
              <Button
                className="size-10 rounded-full bg-primary text-primary-foreground hover:bg-primary/90"
                size="icon"
                type="submit"
                aria-label="Send search"
              >
                <SendHorizontal className="size-4" aria-hidden="true" />
              </Button>
            </div>
          </form>
        </section>
      </div>
    </main>
  )
}

export default App
