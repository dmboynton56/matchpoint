import { useState } from "react"
import { Heart, HeartOff } from "lucide-react"
import { toast } from "sonner"

import {
  toggleMatchFavorite,
  toggleSavedJobFavorite,
  type MatchUpdateResponse,
} from "@/apis/matches"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

type FavoriteJobHeartButtonProps = {
  matchId?: string
  jobId?: string
  onUnfavorited: () => void
  className?: string
}

export function FavoriteJobHeartButton({
  matchId,
  jobId,
  onUnfavorited,
  className,
}: FavoriteJobHeartButtonProps) {
  const [saving, setSaving] = useState(false)

  const handleClick = async () => {
    setSaving(true)
    try {
      let result: MatchUpdateResponse | null = null
      if (jobId) {
        result = await toggleSavedJobFavorite(jobId)
      } else if (matchId) {
        result = await toggleMatchFavorite(matchId)
      }
      if (!result) {
        toast.error("Unable to remove favorite for this job.")
        return
      }
      if (result.is_favorited) {
        toast.message("Still in favorites.")
        return
      }
      onUnfavorited()
      toast.success("Removed from favorites.")
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to remove favorite."
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
          aria-label="Remove from favorites"
          onClick={() => void handleClick()}
        >
          <Heart
            className="size-5 fill-red-500 text-red-500 group-hover:hidden"
            aria-hidden="true"
          />
          <HeartOff
            className="hidden size-5 text-muted-foreground group-hover:block"
            aria-hidden="true"
          />
        </button>
      </TooltipTrigger>
      <TooltipContent side="left" sideOffset={8}>
        Click this heart to unfavorite this job
      </TooltipContent>
    </Tooltip>
  )
}
