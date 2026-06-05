import { useEffect, useMemo, useState } from "react"
import { Link, useLocation } from "react-router-dom"
import { InfoIcon } from "lucide-react"
import { toast } from "sonner"

import { getMyMatches } from "@/apis/matches"
import {
  getProfilePreferences,
  type ProfilePreferences,
} from "@/auth/supabaseAuth"
import { JobApplyFollowUpDrawer } from "@/components/jobs/JobApplyFollowUpDrawer"
import { JobListingCard } from "@/components/jobs/JobListingCard"
import { AppShell } from "@/components/layout/AppShell"
import { RouteLoading } from "@/components/routing/RouteLoading"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { matchToJobMatch, sortByMatchScore } from "@/lib/matchToJobMatch"
import { getMissingProfilePreferenceLabels } from "@/lib/profilePreferences"
import { SignupLoginDialog } from "@/components/user/SignupLoginCard"
import UploadDropzone from "@/components/user/UploadDropzone"
import { useAuth } from "@/hooks/useAuth"
import type { JobMatch } from "@/types/job"

type JobsPageLocationState = {
  jobs?: JobMatch[]
}

export function JobsPage() {
  const location = useLocation()
  const { user, loading: authLoading } = useAuth()
  const state = location.state as JobsPageLocationState | null
  const stateJobs = useMemo(
    () => (state?.jobs ? sortByMatchScore(state.jobs) : []),
    [state]
  )

  const [jobs, setJobs] = useState<JobMatch[]>(stateJobs)
  const [matchesLoading, setMatchesLoading] = useState(false)
  const [applyFollowUpJob, setApplyFollowUpJob] = useState<JobMatch | null>(
    null
  )
  const [signupOpen, setSignupOpen] = useState(false)
  const [profilePreferences, setProfilePreferences] =
    useState<ProfilePreferences | null>(null)
  const [profilePreferencesLoading, setProfilePreferencesLoading] =
    useState(false)

  useEffect(() => {
    if (authLoading || !user) return

    let cancelled = false

    void Promise.resolve()
      .then(() => {
        if (!cancelled) setProfilePreferencesLoading(true)
        return getProfilePreferences(user.id)
      })
      .then((result) => {
        if (cancelled) return
        if (result.ok) {
          setProfilePreferences(result.data)
        }
      })
      .finally(() => {
        if (!cancelled) setProfilePreferencesLoading(false)
      })

    return () => {
      cancelled = true
      setProfilePreferences(null)
    }
  }, [user, authLoading])

  useEffect(() => {
    if (authLoading) return

    if (!user) return

    let cancelled = false

    void Promise.resolve()
      .then(() => {
        if (!cancelled) setMatchesLoading(true)
        return getMyMatches()
      })
      .then((response) => {
        if (cancelled) return
        setJobs(sortByMatchScore(response.matches.map(matchToJobMatch)))
      })
      .catch((error) => {
        if (cancelled) return
        const message =
          error instanceof Error ? error.message : "Failed to load matches"
        toast.error(message)
        if (stateJobs.length > 0) setJobs(stateJobs)
      })
      .finally(() => {
        if (!cancelled) setMatchesLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [user, authLoading, stateJobs])

  if (authLoading || (user && matchesLoading && jobs.length === 0)) {
    return <RouteLoading />
  }

  const displayedJobs = user ? jobs : stateJobs
  const hasMatches = displayedJobs.length > 0
  const missingPreferenceLabels = profilePreferences
    ? getMissingProfilePreferenceLabels(profilePreferences)
    : []
  const showProfilePreferencesAlert =
    !!user && !profilePreferencesLoading && missingPreferenceLabels.length > 0

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <section className="space-y-2">
          <p className="text-xs font-semibold tracking-[0.22em] text-primary uppercase">
            Your matches
          </p>
          <h1 className="font-heading text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
            Jobs tailored to you
          </h1>
          <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base">
            {hasMatches
              ? `Showing ${displayedJobs.length} role${
                  displayedJobs.length === 1 ? "" : "s"
                } ranked against your resume.`
              : "Upload your resume below to see personalized job matches."}
          </p>
        </section>

        {showProfilePreferencesAlert ? (
          <Alert className="bg-black/35 py-4">
            <InfoIcon className="mr-4 size-8 fill-yellow-500" />
            <AlertTitle>Improve your matches</AlertTitle>
            <AlertDescription className="flex flex-col gap-2">
              Add the following on your profile so we can rank jobs more
              accurately against your goals:
              <ul className="list-inside list-disc">
                {missingPreferenceLabels.map((label) => (
                  <li key={label}>{label}</li>
                ))}
              </ul>
              <Button asChild className="w-fit min-w-48">
                <Link to="/profile">Complete profile</Link>
              </Button>
            </AlertDescription>
          </Alert>
        ) : null}

        {hasMatches ? (
          <ul className="space-y-3">
            {displayedJobs.map((job) => (
              <li key={job.id}>
                <JobListingCard
                  job={job}
                  onApplyClick={(selected) => setApplyFollowUpJob(selected)}
                />
              </li>
            ))}
          </ul>
        ) : (
          <div className="rounded-xl border border-dashed border-border bg-card/50 px-6 py-10 text-center">
            <p className="text-sm text-muted-foreground">
              No matches yet. Upload a PDF resume to get started.
            </p>
            <UploadDropzone />
          </div>
        )}
      </div>

      <JobApplyFollowUpDrawer
        job={applyFollowUpJob}
        matchId={applyFollowUpJob?.match_id}
        open={applyFollowUpJob != null}
        isAuthenticated={!!user}
        onSignUpClick={() => setSignupOpen(true)}
        onFavorited={(isFavorited) => {
          if (!applyFollowUpJob?.match_id) return
          setJobs((current) =>
            current.map((job) =>
              job.match_id === applyFollowUpJob.match_id
                ? { ...job, is_favorited: isFavorited }
                : job
            )
          )
          setApplyFollowUpJob((current) =>
            current ? { ...current, is_favorited: isFavorited } : current
          )
        }}
        onApplied={(isApplied) => {
          if (!applyFollowUpJob?.match_id) return
          setJobs((current) =>
            current.map((job) =>
              job.match_id === applyFollowUpJob.match_id
                ? { ...job, is_applied: isApplied }
                : job
            )
          )
          setApplyFollowUpJob((current) =>
            current ? { ...current, is_applied: isApplied } : current
          )
        }}
        onDeleted={(deletedMatchId) => {
          setJobs((current) =>
            current.filter((job) => job.match_id !== deletedMatchId)
          )
          setApplyFollowUpJob(null)
        }}
        onOpenChange={(open) => {
          if (!open) setApplyFollowUpJob(null)
        }}
      />

      <SignupLoginDialog open={signupOpen} onOpenChange={setSignupOpen} />
    </AppShell>
  )
}
