import { toast } from "sonner"

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
  open: boolean
  onOpenChange: (open: boolean) => void
  isAuthenticated: boolean
  onSignUpClick: () => void
}

export function JobApplyFollowUpDrawer({
  job,
  open,
  onOpenChange,
  isAuthenticated,
  onSignUpClick,
}: JobApplyFollowUpDrawerProps) {
  const close = () => onOpenChange(false)

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
              onClick={() => {
                toast.message("Mark as applied — coming soon")
                close()
              }}
            >
              Mark as applied?
            </Button>
            <Button
              type="button"
              variant="secondary"
              className="w-full max-w-56 md:w-auto"
              onClick={() => {
                toast.message("Mark as favorite — coming soon")
                close()
              }}
            >
              Mark as favorite?
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
            <Button
              type="button"
              variant="destructive"
              className="w-full max-w-56 md:w-auto"
              onClick={() => {
                toast.message("Hide job — coming soon")
                close()
              }}
            >
              Delete this job?
            </Button>
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
              Sign up?
            </Button>
            <DrawerClose asChild>
              <Button type="button" variant="outline" className="w-full max-w-56">
                Cancel
              </Button>
            </DrawerClose>
          </DrawerFooter>
        )}
      </DrawerContent>
    </Drawer>
  )
}
