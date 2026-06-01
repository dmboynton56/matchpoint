import { useEffect, useState } from "react"
import { toast } from "sonner"

import {
  changeEmailWithPassword,
  getProfilePreferences,
  updateProfilePreferences,
} from "@/auth/supabaseAuth"
import { AppShell } from "@/components/layout/AppShell"
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

const WORK_MODE_OPTIONS = ["Remote", "Hybrid", "On-site"]

function parseCommaList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
}

export function ProfilePage() {
  const { user } = useAuth()

  const [targetRole, setTargetRole] = useState("")
  const [preferredLocations, setPreferredLocations] = useState("")
  const [preferredWorkModes, setPreferredWorkModes] = useState<string[]>([])
  const [minimumBaseSalary, setMinimumBaseSalary] = useState("")
  const [savedPreferenceKey, setSavedPreferenceKey] = useState("")
  const [profileLoading, setProfileLoading] = useState(true)
  const [preferencesSaving, setPreferencesSaving] = useState(false)

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
          preferredWorkModes: preferences.preferred_work_modes,
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
          preferredWorkModes,
          minimumBaseSalary: salary,
        })
      )
      toast.success("Preferences saved.", { position: "top-center" })
    } finally {
      setPreferencesSaving(false)
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

  const resumePlaceholder = () => {
    toast.message("Resume upload — coming soon", { position: "top-center" })
  }

  if (!user) {
    return null
  }

  const currentPreferenceKey = JSON.stringify({
    targetRole: targetRole.trim(),
    preferredLocations: parseCommaList(preferredLocations).join(", "),
    preferredWorkModes,
    minimumBaseSalary: minimumBaseSalary.trim(),
  })
  const preferencesChanged = currentPreferenceKey !== savedPreferenceKey

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
                      <input
                        type="checkbox"
                        className="size-4 accent-primary"
                        disabled={profileLoading}
                        checked={preferredWorkModes.includes(mode)}
                        onChange={() => toggleWorkMode(mode)}
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

          <Card>
            <CardHeader>
              <CardTitle>Resume</CardTitle>
              <CardDescription>
                View your resume, re-upload it, or delete it.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="rounded-lg border border-dashed border-border bg-muted/30 px-4 py-8 text-center text-sm text-muted-foreground">
                No resume on file — preview coming soon
              </div>
            </CardContent>
            <CardFooter className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={resumePlaceholder}
              >
                View
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={resumePlaceholder}
              >
                Re-upload
              </Button>
              <Button
                type="button"
                variant="destructive"
                onClick={resumePlaceholder}
              >
                Delete
              </Button>
            </CardFooter>
          </Card>
        </div>
      </div>
    </AppShell>
  )
}
