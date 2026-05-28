import { useEffect, useState } from "react"
import { toast } from "sonner"

import {
  changeEmailWithPassword,
  getProfileTargetRole,
  updateProfileTargetRole,
} from "@/auth/supabaseAuth"
import {
  deleteResume,
  getResumeSignedUrl,
  resumeExists,
} from "@/apis/resumes"
import { AppShell } from "@/components/layout/AppShell"
import UploadDropzone from "@/components/user/UploadDropzone"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useAuth } from "@/hooks/useAuth"

export function ProfilePage() {
  const { user } = useAuth()

  const [targetRole, setTargetRole] = useState("")
  const [savedTargetRole, setSavedTargetRole] = useState("")
  const [profileLoading, setProfileLoading] = useState(true)
  const [targetRoleSaving, setTargetRoleSaving] = useState(false)

  const [newEmail, setNewEmail] = useState("")
  const [emailPassword, setEmailPassword] = useState("")
  const [emailSaving, setEmailSaving] = useState(false)

  const [resumeStatus, setResumeStatus] = useState<"unknown" | "none" | "ready">(
    "unknown"
  )
  const [resumeLoading, setResumeLoading] = useState(true)
  const [resumeViewing, setResumeViewing] = useState(false)
  const [resumeDeleting, setResumeDeleting] = useState(false)
  const [showReupload, setShowReupload] = useState(false)

  useEffect(() => {
    if (!user) return

    let cancelled = false
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setProfileLoading(true)

    void getProfileTargetRole(user.id).then((result) => {
      if (cancelled) return
      if (!result.ok) {
        toast.error(result.message, { position: "top-center" })
        setProfileLoading(false)
        return
      }
      const value = result.data ?? ""
      setTargetRole(value)
      setSavedTargetRole(value)
      setProfileLoading(false)
    })

    return () => {
      cancelled = true
    }
  }, [user])

  useEffect(() => {
    if (!user) return

    let cancelled = false
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setResumeLoading(true)

    void resumeExists(user.id).then((exists) => {
      if (cancelled) return
      setResumeStatus(exists ? "ready" : "none")
      setResumeLoading(false)
    })

    return () => {
      cancelled = true
    }
  }, [user])

  const handleSaveTargetRole = async () => {
    if (!user) return

    setTargetRoleSaving(true)
    try {
      const result = await updateProfileTargetRole(user.id, targetRole)
      if (!result.ok) {
        toast.error(result.message, { position: "top-center" })
        return
      }
      setSavedTargetRole(targetRole.trim())
      toast.success("Target role saved.", { position: "top-center" })
    } finally {
      setTargetRoleSaving(false)
    }
  }

  const handleChangeEmail = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!user?.email) return

    setEmailSaving(true)
    try {
      const result = await changeEmailWithPassword(
        user.email,
        emailPassword,
        newEmail
      )
      if (!result.ok) {
        toast.error(result.message, { position: "top-center" })
        return
      }
      setNewEmail("")
      setEmailPassword("")
      toast.success("Email updated.", { position: "top-center" })
    } finally {
      setEmailSaving(false)
    }
  }

  const handleViewResume = async () => {
    if (!user) return

    setResumeViewing(true)
    try {
      const signedUrl = await getResumeSignedUrl(user.id)
      window.open(signedUrl, "_blank", "noopener,noreferrer")
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Could not open resume."
      toast.error(message, { position: "top-center" })
    } finally {
      setResumeViewing(false)
    }
  }

  const handleDeleteResume = async () => {
    if (!user) return

    setResumeDeleting(true)
    try {
      await deleteResume()
      setResumeStatus("none")
      setShowReupload(false)
      toast.success("Resume deleted.", { position: "top-center" })
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Could not delete resume."
      toast.error(message, { position: "top-center" })
    } finally {
      setResumeDeleting(false)
    }
  }

  const handleResumeUploadSuccess = () => {
    setResumeStatus("ready")
    setShowReupload(false)
  }

  if (!user) {
    return null
  }

  const targetRoleChanged = targetRole.trim() !== savedTargetRole.trim()

  return (
    <AppShell>
      <div className="space-y-8">
        <section className="space-y-2">
          <p className="text-xs font-semibold tracking-[0.22em] text-primary uppercase">
            Account
          </p>
          <h1 className="font-heading text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
            Profile
          </h1>
          <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base">
            Update your email, target role, and resume settings.
          </p>
        </section>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Email</CardTitle>
              <CardDescription>
                Current email: {user.email ?? "—"}
              </CardDescription>
            </CardHeader>
            <form onSubmit={handleChangeEmail}>
              <CardContent className="flex flex-col gap-4 pb-4">
                <div className="grid gap-2">
                  <Label htmlFor="new-email">New email</Label>
                  <Input
                    id="new-email"
                    type="email"
                    autoComplete="email"
                    required
                    value={newEmail}
                    onChange={(e) => setNewEmail(e.target.value)}
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="email-password">Current password</Label>
                  <Input
                    id="email-password"
                    type="password"
                    autoComplete="current-password"
                    required
                    value={emailPassword}
                    onChange={(e) => setEmailPassword(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    Re-enter your password to confirm this change.
                  </p>
                </div>
              </CardContent>
              <CardFooter>
                <Button type="submit" disabled={emailSaving}>
                  {emailSaving ? "Saving…" : "Update email"}
                </Button>
              </CardFooter>
            </form>
          </Card>

          <Card className="h-fit">
            <CardHeader>
              <CardTitle>Target role</CardTitle>
              <CardDescription>
                The role you are aiming for (used for job matching).
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="grid gap-2">
                <Label htmlFor="target-role">Target role</Label>
                <Input
                  id="target-role"
                  type="text"
                  placeholder="e.g. Software Engineer"
                  disabled={profileLoading}
                  value={targetRole}
                  onChange={(e) => setTargetRole(e.target.value)}
                />
              </div>
            </CardContent>
            <CardFooter>
              <Button
                type="button"
                disabled={
                  profileLoading || targetRoleSaving || !targetRoleChanged
                }
                onClick={() => void handleSaveTargetRole()}
              >
                {targetRoleSaving ? "Saving…" : "Save target role"}
              </Button>
            </CardFooter>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Resume</CardTitle>
              <CardDescription>
                View your resume, re-upload it, or delete it.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="rounded-lg border border-dashed border-border bg-muted/30 px-4 py-8 text-center text-sm text-muted-foreground">
                {resumeLoading
                  ? "Checking resume status…"
                  : resumeStatus === "ready"
                    ? "Resume on file (PDF)"
                    : "No resume on file"}
              </div>
              {showReupload && (
                <UploadDropzone
                  navigateAfterUpload={false}
                  onUploadSuccess={handleResumeUploadSuccess}
                />
              )}
            </CardContent>
            <CardFooter className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={resumeLoading || resumeStatus !== "ready" || resumeViewing}
                onClick={() => void handleViewResume()}
              >
                {resumeViewing ? "Opening…" : "View"}
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={resumeLoading}
                onClick={() => setShowReupload((current) => !current)}
              >
                {showReupload ? "Cancel re-upload" : "Re-upload"}
              </Button>
              <Button
                type="button"
                variant="destructive"
                disabled={
                  resumeLoading || resumeStatus !== "ready" || resumeDeleting
                }
                onClick={() => void handleDeleteResume()}
              >
                {resumeDeleting ? "Deleting…" : "Delete"}
              </Button>
            </CardFooter>
          </Card>
        </div>
      </div>
    </AppShell>
  )
}
