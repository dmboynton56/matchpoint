import { useEffect, useState } from "react"
import type { User } from "@supabase/supabase-js"

import { supabase } from "@/auth/supabaseAuth"

export function useAuth() {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setUser(session?.user ?? null)
      setLoading(false)
    })

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null)
      setLoading(false)
    })

    return () => subscription.unsubscribe()
  }, [])

  return { user, loading }
}

export function getUserAvatarUrl(user: User | null): string | undefined {
  if (!user) return undefined
  const meta = user.user_metadata as Record<string, unknown>
  const avatar = meta.avatar_url ?? meta.picture
  return typeof avatar === "string" ? avatar : undefined
}

export function getUserDisplayName(user: User | null): string {
  if (!user) return "Account"
  const meta = user.user_metadata as Record<string, unknown>
  const name = meta.full_name ?? meta.name
  if (typeof name === "string" && name.trim()) return name
  return user.email?.split("@")[0] ?? "Account"
}
