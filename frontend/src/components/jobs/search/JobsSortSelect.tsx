import { JOBS_SORT_OPTIONS, type JobsSortOption } from "@/types/jobSearch"
import { JobFilterSelect } from "./JobFilterSelect"

type JobsSortSelectProps = {
  value: JobsSortOption
  onChange: (value: JobsSortOption) => void
}

export function JobsSortSelect({ value, onChange }: JobsSortSelectProps) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground">Sort by</span>
      <JobFilterSelect
        value={value}
        options={JOBS_SORT_OPTIONS}
        onChange={onChange}
        className="min-w-36"
      />
    </div>
  )
}
