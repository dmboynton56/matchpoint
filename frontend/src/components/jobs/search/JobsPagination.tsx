import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { JobFilterSelect } from "./JobFilterSelect"

const PAGE_SIZE_OPTIONS = [
  { value: "10", label: "10 / page" },
  { value: "25", label: "25 / page" },
  { value: "50", label: "50 / page" },
]

type PageToken = number | "ellipsis"

/** Windowed page numbers, e.g. [1, "ellipsis", 5, 6, 7, "ellipsis", 20]. */
function getPageWindow(current: number, totalPages: number): PageToken[] {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, i) => i + 1)
  }

  const keep = new Set<number>([1, totalPages, current - 1, current, current + 1])
  const sorted = Array.from(keep)
    .filter((page) => page >= 1 && page <= totalPages)
    .sort((a, b) => a - b)

  const tokens: PageToken[] = []
  let previous = 0
  for (const page of sorted) {
    if (previous && page - previous > 1) tokens.push("ellipsis")
    tokens.push(page)
    previous = page
  }
  return tokens
}

type JobsPaginationProps = {
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
  onPageSizeChange: (pageSize: number) => void
  className?: string
}

export function JobsPagination({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
  className,
}: JobsPaginationProps) {
  if (total === 0) return null

  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const currentPage = Math.min(page, totalPages)
  const rangeStart = (currentPage - 1) * pageSize + 1
  const rangeEnd = Math.min(currentPage * pageSize, total)
  const pageWindow = getPageWindow(currentPage, totalPages)

  return (
    <div
      className={cn(
        "flex flex-col items-center justify-between gap-3 border-t border-border/60 pt-4 sm:flex-row",
        className
      )}
    >
      <p className="text-xs text-muted-foreground">
        Showing <span className="font-medium text-foreground">{rangeStart}</span>
        {"\u2013"}
        <span className="font-medium text-foreground">{rangeEnd}</span> of{" "}
        <span className="font-medium text-foreground">{total}</span> jobs
      </p>

      <div className="flex items-center gap-3">
        <nav aria-label="Pagination" className="flex items-center gap-1">
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            disabled={currentPage <= 1}
            onClick={() => onPageChange(currentPage - 1)}
            aria-label="Previous page"
          >
            <ChevronLeftIcon className="size-4" aria-hidden="true" />
          </Button>

          {pageWindow.map((token, index) =>
            token === "ellipsis" ? (
              <span
                key={`ellipsis-${index}`}
                className="px-1 text-xs text-muted-foreground"
              >
                …
              </span>
            ) : (
              <Button
                key={token}
                type="button"
                variant={token === currentPage ? "default" : "ghost"}
                size="icon-sm"
                onClick={() => onPageChange(token)}
                aria-current={token === currentPage ? "page" : undefined}
                aria-label={`Page ${token}`}
              >
                {token}
              </Button>
            )
          )}

          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            disabled={currentPage >= totalPages}
            onClick={() => onPageChange(currentPage + 1)}
            aria-label="Next page"
          >
            <ChevronRightIcon className="size-4" aria-hidden="true" />
          </Button>
        </nav>

        <JobFilterSelect
          value={String(pageSize)}
          options={PAGE_SIZE_OPTIONS}
          onChange={(value) => onPageSizeChange(Number(value))}
        />
      </div>
    </div>
  )
}
