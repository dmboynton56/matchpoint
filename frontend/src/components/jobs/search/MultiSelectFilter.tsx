import { ChevronDown } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { cn } from "@/lib/utils"

export type MultiSelectOption<T extends string> = {
  value: T
  label: string
}

type MultiSelectFilterProps<T extends string> = {
  label: string
  options: MultiSelectOption<T>[]
  selected: T[]
  onChange: (next: T[]) => void
  className?: string
}

export function MultiSelectFilter<T extends string>({
  label,
  options,
  selected,
  onChange,
  className,
}: MultiSelectFilterProps<T>) {
  const toggle = (value: T) => {
    onChange(
      selected.includes(value)
        ? selected.filter((current) => current !== value)
        : [...selected, value]
    )
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className={cn(
            "h-8 gap-1.5 text-xs font-medium",
            selected.length > 0 && "border-primary/40 bg-primary/5 text-primary",
            className
          )}
        >
          {label}
          {selected.length > 0 ? (
            <Badge
              variant="secondary"
              className="h-5 min-w-5 justify-center px-1"
            >
              {selected.length}
            </Badge>
          ) : null}
          <ChevronDown className="size-3.5" aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-56 p-1.5">
        <ul className="max-h-64 space-y-0.5 overflow-y-auto">
          {options.map((option) => (
            <li key={option.value}>
              <label className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm text-foreground hover:bg-muted">
                <Checkbox
                  checked={selected.includes(option.value)}
                  onCheckedChange={() => toggle(option.value)}
                />
                {option.label}
              </label>
            </li>
          ))}
        </ul>
        {selected.length > 0 ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="mt-1 w-full text-xs"
            onClick={() => onChange([])}
          >
            Clear
          </Button>
        ) : null}
      </PopoverContent>
    </Popover>
  )
}
