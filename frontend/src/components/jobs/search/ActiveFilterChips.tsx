import { XIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { formatExperienceLevel, formatJobType, formatPayRange, formatWorkplaceType } from "@/types/job"
import {
  DATE_POSTED_OPTIONS,
  clearAllFilters,
  hasActiveFilters,
  type JobSearchFilters,
} from "@/types/jobSearch"

type Chip = {
  key: string
  label: string
  onRemove: () => void
}

function buildChips(
  filters: JobSearchFilters,
  onChange: (next: JobSearchFilters) => void
): Chip[] {
  const chips: Chip[] = []

  if (filters.keywords.trim()) {
    chips.push({
      key: "keywords",
      label: `"${filters.keywords.trim()}"`,
      onRemove: () => onChange({ ...filters, keywords: "", page: 1 }),
    })
  }

  for (const location of filters.locations) {
    chips.push({
      key: `location-${location}`,
      label: location,
      onRemove: () =>
        onChange({
          ...filters,
          locations: filters.locations.filter((l) => l !== location),
          page: 1,
        }),
    })
  }

  for (const level of filters.experienceLevels) {
    chips.push({
      key: `level-${level}`,
      label: formatExperienceLevel(level),
      onRemove: () =>
        onChange({
          ...filters,
          experienceLevels: filters.experienceLevels.filter((l) => l !== level),
          page: 1,
        }),
    })
  }

  for (const type of filters.jobTypes) {
    chips.push({
      key: `type-${type}`,
      label: formatJobType(type),
      onRemove: () =>
        onChange({
          ...filters,
          jobTypes: filters.jobTypes.filter((t) => t !== type),
          page: 1,
        }),
    })
  }

  for (const workplace of filters.workplaceTypes) {
    chips.push({
      key: `workplace-${workplace}`,
      label: formatWorkplaceType(workplace),
      onRemove: () =>
        onChange({
          ...filters,
          workplaceTypes: filters.workplaceTypes.filter((w) => w !== workplace),
          page: 1,
        }),
    })
  }

  if (filters.payMin != null || filters.payMax != null) {
    chips.push({
      key: "pay",
      label: formatPayRange(filters.payMin, filters.payMax) ?? "Pay range",
      onRemove: () => onChange({ ...filters, payMin: null, payMax: null, page: 1 }),
    })
  }

  if (filters.datePosted !== "any") {
    const option = DATE_POSTED_OPTIONS.find((o) => o.value === filters.datePosted)
    chips.push({
      key: "posted",
      label: option?.label ?? filters.datePosted,
      onRemove: () => onChange({ ...filters, datePosted: "any", page: 1 }),
    })
  }

  return chips
}

type ActiveFilterChipsProps = {
  filters: JobSearchFilters
  onChange: (next: JobSearchFilters) => void
}

export function ActiveFilterChips({ filters, onChange }: ActiveFilterChipsProps) {
  if (!hasActiveFilters(filters)) return null

  const chips = buildChips(filters, onChange)

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {chips.map((chip) => (
        <Badge key={chip.key} variant="outline" className="gap-1 py-0.5 pr-1 font-normal">
          {chip.label}
          <button
            type="button"
            onClick={chip.onRemove}
            className="rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label={`Remove ${chip.label} filter`}
          >
            <XIcon className="size-3" aria-hidden="true" />
          </button>
        </Badge>
      ))}
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="h-6 px-2 text-xs text-muted-foreground"
        onClick={() => onChange(clearAllFilters(filters))}
      >
        Clear all
      </Button>
    </div>
  )
}
