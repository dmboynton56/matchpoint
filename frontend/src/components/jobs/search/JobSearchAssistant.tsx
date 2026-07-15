import { useState } from "react"
import { Loader2Icon, SearchIcon, SparklesIcon } from "lucide-react"

import { extractFiltersFromMessage } from "@/apis/jobSearchAssistant"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { describeExtractedFilters } from "@/lib/parseJobQuery"
import { cn } from "@/lib/utils"
import type { JobSearchFilters } from "@/types/jobSearch"

const EXAMPLE_PROMPTS = [
  "Entry level machine learning jobs in Denver, SF, or remote",
  "Senior remote frontend roles paying $150k+",
  "Internships in NYC or Boston",
]

type JobSearchAssistantProps = {
  onFiltersExtracted: (patch: Partial<JobSearchFilters>) => void
  className?: string
}

/**
 * Natural-language search bar: one free-text input that gets parsed into
 * structured filters. Not a chat — each submission simply replaces the
 * active filters, with a one-line status showing what was applied.
 */
export function JobSearchAssistant({
  onFiltersExtracted,
  className,
}: JobSearchAssistantProps) {
  const [inputValue, setInputValue] = useState("")
  const [status, setStatus] = useState<string | null>(null)
  const [isExtracting, setIsExtracting] = useState(false)

  const submit = async (message: string) => {
    const trimmed = message.trim()
    if (!trimmed || isExtracting) return

    setIsExtracting(true)

    try {
      const patch = await extractFiltersFromMessage(trimmed)
      const described = describeExtractedFilters(patch)
      setStatus(
        described.length > 0
          ? `Filtering by ${described.join(" · ")}`
          : "Couldn't pick out any filters from that — try mentioning a role, location, or level, or use the filters below."
      )
      onFiltersExtracted(patch)
    } finally {
      setIsExtracting(false)
    }
  }

  return (
    <div className={cn("space-y-2", className)}>
      <form
        className="relative"
        onSubmit={(event) => {
          event.preventDefault()
          void submit(inputValue)
        }}
      >
        <SparklesIcon
          className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-primary"
          aria-hidden="true"
        />
        <Input
          value={inputValue}
          onChange={(event) => setInputValue(event.target.value)}
          placeholder="Describe the job you want — e.g. senior remote frontend paying $150k+"
          aria-label="Describe the job you're looking for"
          className="h-11 pr-24 pl-10"
        />
        <Button
          type="submit"
          size="sm"
          className="absolute top-1/2 right-1.5 h-8 -translate-y-1/2 gap-1.5"
          disabled={isExtracting || !inputValue.trim()}
        >
          {isExtracting ? (
            <Loader2Icon className="size-3.5 animate-spin" aria-hidden="true" />
          ) : (
            <SearchIcon className="size-3.5" aria-hidden="true" />
          )}
          Search
        </Button>
      </form>

      {status ? (
        <p className="text-xs text-muted-foreground" role="status">
          {status}
        </p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {EXAMPLE_PROMPTS.map((prompt) => (
            <button
              key={prompt}
              type="button"
              onClick={() => {
                setInputValue(prompt)
                void submit(prompt)
              }}
              className="rounded-full border border-border bg-muted/50 px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
            >
              {prompt}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
