import { useState } from "react"
import { ChevronDown } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { cn } from "@/lib/utils"

type PayRangeFilterProps = {
  payMin: number | null
  payMax: number | null
  onChange: (payMin: number | null, payMax: number | null) => void
  className?: string
}

function formatTriggerLabel(min: number | null, max: number | null): string {
  if (min == null && max == null) return "Pay range"
  const fmt = (value: number) =>
    value >= 1000 ? `$${Math.round(value / 1000)}k` : `$${value}`
  if (min != null && max != null) return `${fmt(min)}\u2013${fmt(max)}`
  if (min != null) return `${fmt(min)}+`
  return `Up to ${fmt(max!)}`
}

export function PayRangeFilter({
  payMin,
  payMax,
  onChange,
  className,
}: PayRangeFilterProps) {
  const [minInput, setMinInput] = useState(payMin?.toString() ?? "")
  const [maxInput, setMaxInput] = useState(payMax?.toString() ?? "")
  const hasValue = payMin != null || payMax != null

  const apply = () => {
    const parsedMin = minInput.trim() ? Number(minInput) : null
    const parsedMax = maxInput.trim() ? Number(maxInput) : null
    onChange(
      parsedMin != null && !Number.isNaN(parsedMin) ? parsedMin : null,
      parsedMax != null && !Number.isNaN(parsedMax) ? parsedMax : null
    )
  }

  const clear = () => {
    setMinInput("")
    setMaxInput("")
    onChange(null, null)
  }

  return (
    <Popover
      onOpenChange={(open) => {
        if (!open) apply()
      }}
    >
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className={cn(
            "h-8 gap-1.5 text-xs font-medium",
            hasValue && "border-primary/40 bg-primary/5 text-primary",
            className
          )}
        >
          {formatTriggerLabel(payMin, payMax)}
          <ChevronDown className="size-3.5" aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64">
        <p className="text-xs font-medium text-muted-foreground">
          Annual pay (USD)
        </p>
        <div className="flex items-center gap-2">
          <div className="flex-1 space-y-1">
            <Label htmlFor="pay-min" className="text-xs text-muted-foreground">
              Min
            </Label>
            <Input
              id="pay-min"
              type="number"
              inputMode="numeric"
              placeholder="0"
              value={minInput}
              onChange={(event) => setMinInput(event.target.value)}
              onBlur={apply}
            />
          </div>
          <div className="flex-1 space-y-1">
            <Label htmlFor="pay-max" className="text-xs text-muted-foreground">
              Max
            </Label>
            <Input
              id="pay-max"
              type="number"
              inputMode="numeric"
              placeholder="Any"
              value={maxInput}
              onChange={(event) => setMaxInput(event.target.value)}
              onBlur={apply}
            />
          </div>
        </div>
        {hasValue ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="w-full text-xs"
            onClick={clear}
          >
            Clear
          </Button>
        ) : null}
      </PopoverContent>
    </Popover>
  )
}
