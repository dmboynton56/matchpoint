from __future__ import annotations

import logging
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
    """Normalize text for substring matching.

    Reduces quote-like variations to a comparable form before
    substring checks (`_quote_is_substring` in particular). Steps:
      1. Lowercase.
      2. Manually fold common LLM-emitted punctuation variants
         to ASCII equivalents:
         - Smart quotes (U+201C/D, U+2018/9) to ASCII " and '
         - Em-dash (U+2014) and en-dash (U+2013) to ASCII hyphen
         - Ellipsis (U+2026) to three dots
         Note: NFKC does NOT decompose any of these; explicit
         character substitution is required.
      3. Collapse ASCII stand-in em-dash ("--", common ASCII
         substitute used by career sites) to a single hyphen. The
         regex is bounded by whitespace so we don't accidentally
         fold the em-dashes in "co--operate" or "re--enter".
      4. Strip leading and trailing punctuation (. , ; : ! ? ' ").
         The LLM often appends a period to a quoted sentence that
         appears mid-source-text without one, which would fail a
         strict substring match.
      5. Collapse internal whitespace to single spaces and strip
         leading/trailing whitespace (Python's str.split() handles
         both).
    """
    import re
    # Step 1: lowercase.
    text = text.lower()
    # Step 2: substitute smart punctuation with ASCII equivalents.
    # NFKC alone is insufficient here -- the Unicode consortium
    # preserves these as compatibility characters and does not
    # fold them.
    text = (
        text
        .replace("\u201c", '"')   # left double quote
        .replace("\u201d", '"')   # right double quote
        .replace("\u2018", "'")   # left single quote
        .replace("\u2019", "'")   # right single quote / apostrophe
        .replace("\u2014", "-")   # em-dash
        .replace("\u2013", "-")   # en-dash
        .replace("\u2026", "...")  # ellipsis
    )
    # Step 3: ASCII stand-in em-dash ("--") -> single hyphen.
    text = re.sub(r"(^| )--( |$)", r"\1-\2", text)
    # Step 4: strip leading/trailing punctuation that's likely
    # produced by sentence boundaries rather than content.
    side_punct = ".,;:!?\"'"
    text = text.strip(side_punct)
    # Step 5: collapse whitespace.
    return " ".join(text.split())


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


# Minimum fraction of quote content-stems that must appear in the
# cited job's content-stems for the quote to count as grounded,
# when the strict-substring check fails. 0.5 = at least half of the
# meaningful words in the quote must be present (after stopword /
# structural-token filtering + stemming). Lower numbers admit
# more paraphrasing at the cost of letting fabricated quotes
# through; higher numbers stay closer to the strict check.
#
# Tuned to:
#   - accept the LLM's paraphrased quotes that preserve the JD's
#     substance (e.g. "Annotated and validated machine learning
#     datasets" against a JD that describes the same work in
#     different words but shares the vocabulary)
#   - reject totally fabricated quotes (e.g. "frontier AI labs"
#     against a backend-engineer JD with no AI-lab language)
#     -- the existing test_drops_bullet_with_fabricated_quote
#     exercises this and must keep passing
#
# This is intentionally relaxed: bullet-coach is an experimental
# feature where the cost of a false-reject (a confused user
# hitting 502 mid-workshop) outweighs the cost of a slight
# hallucination in the citation link.
CITATION_GROUNDING_THRESHOLD = 0.5


def _content_stems(text: str) -> set[str]:
    """Stems of tokens in `text`, minus the structural/stopword set.

    The structural set (_COACH_STRUCTURAL_TOKENS) is the same one
    used by rule 2 of `validate_coach_rewrite_grounding` -- it
    filters articles, prepositions, generic verbs, and other glue
    so the overlap score reflects substantive vocabulary rather
    than grammatical coincidence. Tokens shorter than 3 chars are
    dropped because _stem returns them unchanged and they don't
    carry enough signal ("ai" surviving everywhere, "go" / "do" /
    "be" etc. matching unrelated text).
    """
    stems = {_stem(t) for t in _tokens(text)}
    return {
        s for s in stems
        if len(s) >= 3 and s not in _COACH_STRUCTURAL_TOKENS
    }


def _citation_grounding_score(quote: str, source_text: str) -> float:
    """Fraction of quote content-stems present in source content-stems.

    Returns 0.0 when either side has no content tokens after
    filtering, so a quote of all stopwords scores 0 (the strict
    substring fast path is what saves it in that edge case).
    Otherwise returns `len(overlap) / len(quote_stems)`.
    """
    quote_stems = _content_stems(quote)
    if not quote_stems:
        return 0.0
    source_stems = _content_stems(source_text)
    if not source_stems:
        return 0.0
    return len(quote_stems & source_stems) / len(quote_stems)


def _citation_is_grounded(
    quote: str,
    source_text: str,
    *,
    threshold: float = CITATION_GROUNDING_THRESHOLD,
) -> bool:
    """Experimental relaxed citation-grounding check.

    Accepts the quote if EITHER:
      - the normalized quote is a substring of the normalized
        source (verbatim citation -- the original, strict check),
        OR
      - the content-stem overlap ratio is >= `threshold`
        (paraphrased citation that preserves enough vocabulary).

    Replaces the strict substring check in the bullet-coach
    citation validators. Trades a higher false-accept rate on
    fabricated quotes for a lower false-reject rate on paraphrased
    ones; the user explicitly accepted slight hallucinations for
    the experimental bullet-coach feature.
    """
    if _quote_is_substring(quote, source_text):
        return True
    return _citation_grounding_score(quote, source_text) >= threshold


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

# Max questions per WEAK bullet. Must equal len(CoachCategory) --
# one question per missing category, never more. Keep in sync with
# the enum on line 449. Kept as a literal so pydantic's
# `Field(max_length=...)` evaluates statically.
MAX_COACH_QUESTIONS = 6
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
    # Cap is len(CoachCategory) so a bullet genuinely missing all 6
    # qualitative dimensions can ask one question per gap (was 4
    # before, which silently truncated gap coverage).
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


class DroppedCoachBullet(BaseModel):
    """A WEAK bullet the start validator discarded and the reason why.

    Surfaced in `CoachStartResponse.dropped` so the client can show
    "we couldn't ground N of your bullets" and so the paraphrase /
    fabrication rate is measurable from logs without relying on
    silent-drop. Added when the LLM produces a `citation_quote`
    that isn't a substring of the cited job's description -- the
    classic "the LLM echoed the user's answer text back instead of
    pulling from the JD" failure mode.

    The `reason` field is a short stable string so future
    validators can add new reasons (e.g. `original_text_not_in_
    resume`) without a schema migration. Current values:
      - "citation_quote_not_substring": the LLM's quote didn't
        match the cited job's description after normalization.
        Classic paraphrasing failure -- the LLM echoed the user's
        answer text or produced a plausible-looking but fabricated
        excerpt instead of copying verbatim from the JD.
      - "citation_job_id_unknown": the LLM picked a
        `citation_job_id` that wasn't in the user's top matches,
        so no description snapshot exists to ground against.
        Without this drop the bullet would survive start
        (validate_coach_citation_grounding's "missing
        description" branch keeps best-effort, designed for the
        legitimate "job purged from Turso" case) and then fail
        at rewrite because the route coerces the missing
        description to "" and the substring check returns False.
    """

    bullet_id: str = Field(max_length=64)
    citation_job_id: str = Field(max_length=64)
    # Echoed back so the client can show the user which quote
    # failed grounding, useful when debugging paraphrased
    # citations.
    citation_quote: str = Field(max_length=MAX_CITATION_QUOTE_LEN)
    original_text: str = Field(max_length=MAX_SUGGESTION_TEXT_LEN)
    reason: str = Field(max_length=64)


class CoachStartResponse(BaseModel):
    session_id: str = Field(max_length=64)
    # SKILL suggestions carried over from the one-shot flow so the UI
    # can render both in one consolidated view. Same shape as the
    # existing /suggestions/refresh response.
    skills: list[Suggestion] = Field(default_factory=list)
    bullets: list[CoachBullet] = Field(default_factory=list)
    # WEAK bullets the start validator discarded. See
    # `DroppedCoachBullet` for shape and reason. Empty when
    # every bullet the LLM produced grounded cleanly. Surfaces
    # the previously-silent drop so the client can show a
    # "couldn't ground N bullets" hint and so the paraphrase
    # rate is observable in logs and telemetry.
    dropped: list[DroppedCoachBullet] = Field(default_factory=list)


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


# Heuristic keywords that suggest a bullet covers each qualitative
# category. Used by reclassify_overstrong_bullets as a server-side
# safety net: gpt-4o-mini sometimes over-classifies STRONG, leaving
# the user with nothing to workshop. These lists are imperfect
# (keywords overlap across categories) but the consensus-count
# heuristic tolerates the noise. Server counts unique categories
# covered -- a bullet needs to "look like" at least 3 to be
# eligible for STRONG.
_CATEGORY_OVERSTRONG_KEYWORDS: dict[str, set[str]] = {
    "SCOPE": {
        "users", "user", "students", "student", "cohort", "team",
        "teams", "engineers", "engineer", "customers", "customer",
        "members", "member", "users", "company", "companies",
        "client", "clients", "investors", "tenants", "patients",
        "candidates", "stakeholders",
    },
    "OWNERSHIP": {
        "i", "we", "my", "our", "led", "built", "shipped", "designed",
        "implemented", "developed", "created", "owned", "authored",
        "founded", "launched", "drove", "ran", "managed", "led",
    },
    "ARTIFACT": {
        "api", "apis", "dashboard", "tool", "tools", "model", "models",
        "system", "systems", "service", "services", "library",
        "libraries", "feature", "features", "platform", "platforms",
        "app", "apps", "module", "modules", "pipeline", "pipelines",
        "endpoint", "endpoints", "cli", "ui", "sdk",
    },
    "CAUSE_EFFECT": {
        "resulting", "led", "increase", "increased", "decrease",
        "decreased", "reduce", "reduced", "grew", "growing",
        "improving", "improved", "drove", "saved", "added", "adding",
        "boosted", "enabling", "enables", "unblock", "unblocking",
        "unblocked", "yields", "reduced", "increased", "doubled",
        "halved", "%", "x",
    },
    "SPECIFICITY": {
        "the",  # article alone isn't enough -- this is a noisy
                # signal; SPECIFICITY is the weakest of the 6.
        # Marked as a "soft" category in the heuristic below.
    },
    "REPLACEMENT": {
        "replaced", "replacing", "previously", "instead", "legacy",
        "migrated", "migration", "ported", "porting", "instead-of",
        "from", "to",  # noisy without context; also a soft signal.
    },
}

# Sentinel: the SPECIFICITY and REPLACEMENT categories are noisy
# matches on small corpora. The heuristic requires 3 hard matches
# OR 2 hard matches + 1 soft match to consider a bullet STRONG-
# eligible. This avoids false positives where the only category a
# short bullet "covers" is via a conjunction like "from" or "to".
_CATEGORY_STRICT = {"SCOPE", "OWNERSHIP", "ARTIFACT", "CAUSE_EFFECT"}
_CATEGORY_LOOSE = {"SPECIFICITY", "REPLACEMENT"}


def _category_keyword_hits(text: str) -> set[str]:
    """Return the set of category keys whose keywords appear in text.

    Words are tokenized via simple split + lowercase + strip of
    surrounding punctuation. Word boundaries matter only
    loosely -- substring match is fine for short keywords like
    "api" because false positives are bounded by the consensus
    count downstream.
    """
    import re
    tokens: set[str] = set()
    for raw_tok in re.findall(r"[A-Za-z0-9%]+", text.lower()):
        tokens.add(raw_tok.strip())
    hits: set[str] = set()
    for category, words in _CATEGORY_OVERSTRONG_KEYWORDS.items():
        if tokens & words:
            hits.add(category)
    return hits


def _looks_strong(text: str) -> bool:
    """Heuristic STRONG-eligibility based on the bullet's original
    text. Returns True iff the text clearly covers enough
    categories to justify a STRONG classification (no questions,
    no rewrite available). The bar is set deliberately low so
    real-world thin bullets get demoted to WEAK with synthesized
    questions rather than silently locked into STRONG.

    Rule: text covers >=3 strict categories (SCOPE/OWNERSHIP/
    ARTIFACT/CAUSE_EFFECT). Loose categories (SPECIFICITY/
    REPLACEMENT) contribute only as a tiebreaker: a bullet with 2
    strict + 1 loose is also eligible.
    """
    hits = _category_keyword_hits(text)
    strict_count = len(hits & _CATEGORY_STRICT)
    loose_count = len(hits & _CATEGORY_LOOSE)
    if strict_count >= 3:
        return True
    if strict_count >= 2 and loose_count >= 1:
        return True
    return False


# Fallback questions for synthesized-questions demotion. Picked to
# surface the most actionable gap the LLM might've ignored. Keys
# are categories that the heuristic demoted as missing.
_DEMOTION_FALLBACK_QUESTIONS: dict[str, str] = {
    "SCOPE": "Who used this? (classmates, team, customers, etc.)",
    "OWNERSHIP": "Did you lead this end-to-end, or were you part of a team?",
    "ARTIFACT": "What was the most interesting part you built or shipped?",
    "CAUSE_EFFECT": "What changed because of this? (outcome, metric, adoption)",
    "SPECIFICITY": "What was the most specific concrete thing involved?",
    "REPLACEMENT": "What did this replace, or what did it unblock?",
}


def reclassify_overstrong_bullets(
    bullets: list[CoachBullet],
) -> list[CoachBullet]:
    """Server-side safety net for over-generous STRONG classifications.

    When gpt-4o-mini returns STRONG for a thin bullet (the LLM
    decided the bullet was "good enough" but the heuristic
    suggests otherwise), the user sees a session with no WEAK
    bullets and nothing to workshop. This function detects that
    pattern: any STRONG bullet whose original_text clearly fails
    _looks_strong is demoted to WEAK with one synthesized
    question per missing-strict category. The rewrite prompts
    handle these the same as LLM-supplied questions.

    Idempotent: STRONG bullets that pass the heuristic are
    untouched. WEAK bullets pass through unchanged.
    """
    if not bullets:
        return bullets
    strong_count = sum(
        1 for b in bullets if b.verdict == CoachBulletVerdict.STRONG
    )
    weak_count = sum(
        1 for b in bullets if b.verdict == CoachBulletVerdict.WEAK
    )
    # If the LLM already produced at least one WEAK bullet and the
    # STRONG ones look genuinely strong, leave them alone -- the
    # workshop mix is healthy. Demote only when STRONG is full and
    # WEAK is empty.
    if weak_count >= 1:
        return bullets

    rebuilt: list[CoachBullet] = []
    demoted_count = 0
    for bullet in bullets:
        if bullet.verdict != CoachBulletVerdict.STRONG:
            rebuilt.append(bullet)
            continue
        if _looks_strong(bullet.original_text):
            rebuilt.append(bullet)
            continue
        # Demote: synthesize one question per strict-missing
        # category. Use the LLM's checklist if provided to
        # inform "missing"; otherwise fall back to the keyword
        # heuristic for what looks missing. If neither is
        # informative, synthesize a generic gap question.
        missing: list[CoachCategory] = []
        if bullet.checklist is not None:
            for cat in CoachCategory:
                if not getattr(bullet.checklist, cat.value, True):
                    missing.append(cat)
        if not missing:
            hits = _category_keyword_hits(bullet.original_text)
            missing = [
                cat for cat in CoachCategory
                if cat.value in _CATEGORY_STRICT
                and cat.value not in hits
            ]
        if not missing:
            # Last resort: ask the most-impactful single category.
            missing = [CoachCategory.OWNERSHIP]
        questions: list[CoachQuestion] = []
        seen_cats: set[CoachCategory] = set()
        for cat in missing:
            if cat in seen_cats:
                continue
            seen_cats.add(cat)
            label = _DEMOTION_FALLBACK_QUESTIONS.get(
                cat.value,
                f"Tell me more about the {cat.value.lower().replace('_', ' ')}.",
            )
            questions.append(
                CoachQuestion(
                    key=cat.value.lower(),
                    category=cat,
                    label=label,
                    type=CoachQuestionType.TEXT,
                )
            )
        weakness = (
            f"Bullet lacks enough of the key qualitative dimensions "
            f"to count as strong. Reclassified to WEAK."
        )
        rebuilt_bullet = bullet.model_copy(
            update={
                "verdict": CoachBulletVerdict.WEAK,
                "questions": questions,
                "weakness_reason": weakness,
                "checklist": None,
            }
        )
        rebuilt.append(rebuilt_bullet)
        demoted_count += 1

    if demoted_count:
        import logging
        logging.getLogger(__name__).warning(
            "coach_start demoted %d STRONG bullet(s) to WEAK "
            "(missing qualitative coverage). Original strong=%d, "
            "weak=%d, after=%d/%d.",
            demoted_count,
            strong_count,
            weak_count,
            sum(
                1 for b in rebuilt
                if b.verdict == CoachBulletVerdict.WEAK
            ),
            sum(
                1 for b in rebuilt
                if b.verdict == CoachBulletVerdict.STRONG
            ),
        )
    return rebuilt


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
    """Pass WEAK bullets through; STRONG bullets are kept regardless.

    Historically this validator also filtered WEAK bullets whose
    `citation_quote` didn't ground against the cited job's
    description (strict substring, then a relaxed content-stem
    overlap). That check has been disabled: bullet-coach is an
    experimental feature where the user explicitly accepted
    slight hallucinations in exchange for not 502-ing the user
    mid-workshop, and the LLM's paraphrased / lightly fabricated
    quotes routinely scored 0 against the JD's vocabulary.

    The function is retained (rather than deleted) because:
      - STRONG bullets still take the early-return branch (they
        don't go through /coach/rewrite so the citation quote is
        cosmetic; the early return avoids any future re-introduction
        of a check from biting them).
      - WEAK bullets whose `citation_job_id` is missing from the
        snapshot still hit the description-is-None branch and
        fall through. (The route-layer membership check added
        later catches these before this function runs, but the
        best-effort keep-on-missing semantics here remain for
        defense-in-depth.)
      - The membership-style filtering of hallucinated job_ids
        happens at the route layer (`_record_coach_drops` /
        `reason="citation_job_id_unknown"`), not here.

    If you want to re-tighten this validator later, swap the
    `_citation_is_grounded(...)` call back in below and tune
    CITATION_GROUNDING_THRESHOLD.
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
        # Citation grounding check intentionally disabled per the
        # docstring above. The check function is retained so it can
        # be re-enabled later by swapping this block back in:
        #     if _citation_is_grounded(bullet.citation_quote, description):
        #         accepted.append(bullet)
        #         continue
        accepted.append(bullet)
    return accepted


# Structural / common-English tokens that legitimately appear in any
# rewrite. We strip these from the fabricated-token check so the
# validator focuses on substance (numbers, names, claims) rather than
# grammatical glue (verbs, articles, prepositions).
_COACH_STRUCTURAL_TOKENS: frozenset[str] = frozenset({
    "the", "and", "for", "with", "from", "into", "over", "about",
    # Common prepositions/articles not yet in the original list.
    # The category-coverage validator (validate_coach_rewrite_
    # category_coverage) filters answers through this list before
    # stem-comparing to the rewrite, so the user's true-glue
    # words don't accidentally count as substantive overlap.
    "of", "in", "on", "at", "to", "by", "as", "an",
    "is", "it", "its",
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
      1. DISABLED: the citation quote's grounding against the
         cited job's description was originally a hard substring
         check, then relaxed to a content-stem overlap ratio,
         and now disabled entirely. Bullet-coach is an
         experimental feature where the user explicitly accepted
         slight hallucinations in exchange for not 502-ing the
         user mid-workshop. See `validate_coach_citation_grounding`
         for the matching start-side disable. To re-enable:
         add `if not _citation_is_grounded(citation_quote,
         citation_description): reasons.append("citation quote is
         not a substring of the job description")` here.
      2. Every substantive token in the rewrite must be traceable
         to one of:
           - the original bullet (allowed)
           - one of the user's answers (allowed -- user supplied)
           - the cited job quote (allowed, but see rule 4 below)
         and the trace must go through the user's own words, not
         just the quote. The job quote is treated as the AIM of
         the rewrite (target language, target skills) but not as
         a source of facts about the candidate's experience --
         a tech name appearing ONLY in the quote (PyTorch, etc.)
         is still a fabrication if the candidate never used it.
      3. The rewrite must be meaningfully different from the original —
         otherwise the LLM is just returning what we already had.
      4. Substantive rewrite tokens that are in the cited quote but
         NOT in the original bullet or the user's answers are flagged
         as "job-only" with a specific message naming the technology,
         so the UI can tell the candidate which term came from the
         job posting rather than their actual experience.

    Category-coverage (the qualitative-coach v2 upgrade) is enforced
    separately by validate_coach_rewrite_category_coverage, called by
    the route after this check passes.
    """
    reasons: list[str] = []

    # Rule 1: disabled -- see docstring. The citation quote's
    # grounding against the cited job's description used to be
    # checked here. Removed per the user's policy for the
    # experimental bullet-coach feature: slight hallucinations
    # in the citation are accepted in exchange for not 502-ing
    # the user mid-workshop. `_citation_is_grounded` is still
    # available for re-enabling.

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
    # CamelCase / single-word Capitalized tech names ("PyTorch",
    # "FastAPI", "Kafka") are detected via a raw-text scan of the
    # rewrite since _tokens lowercases and destroys casing
    # signals. See _rewrite_tech_words below for the scan + the
    # sentence-initial position filter that keeps verb-led
    # rewrites ("Built", "Created") from being flagged as
    # substantive content.
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

    # Earlier this function passed a "rewrite_titlecase" set built
    # from the rewrite's own text to _is_substantive -- with the idea
    # that "Built the FastAPI service" should mark BOTH "built" and
    # "fastapi" as substantive so they could be matched against
    # allowed stems. The same regex also accepts sentence-initial
    # capital ("Built", "Created", "Designed"), which are the exact
    # words the LLM rewrites commonly lead with -- so each rewrite
    # produced false positives when the original bullet used a
    # different verb. We no longer build or pass rewrite_titlecase.
    #
    # That fix exposed the opposite bug: tokenization lowercases
    # CamelCase tech names ("PyTorch" -> "pytorch") so the rewrite-
    # side substance check no longer sees them as substantive, and
    # the validator could no longer tell whether a tech mention in
    # the rewrite was sourced. So we re-detect CamelCase via a raw-
    # text scan below (see _CAMELCASE_RE) and add those tokens back
    # to substantive_rewrite so they get checked.

    # Tech-name shapes detected in the rewrite's RAW text (before
    # tokenization lowercases and destroys casing signals):
    #   - CamelCase like "FastAPI", "JavaScript", "PyTorch",
    #     "TypeScript" -- leading cap followed by at least one
    #     more [A-Z][a-z]+ chunk.
    #
    # We intentionally do NOT scan for single-word Capitalized
    # shapes ("Kafka", "Rust", "Python"). The naive regex would
    # also match mid-sentence English past-tense verbs
    # ("Developed", "Designed", "Implemented") and there's no
    # word-list-free way to distinguish the two -- earlier we
    # caught "Developed" in legit rewrites as fabricated. Defense
    # in depth: a fabricated single-word tech name used to satisfy
    # a category-gap answer would also fail the category-coverage
    # validator at the OTHER layer (which requires each
    # non-skipped answer's words to appear in the rewrite).
    _CAMELCASE_RE = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b")

    def _is_substantive(token: str, titlecase_source: set[str]) -> bool:
        if any(ch.isdigit() for ch in token):
            return True
        if any(ch.isupper() for ch in token[1:]):
            return True
        # On the rewrite side (called with an empty set), this
        # check is a no-op. On the source side, it captures
        # CamelCase tech names whose lowercase form would
        # otherwise look unsourced.
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

    substantive_rewrite: set[str] = {
        tok for tok in rewrite_tokens
        if _is_substantive(tok, set())
    }
    # Add CamelCase tech names from the rewrite's RAW text (not
    # the lowercased tokens). This recovers the "PyTorch",
    # "FastAPI", "JavaScript" cases that the lowercased substance
    # check misses. Without this, the LLM could append
    # "optimizing PyTorch models" at the end of a rewrite, source
    # that only in the cited job quote (not the user's answers),
    # and the validator wouldn't notice -- a fabrication the user
    # can't catch from the UI. Mid-sentence Capitalized verbs
    # ("Developed", "Designed") are NOT caught here -- by design;
    # see the comment on _CAMELCASE_RE above.
    rewrite_camelcase: set[str] = {
        m.group(0).lower()
        for m in _CAMELCASE_RE.finditer(rewritten_text)
    }
    substantive_rewrite |= rewrite_camelcase

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

    # Split the source stems into what the USER supplied (original
    # + answers -- things the candidate actually said) and what the
    # JOB supplied (cited quote -- things only in the target job's
    # description). A tech token that lands in the rewrite's
    # substantive set is "user-grounded" if its stem is in
    # user_supplied_stems, "job-only" if its stem is in
    # job_supplied_stems but NOT user_supplied_stems, and
    # "fabricated" if neither. The user's recent report caught the
    # case where the LLM took a tech name from the cited job quote
    # (e.g. "PyTorch") and appended it to a rewrite about totally
    # different work -- fabricating a tech claim that doesn't
    # reflect the candidate's experience.
    user_supplied_text = [original_text, " ".join(answers.values())]
    job_supplied_text = [citation_quote]
    user_supplied_token_sets = (original_tokens, answer_tokens)
    job_supplied_token_sets = (quote_tokens,)

    def _build_allowed_stems(token_sets, text_list):
        """Build allowed-substantive stems for a subset of sources.

        Mirrors the build below but scoped to the source slices
        passed in. Same rules: substantive tokens contribute stems,
        pure-numeric tokens are added verbatim.
        """
        out: set[str] = set()
        for src_tokens, src_text in zip(token_sets, text_list):
            for tok in src_tokens:
                if _is_substantive(tok, sources_titlecase):
                    out.add(_stem(tok))
            # Pure-numeric tokens: add verbatim so "5000" matches
            # "5,000" via stem, and "50k" matches "50" (stems don't
            # capture suffixes).
            for tok in src_tokens:
                if any(ch.isdigit() for ch in tok):
                    out.add(tok)
        return out

    user_supplied_stems = _build_allowed_stems(
        user_supplied_token_sets, user_supplied_text
    )
    job_supplied_stems = _build_allowed_stems(
        job_supplied_token_sets, job_supplied_text
    )

    # Backward-compat: a stem is "fabricated" if it's in NEITHER
    # source bucket. A stem is "job-only" if it's in the job-supplied
    # set but NOT in the user-supplied set. A stem is "user-grounded"
    # if it's in the user-supplied set.
    fabricated: set[str] = set()
    job_only_tech: set[str] = set()
    for tok in sorted(substantive_rewrite):
        stem = _stem(tok)
        if stem in user_supplied_stems:
            continue
        # Exact-membership fallback for pure-numeric tokens (e.g.
        # "5,000" vs "5000" stems don't collapse, but exact match
        # does).
        if tok in {t for src in (original_tokens, answer_tokens) for t in src}:
            continue
        if tok in job_supplied_stems or stem in job_supplied_stems:
            # Tech token is in the cited quote but not in anything
            # the user actually said. Flag with a specific reason:
            # this rewrites the candidate as having experience they
            # didn't claim.
            job_only_tech.add(tok)
        else:
            fabricated.add(tok)

    if job_only_tech:
        # Name up to five so the message stays short. Sort for
        # determinism.
        names = sorted(job_only_tech)[:5]
        reasons.append(
            "rewrite uses technology that only appears in the cited "
            "job, not in your answers or the original bullet: "
            + ", ".join(names)
            + ". Remove or replace with something from your answers."
        )
    if fabricated:
        # Same reason wording as before for the legacy fabrication
        # case so existing assertions on this string keep passing.
        names = sorted(fabricated)[:5]
        reasons.append(
            "rewrite contains substantive claims (numbers or "
            "technologies) not present in the original bullet, the "
            "cited quote, or the user's answers: "
            + ", ".join(names)
        )

    return (len(reasons) == 0, reasons)


def validate_coach_rewrite_category_coverage(
    rewritten_text: str,
    *,
    questions: list[CoachQuestion],
    answers: dict[str, str],
    skipped_categories: list[CoachCategory] | None = None,
    category_gaps: list[CoachCategory] | None = None,
) -> tuple[bool, list[str]]:
    """Enforce per-category coverage on the rewrite.

    For every category the LLM flagged as a gap on the bullet, the
    user must EITHER:
      - have answered a question for that category (and at least one
        substantive token from that answer must appear in the
        rewrite), OR
      - have explicitly skipped that category (`skipped_categories`).

    This enforces the one-question-per-gap contract: a WEAK bullet
    that the LLM identified as missing 5 categories must produce 5
    questions, not 4. The old validator only counted coverage for
    questions that existed -- a bullet with gaps {SCOPE, OWNERSHIP,
    ARTIFACT} that only got a question for SCOPE would silently pass
    with the other two categories absent from grounding.

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
      - The gap category is in `skipped_categories`. No question
        required for it.

    Edge case (soft pass, no gap-coverage check):
      - `category_gaps` is None or empty (older clients /
        checklist-not-set). Falls back to per-question coverage
        only -- the old behavior. Logged as warning so we notice
        when this happens in production.
    """
    reasons: list[str] = []
    skipped = set(skipped_categories or [])
    # ------------------------------------------------------------------
    # Rule 1 (new): every non-skipped gap must have a question.
    # Runs BEFORE per-question coverage so the user gets the most
    # actionable message ("you didn't even answer SCOPE") rather than
    # a generic per-question-coverage failure on the question they
    # DID answer. Fall back to per-question-only check when gaps are
    # missing -- this preserves compatibility with older clients.
    # ------------------------------------------------------------------
    missing_gaps: list[CoachCategory] = []
    if category_gaps:
        question_categories: set[CoachCategory] = set()
        # Inline category normalization here: _q_category is defined
        # later in this function and a forward reference inside this
        # branch would raise UnboundLocalError (Python sees the
        # later assignment and treats the name as local throughout).
        for q in questions:
            cat = q.get("category") if isinstance(q, dict) else getattr(q, "category", None)
            if cat is None:
                continue
            if isinstance(cat, CoachCategory):
                question_categories.add(cat)
            elif isinstance(cat, str):
                try:
                    question_categories.add(CoachCategory(cat.strip().upper()))
                except ValueError:
                    pass
        missing_gaps = [
            gap for gap in category_gaps
            if gap not in skipped and gap not in question_categories
        ]
        if missing_gaps:
            missing_names = ", ".join(
                gap.value for gap in missing_gaps
            )
            reasons.append(
                f"rewrite skipped categories without a question or "
                f"skip marker: {missing_names}. Add a question or "
                f"mark the category as skipped before requesting "
                f"a rewrite."
            )
            return (False, reasons)
    # Build the rewrite's stem set once, up front. Used by the
    # per-question coverage check below to compare against each
    # answer's substantive stems. Stems handle morphological
    # variants ("customer" vs "customers") and the structural-
    # token filter handles "the" / "and" / etc. that shouldn't
    # count as a fingerprint.
    rewrite_stems_cached: set[str] = set()
    for tok in _tokens(rewritten_text):
        rewrite_stems_cached.add(_stem(tok))
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
            # Empty answer -- documented as a soft skip ("Empty
            # answer (user skipped without marking the category
            # as skipped). Treated as skipped for this rule.").
            # We `continue` WITHOUT appending a reason so the
            # rewrite route's coverage check accepts this case.
            # The button in the UI is also disabled until the
            # user either fills in an answer or marks the
            # category as skipped, but the validator soft-skips
            # as a safety net (e.g. partially-filled bullets
            # submitted before the in-flight UI changes ship).
            continue
        # Filter out structural-only ("glue") tokens from the
        # answer's stem set before comparing to the rewrite.
        # Without this, an answer like "the" passes trivial-
        # token-overlap even though it carries zero factual
        # information. We compare stems so morphological variants
        # match ("customers" vs "customer", "matched" vs "match").
        answer_stems: set[str] = set()
        for tok in _tokens(answer):
            stem = _stem(tok)
            if stem in _COACH_STRUCTURAL_TOKENS:
                continue
            answer_stems.add(stem)
        if not answer_stems:
            # Answer collapsed to all structural tokens (or was
            # empty after tokenization) -- no substantive
            # fingerprint to check. Soft skip: don't fail, don't
            # penalize. The route can still rely on the LLM
            # having seen the raw text in the prompt and the
            # category_gaps path providing the structural gate.
            continue
        rewrite_stems = rewrite_stems_cached
        overlap = answer_stems & rewrite_stems
        if not overlap:
            reasons.append(
                f"category {category.value}: answer words did not "
                "appear in the rewrite ("
                + ", ".join(sorted(answer_stems)[:3])
                + ")"
            )

    # If category_gaps was missing (None or empty list) and there
    # are no per-question failures, fall back to the old behavior:
    # the per-question coverage was sufficient on its own. Logged
    # at warning level so production can monitor how often the
    # route layer doesn't populate category_gaps -- but never
    # promoted to a hard failure, since that would silently
    # regress the old flow.
    has_real_failures = any(
        "answer words did not appear" in r for r in reasons
    )
    if not category_gaps and not has_real_failures:
        # Don't return the warning as a reason (would gate the
        # route). Log it instead so production telemetry still
        # catches the regression.
        logging.getLogger(__name__).warning(
            "category_gaps not provided to validator; "
            "gap-coverage check skipped. If this happens in "
            "production, the LLM/parser isn't populating "
            "category_gaps before /coach/rewrite, and the "
            "one-question-per-gap contract is unenforceable "
            "for that bullet."
        )

    return (len(reasons) == 0, reasons)