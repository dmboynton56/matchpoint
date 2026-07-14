import { useCallback, useEffect, useRef, useState } from "react"
import { Check, Clipboard, ExternalLink, RefreshCw, Sparkles, X } from "lucide-react"
import { toast } from "sonner"

import {
  getMySuggestions,
  refreshSuggestions,
  rewriteBullet,
  startCoachSession,
  type ResumeSuggestionsResponse,
} from "@/apis/suggestions"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import type {
  CoachBullet,
  CoachCategory,
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
      /**
       * Per-bullet list of categories the user explicitly opted out of.
       * Empty answer text + Skip button = the same thing as not
       * filling it in, but we track the explicit intent so the
       * backend's "do not invent content" rule kicks in.
       */
      skipped_categories: Record<string, CoachCategory[]>
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
 * Short label for a qualitative category, used as a badge on
 * each question input. Maps the enum value to a more readable
 * form ("CAUSE_EFFECT" -> "Cause / effect"). The mapping is
 * intentionally short — these render as small inline pills.
 */
const CATEGORY_LABEL: Record<CoachCategory, string> = {
  SPECIFICITY: "Specificity",
  SCOPE: "Scope",
  OWNERSHIP: "Ownership",
  REPLACEMENT: "Replacement",
  CAUSE_EFFECT: "Cause / effect",
  ARTIFACT: "Artifact",
}

/**
 * Render a single WEAK bullet-coach entry: location breadcrumb,
 * weakness reason, original-text quote, one question input per
 * missing category, and either a rewrite result or a
 * "Get rewrite" button.
 *
 * The question inputs use the question.key as the map key. When
 * the LLM omits question.key (it can), the backend derives one
 * from the category. The UI uses question.key as the answer key
 * because that's what the backend's coverage validator maps back
 * to categories server-side.
 */
function BulletCoachWeakItem({
  bullet,
  answers,
  skippedCategories,
  onAnswerChange,
  onToggleSkip,
  rewrite,
  pending,
  onRequestRewrite,
}: {
  bullet: CoachBullet
  answers: Record<string, string>
  skippedCategories: CoachCategory[]
  onAnswerChange: (key: string, value: string) => void
  onToggleSkip: (category: CoachCategory) => void
  rewrite: CoachRewriteResponse | undefined
  pending: boolean
  onRequestRewrite: () => void
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

  // The backend derives a default key from the category when the
  // LLM omits question.key. We mirror that derivation here so the
  // answer map keys match what the backend expects.
  const fallbackKeyFor: Record<CoachCategory, string> = {
    SPECIFICITY: "specificity",
    SCOPE: "scope",
    OWNERSHIP: "ownership",
    REPLACEMENT: "replacement",
    CAUSE_EFFECT: "cause_effect",
    ARTIFACT: "artifact",
  }
  const resolvedKey = (question: { key?: string | null; category: CoachCategory }) =>
    question.key || fallbackKeyFor[question.category]

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

      {/* Question inputs */}
      {bullet.questions.length > 0 ? (
        <div className="space-y-2">
          <p className="text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">
            Answer to strengthen
          </p>
          <ul className="space-y-2">
            {bullet.questions.map((question) => {
              const key = resolvedKey(question)
              const isSkipped = skippedCategories.includes(question.category)
              const value = answers[key] ?? ""
              return (
                <li
                  key={key}
                  className="space-y-1 rounded-md border border-border bg-muted/20 px-2.5 py-2"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="inline-flex items-center rounded-full border border-border bg-background px-2 py-0.5 text-[10px] font-semibold tracking-wider text-foreground uppercase">
                        {CATEGORY_LABEL[question.category]}
                      </span>
                      <label
                        htmlFor={`q-${bullet.bullet_id}-${key}`}
                        className="text-xs font-medium text-foreground"
                      >
                        {question.label}
                      </label>
                    </div>
                    <button
                      type="button"
                      onClick={() => onToggleSkip(question.category)}
                      className="text-[10px] font-medium text-muted-foreground hover:text-foreground"
                    >
                      {isSkipped ? "Unskip" : "Skip"}
                    </button>
                  </div>
                  {question.hint ? (
                    <p className="text-[11px] text-muted-foreground">
                      {question.hint}
                    </p>
                  ) : null}
                  {isSkipped ? (
                    <p className="text-[11px] italic text-muted-foreground/70">
                      Skipped — the rewrite won&apos;t invent anything for this
                      category.
                    </p>
                  ) : (
                    <textarea
                      id={`q-${bullet.bullet_id}-${key}`}
                      value={value}
                      onChange={(event) =>
                        onAnswerChange(key, event.target.value)
                      }
                      rows={2}
                      placeholder="A short description — qualitative, not a number."
                      className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground placeholder:text-muted-foreground/60 focus:border-primary focus:outline-none"
                    />
                  )}
                </li>
              );
            })}
          </ul>
          <div className="flex items-center gap-2 pt-1">
            <Button
              type="button"
              size="sm"
              onClick={onRequestRewrite}
              disabled={pending}
            >
              {pending ? (
                <>
                  <Spinner className="mr-2 size-3" />
                  Rewriting…
                </>
              ) : (
                "Get rewrite"
              )}
            </Button>
            <p className="text-[11px] italic text-muted-foreground/70">
              The rewrite will use words from your answers + the cited job.
            </p>
          </div>
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
          </div>
          {rewrite.citation_quote ? (
            <p className="text-[11px] text-muted-foreground">
              <CitationJobHeader
                jobTitle={rewrite.citation_job_title}
                jobCompany={rewrite.citation_job_company}
                applyUrl={rewrite.citation_apply_url}
              />
              <span className="mt-1 block italic">
                &ldquo;{rewrite.citation_quote}&rdquo;
              </span>
            </p>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

/**
 * Render a STRONG bullet-coach entry: the coach's positive
 * feedback on a bullet that already covers all six qualitative
 * categories. No inputs, no rewrite button -- the bullet is
 * already strong.
 */
function BulletCoachStrongItem({ bullet }: { bullet: CoachBullet }) {
  return (
    <li className="rounded-md border border-emerald-300/60 bg-emerald-50/40 px-3 py-3 space-y-2 dark:border-emerald-700/50 dark:bg-emerald-950/20">
      <div className="flex items-start gap-2">
        <Check className="mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
        <div className="space-y-1">
          <p className="text-[11px] font-semibold tracking-wider text-emerald-700 uppercase dark:text-emerald-300">
            Already strong
          </p>
          <p className="text-xs leading-relaxed text-foreground/90">
            {bullet.strength_reason}
          </p>
        </div>
      </div>

      <blockquote className="rounded border-l-2 border-emerald-300/60 bg-background/60 px-3 py-2 text-sm italic text-foreground/90">
        &ldquo;{bullet.original_text}&rdquo;
      </blockquote>

      <p className="text-[11px] text-muted-foreground">
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
    </li>
  );
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
        skipped_categories: {},
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

  const handleToggleSkip = (
    bulletId: string,
    category: CoachCategory,
  ) => {
    setState((current) => {
      if (current.kind !== "coach_ready") return current
      const existing = current.skipped_categories[bulletId] ?? []
      const next = existing.includes(category)
        ? existing.filter((c) => c !== category)
        : [...existing, category]
      return {
        ...current,
        skipped_categories: {
          ...current.skipped_categories,
          [bulletId]: next,
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
      // Pull current values out of the state ref so we don't race
      // with pending setState calls above.
      const currentState = state
      if (currentState.kind !== "coach_ready") return
      const answers = currentState.answers[bullet.bullet_id] ?? {}
      const skipped =
        currentState.skipped_categories[bullet.bullet_id] ?? []
      const response = await rewriteBullet({
        session_id: currentState.session.session_id,
        bullet_id: bullet.bullet_id,
        answers,
        skipped_categories: skipped,
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
      // Keep the user's answers intact so they can rephrase and retry.
      // The backend's 502 detail is the user-facing message -- it
      // explains which categories the rewrite didn't reflect.
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
    // Workshop-flow states render below. They're mutually exclusive
    // with the one-shot view: when the user clicks "Workshop my
    // bullets", the whole card switches over.
    return (
      <CoachFlowView
        state={state}
        onStart={handleStartCoach}
        onExit={handleExitCoach}
        onAnswerChange={handleAnswerChange}
        onToggleSkip={handleToggleSkip}
        onRequestRewrite={handleRequestRewrite}
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
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void handleStartCoach()}
          >
            Workshop my bullets
          </Button>
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
 * Workshop-flow view: replaces the one-shot view while a bullet
 * workshop session is in flight or active. The user clicked
 * "Workshop my bullets" and is now defending gaps the tool
 * surfaced + receiving rewrites.
 *
 * The session returns up to 5 bullets -- a mix of STRONG and
 * WEAK. Strong bullets render as positive feedback (no rewrite
 * available). Weak bullets get one input per missing category +
 * a Skip button per category + a Get rewrite button.
 */
function CoachFlowView({
  state,
  onStart,
  onExit,
  onAnswerChange,
  onToggleSkip,
  onRequestRewrite,
}: {
  state: Extract<
    CardState,
    { kind: "coach_loading" } | { kind: "coach_ready" } | { kind: "coach_error" }
  >
  onStart: () => void
  onExit: () => void
  onAnswerChange: (bulletId: string, key: string, value: string) => void
  onToggleSkip: (bulletId: string, category: CoachCategory) => void
  onRequestRewrite: (bullet: CoachBullet) => void
}) {
  // Count bullets the user has actually typed an answer into. We
  // treat an empty string the same as "not typed" so a half-deleted
  // field doesn't count. Used by the refresh button to decide whether
  // to show a confirm dialog before discarding answers.
  const answeredBulletCount =
    state.kind === "coach_ready"
      ? Object.values(state.answers).filter((byKey) =>
          Object.values(byKey).some(
            (value) => typeof value === "string" && value.trim().length > 0,
          ),
        ).length
      : 0
  const hasTypedAnswers = answeredBulletCount > 0

  // The refresh button does what "Back to suggestions" + "Coach
  // me on bullets" does: re-call /coach/start with a fresh
  // session_id. We confirm first only when the user has typed
  // answers — a no-answers refresh shouldn't make them read a
  // dialog just to click through. CONFIRM first.
  const handleRefreshClick = () => {
    if (hasTypedAnswers) {
      const ok = window.confirm(
        `You have answers typed in for ${answeredBulletCount === 1 ? "1 bullet" : `${answeredBulletCount} bullets`}. Refreshing will discard them and pick new bullets to work on.`,
      )
      if (!ok) return
    }
    onStart()
  }

  return (
    <div className="space-y-4 rounded-xl border border-border bg-card/50 px-5 py-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <Sparkles className="mt-0.5 size-5 shrink-0 text-primary" />
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <p className="text-sm font-medium text-foreground">
                Bullet workshop
              </p>
              {/* Experimental: the rewrites can occasionally drop
                  measurable details the user didn't volunteer
                  verbatim, so we don't want anyone treating the
                  output as final. The pill sets expectations before
                  someone pastes it into a real application. */}
              <Badge variant="outline">Experimental</Badge>
            </div>
            <p className="text-xs leading-relaxed text-muted-foreground">
              We&apos;ll surface a few of your bullets and ask you to
              defend the gaps — missing specifics, scope, ownership, or
              results — so we can rewrite them with real numbers instead
              of filler. Strong bullets are flagged as-is. Conversation
              state lives in memory and will be lost on refresh.
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleRefreshClick}
            disabled={state.kind === "coach_loading"}
            aria-label="Refresh questions"
          >
            <RefreshCw className="mr-1.5 size-3" />
            Refresh questions
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onExit}
            disabled={state.kind === "coach_loading"}
          >
            <X className="mr-1.5 size-3" />
            Back to suggestions
          </Button>
        </div>
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
          answers={state.answers}
          skippedCategories={state.skipped_categories}
          rewrites={state.rewrites}
          pending={state.pending}
          onAnswerChange={onAnswerChange}
          onToggleSkip={onToggleSkip}
          onRequestRewrite={onRequestRewrite}
        />
      ) : null}
    </div>
  )
}

/**
 * Render the session's bullets. Branches on verdict:
 *   STRONG -> BulletCoachStrongItem (positive feedback, no inputs)
 *   WEAK   -> BulletCoachWeakItem (one input per missing category)
 */
function CoachSection({
  session,
  answers,
  skippedCategories,
  rewrites,
  pending,
  onAnswerChange,
  onToggleSkip,
  onRequestRewrite,
}: {
  session: CoachStartResponse
  answers: Record<string, Record<string, string>>
  skippedCategories: Record<string, CoachCategory[]>
  rewrites: Record<string, CoachRewriteResponse>
  pending: Record<string, boolean>
  onAnswerChange: (bulletId: string, key: string, value: string) => void
  onToggleSkip: (bulletId: string, category: CoachCategory) => void
  onRequestRewrite: (bullet: CoachBullet) => void
}) {
  const strongBullets = session.bullets.filter((b) => b.verdict === "STRONG")
  const weakBullets = session.bullets.filter((b) => b.verdict === "WEAK")

  return (
    <div className="space-y-4">
      {session.bullets.length === 0 ? (
        <p className="rounded-md border border-dashed border-border bg-muted/30 px-3 py-4 text-sm text-muted-foreground">
          No bullets surfaced this time. Try again in a minute — the
          coach picks different bullets each session.
        </p>
      ) : null}

      {weakBullets.length > 0 ? (
        <div className="space-y-2">
          <p className="text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">
            Needs work
          </p>
          <ul className="space-y-3">
            {weakBullets.map((bullet) => (
              <BulletCoachWeakItem
                key={bullet.bullet_id}
                bullet={bullet}
                answers={answers[bullet.bullet_id] ?? {}}
                skippedCategories={
                  skippedCategories[bullet.bullet_id] ?? []
                }
                onAnswerChange={(key, value) =>
                  onAnswerChange(bullet.bullet_id, key, value)
                }
                onToggleSkip={(category) =>
                  onToggleSkip(bullet.bullet_id, category)
                }
                rewrite={rewrites[bullet.bullet_id]}
                pending={Boolean(pending[bullet.bullet_id])}
                onRequestRewrite={() => onRequestRewrite(bullet)}
              />
            ))}
          </ul>
        </div>
      ) : null}

      {strongBullets.length > 0 ? (
        <div className="space-y-2">
          <p className="text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">
            Already strong
          </p>
          <ul className="space-y-3">
            {strongBullets.map((bullet) => (
              <BulletCoachStrongItem
                key={bullet.bullet_id}
                bullet={bullet}
              />
            ))}
          </ul>
        </div>
      ) : null}

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