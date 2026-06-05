import { useState } from "react"
import { toast } from "sonner"

import { deleteMatch, toggleMatchApplied, toggleMatchFavorite } from "@/apis/matches"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
} from "@/components/ui/drawer"
import type { JobListing } from "@/types/job"

type JobApplyFollowUpDrawerProps = {
  job: JobListing | null
  matchId?: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
  isAuthenticated: boolean
  onSignUpClick: () => void
  onFavorited?: (isFavorited: boolean) => void
  onApplied?: (isApplied: boolean) => void
  onDeleted?: (matchId: string) => void
}

export function JobApplyFollowUpDrawer({
  job,
  matchId,
  open,
  onOpenChange,
  isAuthenticated,
  onSignUpClick,
  onFavorited,
  onApplied,
  onDeleted,
}: JobApplyFollowUpDrawerProps) {
  const [favoriteSaving, setFavoriteSaving] = useState(false)
  const [appliedSaving, setAppliedSaving] = useState(false)
  const [deleteSaving, setDeleteSaving] = useState(false)
  const close = () => onOpenChange(false)

  const handleDeleteMatch = async () => {
    if (!matchId) {
      toast.error("Could not remove this job. Try again from your matches.")
      return
    }

    setDeleteSaving(true)
    try {
      await deleteMatch(matchId)
      onDeleted?.(matchId)
      toast.success("Job removed from your matches.")
      close()
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to remove job."
      toast.error(message)
    } finally {
      setDeleteSaving(false)
    }
  }

  const handleMarkApplied = async () => {
    if (!matchId) {
      toast.error("Could not mark this job as applied. Try again from your matches.")
      return
    }

    setAppliedSaving(true)
    try {
      const result = await toggleMatchApplied(matchId)
      onApplied?.(result.is_applied ?? true)
      toast.success(
        result.is_applied
          ? "Marked as applied."
          : "Removed from applied jobs."
      )
      close()
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to update applied status."
      toast.error(message)
    } finally {
      setAppliedSaving(false)
    }
  }

  const handleMarkFavorite = async () => {
    if (!matchId) {
      toast.error("Could not favorite this job. Try again from your matches.")
      return
    }

    setFavoriteSaving(true)
    try {
      const result = await toggleMatchFavorite(matchId)
      onFavorited?.(result.is_favorited ?? true)
      toast.success(
        result.is_favorited
          ? "Added to favorites."
          : "Removed from favorites."
      )
      close()
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to update favorite."
      toast.error(message)
    } finally {
      setFavoriteSaving(false)
    }
  }

  return (
    <Drawer open={open} onOpenChange={onOpenChange}>
      <DrawerContent>
        <DrawerHeader>
          <DrawerTitle>
            {isAuthenticated
              ? "Track this application?"
              : "Save your progress?"}
          </DrawerTitle>
          <DrawerDescription>
            {job
              ? `${job.title} at ${job.company}`
              : isAuthenticated
                ? "Update how you want to track this role."
                : "Create an account to track applications and favorites."}
          </DrawerDescription>
        </DrawerHeader>
        {isAuthenticated ? (
          <DrawerFooter className="flex flex-col items-center justify-center gap-2 pt-0 md:flex-row md:gap-4">
            <Button
              type="button"
              className="w-full max-w-56 md:w-auto"
              disabled={appliedSaving || !matchId}
              onClick={() => void handleMarkApplied()}
            >
              {appliedSaving
                ? "Saving…"
                : job?.is_applied
                  ? "Remove from applied"
                  : "Mark as applied"}
            </Button>
            <Button
              type="button"
              variant="secondary"
              className="w-full max-w-56 md:w-auto"
              disabled={favoriteSaving || !matchId}
              onClick={() => void handleMarkFavorite()}
            >
              {favoriteSaving
                ? "Saving…"
                : job?.is_favorited
                  ? "Remove from favorites"
                  : "Mark as favorite"}
            </Button>
            <DrawerClose asChild>
              <Button
                type="button"
                variant="outline"
                className="w-full max-w-56 md:w-auto"
              >
                Done
              </Button>
            </DrawerClose>
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  type="button"
                  variant="destructive"
                  className="w-full max-w-56 md:w-auto"
                  disabled={deleteSaving || !matchId}
                >
                  Delete this job
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Remove this job?</AlertDialogTitle>
                  <AlertDialogDescription>
                    {job
                      ? `This removes ${job.title} at ${job.company} from your matches. You can't undo this.`
                      : "This removes the job from your matches. You can't undo this."}
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction
                    variant="destructive"
                    disabled={deleteSaving || !matchId}
                    onClick={() => void handleDeleteMatch()}
                  >
                    {deleteSaving ? "Removing…" : "Confirm"}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </DrawerFooter>
        ) : (
          <DrawerFooter className="flex flex-col items-center gap-2 pt-0">
            <Button
              type="button"
              className="w-full max-w-56"
              onClick={() => {
                close()
                onSignUpClick()
              }}
            >
              Sign up
            </Button>
            <DrawerClose asChild>
              <Button
                type="button"
                variant="outline"
                className="w-full max-w-56"
              >
                Cancel
              </Button>
            </DrawerClose>
          </DrawerFooter>
        )}
      </DrawerContent>
    </Drawer>
  )
}
