import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { toast } from "sonner"

import { getMyMatches } from "@/apis/matches"
import { FavoriteJobHeartButton } from "@/components/jobs/FavoriteJobHeartButton"
import { JobListingCard } from "@/components/jobs/JobListingCard"
import { AppShell } from "@/components/layout/AppShell"
import { RouteLoading } from "@/components/routing/RouteLoading"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/hooks/useAuth"
import { matchToJobMatch, sortByMatchScore } from "@/lib/matchToJobMatch"
import { hasApplyUrl, type JobListing } from "@/types/job"

export function FavoritesPage() {
  const { user, loading: authLoading } = useAuth()
  const [favorites, setFavorites] = useState<JobListing[]>([])
  const [favoritesLoading, setFavoritesLoading] = useState(false)

  useEffect(() => {
    if (authLoading || !user) return

    let cancelled = false

    void Promise.resolve()
      .then(() => {
        if (!cancelled) setFavoritesLoading(true)
        return getMyMatches({ favorited: true })
      })
      .then((response) => {
        if (cancelled) return
        setFavorites(sortByMatchScore(response.matches.map(matchToJobMatch)))
      })
      .catch((error) => {
        if (cancelled) return
        const message =
          error instanceof Error ? error.message : "Failed to load favorites"
        toast.error(message)
      })
      .finally(() => {
        if (!cancelled) setFavoritesLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [user, authLoading])

  if (authLoading || (user && favoritesLoading && favorites.length === 0)) {
    return <RouteLoading />
  }

  const hasFavorites = favorites.length > 0

  const handleUnfavorited = (matchId: string) => {
    setFavorites((current) =>
      current.filter((job) => job.match_id !== matchId)
    )
  }

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <section className="space-y-2">
          <p className="text-xs font-semibold tracking-[0.22em] text-primary uppercase">
            Your favorites
          </p>
          <h1 className="font-heading text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
            Favorite jobs
          </h1>
          <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base">
            {hasFavorites
              ? `Showing ${favorites.length} job${
                  favorites.length === 1 ? "" : "s"
                } you've marked as favorite.`
              : "Mark jobs as favorite from your matches to see them here."}
          </p>
        </section>

        {hasFavorites ? (
          <ul className="space-y-3">
            {favorites.map((job) => (
              <li key={job.match_id ?? job.id}>
                <JobListingCard
                  job={job}
                  showApplyLink={hasApplyUrl(job)}
                  headerAddon={
                    job.match_id ? (
                      <FavoriteJobHeartButton
                        matchId={job.match_id}
                        onUnfavorited={() => handleUnfavorited(job.match_id!)}
                      />
                    ) : null
                  }
                />
              </li>
            ))}
          </ul>
        ) : (
          <div className="rounded-xl border border-dashed border-border bg-card/50 px-6 py-10 text-center">
            <p className="text-sm text-muted-foreground">
              No favorites yet. Apply to a job from your matches and mark it as
              favorite, or browse your job list.
            </p>
            <Button asChild className="mt-4">
              <Link to="/jobs">View matches</Link>
            </Button>
          </div>
        )}
      </div>
    </AppShell>
  )
}
