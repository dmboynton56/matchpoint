from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


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


def _stem(token: str) -> str:
    """Tiny suffix-stripping stemmer.

    Drops common English inflectional suffixes so morphological
    variants match each other in grounding checks. Examples:
      "replacing" -> "replac", "replaced" -> "replac", "replace" -> "replac"
      "serving"   -> "serv",   "served"   -> "serv",   "serves"  -> "serv"
      "built"     -> "built" (no change -- short enough)
      "building"  -> "build",  "builds"   -> "build"

    We do NOT aim for linguistic accuracy (this is not Porter). The
    goal is just to recognize that "replacing" and "replaced" should
    match for the grounding validator -- both come from the same
    user answer or original bullet and the rewrite is allowed to
    flex the form.

    Sufficient stem length: tokens shorter than 4 chars are returned
    unchanged to avoid over-stemming ("the" -> "th", "is" -> "").
    """
    if len(token) < 4:
        return token
    # Order matters: strip longer suffixes first so "ing" doesn't
    # gobble the "e" from "-inge" etc. (rough Porter-like ordering).
    for suffix in ("ation", "izations", "izing", "isation", "isation"):
        if token.endswith(suffix) and len(token) > len(suffix) + 2:
            return token[: -len(suffix)]
    for suffix in ("ies",):
        if token.endswith(suffix) and len(token) > len(suffix) + 2:
            return token[: -len(suffix)] + "y"
    for suffix in ("ing", "edly", "ed"):
        if token.endswith(suffix) and len(token) > len(suffix) + 2:
            return token[: -len(suffix)]
    for suffix in ("ly",):
        if token.endswith(suffix) and len(token) > len(suffix) + 2:
            return token[: -len(suffix)]
    for suffix in ("es", "s"):
        if token.endswith(suffix) and len(token) > len(suffix) + 2:
            return token[: -len(suffix)]
    return token


def _stems(text: str) -> set[str]:
    """Return the set of stems for every token in `text`.

    Use this for grounding checks where morphological variants
    should match ("replacing" matches "replaced"). The structural
    allowlist in _COACH_STRUCTURAL_TOKENS is compared against stems
    too, so "of" / "to" / "the" still work without stemming.
    """
    return {_stem(tok) for tok in _tokens(text)}


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
# Bullet-coach flow (v2: qualitative categories + verdict)
# ---------------------------------------------------------------------------
# A two-step conversational flow that rewrites weak resume bullets and
# acknowledges strong ones. The coach is grounded in qualitative
# categories (specificity, scope, ownership, replacement, cause→effect,
# artifact) rather than asking the user for numeric facts they may not
# have. Every category maps to a question the user can answer without
# measuring.
#
# Verdict: each surfaced bullet is classified as either STRONG or WEAK.
#   - STRONG: bullet already has all six categories. No questions. The
#     UI renders "✓ Already strong" with the LLM's strength_reason. No
#     rewrite possible — /coach/rewrite returns 400 for STRONG bullets.
#   - WEAK: at least one category missing. One question per gap. The
#     user fills in answers (or skips), the validator grounds the
#     rewrite in the original + answers + cited quote.
#
# Step 1 (`POST /suggestions/coach/start`):
#   - LLM scans the resume for bullets, classifies each as STRONG/WEAK.
#     WEAK bullets come with one question per missing category. STRONG
#     bullets come with a strength_reason. The call also returns SKILL
#     suggestions in the same shape as the one-shot flow.
#   - Server allocates session_id (in-memory, 1-hour TTL).
# Step 2 (`POST /suggestions/coach/rewrite`):
#   - User supplies answers to the WEAK bullet's questions. They may
#     skip categories. LLM returns a rewritten bullet grounded only in
#     the original + non-skipped answers + cited quote. The validator
#     enforces per-category coverage: every non-skipped category's
#     answer must contribute at least one substantive token to the
#     rewrite.
# ---------------------------------------------------------------------------

MAX_COACH_QUESTIONS = 4
MAX_COACH_QUESTION_LABEL_LEN = 200
MAX_COACH_ANSWER_LEN = 280
MAX_COACH_BULLETS_PER_SESSION = 5
MIN_STRENGTH_REASON_LEN = 10


class CoachCategory(str, Enum):
    """The six qualitative dimensions a strong resume bullet covers.

    The LLM picks which categories are missing from each bullet and
    the route generates one question per missing category. The user
    fills in answers (or skips). The validator confirms each
    non-skipped answer contributed at least one substantive token to
    the rewrite.

    Order is deliberate: SPECIFICITY first (the most common gap),
    ARTIFACT last (the most concrete).
    """

    SPECIFICITY = "SPECIFICITY"
    SCOPE = "SCOPE"
    OWNERSHIP = "OWNERSHIP"
    REPLACEMENT = "REPLACEMENT"
    CAUSE_EFFECT = "CAUSE_EFFECT"
    ARTIFACT = "ARTIFACT"


class CoachBulletVerdict(str, Enum):
    """Whether the bullet needs work or is already strong."""

    STRONG = "STRONG"
    WEAK = "WEAK"


# Maps each CoachCategory to a default key the UI can use as a stable
# map identifier. The validator fills question.key from this when the
# LLM doesn't supply one. Keys are ASCII-safe (the same regex the
# prompt asks the LLM to produce) so the UI doesn't need to escape.
_CATEGORY_DEFAULT_KEYS: dict[CoachCategory, str] = {
    CoachCategory.SPECIFICITY: "specificity",
    CoachCategory.SCOPE: "scope",
    CoachCategory.OWNERSHIP: "ownership",
    CoachCategory.REPLACEMENT: "replacement",
    CoachCategory.CAUSE_EFFECT: "cause_effect",
    CoachCategory.ARTIFACT: "artifact",
}


class CoachQuestionType(str, Enum):
    TEXT = "TEXT"
    # Future: NUMBER, CHOICE, BOOLEAN. Text-only for the MVP — works for
    # every fact pattern and the validator doesn't need to know the type
    # to do substring grounding on the cited quote.


class CoachQuestion(BaseModel):
    # Stable key the UI uses to send the answer back. Must be unique
    # within a single bullet's question list (the LLM is asked to
    # produce ASCII keys like "scale" or "tech_stack"). When missing
    # (LLM only sends category), the validator fills it from the
    # category's default key. We allow None here so the validator
    # can populate it; the route layer /save_answers loop also
    # tolerates a derived key.
    key: str | None = Field(default=None, max_length=64)
    # Required: which qualitative dimension this question probes.
    # The validator rejects duplicate categories within a bullet.
    category: CoachCategory
    label: str = Field(max_length=MAX_COACH_QUESTION_LABEL_LEN)
    # Hint shown in lighter text under the input. Optional.
    hint: str | None = Field(default=None, max_length=MAX_COACH_QUESTION_LABEL_LEN)
    type: CoachQuestionType = CoachQuestionType.TEXT

    @field_validator("category", mode="before")
    @classmethod
    def _normalize_category(cls, v):
        """Tolerate lowercase / mixed-case category strings from the
        LLM. The prompt asks for uppercase but models slip.
        """
        if isinstance(v, str):
            return v.strip().upper()
        return v


class CategoryChecklist(BaseModel):
    """Six booleans describing which qualitative dimensions the bullet
    ALREADY has. The LLM fills these in for every bullet. Server
    derives category_gaps from this: gaps = [c for c in CoachCategory
    if not checklist[c]].

    Each field is a bool (not an enum) because the MVP only needs
    yes/no. Future versions could add a quality_score per dimension
    (0-3) without breaking the schema.
    """

    # Does the bullet name a concrete artifact or describe the most
    # interesting technical part? ("Built the matching algorithm",
    # not just "Built a thing".)
    SPECIFICITY: bool
    # Does it say who used it / what touched it / how big it was?
    # (40 students, 3 internal teams, 5k MAU, etc.)
    SCOPE: bool
    # Does it say "I owned/led/shipped" rather than "helped with /
    # worked on"? Clear ownership language.
    OWNERSHIP: bool
    # Does it say what existed before, or what got unblocked
    # because of this? ("Replaced the legacy CSV export flow",
    # "unblocked the mobile team".)
    REPLACEMENT: bool
    # Does it connect the work to an outcome? ("X, which led to Y"
    # or "Y because X".)
    CAUSE_EFFECT: bool
    # Does it name a specific thing? (API, dashboard, rule, doc,
    # migration, etc.)
    ARTIFACT: bool


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
    # Whether this bullet needs work (WEAK) or is already strong (STRONG).
    # Required. Drives UI affordance and whether /coach/rewrite is even
    # callable for this bullet.
    verdict: CoachBulletVerdict
    original_text: str = Field(max_length=MAX_SUGGESTION_TEXT_LEN)
    # Why this bullet is weak, surfaced to the user as the "why this
    # matters" framing. One short sentence. Required when verdict is
    # WEAK, ignored when STRONG (the validator drops the bullet if
    # verdict is WEAK without a weakness_reason).
    weakness_reason: str | None = Field(
        default=None, max_length=MAX_WHY_IT_MATTERS_LEN
    )
    # Why this bullet is strong, surfaced to the user as the "✓
    # Already strong — [reason]" affordance. Required when verdict is
    # STRONG, ignored when WEAK (the validator drops the bullet if
    # verdict is STRONG without a strength_reason of at least
    # MIN_STRENGTH_REASON_LEN characters).
    strength_reason: str | None = Field(
        default=None, max_length=MAX_WHY_IT_MATTERS_LEN
    )
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
    # Questions the LLM needs answered before it can rewrite. Empty
    # when verdict is STRONG. One per missing category when verdict is
    # WEAK. Validator enforces: STRONG -> empty list, WEAK -> at least
    # one question. No duplicate categories within a single bullet.
    questions: list[CoachQuestion] = Field(
        default_factory=list, max_length=MAX_COACH_QUESTIONS
    )
    # Checklist of which categories the bullet ALREADY has. Server
    # derives category_gaps from this when the LLM doesn't override.
    # Optional — older clients may not have the field.
    checklist: CategoryChecklist | None = None
    # Explicit list of categories missing from the bullet. Server
    # derives this from the checklist but the LLM is allowed to
    # override when its judgment differs (e.g. it sees a gap the
    # boolean reflection missed).
    category_gaps: list[CoachCategory] = Field(default_factory=list)
    # Where this bullet sits in the candidate's resume. Optional —
    # the parser can fail on unusual resume formats, in which case
    # the route layer falls back to a generic "Resume" location.
    location: BulletLocation | None = None

    @field_validator("category_gaps", mode="before")
    @classmethod
    def _normalize_category_gaps(cls, v):
        """Tolerate lowercase / mixed-case category strings from the LLM
        inside the gaps list."""
        if v is None:
            return []
        if not isinstance(v, list):
            return v
        return [
            item.strip().upper() if isinstance(item, str) else item
            for item in v
        ]

    def resolved_questions(self) -> list[CoachQuestion]:
        """Return questions with their `key` field populated.

        When the LLM supplied a key, it survives. When it didn't,
        we fill in the default key for the question's category.
        UI code that needs to map question -> answer uses this.
        """
        out: list[CoachQuestion] = []
        for question in self.questions:
            if question.key:
                out.append(question)
                continue
            derived_key = _CATEGORY_DEFAULT_KEYS.get(question.category)
            if derived_key is None:
                # Shouldn't happen — categories are constrained.
                continue
            out.append(question.model_copy(update={"key": derived_key}))
        return out


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
    # Categories the user explicitly opted out of. The rewrite prompt
    # treats these as "do not invent content for this dimension" and
    # the validator lets the LLM drop the corresponding category from
    # the rewrite without penalizing it. A category in this list
    # implies the matching question's answer is irrelevant.
    skipped_categories: list[CoachCategory] = Field(default_factory=list)

    @field_validator("skipped_categories", mode="before")
    @classmethod
    def _normalize_skipped(cls, v):
        if v is None:
            return []
        if not isinstance(v, list):
            return v
        return [
            item.strip().upper() if isinstance(item, str) else item
            for item in v
        ]


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


def _resolve_question_keys(
    questions: list[CoachQuestion],
) -> list[CoachQuestion]:
    """Fill question.key from the category default when missing.

    Returns a NEW list with new CoachQuestion instances. Originals
    are not mutated. This is the same logic as
    CoachBullet.resolved_questions() exposed at module level so the
    validator + route layer can use it without instantiating a full
    CoachBullet.
    """
    out: list[CoachQuestion] = []
    for question in questions:
        if question.key and _safe_key_regex().match(question.key):
            out.append(question)
            continue
        derived = _CATEGORY_DEFAULT_KEYS.get(question.category)
        if derived is None:
            out.append(question)  # leave key as-is; validator will reject
            continue
        out.append(question.model_copy(update={"key": derived}))
    return out


def validate_coach_start_request(
    skills: list[Suggestion], bullets: list[CoachBullet]
) -> tuple[list[Suggestion], list[CoachBullet]]:
    """Trim and validate a coach-start response from the LLM.

    - Bullet count is capped at MAX_COACH_BULLETS_PER_SESSION
      (UX budget: more than ~5 bullets to coach at once is
      overwhelming).
    - Bullet IDs must be unique within the response.
    - When verdict is WEAK: at least one question required, question
      keys within a bullet must be unique, no duplicate categories,
      question key format restricted to ASCII letters / digits /
      underscore so the UI can use them safely as map keys.
    - When verdict is STRONG: strength_reason must be at least
      MIN_STRENGTH_REASON_LEN characters; questions must be empty.
    - Each bullet's `original_text` must be a non-empty string
      that is at least 8 chars long (filters out LLM responses
      that send empty or trivial "bullets" like "-" or "n/a").
      Substring-grounding against the entry happens in the
      route layer, which has the parsed resume in scope.

    The validator resolves question.key from category defaults when
    missing (so a question with no explicit key still has a usable
    key in the response).
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

        if bullet.verdict == CoachBulletVerdict.STRONG:
            # STRONG: must have a strength_reason of meaningful length,
            # questions must be empty. The UI treats these as
            # "✓ Already strong" with no rewrite available.
            reason = (bullet.strength_reason or "").strip()
            if len(reason) < MIN_STRENGTH_REASON_LEN:
                # The LLM didn't say what's strong. Drop the bullet
                # rather than ship a half-formed positive feedback.
                continue
            if bullet.questions:
                # STRONG bullets should not have questions. Drop any
                # questions the LLM accidentally produced.
                cleaned = bullet.model_copy(update={"questions": []})
                accepted.append(cleaned)
                seen_bullet_ids.add(bullet.bullet_id)
                continue
            accepted.append(bullet)
            seen_bullet_ids.add(bullet.bullet_id)
            continue

        # WEAK: at least one question, no duplicate categories, valid keys.
        if not bullet.questions:
            # No questions for a weak bullet -> nothing to coach on.
            # Drop silently rather than ship a bullet with no
            # affordance.
            continue

        seen_question_keys: set[str] = set()
        seen_categories: set[CoachCategory] = set()
        cleaned_questions: list[CoachQuestion] = []
        for question in bullet.questions:
            if question.category in seen_categories:
                # Two questions for the same category. Skip the
                # duplicate; first one wins.
                continue
            seen_categories.add(question.category)
            key = (question.key or "").strip()
            if not key:
                # Derive from category default.
                key = _CATEGORY_DEFAULT_KEYS.get(question.category, "")
            if not safe_key.match(key):
                # Bad key -- skip the question. The bullet
                # still survives with its other questions.
                continue
            if key in seen_question_keys:
                continue
            seen_question_keys.add(key)
            # Stamp the resolved key back onto the question so the
            # rest of the pipeline sees a populated key field.
            cleaned_questions.append(
                question.model_copy(update={"key": key})
            )
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


def validate_coach_citation_grounding(
    bullets: list[CoachBullet],
    job_descriptions: dict[str, str],
) -> list[CoachBullet]:
    """Drop bullets whose `citation_quote` isn't a substring of the
    cited job's description.

    The LLM is asked in the prompt to return a verbatim substring
    of the cited job, but it sometimes fabricates a quote -- often
    echoing the user's answer text instead of pulling from the job
    description. When that happens, the session stores a fake quote
    and the rewrite validator later fails with "citation quote is
    not a substring of the job description" -- which is the right
    error but lands too late (the user has already answered
    questions and clicked Rewrite).

    Catching it here, at the start flow, drops the bad bullet
    before the user invests time in it. Better UX than surfacing
    the error after answers.

    For STRONG bullets, we DON'T check -- they have no rewrite
    path, so a bad citation_quote there is cosmetic (the citation
    link still works via citation_job_id). The check is only
    meaningful for WEAK bullets.

    Bullets whose `citation_job_id` is missing from
    `job_descriptions` are kept (best-effort; the validator can't
    prove they're bad either).
    """
    accepted: list[CoachBullet] = []
    for bullet in bullets:
        # STRONG bullets don't go through the rewrite path --
        # citation_quote doesn't gate anything. Skip the check.
        if bullet.verdict == CoachBulletVerdict.STRONG:
            accepted.append(bullet)
            continue
        job_id = bullet.citation_job_id
        description = job_descriptions.get(job_id)
        if description is None:
            # We don't have the description (job purged from Turso,
            # or the LLM picked an unknown job). Skip the check --
            # we can't prove fabrication either way.
            accepted.append(bullet)
            continue
        if _quote_is_substring(bullet.citation_quote, description):
            accepted.append(bullet)
        # else: drop silently. The user gets fewer bullets to
        # coach on, but every bullet shown has a citation they
        # can verify against the actual job posting.
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

    Category-coverage (the qualitative-coach v2 upgrade) is enforced
    separately by validate_coach_rewrite_category_coverage, called by
    the route after this check passes.
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

    # Rule 2: every *substantive* token in the rewrite must be traceable
    # to one of:
    #   - the original bullet (always allowed)
    #   - one of the user's answers (always allowed -- user supplied)
    #   - the cited job quote (allowed -- that's the grounding source)
    #
    # "Substantive" means: digits and numeric words (numbers, %), and
    # technology identifiers (FastAPI, next.js, JWT, k8s). These are
    # the things the LLM can plausibly fabricate to make the rewrite
    # sound more impressive. Connectors, common verbs, articles,
    # prepositions, generic nouns ("replacing", "enabling", "serving")
    # are allowed through -- the LLM needs these to write English
    # and rejecting them for not being sourced produces false
    # positives on every natural rewrite.
    #
    # Two passes -- rewrite-side (digits, dots, symbols) and a raw
    # titlecase pass over both the rewrite and the source -- catch
    # tech names like "Rust", "Python", "Kafka". _tokens lowercases
    # everything so the titlecase check has to run on the raw text
    # before tokenization.
    rewrite_tokens = _tokens(rewritten_text)
    original_tokens = _tokens(original_text)
    answer_tokens: set[str] = set()
    for answer in answers.values():
        answer_tokens |= _tokens(answer)
    quote_tokens = _tokens(citation_quote)

    def _titlecase_set(text: str) -> set[str]:
        out: set[str] = set()
        for raw_tok in re.findall(r"[A-Za-z0-9+#\.]+", text):
            cleaned = raw_tok.rstrip(".,;:!?")
            if not cleaned:
                continue
            if (
                cleaned[0].isupper()
                and any(ch.islower() for ch in cleaned)
                and all(ch.isalpha() for ch in cleaned)
            ):
                out.add(cleaned.lower())
        return out

    rewrite_titlecase = _titlecase_set(rewritten_text)

    def _is_substantive(token: str, titlecase_source: set[str]) -> bool:
        if any(ch.isdigit() for ch in token):
            return True
        if any(ch.isupper() for ch in token[1:]):
            return True
        if token in titlecase_source:
            return True
        if "." in token and not token.endswith("."):
            return True
        if "#" in token or "+" in token:
            return True
        letters = sum(ch.isalpha() for ch in token)
        digits = sum(ch.isdigit() for ch in token)
        if letters > 0 and digits > 0:
            return True
        return False

    substantive_rewrite = {
        tok for tok in rewrite_tokens
        if _is_substantive(tok, rewrite_titlecase)
    }
    # Build the source-side allow-set using the same detection rule
    # over raw source text. Without this, a source token like
    # "FastAPI" gets tokenized as "fastapi" and a rewrite token
    # "FastAPI" gets flagged as fabricated even though the user
    # said "FastAPI" verbatim in their answer.
    sources_text = [
        original_text,
        " ".join(answers.values()),
        citation_quote,
    ]
    sources_titlecase = set()
    for src_text in sources_text:
        sources_titlecase |= _titlecase_set(src_text)

    allowed_substantive_stems: set[str] = set()
    for src_tokens, src_text in zip(
        (original_tokens, answer_tokens, quote_tokens), sources_text
    ):
        for tok in src_tokens:
            if _is_substantive(tok, sources_titlecase):
                allowed_substantive_stems.add(_stem(tok))
    # For pure-numeric tokens, also accept any source token that
    # contains digits (covers "5000" -> "5,000" via stem, but also
    # "50k" -> "50" since stems don't capture suffixes).
    for src in (original_tokens, answer_tokens, quote_tokens):
        for tok in src:
            if any(ch.isdigit() for ch in tok):
                allowed_substantive_stems.add(tok)

    fabricated: set[str] = set()
    for tok in substantive_rewrite:
        # Match either by stem (catches FastAPI vs fastapi) or by
        # exact membership (catches "5,000" vs "5000").
        if _stem(tok) in allowed_substantive_stems:
            continue
        if tok in {t for src in (original_tokens, answer_tokens, quote_tokens) for t in src}:
            continue
        fabricated.add(tok)

    if fabricated:
        reasons.append(
            "rewrite contains substantive claims (numbers or "
            "technologies) not present in the original bullet, the "
            "cited quote, or the user's answers: "
            + ", ".join(sorted(fabricated)[:5])
        )

    return (len(reasons) == 0, reasons)


def validate_coach_rewrite_category_coverage(
    rewritten_text: str,
    *,
    questions: list[CoachQuestion],
    answers: dict[str, str],
    skipped_categories: list[CoachCategory] | None = None,
) -> tuple[bool, list[str]]:
    """Enforce per-category coverage on the rewrite.

    For each question in `questions` whose category is NOT in
    `skipped_categories` and whose answer is non-empty, at least one
    substantive token from the answer must appear in the rewrite.

    This is the qualitative-coach v2 upgrade. It's the structural
    guarantee that the rewrite reflects what the user actually said,
    not what the LLM wished they'd said. The user's fingerprint on
    the rewrite.

    Returns (is_grounded, reasons). Empty `reasons` == OK.

    Edge cases (logged as warnings via the reasons list, NOT as
    rejections):
      - The answer is one word and that word is in the structural
        allowlist (e.g. "yes", "ok"). No substantive fingerprint
        available.
      - The answer is empty (user skipped without marking the
        category as skipped). Treated as skipped for this rule.
      - The answer is in a different language than the rewrite;
        tokens won't match. Warn, don't reject.

    Edge case (silent skip):
      - The question's category is in `skipped_categories`. No
        coverage check runs for that category.
    """
    reasons: list[str] = []
    skipped = set(skipped_categories or [])
    rewrite_tokens = _tokens(rewritten_text)
    # Build a key -> category map so we can resolve answer keys to
    # categories. The UI sends answers keyed by question.key; the
    # validator needs the category. We accept either CoachQuestion
    # objects or plain dicts (the route layer passes dicts because
    # the session store serializes bullets as dicts on read).
    key_to_category: dict[str, CoachCategory] = {}

    def _q_key(q) -> str | None:
        if isinstance(q, dict):
            return q.get("key")
        return getattr(q, "key", None)

    def _q_category(q) -> CoachCategory | None:
        cat = q.get("category") if isinstance(q, dict) else getattr(q, "category", None)
        if cat is None:
            return None
        # Normalize string categories to enum values. The validator
        # also accepts already-enum values.
        if isinstance(cat, CoachCategory):
            return cat
        if isinstance(cat, str):
            try:
                return CoachCategory(cat.strip().upper())
            except ValueError:
                return None
        return None

    for question in questions:
        qkey = _q_key(question)
        qcat = _q_category(question)
        if qkey and qcat is not None:
            key_to_category[qkey] = qcat

    for question in questions:
        category = _q_category(question)
        if category is None:
            continue
        if category in skipped:
            continue
        key = _q_key(question) or _CATEGORY_DEFAULT_KEYS.get(category, "")
        answer = answers.get(key, "") if key else ""
        if not answer or not answer.strip():
            # Empty answer — treat as a soft skip. We log a
            # warning (informational, not a rejection) so the
            # route layer can surface it if it wants.
            reasons.append(
                f"category {category.value}: no answer provided "
                "(treated as skipped for coverage)"
            )
            continue
        answer_tokens = _tokens(answer)
        if not answer_tokens:
            continue
        # Substantive overlap: at least one answer token must appear
        # in the rewrite. We do NOT use the structural allowlist here
        # — we want the user's substantive words, not grammatical
        # glue. This is what makes the coverage check a real
        # fingerprint.
        overlap = answer_tokens & rewrite_tokens
        if not overlap:
            reasons.append(
                f"category {category.value}: answer words did not "
                "appear in the rewrite ("
                + ", ".join(sorted(answer_tokens)[:3])
                + ")"
            )

    return (len(reasons) == 0, reasons)