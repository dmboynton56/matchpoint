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

const MatchesPage = lazy(() =>
  import("@/pages/MatchesPage").then((m) => ({ default: m.MatchesPage }))
)

const ProfilePage = lazy(() =>
  import("@/pages/ProfilePage").then((m) => ({ default: m.ProfilePage }))
)

const FavoritesPage = lazy(() =>
  import("@/pages/FavoritesPage").then((m) => ({ default: m.FavoritesPage }))
)

const AppliedJobsPage = lazy(() =>
  import("@/pages/AppliedJobsPage").then((m) => ({ default: m.AppliedJobsPage }))
)

const ResumePage = lazy(() =>
  import("@/pages/ResumePage").then((m) => ({ default: m.ResumePage }))
)

export function App() {
  return (
    <Suspense fallback={<RouteLoading />}>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/jobs" element={<JobsPage />} />
        <Route path="/matches" element={<MatchesPage />} />
        <Route
          path="/profile"
          element={
            <ProtectedRoute>
              <ProfilePage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/favorites"
          element={
            <ProtectedRoute>
              <FavoritesPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/applied"
          element={
            <ProtectedRoute>
              <AppliedJobsPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/resume"
          element={
            <ProtectedRoute>
              <ResumePage />
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
