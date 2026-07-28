import { apiFetch } from "./client"

// Frontend API client for the profile-related backend endpoints.
// The Profile page already uses supabaseAuth.ts to read/write most
// profile fields directly (the RLS-protected supabase client). This
// file covers the few fields that need a backend round-trip:
//
//   - POST /profile/geocode-city: server-side geocoding of a city
//     string the user types, returning lat/lon for the form preview.
//
// Everything else (country codes, city, radius, target_seniority)
// goes through the existing updateProfilePreferences path which
// writes to Supabase directly.

export interface GeocodeCityResult {
  city: string
  country_code: string | null
  region: string | null
  lat: number
  lon: number
}

export const geocodeCityForProfile = async (
  city: string,
): Promise<GeocodeCityResult> => {
  return apiFetch<GeocodeCityResult>("/profile/geocode-city", {
    method: "POST",
    body: JSON.stringify({ city }),
  })
}
