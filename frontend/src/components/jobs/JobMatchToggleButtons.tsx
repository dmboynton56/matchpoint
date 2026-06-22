import { useState } from "react"
import { ClipboardCheck, Heart } from "lucide-react"
import { toast } from "sonner"

import { toggleMatchApplied, toggleMatchFavorite } from "@/apis/matches"
import { Button } from "@/components/ui/button"

type JobMatchToggleButtonsProps = {
  matchId: string
  isFavorited: boolean
  isApplied: boolean
  onFavorited: (isFavorited: boolean) => void
  onApplied: (isApplied: boolean) => void
}

export function JobMatchToggleButtons({
  matchId,
  isFavorited,
  isApplied,
  onFavorited,
  onApplied,
}: JobMatchToggleButtonsProps) {
  const [favoriteSaving, setFavoriteSaving] = useState(false)
  const [appliedSaving, setAppliedSaving] = useState(false)

  const handleFavoriteToggle = async () => {
    setFavoriteSaving(true)
    try {
      const result = await toggleMatchFavorite(matchId)
      if (result.is_favorited === undefined) {
        throw new Error("Invalid response from server")
      }
      onFavorited(result.is_favorited)
      toast.success(
        result.is_favorited ? "Added to favorites." : "Removed from favorites."
      )
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to update favorite."
      toast.error(message)
    } finally {
      setFavoriteSaving(false)
    }
  }

  const handleAppliedToggle = async () => {
    setAppliedSaving(true)
    try {
      const result = await toggleMatchApplied(matchId)
      if (result.is_applied === undefined) {
        throw new Error("Invalid response from server")
      }
      onApplied(result.is_applied)
      toast.success(
        result.is_applied ? "Marked as applied." : "Removed from applied jobs."
      )
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Failed to update applied status."
      toast.error(message)
    } finally {
      setAppliedSaving(false)
    }
  }

  return (
    <>
      <Button
        type="button"
        size="sm"
        variant={isApplied ? "default" : "outline"}
        className="h-8 gap-1.5 text-xs font-medium"
        disabled={appliedSaving}
        onClick={() => void handleAppliedToggle()}
      >
        <ClipboardCheck className="size-3.5" aria-hidden="true" />
        {appliedSaving ? "Saving…" : isApplied ? "Applied" : "Mark applied"}
      </Button>
      <Button
        type="button"
        size="sm"
        variant={isFavorited ? "secondary" : "outline"}
        className="h-8 gap-1.5 text-xs font-medium"
        disabled={favoriteSaving}
        onClick={() => void handleFavoriteToggle()}
      >
        <Heart
          className={isFavorited ? "size-3.5 fill-current" : "size-3.5"}
          aria-hidden="true"
        />
        {favoriteSaving ? "Saving…" : isFavorited ? "Favorited" : "Favorite"}
      </Button>
    </>
  )
}
