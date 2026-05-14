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

/**
 * Initiates the Google OAuth flow.
 * Returns the user to the current page after authentication.
 */
export const signInWithGoogle = async (): Promise<{
  error: AuthError | null
}> => {
  const { error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: {
      redirectTo: window.location.origin, // Returns the user to app's home after login
    },
  })

  if (error) {
    console.error("Error signing in with Google:", error.message)
  }

  return { error }
}

/**
 * Reads OAuth error params Supabase may append to the URL after redirect,
 * clears them from the address bar, and returns a user-facing message if present.
 */
export const consumeOAuthUrlError = (): string | null => {
  const readMessage = (params: URLSearchParams): string | null => {
    const description = params.get("error_description")
    const code = params.get("error")
    const raw = description ?? code
    if (!raw) {
      return null
    }
    return decodeURIComponent(raw.replace(/\+/g, " "))
  }

  const hashParams = new URLSearchParams(window.location.hash.slice(1))
  const hashMessage = readMessage(hashParams)
  if (hashMessage) {
    window.history.replaceState(
      null,
      "",
      window.location.pathname + window.location.search
    )
    return hashMessage
  }

  const searchParams = new URLSearchParams(window.location.search)
  const searchMessage = readMessage(searchParams)
  if (!searchMessage) {
    return null
  }

  const url = new URL(window.location.href)
  url.searchParams.delete("error")
  url.searchParams.delete("error_description")
  url.searchParams.delete("error_code")
  window.history.replaceState(null, "", `${url.pathname}${url.search}`)

  return searchMessage
}

// Signs the user out of the current session.
export const signOut = async () => {
  const { error } = await supabase.auth.signOut()
  if (error) {
    console.error("Error signing out:", error.message)
    throw error
  }
}
