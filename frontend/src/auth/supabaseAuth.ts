import { createClient, type AuthError } from "@supabase/supabase-js"

// Initialize the Supabase client
const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
const supabasePubKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY

if (!supabaseUrl || !supabasePubKey) {
  throw new Error("Missing Supabase environment variables. Check .env file.")
}

export const supabase = createClient(supabaseUrl, supabasePubKey)

/**
 * Trims and lowercases email for auth. Returns a user-facing message if the
 * string is not in a shape Supabase GoTrue accepts (one @, non-empty parts,
 * domain with a dot).
 */
export const prepareEmailForAuth = (
  email: string
): { ok: true; email: string } | { ok: false; message: string } => {
  const trimmed = email.trim()
  if (!trimmed) {
    return { ok: false, message: "Enter an email address." }
  }
  const atMatches = trimmed.match(/@/g)
  const atCount = atMatches?.length ?? 0
  if (atCount !== 1) {
    return {
      ok: false,
      message:
        atCount > 1
          ? "That email has more than one “@”. Use a single @ between your name and your provider (for example name@gmail.com)."
          : "Email must include an @ between your name and your provider.",
    }
  }
  const [local, domain] = trimmed.split("@")
  if (!local?.length || !domain?.length) {
    return { ok: false, message: "Enter a complete email address." }
  }
  if (!domain.includes(".")) {
    return {
      ok: false,
      message:
        "Enter a valid email with a domain that includes a dot (for example name@example.com).",
    }
  }
  return { ok: true, email: trimmed.toLowerCase() }
}

/** Result of email+password sign-up or sign-in (validation runs via {@link prepareEmailForAuth}). */
export type EmailPasswordAuthResult =
  | { ok: true; error: AuthError | null }
  | { ok: false; message: string }

export const signUpWithEmail = async (
  email: string,
  password: string
): Promise<EmailPasswordAuthResult> => {
  const prepared = prepareEmailForAuth(email)
  if (!prepared.ok) {
    return { ok: false, message: prepared.message }
  }
  const { error } = await supabase.auth.signUp({
    email: prepared.email,
    password,
  })
  return { ok: true, error }
}

export const signInWithEmail = async (
  email: string,
  password: string
): Promise<EmailPasswordAuthResult> => {
  const prepared = prepareEmailForAuth(email)
  if (!prepared.ok) {
    return { ok: false, message: prepared.message }
  }
  const { error } = await supabase.auth.signInWithPassword({
    email: prepared.email,
    password,
  })
  return { ok: true, error }
}

// Signs the user out of the current session.
export const signOut = async () => {
  const { error } = await supabase.auth.signOut()
  if (error) {
    console.error("Error signing out:", error.message)
    throw error
  }
}

export type ProfileResult<T> =
  | { ok: true; data: T }
  | { ok: false; message: string }

export type ProfilePreferences = {
  target_role: string | null
  preferred_locations: string[]
  preferred_work_modes: string[]
  minimum_base_salary: number | null
  salary_currency: string

  preferred_country_codes: string[]
  preferred_city: string | null
  preferred_lat: number | null
  preferred_lon: number | null
  preferred_radius_km: number | null
  target_seniority: string[]
}

export const getProfilePreferences = async (
  userId: string
): Promise<ProfileResult<ProfilePreferences>> => {
  const { data, error } = await supabase
    .from("profiles")
    .select(
      "target_role, preferred_locations, preferred_work_modes, minimum_base_salary, salary_currency, preferred_country_codes, preferred_city, preferred_lat, preferred_lon, preferred_radius_km, target_seniority"
    )
    .eq("id", userId)
    .maybeSingle()

  if (error) {
    return { ok: false, message: error.message }
  }
  return {
    ok: true,
    data: {
      target_role: data?.target_role ?? null,
      preferred_locations: data?.preferred_locations ?? [],
      preferred_work_modes: data?.preferred_work_modes ?? [],
      minimum_base_salary: data?.minimum_base_salary ?? null,
      salary_currency: data?.salary_currency ?? "USD",
      preferred_country_codes: data?.preferred_country_codes ?? [],
      preferred_city: data?.preferred_city ?? null,
      preferred_lat: data?.preferred_lat ?? null,
      preferred_lon: data?.preferred_lon ?? null,
      preferred_radius_km: data?.preferred_radius_km ?? null,
      target_seniority: data?.target_seniority ?? [],
    },
  }
}

export const updateProfilePreferences = async (
  userId: string,
  preferences: {
    target_role: string
    preferred_locations: string[]
    preferred_work_modes: string[]
    minimum_base_salary: number | null
    salary_currency?: string
    preferred_country_codes?: string[]
    preferred_city?: string | null
    preferred_lat?: number | null
    preferred_lon?: number | null
    preferred_radius_km?: number | null
    target_seniority?: string[]
  }
): Promise<ProfileResult<null>> => {
  const targetRole = preferences.target_role.trim()
  const preferredLocations = preferences.preferred_locations
    .map((location) => location.trim())
    .filter(Boolean)
  const preferredWorkModes = preferences.preferred_work_modes
    .map((mode) => mode.trim())
    .filter(Boolean)

  const { error } = await supabase.from("profiles").upsert(
    {
      id: userId,
      target_role: targetRole || null,
      preferred_locations: preferredLocations.length
        ? preferredLocations
        : null,
      preferred_work_modes: preferredWorkModes.length
        ? preferredWorkModes
        : null,
      minimum_base_salary: preferences.minimum_base_salary,
      salary_currency: preferences.salary_currency ?? "USD",
      preferred_country_codes:
        preferences.preferred_country_codes ?? [],
      preferred_city: preferences.preferred_city ?? null,
      preferred_lat: preferences.preferred_lat ?? null,
      preferred_lon: preferences.preferred_lon ?? null,
      preferred_radius_km: preferences.preferred_radius_km ?? null,
      target_seniority: preferences.target_seniority ?? [
        "internship", "entry", "mid",
      ],
    },
    { onConflict: "id" }
  )

  if (error) {
    return { ok: false, message: error.message }
  }
  return { ok: true, data: null }
}

export const getProfileTargetRole = async (
  userId: string
): Promise<ProfileResult<string | null>> => {
  const result = await getProfilePreferences(userId)
  if (!result.ok) return result
  return { ok: true, data: result.data.target_role }
}

export const updateProfileTargetRole = async (
  userId: string,
  targetRole: string
): Promise<ProfileResult<null>> => {
  const trimmed = targetRole.trim()
  const { error } = await supabase
    .from("profiles")
    .upsert({ id: userId, target_role: trimmed || null }, { onConflict: "id" })

  if (error) {
    return { ok: false, message: error.message }
  }
  return { ok: true, data: null }
}

export type ChangeEmailResult =
  | { ok: true }
  | { ok: false; message: string; code?: string }

export const changeEmailWithPassword = async (
  currentEmail: string,
  password: string,
  newEmail: string
): Promise<ChangeEmailResult> => {
  const prepared = prepareEmailForAuth(newEmail)
  if (!prepared.ok) {
    return { ok: false, message: prepared.message }
  }

  const normalizedCurrent = currentEmail.trim().toLowerCase()
  if (prepared.email === normalizedCurrent) {
    return { ok: false, message: "That is already your email address." }
  }

  const { error: signInError } = await supabase.auth.signInWithPassword({
    email: normalizedCurrent,
    password,
  })
  if (signInError) {
    return {
      ok: false,
      message: "Incorrect password. Enter your current password to continue.",
      code: signInError.code,
    }
  }

  const { error: updateError } = await supabase.auth.updateUser({
    email: prepared.email,
  })
  if (updateError) {
    return {
      ok: false,
      message: updateError.message,
      code: updateError.code,
    }
  }

  return { ok: true }
}
