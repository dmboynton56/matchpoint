import { useCallback, useEffect, useRef, useState } from "react"
import { Check, Clipboard, ExternalLink, Sparkles } from "lucide-react"
import { toast } from "sonner"

import {
  getMySuggestions,
  refreshSuggestions,
  rewriteBullet,
  startCoachSession,
  type ResumeSuggestionsResponse,
} from "@/apis/suggestions"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import type {
  CoachBullet,
  CoachRewriteResponse,
  CoachStartResponse,
  Suggestion,
} from "@/types/suggestions"

type ResumeSuggestionsCardProps = {
  /** Hide the card entirely if the user has no resume on file. */
  enabled: boolean
}

type CardState =
  | { kind: "loading" }
  | { kind: "empty" }
  | { kind: "ready"; data: ResumeSuggestionsResponse }
  | { kind: "error"; message: string }
  | { kind: "refreshing"; data: ResumeSuggestionsResponse }
  | { kind: "coach_loading" }
  | {
      kind: "coach_ready"
      session: CoachStartResponse
      /** Per-bullet map of question key -> user's answer. */
      answers: Record<string, Record<string, string>>
      /** Per-bullet rewrite result, once the user has asked for one. */
      rewrites: Record<string, CoachRewriteResponse>
      /** Bullet IDs currently being rewritten. */
      pending: Record<string, boolean>
    }
  | { kind: "coach_error"; message: string }

const KIND_LABEL: Record<Suggestion["kind"], string> = {
  SKILL: "Skill",
}

function formatTimestamp(value: string): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    }).format(new Date(value))
  } catch {
    return value
  }
}

/**
 * Render the "Vercel — Senior Software Engineer ↗" header for a citation.
 * Falls back gracefully when title/company/apply_url are missing (older
 * rows, or jobs without an external posting). The header is the same
 * visual style with or without the link — only the affordance differs.
 */
function CitationJobHeader({
  jobTitle,
  jobCompany,
  applyUrl,
}: {
  jobTitle: string | null | undefined
  jobCompany: string | null | undefined
  applyUrl: string | null | undefined
}) {
  const hasContent = Boolean(jobTitle) || Boolean(jobCompany)
  if (!hasContent) return null

  const companyLabel = jobCompany ?? "Job"
  const content = (
    <>
      <span>{companyLabel}</span>
      {jobTitle ? (
        <>
          <span className="text-muted-foreground">—</span>
          <span>{jobTitle}</span>
        </>
      ) : null}
    </>
  )

  if (applyUrl) {
    return (
      <a
        href={applyUrl}
        target="_blank"
        rel="noreferrer noopener"
        className="inline-flex items-center gap-1 font-medium text-foreground hover:underline"
      >
        {content}
        <ExternalLink className="size-3 shrink-0" />
      </a>
    )
  }
  return <span className="font-medium text-foreground">{content}</span>
}

/**
 * Render a single bullet-coach entry: location breadcrumb,
 * weakness reason, original-text quote, question inputs, and
 * either a rewrite result or a "Get rewrite" button.
 */
function BulletCoachItem({
  bullet,
  rewrite,
}: {
  bullet: CoachBullet
  rewrite: CoachRewriteResponse | undefined
  // NOTE: The rewrite input UI was temporarily hidden while we
  // investigate a /coach/rewrite slowness issue (see comment in the
  // JSX below). The props `answers`, `onAnswerChange`, `pending`,
  // and `onRequestRewrite` were removed from the signature
  // because they were unused. To re-enable the rewrite UI, restore
  // them here and at the call site (search for `<BulletCoachItem`
  // in this file), and uncomment the JSX block marked
  // "REWRITE UI TEMPORARILY HIDDEN" below.
}) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    if (!rewrite) return
    try {
      await navigator.clipboard.writeText(rewrite.rewritten_text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      toast.error("Couldn't copy to clipboard.")
    }
  }

  return (
    <li className="rounded-md border border-border bg-background/60 px-3 py-3 space-y-3">
      {/* Location breadcrumb */}
      <p className="text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">
        Bullet to strengthen
      </p>
      <p className="text-xs text-muted-foreground">
        {bullet.location.section}
        {bullet.location.entry_title ? (
          <>
            <span className="mx-1.5 text-muted-foreground/50">›</span>
            <span className="text-foreground/80">
              {bullet.location.entry_title}
            </span>
          </>
        ) : null}
      </p>

      {/* Original bullet */}
      <blockquote className="rounded border-l-2 border-border bg-muted/30 px-3 py-2 text-sm italic text-foreground/90">
        &ldquo;{bullet.original_text}&rdquo;
      </blockquote>

      {/* Weakness reason */}
      <p className="text-xs leading-relaxed text-muted-foreground">
        <span className="font-medium text-foreground">Why it&apos;s weak: </span>
        {bullet.weakness_reason}
      </p>

      {/* REWRITE UI TEMPORARILY HIDDEN.
          The /coach/rewrite endpoint is hanging on some
          OpenAI calls (30+ second response times). The
          backend code is still in place -- services/bullet_coach.py,
          services/bullet_coach_llm.py:rewrite_bullet, and the
          /suggestions/coach/rewrite route -- but the UI is
          disabled until we diagnose whether the slowness
          is OpenAI's structured-outputs path, our schema, or
          a network issue.

          For now: show the questions as a read-only list so
          the user can see what info is missing. No input
          fields, no "Get rewrite" button. The Copy button
          + rewrite result branch are kept in the code so
          re-enabling is a one-line change. */}
      {bullet.questions.length > 0 ? (
        <div className="space-y-1">
          <p className="text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">
            Info needed to strengthen this bullet
          </p>
          <ul className="space-y-0.5 text-xs text-muted-foreground">
            {bullet.questions.map((question) => (
              <li key={question.key}>
                &bull; {question.label}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11px] italic text-muted-foreground/70">
            Rewrite generation is temporarily disabled while we
            investigate a slowness issue. The questions above
            are what you&apos;d answer to strengthen this bullet
            on your own.
          </p>
        </div>
      ) : null}

      {rewrite ? (
        <div className="space-y-2">
          <p className="text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">
            Suggested rewrite
          </p>
          <p className="rounded border border-primary/30 bg-primary/5 px-3 py-2 text-sm text-foreground">
            {rewrite.rewritten_text}
          </p>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => void handleCopy()}
            >
              {copied ? (
                <>
                  <Check className="mr-1.5 size-3" />
                  Copied
                </>
              ) : (
                <>
                  <Clipboard className="mr-1.5 size-3" />
                  Copy bullet
                </>
              )}
            </Button>
            {!rewrite.grounded && rewrite.grounding_failures.length > 0 ? (
              <p className="text-[11px] text-amber-600">
                Note: this rewrite may be partially ungrounded — verify
                before pasting into your resume.
              </p>
            ) : null}
          </div>
          {rewrite.citation.quote ? (
            <p className="text-[11px] text-muted-foreground">
              <CitationJobHeader
                jobTitle={rewrite.citation.job_title}
                jobCompany={rewrite.citation.job_company}
                applyUrl={rewrite.citation.apply_url}
              />
              <span className="mt-1 block italic">
                &ldquo;{rewrite.citation.quote}&rdquo;
              </span>
            </p>
          ) : null}
        </div>
      ) : null}
    </li>
  )
}

export function ResumeSuggestionsCard({ enabled }: ResumeSuggestionsCardProps) {
  const [state, setState] = useState<CardState>({ kind: "loading" })

  const load = useCallback(async () => {
    setState((current) =>
      current.kind === "ready"
        ? { kind: "refreshing", data: current.data }
        : { kind: "loading" }
    )
    try {
      const data = await getMySuggestions()
      setState({ kind: "ready", data })
    } catch (error) {
      // 404 from the backend means "no cached row yet" — surface that as the
      // empty state, not an error.
      const message =
        error instanceof Error ? error.message : "Failed to load suggestions"
      if (/no suggestions cached/i.test(message)) {
        setState({ kind: "empty" })
        return
      }
      setState({ kind: "error", message })
    }
  }, [])

  useEffect(() => {
    if (!enabled) return
    void load()
  }, [enabled, load])

  // Listen for coach-flow events bubbled up from CoachSection.
  // We use CustomEvent on window because the CoachSection is
  // nested several layers deep; passing callbacks through is
  // possible but a global event is simpler for this one
  // user-driven flow.
  useEffect(() => {
    const handleAnswer = (event: Event) => {
      const detail = (event as CustomEvent<{
        bulletId: string
        key: string
        value: string
      }>).detail
      handleAnswerChange(detail.bulletId, detail.key, detail.value)
    }
    const handleRewrite = (event: Event) => {
      const detail = (event as CustomEvent<{ bulletId: string }>).detail
      setState((current) => {
        if (current.kind !== "coach_ready") return current
        const bullet = current.session.bullets.find(
          (b) => b.bullet_id === detail.bulletId,
        )
        if (!bullet) return current
        // Fire-and-forget; the state updates happen inside
        // handleRequestRewrite via its own setState calls.
        void handleRequestRewrite(bullet)
        return current
      })
    }
    window.addEventListener("coach-answer", handleAnswer)
    window.addEventListener("coach-rewrite", handleRewrite)
    return () => {
      window.removeEventListener("coach-answer", handleAnswer)
      window.removeEventListener("coach-rewrite", handleRewrite)
    }
  }, [])

  const handleRefresh = async () => {
    setState((current) =>
      current.kind === "ready"
        ? { kind: "refreshing", data: current.data }
        : { kind: "loading" }
    )
    try {
      const response = await refreshSuggestions()
      // Build a response in the same shape as getMySuggestions so the UI
      // doesn't have to branch on which endpoint produced the data.
      const data: ResumeSuggestionsResponse = {
        id: "",
        cache_key: response.cache_key,
        created_at: new Date().toISOString(),
        suggestions: response.suggestions,
      }
      if (response.below_minimum) {
        toast.message(
          "Only a few grounded suggestions were found. Try refreshing again."
        )
      } else {
        toast.success("Suggestions updated.")
      }
      setState({ kind: "ready", data })
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Failed to generate suggestions."
      toast.error(message)
      // Roll back to whatever we had.
      setState((current) =>
        current.kind === "refreshing"
          ? { kind: "ready", data: current.data }
          : { kind: "error", message }
      )
    }
  }

  const handleStartCoach = async () => {
    setState({ kind: "coach_loading" })
    try {
      const session = await startCoachSession()
      setState({
        kind: "coach_ready",
        session,
        answers: {},
        rewrites: {},
        pending: {},
      })
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Failed to start coach session."
      setState({ kind: "coach_error", message })
    }
  }

  // Return to the one-shot view. We keep a ref of the most
  // recent one-shot state (ready / refreshing / empty) so the
  // user lands back where they were, with their cached
  // suggestions intact.
  const lastOneShotStateRef = useRef<
    | { kind: "ready"; data: ResumeSuggestionsResponse }
    | { kind: "refreshing"; data: ResumeSuggestionsResponse }
    | { kind: "empty" }
    | null
  >(null)

  useEffect(() => {
    if (
      state.kind === "ready" ||
      state.kind === "refreshing" ||
      state.kind === "empty"
    ) {
      lastOneShotStateRef.current = state
    }
  }, [state])

  const handleExitCoach = () => {
    const previous = lastOneShotStateRef.current
    if (previous) {
      setState(previous)
    } else {
      setState({ kind: "empty" })
    }
  }

  const handleAnswerChange = (
    bulletId: string,
    key: string,
    value: string,
  ) => {
    setState((current) => {
      if (current.kind !== "coach_ready") return current
      const existing = current.answers[bulletId] ?? {}
      return {
        ...current,
        answers: {
          ...current.answers,
          [bulletId]: { ...existing, [key]: value },
        },
      }
    })
  }

  const handleRequestRewrite = async (bullet: CoachBullet) => {
    setState((current) => {
      if (current.kind !== "coach_ready") return current
      return {
        ...current,
        pending: { ...current.pending, [bullet.bullet_id]: true },
      }
    })
    try {
      // Look up the current state in a way that survives the
      // setState callback being async-batched.
      const currentState = state
      if (currentState.kind !== "coach_ready") return
      const answers = currentState.answers[bullet.bullet_id] ?? {}
      const response = await rewriteBullet({
        session_id: currentState.session.session_id,
        bullet_id: bullet.bullet_id,
        answers,
      })
      setState((current) => {
        if (current.kind !== "coach_ready") return current
        return {
          ...current,
          rewrites: { ...current.rewrites, [bullet.bullet_id]: response },
          pending: { ...current.pending, [bullet.bullet_id]: false },
        }
      })
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Failed to generate rewrite."
      toast.error(message)
      setState((current) => {
        if (current.kind !== "coach_ready") return current
        return {
          ...current,
          pending: { ...current.pending, [bullet.bullet_id]: false },
        }
      })
    }
  }

  if (!enabled) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-muted/30 px-4 py-6 text-center text-sm text-muted-foreground">
        Upload a resume first to get tailored resume tips.
      </div>
    )
  }

  if (state.kind === "loading") {
    return (
      <div className="flex items-center justify-center rounded-xl border border-border bg-card/50 px-4 py-10 text-sm text-muted-foreground">
        <Spinner className="mr-2 size-4" />
        Loading suggestions…
      </div>
    )
  }

  if (state.kind === "error") {
    return (
      <div className="space-y-3 rounded-xl border border-destructive/40 bg-destructive/5 px-4 py-4 text-sm text-destructive">
        <p>{state.message}</p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void load()}
        >
          Retry
        </Button>
      </div>
    )
  }

  if (state.kind === "empty") {
    return (
      <div className="space-y-4 rounded-xl border border-border bg-card/50 px-5 py-6">
        <div className="flex items-start gap-3">
          <Sparkles className="mt-0.5 size-5 shrink-0 text-primary" />
          <div className="space-y-1">
            <p className="text-sm font-medium text-foreground">
              Get tailored resume tips
            </p>
            <p className="text-xs leading-relaxed text-muted-foreground">
              We&apos;ll suggest 2-5 skills or short bullets to add to
              your resume, based on what your top job matches are asking
              for. Each suggestion is grounded in real job descriptions,
              cites the source, and may include a course link and a
              quick &ldquo;why it matters&rdquo; note.
            </p>
          </div>
        </div>
        <Button
          type="button"
          onClick={() => void handleRefresh()}
        >
          Generate suggestions
        </Button>
      </div>
    )
  }

  // ready or refreshing — narrow the union explicitly so TS sees
  // `data` is available.
  if (state.kind !== "ready" && state.kind !== "refreshing") {
    // Coach-flow states render below. They're mutually exclusive
    // with the one-shot view: when the user clicks "Coach me",
    // the whole card switches over.
    return (
      <CoachFlowView
        state={state}
        onStart={handleStartCoach}
        onExit={handleExitCoach}
      />
    )
  }
  const suggestions = state.data.suggestions
  const generatedAt = formatTimestamp(state.data.created_at)
  const isRefreshing = state.kind === "refreshing"

  return (
    <div className="space-y-4 rounded-xl border border-border bg-card/50 px-5 py-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <Sparkles className="mt-0.5 size-5 shrink-0 text-primary" />
          <div className="space-y-1">
            <p className="text-sm font-medium text-foreground">
              Resume suggestions
            </p>
            <p className="text-xs text-muted-foreground">
              Generated {generatedAt}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/* COACH ME BUTTON TEMPORARILY HIDDEN.
              The /coach/rewrite endpoint is hanging on some
              OpenAI calls. The button is hidden until we
              diagnose the slowness. The backend route +
              service code is preserved so re-enabling is a
              one-line change. */}
          {/* <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void handleStartCoach()}
          >
            Coach me on bullets
          </Button> */}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void handleRefresh()}
            disabled={isRefreshing}
          >
            {isRefreshing ? (
              <>
                <Spinner className="mr-2 size-3" />
                Refreshing…
              </>
            ) : (
              "Refresh"
            )}
          </Button>
        </div>
      </div>

      {suggestions.length === 0 ? (
        <p className="rounded-md border border-dashed border-border bg-muted/30 px-3 py-4 text-sm text-muted-foreground">
          No suggestions passed grounding. Try refreshing — sometimes the
          model finds a different set of skills on retry.
        </p>
      ) : (
        <ul className="space-y-3">
          {suggestions.map((suggestion) => (
            <li
              key={`${suggestion.kind}-${suggestion.text}`}
              className="rounded-md border border-border bg-background/60 px-3 py-3"
            >
              <p className="text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">
                {KIND_LABEL[suggestion.kind]}
              </p>
              <p className="mt-1 text-sm font-medium text-foreground">
                {suggestion.text}
              </p>
              {suggestion.evidence.length > 0 ? (
                <details className="mt-2 group">
                  <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
                    Based on {suggestion.evidence.length} job
                    {suggestion.evidence.length === 1 ? "" : "s"}
                  </summary>
                  <ul className="mt-2 space-y-2 pl-3 text-xs leading-relaxed text-muted-foreground">
                    {suggestion.evidence.map((citation) => (
                      <li
                        key={`${citation.job_id}-${citation.quote}`}
                        className="border-l-2 border-border pl-2"
                      >
                        <CitationJobHeader
                          jobTitle={citation.job_title}
                          jobCompany={citation.job_company}
                          applyUrl={citation.apply_url}
                        />
                        <span className="mt-1 block italic">
                          &ldquo;{citation.quote}&rdquo;
                        </span>
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}
              {suggestion.why_it_matters ? (
                <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                  <span className="font-medium text-foreground">
                    Why it matters:{" "}
                  </span>
                  {suggestion.why_it_matters}
                </p>
              ) : null}
              {suggestion.learning_link ? (
                <a
                  href={suggestion.learning_link.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="mt-2 inline-flex items-center gap-1.5 text-xs font-medium text-primary hover:underline"
                >
                  Learn it: {suggestion.learning_link.label}
                  <ExternalLink className="size-3" />
                </a>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/**
 * Coach-flow view: replaces the one-shot view while a coach
 * session is in flight or active. The user clicked "Coach me on
 * bullets" and is now answering questions + receiving rewrites.
 */
function CoachFlowView({
  state,
  onStart,
  onExit,
}: {
  state: Extract<
    CardState,
    { kind: "coach_loading" } | { kind: "coach_ready" } | { kind: "coach_error" }
  >
  onStart: () => void
  onExit: () => void
}) {
  return (
    <div className="space-y-4 rounded-xl border border-border bg-card/50 px-5 py-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <Sparkles className="mt-0.5 size-5 shrink-0 text-primary" />
          <div className="space-y-1">
            <p className="text-sm font-medium text-foreground">Bullet coach</p>
            <p className="text-xs leading-relaxed text-muted-foreground">
              Answer the questions for any bullet to get a rewrite
              grounded in your own facts. Conversation state lives in
              memory and will be lost on refresh.
            </p>
          </div>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onExit}
        >
          Back to suggestions
        </Button>
      </div>
      {state.kind === "coach_loading" ? (
        <div className="flex items-center justify-center rounded-md border border-dashed border-border bg-muted/30 px-4 py-6 text-sm text-muted-foreground">
          <Spinner className="mr-2 size-4" />
          Looking for bullets to coach on…
        </div>
      ) : null}
      {state.kind === "coach_error" ? (
        <div className="space-y-3 rounded-md border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          <p>{state.message}</p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onStart}
          >
            Try again
          </Button>
        </div>
      ) : null}
      {state.kind === "coach_ready" ? (
        <CoachSection
          session={state.session}
          // `answers`, `rewrites`, and `pending` were unused after
          // the rewrite input UI was hidden. When re-enabling,
          // restore them here and in CoachSection's signature.
          rewrites={state.rewrites}
        />
      ) : null}
    </div>
  )
}

function CoachSection({
  session,
  rewrites,
}: {
  session: CoachStartResponse
  // NOTE: `answers` and `pending` were dropped from this signature
  // along with the rewrite input UI. When re-enabling, restore
  // them here and at the call site (search for `<CoachSection` in
  // this file).
  rewrites: Record<string, CoachRewriteResponse>
}) {
  return (
    <div className="space-y-4">
      {session.bullets.length === 0 ? (
        <p className="rounded-md border border-dashed border-border bg-muted/30 px-3 py-4 text-sm text-muted-foreground">
          No weak bullets found. Your resume already mentions scale
          and impact for everything we looked at.
        </p>
      ) : (
        <ul className="space-y-3">
          {session.bullets.map((bullet) => (
            <BulletCoachItem
              key={bullet.bullet_id}
              bullet={bullet}
              rewrite={rewrites[bullet.bullet_id]}
              // `answers`, `onAnswerChange`, `pending`, and
              // `onRequestRewrite` were dropped from the
              // BulletCoachItem signature while the rewrite UI
              // is hidden. See the NOTE in BulletCoachItem's
              // definition for how to restore them.
            />
          ))}
        </ul>
      )}

      {session.skills.length > 0 ? (
        <div className="space-y-2 border-t border-border pt-3">
          <p className="text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">
            Skills from the same scan
          </p>
          <ul className="space-y-2">
            {session.skills.map((skill) => (
              <li
                key={`${skill.kind}-${skill.text}`}
                className="text-sm text-foreground"
              >
                {skill.text}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}
