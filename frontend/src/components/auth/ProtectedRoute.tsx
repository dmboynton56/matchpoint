import type { ReactNode } from "react"
import { Navigate } from "react-router-dom"

import { RouteLoading } from "@/components/routing/RouteLoading"
import { useAuth } from "@/hooks/useAuth"

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()

  if (loading) {
    return <RouteLoading />
  }

  if (!user) {
    return <Navigate to="/" replace />
  }

  return children
}
