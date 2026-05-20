import { lazy, Suspense } from "react"
import { Route, Routes } from "react-router-dom"

import { LandingPage } from "@/pages/LandingPage"

const JobsPage = lazy(() =>
  import("@/pages/JobsPage").then((m) => ({ default: m.JobsPage }))
)

function RouteFallback() {
  return (
    <div className="flex min-h-svh items-center justify-center bg-background text-sm text-muted-foreground">
      Loading…
    </div>
  )
}

export function App() {
  return (
    <Suspense fallback={<RouteFallback />}>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/jobs" element={<JobsPage />} />
      </Routes>
    </Suspense>
  )
}

export default App
