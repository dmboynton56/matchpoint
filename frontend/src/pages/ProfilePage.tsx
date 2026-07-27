import { useEffect, useMemo, useState } from "react"
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

// Common countries with English-speaking tech markets. The set is
// hand-picked rather than auto-generated from a list so the UI stays
// short and the user can scan it. A "more..." picker could be added
// later if the user base expands beyond these.
const COUNTRY_OPTIONS = [
  { code: "US", label: "United States" },
  { code: "CA", label: "Canada" },
  { code: "GB", label: "United Kingdom" },
  { code: "DE", label: "Germany" },
  { code: "IE", label: "Ireland" },
  { code: "NL", label: "Netherlands" },
  { code: "AU", label: "Australia" },
  { code: "NZ", label: "New Zealand" },
  { code: "IN", label: "India" },
  { code: "JP", label: "Japan" },
]

// Match the values used in app/services/job_metadata.py for the
// experience_level column. The default of internship/entry/mid is
// set on the backend too, so a user who has never opened this page
// gets a sensible filter automatically.
const SENIORITY_OPTIONS = [
  { value: "internship", label: "Internship" },
  { value: "entry", label: "Entry level" },
  { value: "mid", label: "Mid level" },
  { value: "senior", label: "Senior" },
  { value: "lead", label: "Lead / Staff" },
  { value: "executive", label: "Director / VP" },
]

const DEFAULT_SENIORITY = ["internship", "entry", "mid"]
const DEFAULT_RADIUS_KM = 500

// Fixed list of valid anchor cities. Values are stored/displayed as
// "City, ST" (US Postal Service two-letter state abbreviation), which
// matches how US locations are conventionally written in job listings.
// Lat/lon are pre-resolved here so we never need to call a geocoding
// endpoint for this field, and never have to guess what string format
// a backend geocoder expects.
//
// NOTE: this list is intentionally a curated set of major US metros,
// not exhaustive. If you need a specific city added, append it below
// with { label, region (2-letter state), lat, lon }. Coordinates here
// are city-center approximations, fine for radius-based matching.
type CityOption = {
  label: string // "City, ST" — shown in the dropdown and stored as preferred_city
  region: string // 2-letter state code
  lat: number
  lon: number
}

const US_CITY_OPTIONS: CityOption[] = [
  { label: "New York, NY", region: "NY", lat: 40.7128, lon: -74.006 },
  { label: "Los Angeles, CA", region: "CA", lat: 34.0522, lon: -118.2437 },
  { label: "San Francisco, CA", region: "CA", lat: 37.7749, lon: -122.4194 },
  { label: "San Jose, CA", region: "CA", lat: 37.3382, lon: -121.8863 },
  { label: "Oakland, CA", region: "CA", lat: 37.8044, lon: -122.2711 },
  { label: "San Diego, CA", region: "CA", lat: 32.7157, lon: -117.1611 },
  { label: "Sacramento, CA", region: "CA", lat: 38.5816, lon: -121.4944 },
  { label: "Seattle, WA", region: "WA", lat: 47.6062, lon: -122.3321 },
  { label: "Portland, OR", region: "OR", lat: 45.5152, lon: -122.6784 },
  { label: "Denver, CO", region: "CO", lat: 39.7392, lon: -104.9903 },
  { label: "Boulder, CO", region: "CO", lat: 40.015, lon: -105.2705 },
  { label: "Austin, TX", region: "TX", lat: 30.2672, lon: -97.7431 },
  { label: "Dallas, TX", region: "TX", lat: 32.7767, lon: -96.797 },
  { label: "Houston, TX", region: "TX", lat: 29.7604, lon: -95.3698 },
  { label: "San Antonio, TX", region: "TX", lat: 29.4241, lon: -98.4936 },
  { label: "Chicago, IL", region: "IL", lat: 41.8781, lon: -87.6298 },
  { label: "Minneapolis, MN", region: "MN", lat: 44.9778, lon: -93.265 },
  { label: "Detroit, MI", region: "MI", lat: 42.3314, lon: -83.0458 },
  { label: "Columbus, OH", region: "OH", lat: 39.9612, lon: -82.9988 },
  { label: "Cincinnati, OH", region: "OH", lat: 39.1031, lon: -84.512 },
  { label: "Cleveland, OH", region: "OH", lat: 41.4993, lon: -81.6944 },
  { label: "Indianapolis, IN", region: "IN", lat: 39.7684, lon: -86.1581 },
  { label: "Pittsburgh, PA", region: "PA", lat: 40.4406, lon: -79.9959 },
  { label: "Philadelphia, PA", region: "PA", lat: 39.9526, lon: -75.1652 },
  { label: "Boston, MA", region: "MA", lat: 42.3601, lon: -71.0589 },
  { label: "Cambridge, MA", region: "MA", lat: 42.3736, lon: -71.1097 },
  { label: "Providence, RI", region: "RI", lat: 41.824, lon: -71.4128 },
  { label: "New Haven, CT", region: "CT", lat: 41.3083, lon: -72.9279 },
  { label: "Washington, DC", region: "DC", lat: 38.9072, lon: -77.0369 },
  { label: "Baltimore, MD", region: "MD", lat: 39.2904, lon: -76.6122 },
  { label: "Richmond, VA", region: "VA", lat: 37.5407, lon: -77.436 },
  { label: "Arlington, VA", region: "VA", lat: 38.8816, lon: -77.0910 },
  { label: "Raleigh, NC", region: "NC", lat: 35.7796, lon: -78.6382 },
  { label: "Durham, NC", region: "NC", lat: 35.994, lon: -78.8986 },
  { label: "Charlotte, NC", region: "NC", lat: 35.2271, lon: -80.8431 },
  { label: "Atlanta, GA", region: "GA", lat: 33.749, lon: -84.388 },
  { label: "Nashville, TN", region: "TN", lat: 36.1627, lon: -86.7816 },
  { label: "Miami, FL", region: "FL", lat: 25.7617, lon: -80.1918 },
  { label: "Orlando, FL", region: "FL", lat: 28.5383, lon: -81.3792 },
  { label: "Tampa, FL", region: "FL", lat: 27.9506, lon: -82.4572 },
  { label: "Phoenix, AZ", region: "AZ", lat: 33.4484, lon: -112.074 },
  { label: "Salt Lake City, UT", region: "UT", lat: 40.7608, lon: -111.891 },
  { label: "Las Vegas, NV", region: "NV", lat: 36.1699, lon: -115.1398 },
  { label: "Kansas City, MO", region: "MO", lat: 39.0997, lon: -94.5786 },
  { label: "St. Louis, MO", region: "MO", lat: 38.627, lon: -90.1994 },
  { label: "Madison, WI", region: "WI", lat: 43.0731, lon: -89.4012 },
  { label: "Milwaukee, WI", region: "WI", lat: 43.0389, lon: -87.9065 },
  { label: "Omaha, NE", region: "NE", lat: 41.2565, lon: -95.9345 },
  { label: "Boise, ID", region: "ID", lat: 43.615, lon: -116.2023 },
]

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
  const [preferredCountryCodes, setPreferredCountryCodes] = useState<string[]>([])
  // preferredCity now holds one of the fixed US_CITY_OPTIONS labels
  // (or "" for "no anchor city"), rather than free text.
  const [preferredCity, setPreferredCity] = useState("")
  const [preferredRadiusKm, setPreferredRadiusKm] = useState<string>("")
  const [targetSeniority, setTargetSeniority] = useState<string[]>(DEFAULT_SENIORITY)
  const [savedPreferenceKey, setSavedPreferenceKey] = useState("")
  const [profileLoading, setProfileLoading] = useState(true)
  const [preferencesSaving, setPreferencesSaving] = useState(false)
  const [preferenceRecalcDialogOpen, setPreferenceRecalcDialogOpen] =
    useState(false)
  const [matchesRecalculating, setMatchesRecalculating] = useState(false)

  const [newEmail, setNewEmail] = useState("")
  const [emailPassword, setEmailPassword] = useState("")
  const [emailSaving, setEmailSaving] = useState(false)

  // Look up lat/lon/region for the currently selected city from the
  // fixed list. If the saved preferred_city doesn't match any option
  // in the list (e.g. it was set before this list existed, or via a
  // different flow), we still display it, but geocodedCity resolves
  // to null and no lat/lon gets sent up on save until the user picks
  // a valid option from the dropdown.
  const geocodedCity = useMemo(
    () => US_CITY_OPTIONS.find((c) => c.label === preferredCity) ?? null,
    [preferredCity]
  )

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
      setPreferredCountryCodes(preferences.preferred_country_codes ?? [])
      setPreferredCity(preferences.preferred_city ?? "")
      setPreferredRadiusKm(
        preferences.preferred_radius_km != null
          ? preferences.preferred_radius_km.toString()
          : ""
      )
      setTargetSeniority(
        preferences.target_seniority && preferences.target_seniority.length > 0
          ? preferences.target_seniority
          : DEFAULT_SENIORITY
      )
      setSavedPreferenceKey(
        JSON.stringify({
          targetRole: preferences.target_role ?? "",
          preferredLocations: locations,
          preferredWorkModes: sortWorkModes(preferences.preferred_work_modes),
          minimumBaseSalary: salary,
          preferredCountryCodes: preferences.preferred_country_codes ?? [],
          preferredCity: preferences.preferred_city ?? "",
          preferredRadiusKm:
            preferences.preferred_radius_km != null
              ? preferences.preferred_radius_km.toString()
              : "",
          targetSeniority:
            preferences.target_seniority && preferences.target_seniority.length > 0
              ? preferences.target_seniority
              : DEFAULT_SENIORITY,
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

    const radius = preferredRadiusKm.trim()
    if (radius && !/^\d+$/.test(radius)) {
      toast.error("Enter willing-to-relocate distance as a whole number of kilometers.", {
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
      preferred_country_codes: preferredCountryCodes,
      preferred_city: preferredCity || null,
      preferred_lat: geocodedCity?.lat ?? null,
      preferred_lon: geocodedCity?.lon ?? null,
      preferred_radius_km: radius ? Number(radius) : null,
      target_seniority: targetSeniority,
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
          preferredCountryCodes: preferredCountryCodes,
          preferredCity: preferences.preferred_city ?? "",
          preferredRadiusKm: preferences.preferred_radius_km != null
            ? preferences.preferred_radius_km.toString()
            : "",
          targetSeniority: targetSeniority,
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
      navigate("/matches", { state: { jobs: response.jobs } })
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

  const toggleCountryCode = (code: string) => {
    setPreferredCountryCodes((current) =>
      current.includes(code)
        ? current.filter((c) => c !== code)
        : [...current, code]
    )
  }

  const toggleSeniority = (level: string) => {
    setTargetSeniority((current) =>
      current.includes(level)
        ? current.filter((c) => c !== level)
        : [...current, level]
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
    preferredCountryCodes: sortWorkModes(preferredCountryCodes),
    preferredCity: preferredCity,
    preferredRadiusKm: preferredRadiusKm.trim(),
    targetSeniority: sortWorkModes(targetSeniority),
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
                <Label>Preferred countries</Label>
                <p className="text-xs text-muted-foreground">
                  Leave empty to see jobs in any country. Pick at least
                  one if you want the location filter to be strict.
                </p>
                <div className="flex flex-wrap gap-2">
                  {COUNTRY_OPTIONS.map((country) => {
                    const checked = preferredCountryCodes.includes(country.code)
                    return (
                      <label
                        key={country.code}
                        className="flex items-center gap-1.5 rounded-md border border-input px-2.5 py-1.5 text-sm text-foreground cursor-pointer hover:bg-accent/40"
                      >
                        <Checkbox
                          disabled={profileLoading}
                          checked={checked}
                          onCheckedChange={() => toggleCountryCode(country.code)}
                        />
                        {country.label}
                      </label>
                    )
                  })}
                </div>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="preferred-city">Anchor city</Label>
                <select
                  id="preferred-city"
                  disabled={profileLoading}
                  value={preferredCity}
                  onChange={(e) => setPreferredCity(e.target.value)}
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <option value="">No anchor city</option>
                  {US_CITY_OPTIONS.map((city) => (
                    <option key={city.label} value={city.label}>
                      {city.label}
                    </option>
                  ))}
                </select>
                {geocodedCity && (
                  <p className="text-xs text-muted-foreground">
                    {geocodedCity.region} · {geocodedCity.lat.toFixed(2)},{" "}
                    {geocodedCity.lon.toFixed(2)}
                  </p>
                )}
                <p className="text-xs text-muted-foreground">
                  Used to score jobs by distance. Leave as "No anchor
                  city" to fall back to a country-centroid anchor.
                </p>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="preferred-radius-km">
                  Willing to relocate (km)
                </Label>
                <Input
                  id="preferred-radius-km"
                  type="text"
                  inputMode="numeric"
                  placeholder={`${DEFAULT_RADIUS_KM}`}
                  disabled={profileLoading}
                  value={preferredRadiusKm}
                  onChange={(e) => setPreferredRadiusKm(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  How far you{"'"}re willing to move for a job. Default
                  is {DEFAULT_RADIUS_KM} km (~5 hours{" "}
                  drive). Lower = strict local; higher = open to
                  regional moves.
                </p>
              </div>
              <div className="grid gap-2">
                <Label>Target seniority</Label>
                <p className="text-xs text-muted-foreground">
                  Only jobs at these levels will be shown. Default is
                  Internship / Entry / Mid for early-career candidates.
                </p>
                <div className="flex flex-wrap gap-2">
                  {SENIORITY_OPTIONS.map((level) => {
                    const checked = targetSeniority.includes(level.value)
                    return (
                      <label
                        key={level.value}
                        className="flex items-center gap-1.5 rounded-md border border-input px-2.5 py-1.5 text-sm text-foreground cursor-pointer hover:bg-accent/40"
                      >
                        <Checkbox
                          disabled={profileLoading}
                          checked={checked}
                          onCheckedChange={() => toggleSeniority(level.value)}
                        />
                        {level.label}
                      </label>
                    )
                  })}
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