import { createClient } from "@supabase/supabase-js"

// Initialize the Supabase client
const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
const supabasePubKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY

if (!supabaseUrl || !supabasePubKey) {
  throw new Error("Missing Supabase environment variables. Check .env file.")
}

export const supabase = createClient(supabaseUrl, supabasePubKey)

/**
 * Initiates the Google OAuth flow.
 * Returns the user to the current page after authentication.
 */
export const signInWithGoogle = async () => {
  const { error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: {
      redirectTo: window.location.origin, // Returns the user to app's home after login
    },
  })

  if (error) {
    console.error("Error signing in with Google:", error.message)
    throw error
  }
}

// Signs the user out of the current session.
export const signOut = async () => {
  const { error } = await supabase.auth.signOut()
  if (error) {
    console.error("Error signing out:", error.message)
    throw error
  }
}
