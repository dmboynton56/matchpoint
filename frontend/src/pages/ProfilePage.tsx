import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { toast } from "sonner"

import { recalculateMyMatches } from "@/apis/matches"
import {
  changeEmailWithPassword,
  getProfilePreferences,
  updateProfilePreferences,
} from "@/auth/supabaseAuth"
import { AppShell } from "@/components/layout/AppShell"
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
      // Always offer to recalc — preference changes affect what
      // gets matched, regardless of whether the user has a resume
      // on file (the resume state lives on the /resume page now).
      setPreferenceRecalcDialogOpen(true)
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
            Update your email and match preferences. Manage your resume and
            tailored suggestions on the Resume page.
          </p>
        </section>

        <div className="flex flex-col items-center gap-6">
          <Card className="h-fit min-w-100 md:min-w-150 lg:min-w-200">
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

          <Card className="h-fit min-w-100 md:min-w-150 lg:min-w-200">
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
