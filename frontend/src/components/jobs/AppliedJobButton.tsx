import { useState } from "react"
import { ClipboardCheck, ClipboardX } from "lucide-react"
import { toast } from "sonner"

import {
  toggleMatchApplied,
  toggleSavedJobApplied,
  type MatchUpdateResponse,
} from "@/apis/matches"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

type AppliedJobButtonProps = {
  matchId?: string
  jobId?: string
  onUnapplied: () => void
  className?: string
}

export function AppliedJobButton({
  matchId,
  jobId,
  onUnapplied,
  className,
}: AppliedJobButtonProps) {
  const [saving, setSaving] = useState(false)

  const handleClick = async () => {
    setSaving(true)
    try {
      let result: MatchUpdateResponse | null = null
      if (jobId) {
        result = await toggleSavedJobApplied(jobId)
      } else if (matchId) {
        result = await toggleMatchApplied(matchId)
      }
      if (!result) {
        toast.error("Unable to remove applied status for this job.")
        return
      }
      if (result.is_applied) {
        toast.message("Still marked as applied.")
        return
      }
      onUnapplied()
      toast.success("Removed from applied jobs.")
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to remove applied status."
      toast.error(message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className={cn(
            "group rounded-md p-1 outline-none transition-colors hover:bg-muted/80 focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50",
            className
          )}
          disabled={saving || (!matchId && !jobId)}
          aria-label="Remove from applied jobs"
          onClick={() => void handleClick()}
        >
          <ClipboardCheck
            className="size-5 fill-emerald-500 text-emerald-500 group-hover:hidden"
            aria-hidden="true"
          />
          <ClipboardX
            className="hidden size-5 text-muted-foreground group-hover:block"
            aria-hidden="true"
          />
        </button>
      </TooltipTrigger>
      <TooltipContent side="left" sideOffset={8}>
        Click to remove this job from applied jobs
      </TooltipContent>
    </Tooltip>
  )
}
