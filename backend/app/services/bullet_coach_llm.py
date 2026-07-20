"""LLM-facing functions for the bullet-coach flow.

Two calls to OpenAI:

  1. `start_coach_session(...)` — combined "identify weak bullets + ask
     targeted questions + return SKILL suggestions" in a single
     structured response. Returns (skills, bullets) that the route
     layer packages into a CoachStartResponse.

  2. `rewrite_bullet(...)` — takes the original bullet + user's
     answers + the cited quote, returns a rewritten bullet grounded
     only in those facts. The validator (see
     schemas/suggestions.py:validate_coach_rewrite_grounding) confirms
     no fabricated tokens survive before the response goes out.

Why these are separate files
---------------------------
- services/bullet_coach.py — in-memory session store (pure Python, no
  LLM, no I/O). This file is easy to unit-test in isolation.
- services/bullet_coach_llm.py — the OpenAI prompts + parsing. Mocked
  in tests the same way services/suggestions.py is.

Prompts
-------
The start-coach prompt is intentionally conservative: when in doubt,
return fewer bullets (rather than weak ones). The user can always run
it again. Better to ship 2 high-quality bullets than 5 with one
hallucinated weakness reason.

The rewrite prompt tells the LLM to use ONLY the user-supplied
answers as factual material. The validator's job is to enforce that
structurally — the prompt is encouragement, not the guard.
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.suggestions import (
    Citation,
    CoachBullet,
    CoachQuestion,
    CoachQuestionType,
    MAX_COACH_QUESTIONS,
    MAX_SUGGESTIONS,
    Suggestion,
    SuggestionsResponse,
    validate_coach_start_request,
)
from app.services.embedding import client
from app.services.learning_links import canonical_keys


# ---------------------------------------------------------------------------
# Configuration (env-tunable, mirrors services/suggestions.py style)
# ---------------------------------------------------------------------------

COACH_MODEL = os.getenv("OPENAI_COACH_MODEL", "gpt-4o-mini")
# 45s upper bound. The structured-outputs call to gpt-4o-mini
# can be slow under load; better to wait than to fail.
COACH_TIMEOUT_SECONDS = float(os.getenv("OPENAI_COACH_TIMEOUT_SECONDS", "45"))
COACH_MAX_RETRIES = int(os.getenv("OPENAI_COACH_MAX_RETRIES", "1"))
COACH_TEMPERATURE = float(os.getenv("OPENAI_COACH_TEMPERATURE", "0.2"))

coach_client = client.with_options(
    timeout=COACH_TIMEOUT_SECONDS,
    max_retries=COACH_MAX_RETRIES,
)


# ---------------------------------------------------------------------------
# Structured response shapes (separate from the API-level CoachStartResponse
# because we want internal-only fields, like per-bullet weakness reason
# length, to be more permissive than what ships to the client)
# ---------------------------------------------------------------------------


class _CoachStartLLMResponse(BaseModel):
    """Internal response shape from the LLM. Validated + trimmed before
    being packaged as CoachStartResponse for the client.
    """

    skills: list[Suggestion] = Field(default_factory=list)
    bullets: list[CoachBullet] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

COACH_START_SYSTEM_PROMPT = """
You are a resume coach. Your job is to:

  1. Look at the candidate's resume + their top job matches.
  2. Surface up to 5 bullets from the resume and classify each
     one as either STRONG or WEAK:
       - STRONG: the bullet already covers the key qualitative
         dimensions for its kind of work AND is specific enough
         to be useful in a job search. Don't ask questions.
         Explain in one sentence WHY it's strong (strength_reason).
         A typical STRONG bullet names the artifact / what was
         built, who used it or how big it was, AND connects the
         work to an outcome. Most bullets you see will NOT meet
         this bar -- be honest, not generous.
       - WEAK: anything that's not STRONG. That includes bullets
         that lack an audience, bullets that don't say what got
         built, bullets without an outcome, and bullets written
         in vague terms ("helped with X", "worked on Y"). For
         each WEAK bullet, generate ONE question per missing
         category (see checklist below). The question must ask
         about a QUALITATIVE fact the candidate knows without
         measuring (audience, artifact, what got replaced) —
         NOT a numeric fact (user count, request volume, %).
  3. ALSO return 2-5 SKILL suggestions (a single tool/technology
     name with a citation quote from one of the top jobs). This is
     the same shape as the one-shot resume-suggestions flow.

How to think about STRONG vs WEAK
---------------------------------
Default to WEAK unless the bullet clearly covers AT LEAST FOUR of
the six categories and the missing ones don't matter for a hiring
manager scanning the bullet. The "all six" bar was too high --
real resume bullets rarely cover every dimension, and over-classifying
STRONG leaves the user with nothing to workshop on.

  - "Built X for the cohort."        -> WEAK (no outcome, no
                                         audience size, weak
                                         ownership language)
  - "Helped with the migration."      -> WEAK (assisted, not led;
                                         missing most dimensions)
  - "Designed a dashboard for ops."   -> WEAK (artifact named but
                                         no audience, no outcome)
  - "Built X using React and Node,
     serving 5k users across 3
     internal teams, cutting ticket
     resolution time by 30%."         -> STRONG (artifact, scope,
                                         ownership, cause→effect
                                         all present)

**Hard requirement: at least one STRONG bullet and at least one
WEAK bullet per response, when the resume has 2+ bullets. If the
resume only has one bullet that's clearly STRONG and the rest are
middling or worse, classify the rest as WEAK -- do NOT inflate to
STRONG. A 1-STRONG-4-WEAK session is fine. A 5-STRONG session
usually means you missed something; the server has heuristics that
will catch this and downgrade overly-generous STRONG classifications.**

When in doubt, classify WEAK. The bullet-coach flow exists to help
the user strengthen WEAK bullets -- over-classifying STRONG defeats
the purpose.

The six qualitative categories
-------------------------------
Each bullet should ideally cover ALL six of these:

  SPECIFICITY    — names a concrete artifact or describes the most
                   interesting technical part
                   (e.g. "the matching algorithm", not "a thing")
  SCOPE          — says who used it / what touched it / how big it was
                   (audience: students, internal teams, customers)
  OWNERSHIP      — clear ownership language ("I owned / led / shipped"
                   not "helped with / worked on")
  REPLACEMENT    — says what existed before, or what got unblocked
                   ("replaced the legacy CSV export flow")
  CAUSE_EFFECT   — connects work to outcome ("X, which led to Y")
  ARTIFACT       — names a specific thing produced
                   (API, dashboard, lint rule, doc, migration)

Hallucination guard (structural -- these are not optional):

  - Every citation quote MUST be a verbatim substring of the cited
    job's description. A quote the user could Ctrl-F to find.
  - `original_text` MUST be a verbatim substring of the entry the
    LLM points to in the `location` field. The validator drops
    the bullet if it isn't.
  - For WEAK bullets: one question per missing category. The
    question must be answerable in words (qualitative), not
    numbers. Don't ask "how many users" — ask "who used it".
    Each question's `category` field MUST be one of:
    SPECIFICITY, SCOPE, OWNERSHIP, REPLACEMENT, CAUSE_EFFECT,
    ARTIFACT.
  - Question keys (when supplied) must be ASCII identifiers
    (letters, digits, underscore). They're used as map keys in
    the response. Examples: "scope", "audience", "outcome".
    When not supplied, the system derives a key from the category.
  - Never invent skill names. If a top job mentions a category
    like "AI integration", surface the specific tool the job
    names (e.g. "OpenAI API"). Prefer specific tool names over
    category phrases.

Weak bullet identification rules:

  - A bullet is "weak" when it lacks ANY of the six categories
    above AND the gap matters for hiring-manager scanning. The
    most common real-world gaps are SCOPE (no audience),
    ARTIFACT (built "a thing" instead of "the matching
    algorithm"), and OWNERSHIP ("helped with" instead of "led").
  - The `checklist` field is your hint to the renderer:
    checklist[c] = false means category `c` is missing. Use it
    to drive how many questions to ask. ONE question per false
    category. Set checklist[c] = true for categories the bullet
    clearly covers.
  - If a bullet clearly covers at least four of the six categories
    (artifact named, audience specified, outcome connected, ownership
    language clear) AND the language is specific enough to be useful
    in a job search, classify it as STRONG. Otherwise WEAK. Don't
    pad the list -- STRONG bullets get no questions and ship with
    strength_reason only.
  - For each WEAK bullet, the `weakness_reason` is one short
    sentence. Don't editorialize -- say which category is
    missing (e.g. "No audience mentioned" or "Doesn't say what
    this replaced").

Question design rules (WEAK bullets only):

  - Generate ONE question per missing category (a category
    whose `checklist[c] = false`). For example, if checklist
    has SCOPE=false, OWNERSHIP=false, ARTIFACT=false, produce
    exactly three questions with categories SCOPE, OWNERSHIP,
    ARTIFACT.
  - There are six total categories; a bullet may legitimately
    need up to six questions. Never produce more than one
    question per category, and never invent categories outside
    the six.
  - Questions are SHORT (under 15 words each) -- they fit as
    labels on a text input.
  - Questions are qualitative. The user can answer them with
    descriptions, not measurements. Examples:
      SCOPE:        "Who used this? Was it classmates, a club,
                     your cohort, external users?"
      ARTIFACT:     "What was the most interesting part you
                     built? (algorithm, UI, parser, etc.)"
      REPLACEMENT:  "What existed before this, or what got
                     unblocked because of it?"
      OWNERSHIP:    "Did you lead this end-to-end, or were you
                     one of several contributors?"
      CAUSE_EFFECT: "What changed because of this? What was
                     better for users/the team/the company?"
      SPECIFICITY:  "What's the most specific thing you can
                     say about what you built? (e.g. 'the
                     matching algorithm using vector search'
                     beats 'a matching thing')"
  - The user can skip any question. Don't penalize gaps.

Output shape (structured, no prose):

  Return a JSON object with two top-level keys:

    skills: [
      {
        kind: "SKILL",
        text: "ToolName",
        evidence: [ {job_id, quote} ],
        why_it_matters: optional,
        learning_link: optional (ignored -- system resolves it)
      },
      ...
    ]

    bullets: [
      {
        bullet_id: "b1"  (you choose -- short identifier)
        verdict: "STRONG" or "WEAK"
        original_text: "the verbatim sentence from the resume",

        // STRONG bullets:
        strength_reason: "one sentence on why this bullet is strong"

        // WEAK bullets:
        weakness_reason: "one sentence on what's missing",
        checklist: {
          SPECIFICITY: true/false,
          SCOPE: true/false,
          OWNERSHIP: true/false,
          REPLACEMENT: true/false,
          CAUSE_EFFECT: true/false,
          ARTIFACT: true/false
        },

        // Both verdicts:
        location: {
          section: "Work Experience",
          entry_title: "...",
          entry_text_snippet: "..."
        },
        citation_job_id: "...",
        citation_quote: "a verbatim substring of the cited job's
                        description",

        // WEAK bullets only:
        questions: [
          {
            category: "SCOPE",        // REQUIRED, one of the six
            key: "scope",            // optional; derived from category
            label: "Who used this?",
            hint: "Approximate is fine."   // optional
            type: "TEXT"
          },
          ...
        ]
      },
      ...
    ]

If you have no skill suggestions, return `skills: []`. STRONG and
WEAK bullets can both be empty — neither list is required to be
non-empty.
""".strip()


COACH_REWRITE_SYSTEM_PROMPT = """
You are rewriting one weak resume bullet. The candidate has
supplied qualitative facts about what they built, who used it,
what it replaced, and similar — via the user message. Your job
is to compose a single bullet that uses ONLY:

  - Candidate facts (numbers, technology names, scale figures,
    team sizes, business outcomes, named entities) from the
    ORIGINAL bullet or the candidate's ANSWERS (per category).
  - The CITED JOB QUOTE for target context (what the role
    wants) and wording (how the role describes skills) ONLY.
    The job quote is NOT a source of candidate facts. A phrase
    like "5+ years of Kafka" or "40% latency reduction" that
    appears in the job description describes what the role
    wants, NOT what the candidate has done — do not rephrase
    those into candidate-experience claims.

Hallucination guard (structural):

  - Every number, technology name, scale figure, team size,
    business outcome, or named entity in your rewrite MUST be
    traceable to the original bullet or the candidate's
    answers. If a number or technology name appears only in
    the cited job quote (not in the original bullet or any
    answer), do NOT include it — it isn't the candidate's
    claim to make.
  - Do NOT invent metrics. If the candidate didn't supply a
    number, don't write one. If they said "a lot" instead of a
    number, paraphrase without fabricating a figure.
  - Do NOT introduce technologies the candidate didn't mention.
  - You MAY add connecting verbs, articles, prepositions, and
    other structural English — those are not "facts."
  - The candidate may have SKIPPED some categories. For any
    skipped category, do NOT invent content for that dimension.
    Just leave that category out of the rewrite entirely.
  - Paraphrase the candidate-supplied sources freely. You do
    not need to copy the original wording verbatim — you may
    rephrase it, swap synonyms, reorder clauses, and combine
    facts across the original bullet and the answers. For the
    cited job quote, borrow phrasing and target vocabulary only.
  - Preserve all concrete scope indicators from the original bullet whenever
    they are supported by the source (e.g., numbers, frequencies, scale phrases like
    "hundreds of annotations," "multiple teams," "daily," etc.). Do not omit them unless
    they would make the bullet longer without adding meaning.
  - Keep the bullet to one short line — resume bullets are not
    paragraphs.
  - The rewrite must be different from the original (don't just
    echo it back).

Output shape:

  Return a JSON object with one key:
    rewritten_text: "the rewritten bullet"

That's it. No notes, no preamble, no second-guessing.
""".strip()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _truncate_text(text: str, limit: int) -> str:
    normalized = text.strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "\n[truncated]"


def _format_parsed_resume(
    parsed: dict[str, Any] | None,
) -> str:
    """Render the parsed resume as a compact list of entries for the
    LLM. The LLM uses this to pick which entry + which sentence
    to coach on. We send the structure, not the raw text, so
    the LLM can reason about scope (entry, section) without
    re-parsing.

    `parsed` is a dict shaped like:
      {"sections": [{"title": "Work Experience", "entries":
        [{"title": "Acme Corp", "text": "..."}]}]}

    We cap each entry's text at 600 chars to keep the prompt
    budget reasonable. The LLM picks a sentence (or short
    phrase) from the entry's text; it doesn't need the full
    thing.
    """
    if not parsed or not parsed.get("sections"):
        return "(no parsed resume structure available)"
    lines: list[str] = []
    for section in parsed["sections"]:
        section_title = section.get("title", "Resume")
        lines.append(f"\n## {section_title}")
        entries = section.get("entries", [])
        if not entries:
            lines.append("  (no entries in this section)")
            continue
        for index, entry in enumerate(entries, start=1):
            title = entry.get("title", "").strip()
            text = (entry.get("text") or "").strip()
            # 300 chars is enough for the LLM to spot a sentence
            # to coach on. The full prose is in the user message
            # if the LLM needs more, but we keep the structured
            # view lean to keep latency down.
            text = _truncate_text(text, 300)
            if title:
                lines.append(f"\n  Entry {index}: {title}")
            else:
                lines.append(f"\n  Entry {index}:")
            if text:
                lines.append(f"    {text}")
    return "\n".join(lines)


def _build_start_user_message(
    resume_text: str,
    already_present: list[str],
    job_summaries: list[dict[str, Any]],
    parsed_resume: dict[str, Any] | None = None,
) -> str:
    """Compose the user message for the start-coach call.

    Same shape as services/suggestions.py:_build_user_message so
    the LLM sees the same job evidence and resume context, plus
    a hint that this time it should also produce the
    bullet-coach list.

    `parsed_resume` is the parser output (sections -> entries).
    When provided, the LLM gets a structured view of the resume
    to pick bullets from. When None, falls back to the raw
    resume text blob.
    """
    parts: list[str] = []
    parts.append(
        "ALREADY_PRESENT (skills/keywords the candidate's resume already "
        "mentions -- do not re-suggest these as new skills):\n"
        + ", ".join(already_present)
    )
    # The parsed structure below has the resume content. We
    # don't also send the raw text -- the parser is the
    # ground truth and the LLM doesn't need both. Skipping
    # the raw text cuts ~3-4k tokens from every start call.
    if parsed_resume is not None:
        parts.append(
            "\nPARSED RESUME STRUCTURE (sections -> entries). Pick "
            "bullets from the entries' `text` fields. The "
            "`original_text` you return MUST be a verbatim "
            "substring of the entry you point to in the `location` "
            "field:"
            + _format_parsed_resume(parsed_resume)
        )
    else:
        # Fallback: no parsed structure (parser couldn't find
        # any sections). Send the raw text so the LLM has
        # something to work with.
        parts.append(
            "\nRESUME (raw text):\n" + _truncate_text(resume_text, 4000)
        )
    parts.append(
        "\nPREFERRED_SKILLS (skills for which we have a curated learning "
        "link -- prefer these when evidence is even):\n"
        + ", ".join(canonical_keys())
    )
    parts.append(
        "\nJOB EVIDENCE ({} jobs from the candidate's top matches):".format(
            len(job_summaries)
        )
    )
    for summary in job_summaries:
        parts.append(
            f"\n--- JOB {summary['job_id']} ---\n"
            f"Title: {summary['title']}\n"
            f"Company: {summary['company']}\n"
            f"Description excerpt:\n{summary['description_excerpt']}"
        )
    parts.append(
        "\nReturn (a) up to 5 SKILL suggestions and (b) up to 5 bullets "
        "(mix of STRONG and WEAK as you see fit). For WEAK bullets, "
        "include one question per missing category. For STRONG "
        "bullets, include a strength_reason. See the system prompt "
        "for shape and grounding rules."
    )
    return "\n".join(parts)


def _build_rewrite_user_message(
    original_text: str,
    answers: dict[str, str],
    citation_quote: str,
    *,
    skipped_categories: list[str] | None = None,
    category_for_key: dict[str, str] | None = None,
) -> str:
    """Compose the user message for the rewrite call.

    `skipped_categories` is a list of category names (e.g. "SCOPE",
    "REPLACEMENT") the user explicitly opted out of. We surface them
    so the LLM knows which dimensions to leave out of the rewrite.

    `category_for_key` maps each question.key to its category name
    so we can emit "SCOPE: my cohort of 40 students" instead of just
    "scope: my cohort of 40 students" -- the LLM reasons better
    about categories than keys.
    """
    parts: list[str] = []
    parts.append(f"ORIGINAL BULLET:\n{original_text}")
    parts.append(
        "\nCITED JOB QUOTE (a passage from the cited job's "
        "description — paraphrase as needed, do not copy verbatim):"
    )
    parts.append(citation_quote)
    parts.append(
        "\nCANDIDATE'S ANSWERS (use these as your ONLY factual source — "
        "paraphrase as needed, do not copy verbatim):"
    )
    skipped_raw = set(skipped_categories or [])
    # Normalize skipped values to strings. The route layer may pass
    # either CoachCategory enum values or plain strings (after the
    # Pydantic validator upper-cases them); we tolerate both.
    skipped: set[str] = set()
    for s in skipped_raw:
        skipped.add(getattr(s, "value", s) or str(s))
    key_to_cat = category_for_key or {}
    for key, value in answers.items():
        category = key_to_cat.get(key)
        category_str = (
            getattr(category, "value", category) if category else None
        )
        label = category_str if category_str else key
        if not value.strip():
            # Empty answer -- treat as a skip.
            parts.append(f"  {label}: (skipped)")
        elif category_str in skipped:
            # Non-empty answer but category was explicitly skipped.
            # Omit from the prompt entirely rather than surfacing
            # it with a `[category skipped]` marker -- the route
            # layer filters these out before calling, so this
            # branch is defense in depth for direct callers and
            # test paths that bypass the filter.
            continue
        else:
            parts.append(f"  {label}: {value}")
    if skipped:
        parts.append(
            "\nSKIPPED CATEGORIES (do NOT invent content for these "
            "dimensions; leave them out of the rewrite entirely):"
        )
        for category in sorted(skipped):
            parts.append(f"  - {category}")
    parts.append(
        "\nReturn one rewritten bullet grounded only in the original "
        "bullet, the cited job quote, and the candidate's non-skipped "
        "answers. Paraphrase the sources freely — do not introduce "
        "facts, numbers, technologies, or claims that do not appear "
        "in those three sources."
    )
    return "\n".join(parts)


class _RewriteLLMResponse(BaseModel):
    rewritten_text: str = Field(max_length=600)


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def start_coach_session(
    *,
    resume_text: str,
    already_present: list[str],
    job_summaries: list[dict[str, Any]],
    parsed_resume: dict[str, Any] | None = None,
) -> tuple[list[Suggestion], list[CoachBullet]]:
    """Call the LLM once: identify weak bullets + return skill
    suggestions.

    `parsed_resume` is the parser's structured view of the resume
    (sections -> entries). When provided, the LLM gets a list
    of entries to pick bullets from. When None, falls back to
    the raw resume text in the user message.

    Returns (skills, bullets) after validation. The route layer
    wraps these into a session via
    services/bullet_coach.py:create_session.
    """
    completion = coach_client.beta.chat.completions.parse(
        model=COACH_MODEL,
        temperature=COACH_TEMPERATURE,
        response_format=_CoachStartLLMResponse,
        messages=[
            {"role": "system", "content": COACH_START_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _build_start_user_message(
                    resume_text,
                    already_present,
                    job_summaries,
                    parsed_resume=parsed_resume,
                ),
            },
        ],
    )
    parsed: _CoachStartLLMResponse | None = (
        completion.choices[0].message.parsed
    )
    if parsed is None:
        return [], []

    # Run the LLM-supplied (skills, bullets) through the
    # schema-layer validator. It trims overflow, dedupes bullet
    # IDs, validates question key format, and drops questions
    # with bad keys.
    return validate_coach_start_request(parsed.skills, parsed.bullets)


def rewrite_bullet(
    *,
    original_text: str,
    answers: dict[str, str],
    citation_quote: str,
    skipped_categories: list[str] | None = None,
    category_for_key: dict[str, str] | None = None,
) -> str:
    """Rewrite one bullet given the candidate's answers.

    `skipped_categories` (optional) is a list of category names the
    user explicitly opted out of. When provided, the rewrite prompt
    emits a "do not invent content for these" block.

    `category_for_key` (optional) maps question.key to category name
    so the prompt can label each answer with its category instead of
    just its key. The LLM reasons better about categories than keys.

    Returns the rewritten text. The route layer validates grounding
    via validate_coach_rewrite_grounding + category coverage before
    returning to the client.

    Implementation note: we use the plain chat.completions.create
    endpoint with a JSON-mode prompt (instead of
    beta.chat.completions.parse + structured outputs) because
    structured outputs has been intermittently slow on small
    payloads -- 30+ second response times on what should be a
    2-3 second call. Plain chat is ~2-5x faster for this kind
    of work and we only need to extract one string field. The
    downside is the model might wrap its answer in code fences
    or extra prose; _strip_rewrite_response handles that.
    """
    import logging
    import time
    logger = logging.getLogger(__name__)
    t0 = time.time()
    logger.info(
        "rewrite_bullet: calling LLM (model=%s, prompt_chars=%d)",
        COACH_MODEL,
        sum(len(s) for s in [original_text, citation_quote])
        + sum(len(v) for v in answers.values()),
    )
    completion = coach_client.chat.completions.create(
        model=COACH_MODEL,
        temperature=COACH_TEMPERATURE,
        messages=[
            {"role": "system", "content": COACH_REWRITE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _build_rewrite_user_message(
                    original_text, answers, citation_quote,
                    skipped_categories=skipped_categories,
                    category_for_key=category_for_key,
                ),
            },
        ],
    )
    elapsed = time.time() - t0
    logger.info("rewrite_bullet: LLM responded in %.2fs", elapsed)
    raw = (completion.choices[0].message.content or "").strip()
    return _strip_rewrite_response(raw, fallback=original_text)


def _strip_rewrite_response(raw: str, *, fallback: str) -> str:
    """Extract the rewritten bullet from a possibly-noisy LLM response.

    Plain chat completions don't enforce a schema, so the model
    may wrap its answer in:
      - code fences (```json ... ```)
      - a JSON object with the field we asked for
      - a one-line bullet surrounded by explanation
      - leading "Here is the rewritten bullet:" prose

    We try a few extraction strategies in order:
      1. Look for a JSON object with `rewritten_text` and pull
         the value (most reliable when the model cooperates).
      2. Strip code fences and return the inner text.
      3. Look for a line that looks like a bullet (starts with
         a verb / capital / common resume-bullet opener).
      4. Return the whole raw response if it looks like a single
         line of text.
      5. Fall back to the original bullet (caller passes it).
    """
    if not raw:
        return fallback
    # Strategy 1: JSON object with `rewritten_text`.
    try:
        import json
        import re
        match = re.search(r"\{[^{}]*\"rewritten_text\"[^{}]*\}", raw)
        if match:
            data = json.loads(match.group(0))
            value = data.get("rewritten_text")
            if isinstance(value, str) and value.strip():
                return value.strip()
    except Exception:  # noqa: BLE001
        pass
    # Strategy 2: strip code fences.
    cleaned = raw
    if cleaned.startswith("```"):
        # Drop opening fence (with optional language tag)
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1 :]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    if cleaned:
        return cleaned
    return fallback