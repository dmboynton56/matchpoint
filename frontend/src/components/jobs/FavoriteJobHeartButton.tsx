import { useState } from "react"
import { Heart, HeartOff } from "lucide-react"
import { toast } from "sonner"

import { toggleMatchFavorite } from "@/apis/matches"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

type FavoriteJobHeartButtonProps = {
  matchId: string
  onUnfavorited: () => void
  className?: string
}

export function FavoriteJobHeartButton({
  matchId,
  onUnfavorited,
  className,
}: FavoriteJobHeartButtonProps) {
  const [saving, setSaving] = useState(false)

  const handleClick = async () => {
    setSaving(true)
    try {
      const result = await toggleMatchFavorite(matchId)
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
          disabled={saving}
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
