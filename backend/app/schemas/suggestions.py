from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


MAX_SUGGESTIONS = 5
MIN_SUGGESTIONS = 2  # relaxed from 3 — see validate_suggestions docstring
MAX_CITATION_QUOTE_LEN = 280
MAX_SUGGESTION_TEXT_LEN = 240
MAX_LEARNING_LABEL_LEN = 80
MAX_LEARNING_URL_LEN = 500
MAX_WHY_IT_MATTERS_LEN = 320


# Skills so broad that suggesting them as a single line item is
# useless to the candidate. The prompt tells the LLM to name a
# concrete tool, not a category — if the LLM slips and emits one of
# these verbatim, the validator drops the suggestion as a last-line
# defense. Comparison is case-insensitive on the normalized
# (lowercased, whitespace-collapsed) suggestion text.
#
# Adding to this list: a single line per banned phrase, with a
# comment explaining what concrete tool the LLM should have
# suggested instead. This makes the intent obvious to a future
# maintainer.
BANNED_SUGGESTION_TEXTS: frozenset[str] = frozenset({
    # === Bare single-word category phrases ===
    # No real tool called "AI" or "ML" — the LLM should name a
    # specific framework (TensorFlow, PyTorch), provider
    # (Anthropic, OpenAI), or concept (RAG, fine-tuning).
    "ai",
    "artificial intelligence",
    "ml",
    "machine learning",
    "deep learning",
    "neural networks",
    "neural network",
    "ai tools",
    "ml tools",
    "ai tech",
    "ai technology",
    "data science",
    # === Generic engineering categories ===
    # These are job-track terms, not skills to add to a resume line.
    "programming",
    "coding",
    "software development",
    "web development",
    "app development",
    # === Multi-word AI/ML category phrases ===
    # The LLM emits these as fill-in-the-blank "skills" but they're
    # patterns or buzzwords, not tools the candidate would put on
    # a resume. Each entry should suggest naming the concrete
    # alternative instead (see the prompt's HARD BLACKLIST section).
    # --- LLM/AI integration phrases (route to OpenAI API) ---
    "ai integration",
    "ai integrations",
    "llm integration",
    "llm integrations",
    # --- LLM/AI tooling phrases (route to LangChain) ---
    "ai-powered tools",
    "ai adoption",
    "ai tooling",
    "ai tools",
    "llm tooling",
    "llm tools",
    # --- AI infrastructure / system phrases ---
    "ai infrastructure",
    "ai sdk",
    "agentic systems",
    "ai systems",
    "ai solutions",
    "ai automation",
    "ai applications",
    "ai workflows",
    "ai experience",
    # --- Vector DB / embedding category phrases ---
    # "Vector database" is a category; specific tools are Pinecone,
    # Chroma, Qdrant, etc.
    "vector database",
    "vector databases",
    "vector db",
    "vector store",
    "vector stores",
    "vector search",
    "embeddings database",
    "embedding database",
    # --- RAG / fine-tuning (patterns, not tools) ---
    "rag",
    "retrieval augmented generation",
    "fine-tuning",
    "finetuning",
    "fine tuning",
    # --- LLM runtime category phrases ---
    "local llm",
    "local model",
    "local models",
    # === Vendor / model nicknames that aren't specific skills ===
    # The candidate should say "Anthropic API" / "Gemini API" /
    # "HuggingFace" — the vendor name alone is too vague.
    "claude",
    "anthropic",
    "gemini",
    "google ai",
    "google gemini",
    "google ai studio",
    "hugging face",
    "hf",
})


class SuggestionKind(str, Enum):
    # `KEYWORD` used to be a kind for "domain terms or phrasing"
    # (e.g. "stakeholder management"); it produced suggestions that read
    # as fluff because the substring-quote grounding check couldn't tell
    # a domain term from a passing mention. `BULLET` used to be a second
    # kind for "concrete accomplishment-style lines" the LLM could
    # generate in the one-shot /suggestions/refresh flow; it was
    # removed once the dedicated bullet-coach flow (POST
    # /suggestions/coach/start + /coach/rewrite) shipped, because
    # bullet rewriting is now an interactive Q&A flow and the one-shot
    # suggestion path only emits single tool/technology/framework
    # names. See the SYSTEM_PROMPT in services/suggestions.py for
    # the current shape.
    SKILL = "SKILL"


class Citation(BaseModel):
    job_id: str
    quote: str = Field(max_length=MAX_CITATION_QUOTE_LEN)
    # Job-context enrichment. All three are value-add: they let the UI
    # render "Vercel — Senior Software Engineer ↗" next to each quote,
    # linking to the external job posting. None when the validator
    # can't pair this citation with a known job (e.g. job_id not in
    # the user's top matches) or when the job has no apply_url.
    # The validator never requires these — they pass through.
    job_title: str | None = Field(default=None, max_length=MAX_SUGGESTION_TEXT_LEN)
    job_company: str | None = Field(default=None, max_length=MAX_SUGGESTION_TEXT_LEN)
    apply_url: str | None = Field(default=None, max_length=MAX_LEARNING_URL_LEN)


class LearningLink(BaseModel):
    label: str = Field(max_length=MAX_LEARNING_LABEL_LEN)
    url: str = Field(max_length=MAX_LEARNING_URL_LEN)


class Suggestion(BaseModel):
    kind: SuggestionKind
    text: str = Field(max_length=MAX_SUGGESTION_TEXT_LEN)
    evidence: list[Citation] = Field(min_length=1, max_length=10)
    # Optional enrichment. Both are value-add, not part of the
    # grounding contract — the validator never requires them, and
    # the UI hides them when null. A null `learning_link` is fine.
    learning_link: LearningLink | None = None
    why_it_matters: str | None = Field(
        default=None, max_length=MAX_WHY_IT_MATTERS_LEN
    )


class SuggestionsResponse(BaseModel):
    suggestions: list[Suggestion]


# ---------------------------------------------------------------------------
# Validation: drop suggestions that cannot be grounded in the job evidence.
# This is the hallucination guard.
#
# Grounding contract (TIGHT — kept strict):
#   1. Every citation's `quote` must be a substring of the cited job's
#      description (case-insensitive, whitespace-collapsed). This is the
#      primary fabrication guard. A quote the user can Ctrl-F to find.
#   2. The suggestion is accepted if it is grounded in EITHER:
#        (a) at least TWO surviving citations, OR
#        (b) one surviving citation AND the suggestion's text shares at
#            least one meaningful token (length >= 3) with that citation's
#            quote.
#      This replaces the previous "always require token overlap" rule. The
#      effect: cross-job prevalence becomes enough on its own (more
#      permissive in the multi-job case), but a single-job claim still has
#      to actually mention the skill in the quote (still tight on the
#      single-job case — fabrication guard intact).
#   3. No duplicate suggestion text (case-insensitive) in one response.
#   4. `learning_link` and `why_it_matters` are NOT required. They are
#      value-add, not grounding. Optional fields default to None and
#      survive validation as-is.
# Suggestions that fail the grounding contract are dropped silently. The
# UI handles below-minimum via a "Refresh" affordance.
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _tokens(text: str) -> set[str]:
    """Loose tokenization: lowercase, alphanumerics + a few separators only.
    Good enough for "does this suggestion's text appear in this quote".

    Trailing sentence punctuation (`.`, `,`, `;`, `:`, `!`, `?`) is
    stripped from each token. Without this, a quote like "We use Kotlin."
    produces a `kotlin.` token that fails to match the suggestion
    token `kotlin` — token-overlap returns False and a perfectly-cited
    "Kotlin" suggestion gets dropped at validation. Internal dots are
    preserved (e.g. `next.js` stays `next.js`), since the separator
    check below only triggers on word-boundary punctuation.
    """
    SENTENCE_PUNCT = ".,;:!?"
    normalized = _normalize(text)
    out: set[str] = set()
    current: list[str] = []
    for ch in normalized:
        if ch.isalnum() or ch in {"+", "#", ".", "-"}:
            current.append(ch)
        else:
            if current:
                out.add("".join(current))
                current = []
    if current:
        out.add("".join(current))
    # Strip trailing sentence punctuation from each token. Don't
    # touch internal dots — those stay as part of the token.
    cleaned = set()
    for tok in out:
        while tok and tok[-1] in SENTENCE_PUNCT:
            tok = tok[:-1]
        if tok:
            cleaned.add(tok)
    return {t for t in cleaned if len(t) >= 2}


def _quote_is_substring(quote: str, source_text: str) -> bool:
    return _normalize(quote) in _normalize(source_text)


def _has_token_overlap(suggestion_text: str, citation_quotes: list[str]) -> bool:
    suggestion_tokens = _tokens(suggestion_text)
    if not suggestion_tokens:
        return False
    quote_tokens: set[str] = set()
    for quote in citation_quotes:
        quote_tokens |= _tokens(quote)
    return bool(suggestion_tokens & quote_tokens)


def _is_grounded(
    suggestion_text: str, surviving_quotes: list[str]
) -> bool:
    """Apply the relaxed grounding contract from the module docstring.

    Returns True when the suggestion is well-supported by the surviving
    evidence, False when it should be dropped.
    """
    if len(surviving_quotes) >= 2:
        # Multi-job prevalence: grounding is strong enough on its own.
        return True
    # Single-job: require the suggestion's text to actually share a token
    # with the cited quote. Catches the "LLM invented a skill on a job
    # that doesn't mention it" case even when the substring check somehow
    # passed (it shouldn't, but defense-in-depth).
    return _has_token_overlap(suggestion_text, surviving_quotes)


def validate_suggestions(
    response: SuggestionsResponse,
    *,
    job_descriptions: dict[str, str],
) -> list[Suggestion]:
    """Return only the suggestions that pass the grounding checks.

    `job_descriptions` maps `job_id` -> job description text. Citations
    whose quotes cannot be found in their cited job are dropped, as is
    the whole suggestion if grounding fails after that.
    """
    seen_texts: set[str] = set()
    accepted: list[Suggestion] = []

    for suggestion in response.suggestions:
        key = _normalize(suggestion.text)
        if key in seen_texts:
            continue
        if not suggestion.evidence:
            continue
        # Hard blacklist: category phrases the prompt explicitly tells
        # the LLM never to suggest. The validator drops them as a
        # last-line defense in case the LLM emits one despite the
        # instruction. This is independent of the grounding check —
        # even a perfectly-cited "AI" suggestion is dropped here.
        if key in BANNED_SUGGESTION_TEXTS:
            continue

        surviving_quotes: list[str] = []
        surviving_job_ids: list[str] = []
        # Index the original evidence by job_id so we can pass the
        # LLM-supplied enrichment fields (job_title / job_company /
        # apply_url) through to the rebuilt Citation. The service
        # layer will overwrite them with authoritative values from
        # the user's top matches, but if the LLM happened to send
        # them and we have nothing better, the LLM's value survives
        # validation — it's just value-add.
        original_by_job_id: dict[str, Citation] = {
            c.job_id: c for c in suggestion.evidence
        }
        for citation in suggestion.evidence:
            description = job_descriptions.get(citation.job_id)
            if not description:
                continue
            if not _quote_is_substring(citation.quote, description):
                continue
            surviving_quotes.append(citation.quote)
            surviving_job_ids.append(citation.job_id)

        if not surviving_quotes:
            continue
        if not _is_grounded(suggestion.text, surviving_quotes):
            continue

        seen_texts.add(key)
        accepted.append(
            Suggestion(
                kind=suggestion.kind,
                text=suggestion.text,
                evidence=[
                    Citation(
                        job_id=jid,
                        quote=q,
                        # Pass-through enrichment. The LLM is allowed
                        # to populate these and we don't strip them —
                        # the service layer overwrites them with the
                        # authoritative title/company/apply_url from
                        # the user's top matches.
                        job_title=original_by_job_id[jid].job_title
                        if jid in original_by_job_id
                        else None,
                        job_company=original_by_job_id[jid].job_company
                        if jid in original_by_job_id
                        else None,
                        apply_url=original_by_job_id[jid].apply_url
                        if jid in original_by_job_id
                        else None,
                    )
                    for jid, q in zip(surviving_job_ids, surviving_quotes)
                ],
                # Pass through the optional enrichment fields unchanged.
                # Whatever the LLM sent (or null) survives validation.
                learning_link=suggestion.learning_link,
                why_it_matters=suggestion.why_it_matters,
            )
        )

    return accepted[:MAX_SUGGESTIONS]


# ---------------------------------------------------------------------------
# Bullet-coach flow
# ---------------------------------------------------------------------------
# A two-step conversational flow that rewrites a weak resume bullet with
# measurable impact. The LLM never invents numbers — instead it asks the
# user for the facts it needs (technologies, scale, team size, etc.) and
# the user supplies them. The rewrite then grounds only in those user
# facts plus the original bullet text plus the cited job's quote.
#
# Step 1 (`POST /suggestions/coach/start`):
#   - LLM scans the resume for weak bullets AND returns SKILL suggestions
#     (the same shape as the one-shot flow) in a single call. Returns
#     `session_id` + the bullets to coach on.
# Step 2 (`POST /suggestions/coach/rewrite`):
#   - User supplies answers to the LLM's questions. LLM returns the
#     rewritten bullet grounded in the original + answers + cited quote.
# ---------------------------------------------------------------------------

MAX_COACH_QUESTIONS = 4
MAX_COACH_QUESTION_LABEL_LEN = 200
MAX_COACH_ANSWER_LEN = 280
MAX_COACH_BULLETS_PER_SESSION = 5


class CoachQuestionType(str, Enum):
    TEXT = "TEXT"
    # Future: NUMBER, CHOICE, BOOLEAN. Text-only for the MVP — works for
    # every fact pattern and the validator doesn't need to know the type
    # to do substring grounding on the cited quote.


class CoachQuestion(BaseModel):
    # Stable key the UI uses to send the answer back. Must be unique
    # within a single bullet's question list (the LLM is asked to
    # produce ASCII keys like "scale" or "tech_stack").
    key: str = Field(max_length=64)
    label: str = Field(max_length=MAX_COACH_QUESTION_LABEL_LEN)
    # Hint shown in lighter text under the input. Optional.
    hint: str | None = Field(default=None, max_length=MAX_COACH_QUESTION_LABEL_LEN)
    type: CoachQuestionType = CoachQuestionType.TEXT


class BulletDiagnosis(BaseModel):
    """Structured analysis of why a bullet is weak.

    The LLM fills this in for every weak bullet it surfaces. The
    five booleans are independent — a bullet can be strong on
    `mentions_technology` but weak on `mentions_metric`, for example.
    The UI renders these as a row of checkmarks/crosses so the user
    can see WHY the bullet was flagged before they read the
    questions. The validator also uses them to sanity-check: if
    `mentions_metric = true` but the original text has no number,
    something is off.

    Each field is intentionally a bool (not an enum) because the
    MVP only needs yes/no. Future versions could add a `quality_score`
    per dimension (0-3) without breaking the schema.
    """

    # Did the bullet describe an action the candidate took?
    # ("Built", "Led", "Migrated", "Designed", "Owned", ...)
    mentions_action: bool
    # Did the bullet name specific tools, languages, frameworks?
    mentions_technology: bool
    # Did the bullet describe the size / scale of the work?
    # (How many users, requests/sec, MB, team size, etc.)
    mentions_scope: bool
    # Did the bullet describe a business or user outcome?
    # (Faster, cheaper, reduced churn, opened a new market, ...)
    mentions_outcome: bool
    # Did the bullet include a numeric anchor?
    # (A number, %, $, latency figure, request count, etc.)
    mentions_metric: bool


class BulletLocation(BaseModel):
    """Where this bullet lives in the candidate's resume.

    The UI uses this to render "Your bullet in Work Experience ->
    Flatiron School -- Software Engineering Coach" so the user
    can find the bullet in their actual resume file.

    All three fields are best-effort: the parser can usually
    recover section + entry from common resume formats, but it
    can miss headers or section names. When the parser can't,
    the route layer falls back to section = "Resume" and leaves
    the rest null. The LLM is allowed to override any of these
    if it has better information; the route layer trusts the
    LLM's choices.
    """

    # "Work Experience", "Projects", "Education", or "Resume"
    # (fallback when the parser couldn't identify a section).
    section: str = Field(max_length=80)
    # "Flatiron School -- Software Engineering Coach" or None
    # when the parser couldn't identify a specific entry. The
    # LLM may populate this even when the parser couldn't.
    entry_title: str | None = Field(default=None, max_length=160)
    # First ~200 chars of the entry's text. The UI shows this
    # so the user can see the context the bullet came from.
    # The LLM may populate this; the parser does not.
    entry_text_snippet: str | None = Field(
        default=None, max_length=400
    )


class CoachBullet(BaseModel):
    # Server-issued ID for this bullet in the session. Used by the UI
    # when calling /coach/rewrite. Random short string, opaque to the
    # client.
    bullet_id: str = Field(max_length=64)
    original_text: str = Field(max_length=MAX_SUGGESTION_TEXT_LEN)
    # Why this bullet is weak, surfaced to the user as the "why this
    # matters" framing. One short sentence.
    weakness_reason: str = Field(max_length=MAX_WHY_IT_MATTERS_LEN)
    # The job whose evidence supports the rewrite. The UI renders the
    # standard "Vercel — Senior Software Engineer ↗" link off this.
    citation_job_id: str = Field(max_length=64)
    citation_job_title: str | None = Field(
        default=None, max_length=MAX_SUGGESTION_TEXT_LEN
    )
    citation_job_company: str | None = Field(
        default=None, max_length=MAX_SUGGESTION_TEXT_LEN
    )
    citation_apply_url: str | None = Field(
        default=None, max_length=MAX_LEARNING_URL_LEN
    )
    citation_quote: str = Field(max_length=MAX_CITATION_QUOTE_LEN)
    # 2-4 questions the LLM needs answered before it can rewrite.
    # Min 1, max MAX_COACH_QUESTIONS — enforced server-side because
    # the LLM occasionally returns 0 or 5+ and we want predictable
    # UX.
    questions: list[CoachQuestion] = Field(
        min_length=1, max_length=MAX_COACH_QUESTIONS
    )
    # Structured diagnosis of why this bullet is weak. Drives both
    # the question-picking logic (LLM uses it as the conditioning
    # signal) and the UI's "why is this weak" affordance. Optional —
    # the validator doesn't require it (older clients may not have
    # the field).
    diagnosis: BulletDiagnosis | None = None
    # Where this bullet sits in the candidate's resume. Optional —
    # the parser can fail on unusual resume formats, in which case
    # the route layer falls back to a generic "Resume" location.
    location: BulletLocation | None = None


class CoachStartResponse(BaseModel):
    session_id: str = Field(max_length=64)
    # SKILL suggestions carried over from the one-shot flow so the UI
    # can render both in one consolidated view. Same shape as the
    # existing /suggestions/refresh response.
    skills: list[Suggestion] = Field(default_factory=list)
    bullets: list[CoachBullet] = Field(default_factory=list)


class CoachRewriteRequest(BaseModel):
    session_id: str = Field(max_length=64)
    bullet_id: str = Field(max_length=64)
    # Map of question.key -> user's answer text. Empty values are
    # allowed (the user can skip a question), but every key the LLM
    # produced for this bullet must be present (validator below).
    answers: dict[str, str] = Field(default_factory=dict)


class CoachRewriteResponse(BaseModel):
    bullet_id: str = Field(max_length=64)
    original_text: str = Field(max_length=MAX_SUGGESTION_TEXT_LEN)
    rewritten_text: str = Field(max_length=MAX_SUGGESTION_TEXT_LEN)
    # Echoed back so the UI can render the citation link.
    citation_job_id: str = Field(max_length=64)
    citation_job_title: str | None = Field(
        default=None, max_length=MAX_SUGGESTION_TEXT_LEN
    )
    citation_job_company: str | None = Field(
        default=None, max_length=MAX_SUGGESTION_TEXT_LEN
    )
    citation_apply_url: str | None = Field(
        default=None, max_length=MAX_LEARNING_URL_LEN
    )
    citation_quote: str = Field(max_length=MAX_CITATION_QUOTE_LEN)


_COACH_KEY_PATTERN = None


def _safe_key_regex():
    """Compiled once on first use. ASCII letters / digits / underscore,
    starting with a letter, max 64 chars. Safe for the UI to use as a
    map key without escaping."""
    global _COACH_KEY_PATTERN
    if _COACH_KEY_PATTERN is None:
        import re
        _COACH_KEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
    return _COACH_KEY_PATTERN


def validate_coach_start_request(
    skills: list[Suggestion], bullets: list[CoachBullet]
) -> tuple[list[Suggestion], list[CoachBullet]]:
    """Trim and validate a coach-start response from the LLM.

    - Bullet count is capped at MAX_COACH_BULLETS_PER_SESSION
      (UX budget: more than ~5 bullets to coach at once is
      overwhelming).
    - Bullet IDs must be unique within the response.
    - Question keys within a bullet must be unique.
    - Question key format is restricted to ASCII letters /
      digits / underscore so the UI can use them safely as
      map keys.
    - Each bullet's `original_text` must be a non-empty string
      that is at least 8 chars long (filters out LLM responses
      that send empty or trivial "bullets" like "-" or "n/a").
      Substring-grounding against the entry happens in the
      route layer, which has the parsed resume in scope.
    """
    safe_key = _safe_key_regex()

    seen_bullet_ids: set[str] = set()
    accepted: list[CoachBullet] = []
    for bullet in bullets[:MAX_COACH_BULLETS_PER_SESSION]:
        if bullet.bullet_id in seen_bullet_ids:
            continue
        if len(bullet.original_text.strip()) < 8:
            # Trivial "bullet" (likely the LLM degenerated).
            continue
        seen_question_keys: set[str] = set()
        cleaned_questions = []
        for question in bullet.questions:
            if not safe_key.match(question.key):
                # Bad key -- skip the question. The bullet
                # still survives with its other questions.
                continue
            if question.key in seen_question_keys:
                continue
            seen_question_keys.add(question.key)
            cleaned_questions.append(question)
        if not cleaned_questions:
            # Every question was rejected -- drop the bullet
            # rather than ship a "no questions" coach entry.
            continue
        cleaned_bullet = bullet.model_copy(
            update={"questions": cleaned_questions}
        )
        accepted.append(cleaned_bullet)
        seen_bullet_ids.add(bullet.bullet_id)
    return skills[:MAX_SUGGESTIONS], accepted


def validate_coach_rewrite_answer_keys(
    requested_keys: list[str], answers: dict[str, str]
) -> list[str]:
    """Return the keys that were requested but missing from `answers`.

    The user can submit empty strings for keys they want to skip --
    that is not "missing". What we don't allow is requesting a
    rewrite for a bullet whose questions we never asked, or omitting
    a requested key entirely (frontend bug).

    Returns the list of *missing* keys. Empty list == OK.
    """
    missing = []
    for key in requested_keys:
        if key not in answers:
            missing.append(key)
    return missing


def validate_coach_bullet_grounding(
    bullets: list[CoachBullet],
    parsed_resume: dict,
) -> list[CoachBullet]:
    """Drop bullets whose `original_text` doesn't substring-match
    one of the parsed-resume entries' text.

    The LLM promises in the prompt to return a verbatim substring,
    but on the off chance it slips (paraphrases, rewords, picks
    a different entry's text), this validator catches it. Bullets
    that fail the check are dropped silently rather than shown
    to the user with a broken "where is this in my resume?"
    affordance.

    The check is a normalized substring match: whitespace
    differences and case differences don't count, since the
    parser collapses whitespace and the LLM may reformat.
    """
    if not parsed_resume or not parsed_resume.get("sections"):
        return bullets
    # Build a flat set of normalized entry texts to check
    # against. We include the section title + entry title as
    # acceptable sources too (the LLM might pick a fragment
    # that's in the header but not the body).
    accepted_texts: list[str] = []
    for section in parsed_resume["sections"]:
        section_title = section.get("title", "")
        if section_title:
            accepted_texts.append(_normalize(section_title))
        for entry in section.get("entries", []):
            if entry.get("title"):
                accepted_texts.append(_normalize(entry["title"]))
            if entry.get("text"):
                accepted_texts.append(_normalize(entry["text"]))
    if not accepted_texts:
        return bullets
    accepted: list[CoachBullet] = []
    for bullet in bullets:
        normalized_original = _normalize(bullet.original_text)
        # Substring match: any of the entry texts contains the
        # bullet's original_text. We use `in` rather than equality
        # so a partial sentence counts.
        if any(
            normalized_original in accepted_text
            for accepted_text in accepted_texts
        ):
            accepted.append(bullet)
        # else: drop silently. The user gets fewer bullets to
        # coach on, but every bullet shown is one they can
        # actually find in their resume.
    return accepted


# Structural / common-English tokens that legitimately appear in any
# rewrite. We strip these from the fabricated-token check so the
# validator focuses on substance (numbers, names, claims) rather than
# grammatical glue (verbs, articles, prepositions).
_COACH_STRUCTURAL_TOKENS: frozenset[str] = frozenset({
    "the", "and", "for", "with", "from", "into", "over", "about",
    "this", "that", "these", "those", "have", "has", "had", "are",
    "was", "were", "been", "will", "would", "could", "should", "may",
    "can", "must", "shall", "their", "they", "them", "your", "yours",
    "our", "ours", "you", "who", "what", "when", "where", "which",
    "how", "why", "than", "then", "also", "just", "only", "very",
    "more", "less", "most", "least", "some", "any", "all", "each",
    "every", "both", "either", "neither", "using", "used", "use",
    "uses", "build", "built", "building", "develop", "developed",
    "developing", "development", "implement", "implemented",
    "implementation", "deploy", "deployed", "deployment", "design",
    "designed", "designing", "create", "created", "creating", "manage",
    "managed", "managing", "lead", "led", "leading", "leadership",
    "support", "supported", "supporting", "improve", "improved",
    "improving", "working", "worked", "works", "helped", "helping",
    "helps", "across", "within", "while", "during", "through",
    "throughout", "via", "based", "including", "include", "includes",
    "new", "key", "core", "main", "primary", "secondary", "across",
    "around", "toward", "against", "between", "before", "after",
    # User-filler tokens: vague qualifiers a user might type that
    # don't introduce new factual claims. The LLM can use them in
    # a rewrite without it counting as a "fabrication". Substantive
    # words (numbers, names, technologies) are NOT in this set --
    # those still need to come from a real source.
    "lots", "lot", "many", "much", "few", "several", "couple",
    "really", "extremely", "totally", "absolutely", "quite",
    "good", "bad", "great", "nice", "fine", "okay", "ok",
    "kind", "kinda", "sort", "sorta", "ish", "approximately",
    "yes", "no", "yeah", "nah", "yep", "nope", "maybe", "perhaps",
    "i", "we", "my", "mine", "us",
})


def validate_coach_rewrite_grounding(
    rewritten_text: str,
    *,
    original_text: str,
    answers: dict[str, str],
    citation_quote: str,
    citation_description: str,
) -> tuple[bool, list[str]]:
    """Confirm the rewrite is grounded only in user-supplied facts.

    Returns (is_grounded, reasons). `reasons` is a list of human-readable
    explanations for why grounding failed (empty when grounded).

    Hallucination guard, structural:
      1. The citation quote must substring-match the cited job
         description. (Same rule as the one-shot validator.)
      2. Every token in the rewrite that ISN'T in the original bullet,
         the user's answers, or the cited quote is treated as a
         fabrication candidate. We allow structural / grammatical
         tokens through (verbs, articles, prepositions) but anything
         substantive (numbers, names, claims) fails the rewrite.
      3. The rewrite must be meaningfully different from the original —
         otherwise the LLM is just returning what we already had.
    """
    reasons: list[str] = []

    # Rule 1: citation quote must be a substring of the cited job
    # description.
    if not _quote_is_substring(citation_quote, citation_description):
        reasons.append(
            "citation quote is not a substring of the job description"
        )

    # Rule 3 (cheap check first — fail fast): the rewrite must add
    # measurable content. If normalized equal, nothing changed.
    if _normalize(rewritten_text) == _normalize(original_text):
        reasons.append("rewrite is identical to the original bullet")

    # Rule 2: every substantive token in the rewrite must be traceable
    # to one of:
    #   - the original bullet (always allowed)
    #   - one of the user's answers (always allowed — user supplied)
    #   - the cited job quote (allowed — that's the grounding source)
    rewrite_tokens = _tokens(rewritten_text)
    original_tokens = _tokens(original_text)
    answer_tokens: set[str] = set()
    for answer in answers.values():
        answer_tokens |= _tokens(answer)
    quote_tokens = _tokens(citation_quote)
    allowed_tokens = original_tokens | answer_tokens | quote_tokens
    fabricated_tokens = rewrite_tokens - allowed_tokens
    suspicious = fabricated_tokens - _COACH_STRUCTURAL_TOKENS
    if suspicious:
        reasons.append(
            "rewrite contains tokens not present in the original "
            "bullet, the cited quote, or the user's answers: "
            + ", ".join(sorted(suspicious)[:5])
        )

    return (len(reasons) == 0, reasons)