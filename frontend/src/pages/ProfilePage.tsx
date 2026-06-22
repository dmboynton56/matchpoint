import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { ExternalLink, FileText, Trash2, Upload } from "lucide-react"
import { toast } from "sonner"

import { recalculateMyMatches } from "@/apis/matches"
import {
  deleteResume,
  getResumeDetails,
  type ResumeDetailsResponse,
  uploadResume,
} from "@/apis/resumes"
import {
  changeEmailWithPassword,
  getProfilePreferences,
  updateProfilePreferences,
} from "@/auth/supabaseAuth"
import { AppShell } from "@/components/layout/AppShell"
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
import { Checkbox } from "@/components/ui/checkbox"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useAuth } from "@/hooks/useAuth"

const WORK_MODE_OPTIONS = ["Remote", "Hybrid", "On-site"]

function sortWorkModes(modes: string[]): string[] {
  return [...modes].sort()
}

function parseCommaList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
}

export function ProfilePage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const resumeInputRef = useRef<HTMLInputElement>(null)

  const [targetRole, setTargetRole] = useState("")
  const [preferredLocations, setPreferredLocations] = useState("")
  const [preferredWorkModes, setPreferredWorkModes] = useState<string[]>([])
  const [minimumBaseSalary, setMinimumBaseSalary] = useState("")
  const [savedPreferenceKey, setSavedPreferenceKey] = useState("")
  const [profileLoading, setProfileLoading] = useState(true)
  const [preferencesSaving, setPreferencesSaving] = useState(false)
  const [preferenceRecalcDialogOpen, setPreferenceRecalcDialogOpen] =
    useState(false)
  const [matchesRecalculating, setMatchesRecalculating] = useState(false)

  const [newEmail, setNewEmail] = useState("")
  const [emailPassword, setEmailPassword] = useState("")
  const [emailSaving, setEmailSaving] = useState(false)
  const [resume, setResume] = useState<ResumeDetailsResponse | null>(null)
  const [resumeLoading, setResumeLoading] = useState(true)
  const [resumeUploading, setResumeUploading] = useState(false)
  const [resumeDeleting, setResumeDeleting] = useState(false)
  const [resumeMutationPending, setResumeMutationPending] = useState(false)

  const refreshResume = useCallback(async (showLoading = true) => {
    if (showLoading) {
      setResumeLoading(true)
    }
    try {
      setResume(await getResumeDetails())
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Could not load resume."
      toast.error(message, { position: "top-center" })
    } finally {
      setResumeLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!user) return

    let cancelled = false
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setProfileLoading(true)

    void getProfilePreferences(user.id).then((result) => {
      if (cancelled) return
      if (!result.ok) {
        toast.error(result.message, { position: "top-center" })
        setProfileLoading(false)
        return
      }
      const preferences = result.data
      const locations = preferences.preferred_locations.join(", ")
      const salary = preferences.minimum_base_salary?.toString() ?? ""
      setTargetRole(preferences.target_role ?? "")
      setPreferredLocations(locations)
      setPreferredWorkModes(preferences.preferred_work_modes)
      setMinimumBaseSalary(salary)
      setSavedPreferenceKey(
        JSON.stringify({
          targetRole: preferences.target_role ?? "",
          preferredLocations: locations,
          preferredWorkModes: sortWorkModes(preferences.preferred_work_modes),
          minimumBaseSalary: salary,
        })
      )
      setProfileLoading(false)
    })

    return () => {
      cancelled = true
    }
  }, [user])

  useEffect(() => {
    if (!user) return

    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refreshResume(false)
  }, [refreshResume, user])

  const handleSavePreferences = async () => {
    if (!user) return

    const salary = minimumBaseSalary.trim()
    if (salary && !/^\d+$/.test(salary)) {
      toast.error("Enter minimum base salary as a whole number.", {
        position: "top-center",
      })
      return
    }

    const preferences = {
      target_role: targetRole,
      preferred_locations: parseCommaList(preferredLocations),
      preferred_work_modes: preferredWorkModes,
      minimum_base_salary: salary ? Number(salary) : null,
      salary_currency: "USD",
    }

    setPreferencesSaving(true)
    try {
      const result = await updateProfilePreferences(user.id, preferences)
      if (!result.ok) {
        toast.error(result.message, { position: "top-center" })
        return
      }
      setSavedPreferenceKey(
        JSON.stringify({
          targetRole: targetRole.trim(),
          preferredLocations: preferences.preferred_locations.join(", "),
          preferredWorkModes: sortWorkModes(preferredWorkModes),
          minimumBaseSalary: salary,
        })
      )
      if (resume?.has_resume) {
        setPreferenceRecalcDialogOpen(true)
      } else {
        toast.success("Preferences saved.", { position: "top-center" })
      }
    } finally {
      setPreferencesSaving(false)
    }
  }

  const handleRecalculateMatches = async () => {
    setMatchesRecalculating(true)
    try {
      const response = await recalculateMyMatches()
      setPreferenceRecalcDialogOpen(false)
      toast.success("Matches recalculated.", { position: "top-center" })
      navigate("/jobs", { state: { jobs: response.jobs } })
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Match recalculation failed."
      toast.error(message, { position: "top-center" })
    } finally {
      setMatchesRecalculating(false)
    }
  }

  const toggleWorkMode = (mode: string) => {
    setPreferredWorkModes((current) =>
      current.includes(mode)
        ? current.filter((item) => item !== mode)
        : [...current, mode]
    )
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

  const handleViewResume = () => {
    if (!resume?.signed_url) return

    window.open(resume.signed_url, "_blank", "noopener,noreferrer")
  }

  const handleResumeUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ""

    if (!file) return
    if (file.type !== "application/pdf") {
      toast.error("Only PDF files are supported.", { position: "top-center" })
      return
    }

    setResumeMutationPending(true)
    setResumeUploading(true)
    try {
      const response = await uploadResume(file)
      await refreshResume()
      toast.success("Resume updated.", { position: "top-center" })
      navigate("/jobs", { state: { jobs: response.jobs } })
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Resume upload failed."
      toast.error(message, { position: "top-center" })
    } finally {
      setResumeUploading(false)
      setResumeMutationPending(false)
    }
  }

  const handleDeleteResume = async () => {
    setResumeMutationPending(true)
    setResumeDeleting(true)
    try {
      await deleteResume()
      await refreshResume()
      toast.success("Resume deleted.", { position: "top-center" })
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Resume delete failed."
      toast.error(message, { position: "top-center" })
    } finally {
      setResumeDeleting(false)
      setResumeMutationPending(false)
    }
  }

  if (!user) {
    return null
  }

  const currentPreferenceKey = JSON.stringify({
    targetRole: targetRole.trim(),
    preferredLocations: parseCommaList(preferredLocations).join(", "),
    preferredWorkModes: sortWorkModes(preferredWorkModes),
    minimumBaseSalary: minimumBaseSalary.trim(),
  })
  const preferencesChanged = currentPreferenceKey !== savedPreferenceKey
  const resumeUploadedAt =
    resume?.uploaded_at === null || resume?.uploaded_at === undefined
      ? null
      : new Intl.DateTimeFormat(undefined, {
          month: "short",
          day: "numeric",
          year: "numeric",
        }).format(new Date(resume.uploaded_at))

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-5xl space-y-8">
        <section className="space-y-2">
          <p className="text-xs font-semibold tracking-[0.22em] text-primary uppercase">
            Account
          </p>
          <h1 className="font-heading text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
            Profile
          </h1>
          <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base">
            Update your email, match preferences, and resume.
          </p>
        </section>

        <div className="grid gap-6 md:grid-cols-2">
          <Card className="h-fit">
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
                <Button
                  type="submit"
                  disabled={
                    emailSaving ||
                    !newEmail ||
                    !emailPassword ||
                    newEmail === user.email
                  }
                  className="w-full md:w-auto"
                >
                  {emailSaving ? "Saving…" : "Update email"}
                </Button>
              </CardFooter>
            </form>
          </Card>

          <Card className="h-fit">
            <CardHeader>
              <CardTitle>Match preferences</CardTitle>
              <CardDescription>
                Used to ground role, location, and pay fit.
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
              <div className="grid gap-2">
                <Label htmlFor="preferred-locations">Preferred locations</Label>
                <Input
                  id="preferred-locations"
                  type="text"
                  placeholder="e.g. Denver, Remote US"
                  disabled={profileLoading}
                  value={preferredLocations}
                  onChange={(e) => setPreferredLocations(e.target.value)}
                />
              </div>
              <div className="grid gap-2">
                <Label>Work mode</Label>
                <div className="flex flex-wrap gap-3">
                  {WORK_MODE_OPTIONS.map((mode) => (
                    <label
                      key={mode}
                      className="flex items-center gap-2 text-sm text-foreground"
                    >
                      <Checkbox
                        disabled={profileLoading}
                        checked={preferredWorkModes.includes(mode)}
                        onCheckedChange={() => toggleWorkMode(mode)}
                      />
                      {mode}
                    </label>
                  ))}
                </div>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="minimum-base-salary">Minimum base salary</Label>
                <Input
                  id="minimum-base-salary"
                  type="text"
                  inputMode="numeric"
                  placeholder="e.g. 160000"
                  disabled={profileLoading}
                  value={minimumBaseSalary}
                  onChange={(e) => setMinimumBaseSalary(e.target.value)}
                />
              </div>
            </CardContent>
            <CardFooter>
              <Button
                type="button"
                disabled={
                  profileLoading || preferencesSaving || !preferencesChanged
                }
                onClick={() => void handleSavePreferences()}
              >
                {preferencesSaving ? "Saving…" : "Save preferences"}
              </Button>
            </CardFooter>
          </Card>

          <Card className="h-fit md:col-start-1">
            <CardHeader>
              <CardTitle>Resume</CardTitle>
              <CardDescription>
                View your resume, re-upload it, or delete it.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {resumeLoading ? (
                <div className="flex h-72 items-center justify-center rounded-lg border border-dashed border-border bg-muted/30 text-sm text-muted-foreground">
                  Loading resume…
                </div>
              ) : resume?.has_resume && resume.signed_url ? (
                <div className="space-y-3">
                  <div
                    role="button"
                    tabIndex={0}
                    className="group relative h-72 w-full overflow-hidden rounded-lg border border-border bg-muted/30 text-left"
                    onClick={handleViewResume}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault()
                        handleViewResume()
                      }
                    }}
                    aria-label="Open uploaded resume"
                  >
                    <iframe
                      title="Uploaded resume preview"
                      src={`${resume.signed_url}#page=1&toolbar=0&navpanes=0&scrollbar=0`}
                      className="pointer-events-none h-full w-full bg-white"
                    />
                    <span className="absolute inset-0 bg-transparent transition-colors group-hover:bg-background/10" />
                  </div>
                  <div className="flex items-center gap-3 text-sm">
                    <FileText
                      className="size-4 shrink-0 text-muted-foreground"
                      aria-hidden="true"
                    />
                    <div className="min-w-0">
                      <p className="truncate font-medium text-foreground">
                        {resume.file_name ?? "resume.pdf"}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {resumeUploadedAt
                          ? `Uploaded ${resumeUploadedAt}`
                          : "Uploaded resume on file"}
                      </p>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="flex h-72 flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border bg-muted/30 px-4 text-center text-sm text-muted-foreground">
                  <FileText className="size-8" aria-hidden="true" />
                  No resume on file
                </div>
              )}
              <input
                ref={resumeInputRef}
                type="file"
                accept="application/pdf"
                className="hidden"
                disabled={resumeMutationPending}
                onChange={(e) => void handleResumeUpload(e)}
              />
            </CardContent>
            <CardFooter className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={!resume?.has_resume || !resume.signed_url}
                onClick={handleViewResume}
              >
                <ExternalLink className="size-4" aria-hidden="true" />
                View
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={resumeUploading || resumeMutationPending}
                onClick={() => resumeInputRef.current?.click()}
              >
                <Upload className="size-4" aria-hidden="true" />
                {resume?.has_resume ? "Re-upload" : "Upload"}
              </Button>
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button
                    type="button"
                    variant="destructive"
                    disabled={
                      !resume?.has_resume ||
                      resumeDeleting ||
                      resumeMutationPending
                    }
                  >
                    <Trash2 className="size-4" aria-hidden="true" />
                    Delete
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Delete resume?</AlertDialogTitle>
                    <AlertDialogDescription>
                      This removes your uploaded resume from your profile. You
                      can upload a new one anytime.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction
                      variant="destructive"
                      disabled={resumeDeleting || resumeMutationPending}
                      onClick={() => void handleDeleteResume()}
                    >
                      Confirm
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </CardFooter>
          </Card>
        </div>
      </div>

      <Dialog
        open={preferenceRecalcDialogOpen}
        onOpenChange={(open) => {
          if (!matchesRecalculating) setPreferenceRecalcDialogOpen(open)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Recalculate matches?</DialogTitle>
            <DialogDescription>
              Your preferences were saved. Recalculate matches now, or wait
              until the next scheduled refresh?
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={matchesRecalculating}
              onClick={() => setPreferenceRecalcDialogOpen(false)}
            >
              Wait until refresh
            </Button>
            <Button
              type="button"
              disabled={matchesRecalculating}
              onClick={() => void handleRecalculateMatches()}
            >
              {matchesRecalculating ? "Recalculating..." : "Recalculate now"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AppShell>
  )
}
