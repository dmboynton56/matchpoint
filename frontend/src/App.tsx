import { lazy, Suspense } from "react"
import { Route, Routes } from "react-router-dom"

import { ProtectedRoute } from "@/components/auth/ProtectedRoute"
import { RouteLoading } from "@/components/routing/RouteLoading"
import { LandingPage } from "@/pages/LandingPage"
import { NotFoundPage } from "@/pages/NotFoundPage"
import Footer from "@/components/Footer"

const JobsPage = lazy(() =>
  import("@/pages/JobsPage").then((m) => ({ default: m.JobsPage }))
)

const ProfilePage = lazy(() =>
  import("@/pages/ProfilePage").then((m) => ({ default: m.ProfilePage }))
)

export function App() {
  return (
    <Suspense fallback={<RouteLoading />}>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/jobs" element={<JobsPage />} />
        <Route
          path="/profile"
          element={
            <ProtectedRoute>
              <ProfilePage />
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
      <Footer />
    </Suspense>
  )
}

export default App
