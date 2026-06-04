import type { ProfilePreferences } from "@/auth/supabaseAuth"

export function getMissingProfilePreferenceLabels(
  preferences: ProfilePreferences
): string[] {
  const missing: string[] = []
  if (!preferences.target_role?.trim()) {
    missing.push("Target role")
  }
  if (preferences.preferred_locations.length === 0) {
    missing.push("Preferred locations")
  }
  if (preferences.preferred_work_modes.length === 0) {
    missing.push("Work mode")
  }
  if (preferences.minimum_base_salary == null) {
    missing.push("Minimum base salary")
  }
  return missing
}
