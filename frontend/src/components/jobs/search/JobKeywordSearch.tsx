import { SearchIcon } from "lucide-react"

import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

type JobKeywordSearchProps = {
  value: string
  onChange: (value: string) => void
  onSubmit?: () => void
  className?: string
}

export function JobKeywordSearch({
  value,
  onChange,
  onSubmit,
  className,
}: JobKeywordSearchProps) {
  return (
    <form
      role="search"
      className={cn("relative flex-1", className)}
      onSubmit={(event) => {
        event.preventDefault()
        onSubmit?.()
      }}
    >
      <SearchIcon
        className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
        aria-hidden="true"
      />
      <Input
        type="search"
        placeholder="Search job titles, companies, or keywords"
        aria-label="Search jobs"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 pl-8"
      />
    </form>
  )
}
