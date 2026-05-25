import { useContext } from "react"
import type { User } from "@supabase/supabase-js"

import { AuthContext } from "@/context/AuthContext"

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider")
  }
  return context
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
