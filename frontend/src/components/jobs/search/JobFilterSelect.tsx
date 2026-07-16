import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { cn } from "@/lib/utils"

type JobFilterSelectOption<T extends string> = {
  value: T
  label: string
}

type JobFilterSelectProps<T extends string> = {
  value: T
  options: JobFilterSelectOption<T>[]
  onChange: (value: T) => void
  placeholder?: string
  className?: string
}

export function JobFilterSelect<T extends string>({
  value,
  options,
  onChange,
  placeholder,
  className,
}: JobFilterSelectProps<T>) {
  return (
    <Select value={value} onValueChange={(next) => onChange(next as T)}>
      <SelectTrigger
        size="sm"
        className={cn("h-8 text-xs font-medium", className)}
      >
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
