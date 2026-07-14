# Bullet Coach v2: Qualitative Categories Instead of Factual Q&A

## Why this is being written

The current bullet coach asks the LLM to pick 2-4 questions per weak bullet and
asks the user for numeric facts (user counts, request volume, latency, team size).
In practice:

- Users often don't know the number ("how many users did the platform have?" —
  "idk, like 40?"). They either lie or skip.
- The LLM picks questions stochastically, so the same bullet gets different
  questions across runs.
- A user with nothing to measure gets a stuck flow (the validator drops their
  rewrite for having no metric, even when their work was meaningful).

The fix is to reframe what the coach is asking for. Resume bullets don't need
numbers to be strong — they need **specificity, scope, ownership, replacement,
cause→effect, and artifacts**. These are qualitative properties that the user
almost always knows the answer to without measuring.

This spec covers (1) what's already built for bullet coach on `jasonbullets`,
(2) what changes to convert it from numeric-facts to qualitative-categories,
(3) the validator changes, (4) the prompt changes, and (5) the UI impact.

---

## Part 1 — What already exists on `jasonbullets`

Bullet coach is implemented end-to-end. Five backend files plus a UI surface
already ship the current behavior.

### 1.1 Schemas (`backend/app/schemas/suggestions.py`)

- `CoachQuestion` — single free-text question with `key`, `label`, optional
  `hint`, `type: CoachQuestionType.TEXT`. `MAX_COACH_QUESTIONS = 4`.
- `CoachQuestionType` enum — currently only `TEXT`. Comment says NUMBER /
  CHOICE / BOOLEAN are future.
- `BulletDiagnosis` — five booleans classifying a bullet:
  `mentions_action`, `mentions_technology`, `mentions_scope`,
  `mentions_outcome`, `mentions_metric`. Drives the UI's "why is this weak"
  row. The validator doesn't use it — only the prompt does as a conditioning
  signal.
- `BulletLocation` — `section`, `entry_title`, `entry_text_snippet`. Surfaces
  "your bullet in Work Experience → Flatiron School — Software Engineering
  Coach" in the UI. Best-effort: the parser can miss headers, in which case
  the route layer falls back to `section = "Resume"`.
- `CoachBullet` — the per-bullet payload: `bullet_id`, `original_text`,
  `weakness_reason`, citation fields, `questions: list[CoachQuestion]`
  (min 1, max 4), optional `diagnosis` and `location`.
- `CoachStartResponse` — `{session_id, skills, bullets}`. SKILL suggestions
  are carried over from the one-shot flow so the UI can render both in one
  view.
- `CoachRewriteRequest` — `{session_id, bullet_id, answers: dict[str,str]}`.
- `CoachRewriteResponse` — `{bullet_id, original_text, rewritten_text,
  citation_*}`.
- `validate_coach_start_request` — trims to `MAX_COACH_BULLETS_PER_SESSION
  = 5`, dedupes bullet IDs, validates question key format
  (`^[A-Za-z][A-Za-z0-9_]{0,63}$`), drops bullets whose original_text is
  under 8 chars.
- `validate_coach_rewrite_answer_keys` — checks every requested key has
  some entry in the answers dict. Empty strings are allowed (skip).
- `validate_coach_bullet_grounding` — drops bullets whose `original_text`
  isn't a substring of any parsed-resume section title / entry title /
  entry text. Normalized whitespace.
- `validate_coach_rewrite_grounding` — three structural rules:
  1. citation_quote must be substring of cited job description
  2. rewrite is meaningfully different from original (not identical)
  3. every substantive token in rewrite must appear in {original bullet,
     user answers, citation quote}, minus a `_COACH_STRUCTURAL_TOKENS`
     allowlist (verbs, articles, prepositions, vague qualifiers)
- `MAX_COACH_ANSWER_LEN = 280`, `MAX_COACH_BULLETS_PER_SESSION = 5`.

### 1.2 Session store (`backend/app/services/bullet_coach.py`)

In-memory dict keyed by `session_id` (a `secrets.token_urlsafe(16)` value).
Holds: `user_id`, `created_at`, `last_touched_at`, `skills` (snapshot),
`bullets` (each with an `answers` slot that fills in over time),
`job_descriptions` (cached at start so rewrite doesn't re-fetch from Turso).

- 1-hour idle TTL.
- Process-wide `threading.Lock` for FastAPI's thread-pool dispatch.
- `create_session`, `get_session`, `get_bullet`, `save_answers`,
  `get_citation_description`, `prune_expired`, `clear_all` (test helper).
- Module docstring is explicit: not multi-process safe, not persistent.
  Migration path is to swap `_sessions` for a Supabase table; public API
  doesn't change.

### 1.3 LLM service (`backend/app/services/bullet_coach_llm.py`)

Two OpenAI calls.

- `start_coach_session(...)` — `beta.chat.completions.parse` with structured
  `_CoachStartLLMResponse` schema. `COACH_MODEL = "gpt-4o-mini"`,
  `COACH_TEMPERATURE = 0.2`, `COACH_TIMEOUT_SECONDS = 45`. Returns
  `(skills, bullets)` after `validate_coach_start_request`.
- `rewrite_bullet(...)` — plain `chat.completions.create` (NOT the beta
  parse endpoint — comment says structured outputs is "intermittently slow
  on small payloads, 30+ second response times on what should be a 2-3
  second call"). `_strip_rewrite_response` handles the JSON-or-prose-or-
  fenced response with five extraction strategies, falling back to the
  original bullet.
- `COACH_START_SYSTEM_PROMPT` — instructs the LLM to identify weak bullets
  (defined as "lack ANY of: a number, a percentage, a $ amount, a
  latency/time figure, a request-volume or user-count figure, a team
  size, or a concrete business outcome"), ask 2-4 targeted questions,
  return SKILL suggestions in the same call.
- `COACH_REWRITE_SYSTEM_PROMPT` — instructs the LLM to use ONLY the
  original bullet, the user's answers, and the cited quote. Encourages
  but does not structurally enforce the grounding (the validator does).
- `_build_start_user_message` includes `PREFERRED_SKILLS` (the curated
  learning-link table) and `_format_parsed_resume` (sections → entries
  with each entry text truncated to 300 chars). Falls back to raw text
  if no parsed structure.
- `_build_rewrite_user_message` emits the original, the cited quote, and
  the candidate's answers (with "(skipped)" for empty values).

### 1.4 Route (`backend/app/routes/suggestions.py`)

- `POST /suggestions/coach/start` — fetches resume + top matches, calls
  `parse_resume`, calls `start_coach_session`, applies
  `_apply_citation_enrichment` (skills) and `_attach_bullet_enrichment`
  (bullets), runs `validate_coach_bullet_grounding`, snapshots
  `job_descriptions`, calls `create_session`, returns.
- `POST /suggestions/coach/rewrite` — looks up session + bullet, checks
  user owns session, validates answer keys, persists answers, calls
  `rewrite_bullet`, runs `validate_coach_rewrite_grounding`, returns the
  rewrite.
- Top-level module docstring notes: "LLM never invents numbers — instead
  it asks the user for the facts it needs."

### 1.5 Frontend (`frontend/src/components/user/ResumeSuggestionsCard.tsx`)

- Inline `CoachSection` component (no separate file).
- State machine: `coach_loading | coach_ready | coach_error`.
- For each bullet: renders location breadcrumb, original text, weakness
  reason, one input per question, a "Rewrite" button.
- Communicates with the parent via `window.addEventListener("coach-answer",
  ...)` and `window.addEventListener("coach-rewrite", ...)`. Bubbles events
  up to `ResumeSuggestionsCard` which calls the API and renders the result.
- A "hanging on some requests" comment exists at line ~171 referencing
  /coach/rewrite slowness investigation. Existing /coach/rewrite is not
  currently called from the UI — only /coach/start is wired.
- `frontend/src/apis/suggestions.ts` has typed wrappers for both endpoints.

### 1.6 Tests

- `backend/tests/test_suggestions.py` has `test_bullet_coach_grounding_drops_fabricated`
  and `test_bullet_coach_grounding_normalizes_whitespace` covering
  `validate_coach_bullet_grounding`. Plus
  `StripRewriteResponseTests` covering `_strip_rewrite_response`.
- No dedicated `test_bullet_coach.py` exists. No tests cover
  `validate_coach_start_request`, `validate_coach_rewrite_answer_keys`,
  or `validate_coach_rewrite_grounding`.

### 1.7 What's NOT built yet

- The "weak bullet identification rules" prompt section leans entirely on
  the LLM — there's no deterministic heuristic, no regex check, no
  scoring. Every run is potentially different.
- The "if user can't answer, the rewrite fails" path doesn't exist. The
  validator just rejects with 502.
- The `BulletDiagnosis` field is currently used only for the UI affordance
  — it isn't checked against the original text (the comment in the schema
  says "if mentions_metric = true but the original text has no number,
  something is off", but nothing implements that check).
- The UI CoachSection is currently not wired to call /coach/rewrite
  end-to-end. The "Rewrite" button exists but the flow stalls.

---

## Part 2 — What changes: qualitative categories

### 2.1 Replace the question schema

Current `CoachQuestion` is type-agnostic free text. The category-gap design
needs questions to be tied to a known category, both for the UI and the
validator.

**Change:** add a `category: CoachCategory` field to `CoachQuestion`. The
LLM produces one question per gap it identifies. The validator knows
which categories were filled.

```python
class CoachCategory(str, Enum):
    SPECIFICITY = "SPECIFICITY"     # What was the most interesting thing you built?
    SCOPE = "SCOPE"                 # Who used this? Audience / scale / context.
    OWNERSHIP = "OWNERSHIP"         # Did you lead this? Who else worked on it?
    REPLACEMENT = "REPLACEMENT"     # What existed before, or what got unblocked?
    CAUSE_EFFECT = "CAUSE_EFFECT"   # What changed because of this?
    ARTIFACT = "ARTIFACT"           # Name the thing (API, dashboard, rule, doc).
```

`CoachQuestion` gains `category: CoachCategory`. `key` is derived from
category (`spec`, `scope`, `own`, `replace`, `cause_effect`, `artifact`)
unless the LLM supplies an override — but the validator keys off
`category`, not `key`, so a bad key doesn't sink the bullet.

Keep the `CoachQuestionType.TEXT` enum. Future NUMBER etc. stays future.

### 2.2 Replace the question-picking prompt

**Current:** LLM picks 2-4 free-form questions per bullet.

**Change:** LLM returns a structured `category_gaps: list[CoachCategory]`
per bullet, plus a question per gap. The categories drive everything;
the question text is just the label.

New system prompt section replaces the existing "Question design rules":

```
For each weak bullet, identify which categories are missing from the
original text. Pick from this fixed list:

  SPECIFICITY     — does the bullet name a concrete artifact or
                    describe the most interesting technical part?
  SCOPE           — does it say who used it / what touched it / how
                    big it was?
  OWNERSHIP       — does it say "I owned/led/shipped" rather than
                    "helped with / worked on"?
  REPLACEMENT     — does it say what existed before, or what got
                    unblocked because of this?
  CAUSE_EFFECT    — does it connect the work to an outcome ("X,
                    which led to Y" or "Y because X")?
  ARTIFACT        — does it name a specific thing (API, dashboard,
                    rule, doc, migration)?

Return one question per missing category. Use short labels (under 15
words). Categories, not numbers — the user can always answer
qualitative questions; numeric facts are optional and only useful when
the candidate actually has them.

Do not ask for numbers unless the candidate's cited job demands one
and the candidate would obviously have the figure.
```

**Tone shift:** the LLM no longer asks "how many users did the platform
have?" as a default. It asks "who used this? was it classmates, a club,
your cohort, external users?" — a question the user can answer without
measuring.

### 2.3 Replace `BulletDiagnosis` with a category checklist

The current five booleans (`mentions_action`, `mentions_technology`,
`mentions_scope`, `mentions_outcome`, `mentions_metric`) overlap awkwardly
with the new categories. Replace with the six CoachCategory booleans:

```python
class CategoryChecklist(BaseModel):
    SPECIFICITY: bool
    SCOPE: bool
    OWNERSHIP: bool
    REPLACEMENT: bool
    CAUSE_EFFECT: bool
    ARTIFACT: bool
```

The LLM fills these in for every bullet. The UI renders them as
checkmarks/crosses (reuses the existing affordance). The route layer
derives `category_gaps` from this checklist: `gaps = [c for c in
CoachCategory if not checklist[c]]`.

If the LLM puts a category in `gaps` that contradicts the checklist (i.e.
the checklist says `SPECIFICITY: true` but `gaps` contains SPECIFICITY),
the route layer trusts the gaps list — the LLM's signal about what's
missing matters more than the boolean reflection of the original text.

### 2.4 Add a "I don't know" path

The current flow treats empty-string answers as a skip — the rewrite
runs anyway, and the validator may or may not reject it depending on
whether the LLM hallucinates something for the gap.

**Change:** surface the "skip" explicitly in the request schema.

- `CoachRewriteRequest.answers: dict[str, str]` stays. Empty string
  remains the skip signal.
- Add a new optional field `skipped_categories: list[CoachCategory]`
  the UI fills in for any category the user opted out of (e.g. they
  said "I genuinely don't know who used it" — the UI provides a small
  "skip this" button per question that adds the category here).
- The rewrite prompt explicitly handles skipped categories: "For any
  skipped category, do NOT invent content. Just leave that dimension
  out of the bullet."
- The validator gains a new rule: tokens added to the rewrite that
  relate to a skipped category must be traceable to either the
  original bullet or the cited quote — never to the empty answer
  (which is structurally absent).

### 2.5 Strengthen the rewrite grounding rule

Current `validate_coach_rewrite_grounding` has three rules:

1. citation_quote is a substring of cited job description.
2. rewrite != original (normalized).
3. every substantive rewrite token is in {original, answers, quote} minus
   structural allowlist.

**Change:** add a category-coverage rule.

```
For each category the user filled in (not skipped), at least one
substantive token from the user's answer for that category must appear
in the rewrite.
```

This means: if the user answered the SCOPE question with "my cohort of
40 students", the rewrite must contain "cohort" or "40" or "students".
This is the user's fingerprint on the rewrite — no LLM can satisfy the
rule without echoing the user's words. It's the structural guarantee
that the rewrite reflects what the user actually said, not what the
LLM wished they'd said.

Implementation: tokenize each non-skipped answer, intersect with rewrite
tokens, require at least one hit per category. Use the existing
`_tokens` helper. The structural allowlist does NOT apply here — we
want the user's substantive words, not grammatical glue.

Edge cases:
- User answered with one word ("yes", "no") and that word is in the
  structural allowlist. The category-coverage check fails for that
  category but the rewrite still passes overall (we log a warning,
  don't reject — the user gave us nothing substantive to anchor on).
- Category was skipped. Coverage check doesn't run.
- User answered in a different language. Same path as above —
  fingerprint missing, warn but don't reject.

### 2.6 Drop `mentions_metric` from the diagnosis

The previous diagnosis had `mentions_metric`. The new design replaces
it with REPLACEMENT and CAUSE_EFFECT, which are stronger. If the
candidate has a number, great; if not, REPLACEMENT and CAUSE_EFFECT
can produce equally strong bullets. The schema's enum shrinks from
five to six (SPECIFICITY, SCOPE, OWNERSHIP, REPLACEMENT, CAUSE_EFFECT,
ARTIFACT), which is intentional — categories are richer than the old
booleans.

---

## Part 3 — Concrete file changes

### 3.1 `backend/app/schemas/suggestions.py`

- Add `CoachCategory` enum (six members).
- Add `CoachBulletVerdict(str, Enum)` with members `STRONG` and
  `WEAK`.
- Add `category: CoachCategory` field to `CoachQuestion`. Make
  `key` auto-derived when missing (default `None`); validator
  fills it from the category.
- Replace `BulletDiagnosis` with `CategoryChecklist` (six booleans
  matching the enum). Update the field on `CoachBullet` from
  `diagnosis: BulletDiagnosis | None` to
  `checklist: CategoryChecklist | None`.
- Add `category_gaps: list[CoachCategory]` field to `CoachBullet`.
  Server-derived from checklist but LLM-allowed to override.
- Add `verdict: CoachBulletVerdict` field to `CoachBullet` (required).
- Add `strength_reason: str | None` field to `CoachBullet`. Required
  when verdict is STRONG, ignored otherwise. Validator enforces
  presence/absence.
- Update `CoachBullet.questions: list[CoachQuestion]`:
  - Drop the `min_length=1` constraint. Allow empty lists when
    verdict is STRONG.
  - Reject duplicate categories within a single bullet's questions
    (when verdict is WEAK).
- Add `skipped_categories: list[CoachCategory] | None` to
  `CoachRewriteRequest`.
- Update `validate_coach_start_request`:
  - When verdict is STRONG: drop bullets without a `strength_reason`,
    or with a strength_reason shorter than ~10 chars.
  - When verdict is WEAK: drop bullets with empty `questions` (the
    LLM should have asked at least one question for a weak bullet).
  - For both verdicts: keep the existing bullet-id dedupe and
    question-key format validation.
- Add `validate_coach_rewrite_category_coverage(...)` returning the
  same `(bool, list[str])` shape as
  `validate_coach_rewrite_grounding`. Skips bullets whose verdict
  is STRONG (no rewrite is possible).
- Update `validate_coach_rewrite_grounding` to call the new
  category-coverage check after the existing three rules. Fail
  reasons include category-level details.

### 3.2 `backend/app/services/bullet_coach_llm.py`

- Replace the "Question design rules" section of `COACH_START_SYSTEM_PROMPT`
  with the new categories-and-gaps prompt (see 2.2).
- Add a new section to `COACH_START_SYSTEM_PROMPT`: "Verdict rules".
  The LLM classifies each surfaced bullet as either `STRONG` or
  `WEAK`:
  - `STRONG`: bullet already has specificity, scope, ownership,
    replacement, cause→effect, AND artifact. No questions. Fill
    `strength_reason` with what's working.
  - `WEAK`: at least one category is missing. Fill the checklist
    with what's missing, generate one question per gap.
- Replace the "Weak bullet identification rules" section with the
  categories-based version. The "weak = lacks numbers" definition
  becomes "weak = at least one category gap or STRONG verdict is
  not warranted."
- Replace `_build_start_user_message`'s phrasing from "ask 2-4
  targeted questions" to "for each WEAK bullet, return one question
  per missing category; for each STRONG bullet, return a
  strength_reason and no questions."
- Update `_build_rewrite_user_message` to handle skipped
  categories: emit a separate `SKIPPED CATEGORIES (do not
  invent content for these):` block listing each skipped category
  and its null answer.
- Add `_build_rewrite_user_message` to mention the category-coverage
  expectation: "Every non-skipped category's answer should
  contribute at least one word to your rewrite."
- No model or temperature changes. The LLM still picks the
  questions, just from a constrained space.

### 3.3 `backend/app/services/bullet_coach.py`

- No structural changes. Session store already supports any
  question shape. `save_answers` already accepts arbitrary dicts.

### 3.4 `backend/app/routes/suggestions.py`

- `coach_start` — no functional change. The LLM service now returns
  bullets with verdicts + categories; the route passes them through.
- `coach_rewrite` — accept and pass through `skipped_categories`
  to `rewrite_bullet`. Reject the call early if the bullet's
  verdict is STRONG (return 400 with a clear message: "This
  bullet is already strong and has no questions to answer"). After
  the existing grounding check, also call
  `validate_coach_rewrite_category_coverage`. Return 502 on
  failure with the same error UX as today.

### 3.5 `backend/tests/test_suggestions.py`

- Add `CategoryCoverageTests` class with at least four cases:
  - `test_each_non_skipped_category_token_appears_in_rewrite`
  - `test_skipped_categories_are_not_required`
  - `test_one_word_answer_in_structural_allowlist_warns_but_passes`
  - `test_failed_coverage_rejects_with_actionable_reasons`
- Add `CoachCategoryTests` for the new enum:
  - six members, alphabetical order, stable values.
- Add `CategoryChecklistTests`:
  - derives `category_gaps` correctly from unchecked categories.
  - LLM override of gaps respected when checklist contradicts.
- Add `CoachVerdictTests`:
  - `test_strong_bullet_requires_strength_reason`
  - `test_strong_bullet_allows_zero_questions`
  - `test_weak_bullet_requires_at_least_one_question`
  - `test_strong_bullet_dropped_without_strength_reason`
  - `test_duplicate_categories_rejected_within_weak_bullet`
- Update existing tests if their `CoachBullet` literals need
  verdicts + categories added. Likely:
  - `test_bullet_coach_grounding_drops_fabricated`
  - `test_bullet_coach_grounding_normalizes_whitespace`
- Add `CoachRewriteRouteTests` for the new route-level behavior:
  - `test_rewrite_rejected_for_strong_bullet`
  - `test_rewrite_passes_through_skipped_categories`
- Add `CoachStartValidationTests` for the new
  `validate_coach_start_request` behavior (zero-question bullet
  allowed when verdict is STRONG, dropped when verdict is WEAK).

### 3.6 Frontend

- `frontend/src/components/user/ResumeSuggestionsCard.tsx`
  - For each bullet, branch on `verdict`:
    - `STRONG`: render `strength_reason` as a single line in green
      ("✓ Already strong — [reason]"). No input forms. No Rewrite
      button. Citation link still rendered.
    - `WEAK`: render the existing affordance (location breadcrumb,
      original text, weakness reason, one input per question, a
      Skip button per question, a Rewrite button).
  - For each WEAK-bullet question, render the `category` as a small
    label badge next to the input ("SCOPE", "ARTIFACT", etc.).
    Color them by category so the user can scan.
  - Add a "Skip" affordance per question that adds the category to
    `skipped_categories` and clears the answer.
  - Wire `/coach/rewrite` end-to-end if it's not already wired
    (per the existing comment, the UI currently stalls). Add the
    `skipped_categories` array to the request body.
  - Render the rewritten bullet + a small diff against the original
    so the user sees what changed.

No new files unless `CoachSection` gets long enough to warrant
extraction. Right now it's inline.

---

## Part 4 — Decisions made and open questions worth flagging

### 4.1 Decisions made

**Backward compatibility is not a concern.** This is a project, not a
production app affecting real users. The hard cutover is the right call:
rename `diagnosis` → `checklist`, drop the old five-boolean diagnosis,
add the six-category checklist, break whatever breaks. Frontend and
backend ship in the same PR. No deprecation cycle, no soft-launch
window.

**The LLM identifies both strong and weak bullets.** Instead of the
coach looking only for gaps, the LLM classifies each bullet it surfaces
as either `STRONG` or `WEAK`:

- `WEAK` bullets get the existing treatment: checklist of which
  categories are missing, one question per gap, the user fills in
  answers, the rewrite runs.
- `STRONG` bullets still appear in the response (the user wants to
  know what the coach thinks is already working), but with no
  questions and a `strength_reason: str` field explaining what's
  working. The UI renders these as "✓ Already strong — [reason]"
  with no question forms. The user can see the coach's positive
  feedback without doing any work.

Schema changes implied by this decision:

- New enum `CoachBulletVerdict(str, Enum)` with members `STRONG` and
  `WEAK`.
- New field on `CoachBullet`: `verdict: CoachBulletVerdict`.
- New field on `CoachBullet`: `strength_reason: str | None` (required
  when verdict is STRONG, optional otherwise).
- For STRONG bullets, `questions: list[CoachQuestion]` is empty (the
  existing `min_length=1` constraint needs to relax or be conditional
  on verdict). The validator must allow zero questions when verdict is
  STRONG.
- For STRONG bullets, the route layer should still attach citation
  enrichment (so the user can see which job this bullet was
  evaluated against) but should not call `coach_rewrite` (nothing to
  rewrite).

UI changes implied by this decision:

- The coach list is now a mix of "✓ Already strong" entries and
  "Needs work" entries. The user can see both kinds of feedback in
  one view.
- STRONG bullets are visually distinct (green checkmark, no input
  forms) but render in the same scrollable list.
- The "✓ Already strong" affordance is the primary positive-feedback
  state, not a fallback. Treat it as a feature, not an edge case.

### 4.2 Open questions

1. **Skip UX.** When a user says "I don't know" to SCOPE, the rewrite
   should not invent an audience. That's the rule. But should the UI
   show a placeholder ("we won't make anything up for this one") or
   just silently drop the question from the rewrite? I'd default to
   the explicit placeholder — it's honest about why the bullet might
   still feel thin.

2. **Two-pass coaching.** Some bullets will need more than one
   category filled. Showing all six questions at once might be
   overwhelming. Should we show one question at a time and let the
   user advance? That's a UX change beyond this spec but worth
   considering after the MVP ships.

3. **Test runs.** I'd suggest a manual smoke test before shipping:
   pick a real user with a real resume, run coach_start + coach_rewrite
   on a known weak bullet, eyeball whether the rewrite actually uses
   the user's words. The category-coverage check is structural
   guarantee but the user experience of it is something only a human
   can validate.

---

## Part 5 — Estimated scope

- Schemas: ~110 lines added/changed, ~30 removed (the old diagnosis
  shrinks, the verdict enum + strength_reason field + skip-validation
  logic add).
- LLM prompt: ~60 lines rewritten (the question-picking section +
  the new verdict section).
- Route: ~15 lines added (pass through skipped_categories, reject
  STRONG bullets early, run new validator).
- Tests: ~200 lines added (CategoryCoverageTests, CoachCategoryTests,
  CategoryChecklistTests, CoachVerdictTests, CoachRewriteRouteTests,
  CoachStartValidationTests, updated existing).
- Frontend: ~70 lines added (STRONG/WEAK branching, badges, skip
  affordance, end-to-end wire).

Total: roughly 2 working days end-to-end if you write the schema +
prompts and I write the tests + UI. Reuses everything in Part 1 — no
new files unless `CoachSection` gets extracted, no new endpoints, no
new schema migrations.

The verdict decision adds about 0.5 days over the original scope
estimate (an enum, two new schema fields, ~5 new tests, the
STRONG/WEAK UI branch). Worth it: positive feedback on already-strong
bullets is half the value of the coach, not an afterthought.