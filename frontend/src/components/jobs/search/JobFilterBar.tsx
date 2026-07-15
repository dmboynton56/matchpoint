import { SlidersHorizontalIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Drawer,
  DrawerContent,
  DrawerDescription,
  DrawerHeader,
  DrawerTitle,
  DrawerTrigger,
} from "@/components/ui/drawer"
import {
  DATE_POSTED_OPTIONS,
  EXPERIENCE_LEVEL_OPTIONS,
  JOB_TYPE_OPTIONS,
  LOCATION_MULTI_SELECT_OPTIONS,
  WORKPLACE_TYPE_OPTIONS,
  hasActiveFilters,
  type JobSearchFilters,
} from "@/types/jobSearch"
import { JobFilterSelect } from "./JobFilterSelect"
import { JobKeywordSearch } from "./JobKeywordSearch"
import { MultiSelectFilter } from "./MultiSelectFilter"
import { PayRangeFilter } from "./PayRangeFilter"

type JobFilterBarProps = {
  filters: JobSearchFilters
  onChange: (next: JobSearchFilters) => void
}

export function JobFilterBar({ filters, onChange }: JobFilterBarProps) {
  const filterControls = (
    <>
      <MultiSelectFilter
        label="Location"
        options={LOCATION_MULTI_SELECT_OPTIONS}
        selected={filters.locations}
        onChange={(locations) => onChange({ ...filters, locations, page: 1 })}
      />
      <MultiSelectFilter
        label="Experience"
        options={EXPERIENCE_LEVEL_OPTIONS}
        selected={filters.experienceLevels}
        onChange={(experienceLevels) =>
          onChange({ ...filters, experienceLevels, page: 1 })
        }
      />
      <MultiSelectFilter
        label="Job type"
        options={JOB_TYPE_OPTIONS}
        selected={filters.jobTypes}
        onChange={(jobTypes) => onChange({ ...filters, jobTypes, page: 1 })}
      />
      <MultiSelectFilter
        label="Workplace"
        options={WORKPLACE_TYPE_OPTIONS}
        selected={filters.workplaceTypes}
        onChange={(workplaceTypes) =>
          onChange({ ...filters, workplaceTypes, page: 1 })
        }
      />
      <PayRangeFilter
        payMin={filters.payMin}
        payMax={filters.payMax}
        onChange={(payMin, payMax) =>
          onChange({ ...filters, payMin, payMax, page: 1 })
        }
      />
      <JobFilterSelect
        value={filters.datePosted}
        options={DATE_POSTED_OPTIONS}
        onChange={(datePosted) => onChange({ ...filters, datePosted, page: 1 })}
      />
    </>
  )

  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
      <JobKeywordSearch
        value={filters.keywords}
        onChange={(keywords) => onChange({ ...filters, keywords, page: 1 })}
      />

      {/* Inline filter row on larger screens. */}
      <div className="hidden flex-wrap items-center gap-2 sm:flex">
        {filterControls}
      </div>

      {/* Bottom-sheet filters on small screens (matches AppShell breakpoints). */}
      <Drawer>
        <DrawerTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-9 gap-1.5 self-start sm:hidden"
          >
            <SlidersHorizontalIcon className="size-4" aria-hidden="true" />
            Filters
            {hasActiveFilters(filters) ? (
              <span className="ml-0.5 size-1.5 rounded-full bg-primary" aria-hidden="true" />
            ) : null}
          </Button>
        </DrawerTrigger>
        <DrawerContent>
          <DrawerHeader>
            <DrawerTitle>Filter jobs</DrawerTitle>
            <DrawerDescription>
              Narrow results by location, experience, job type, and more.
            </DrawerDescription>
          </DrawerHeader>
          <div className="flex flex-wrap gap-2 px-4 pb-6">{filterControls}</div>
        </DrawerContent>
      </Drawer>
    </div>
  )
}
