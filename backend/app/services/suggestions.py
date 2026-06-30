from __future__ import annotations

import hashlib
import os
import re
from typing import Iterable

from app.schemas.suggestions import (
    Citation,
    MAX_SUGGESTIONS,
    MIN_SUGGESTIONS,
    Suggestion,
    SuggestionKind,
    SuggestionsResponse,
    validate_suggestions,
)
from app.services.embedding import client
from app.services.learning_links import (
    canonical_keys,
    lookup as lookup_learning_link,
)

# ---------------------------------------------------------------------------
# Configuration (env-tunable, mirrors services/ranking.py style)
# ---------------------------------------------------------------------------

SUGGESTIONS_MODEL = os.getenv("OPENAI_SUGGESTIONS_MODEL", "gpt-4o-mini")
SUGGESTIONS_TIMEOUT_SECONDS = float(
    os.getenv("OPENAI_SUGGESTIONS_TIMEOUT_SECONDS", "45")
)
SUGGESTIONS_MAX_RETRIES = int(os.getenv("OPENAI_SUGGESTIONS_MAX_RETRIES", "1"))
SUGGESTIONS_JOB_DESCRIPTION_CHAR_LIMIT = int(
    os.getenv("SUGGESTIONS_JOB_DESCRIPTION_CHAR_LIMIT", "1000")
)
SUGGESTIONS_TEMPERATURE = float(os.getenv("SUGGESTIONS_TEMPERATURE", "0.1"))

suggestions_client = client.with_options(
    timeout=SUGGESTIONS_TIMEOUT_SECONDS,
    max_retries=SUGGESTIONS_MAX_RETRIES,
)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """
You generate resume improvement suggestions for a candidate based on their
existing top-ranked job matches.

You suggest SKILLS (single tools, technologies, or frameworks) the
candidate doesn't currently have on their resume but should consider
adding, based on the JOB EVIDENCE provided. Bullet-level rewriting
is a separate interactive flow (the bullet coach) and is NOT in
scope here — do not propose bullet rewrites or accomplishment-style
lines, only skills.

Grounding rules (HALLUCINATION GUARD — these are not optional):

  - Every suggestion must be supported by the JOB EVIDENCE provided.
  - A suggestion is supported only if at least one JOB's description contains
    the skill you are suggesting, either verbatim or as a
    clear paraphrase.
  - For every supporting JOB, you MUST include a `quote` field containing the
    verbatim snippet from that job's description (the snippet the user could
    Ctrl-F to find). The quote must be an exact substring of the JOB's
    description text provided to you.
  - Do NOT invent tools, certifications, libraries, frameworks, or experience
    the candidate does not already imply. If the resume says "built APIs in
    Python" and a job wants "FastAPI", that is fair. If the resume says
    nothing about Kubernetes and a job mentions it once in passing, do NOT
    suggest Kubernetes.
  - Use the ALREADY_PRESENT list to filter out skills the
    candidate's resume already mentions. Only suggest additions not in that
    list. Note: ALREADY_PRESENT is a best-effort word-token list and may
    miss short acronyms (e.g. "API", "CI", "AI") — still apply common sense.

Prevalence rule:

  - Prefer skills that appear in 3 or more of the provided
    jobs. These are the most prevalent in the candidate's top matches.
  - 2-of-N is also acceptable when a strong overlap exists. Single-job
    suggestions are allowed when the cited quote clearly mentions the skill.
  - Order suggestions by prevalence (most-cited first).

Soft preference for skills with learning resources:

  - The user message will include a PREFERRED_SKILLS list of skill
    names that have a curated learning link. When two candidate
    suggestions are similarly supported by the evidence, prefer the
    one whose name is in PREFERRED_SKILLS — the user gets a
    "Learn it" link, which is more useful than a SKILL with no link.
  - This is a TIEBREAKER, not a constraint. Grounding still wins:
    do NOT suggest a PREFERRED skill that lacks a real citation in
    the job evidence. The validator will drop it anyway.
  - If a job clearly asks for a skill NOT in PREFERRED_SKILLS (e.g.
    "observability experience") and that skill has a real
    citation, still suggest it — the user gets a SKILL with no
    learning link, which is better than ignoring the job.

Specificity rule (TIEBREAKER that beats PREFERRED_SKILLS):

  - When the cited evidence names a specific tool or framework,
    suggest THAT specific name — not a category phrase that
    contains it.
  - Good (specific): "OpenAI API", "LangChain", "n8n", "LangGraph".
  - Bad (category): "AI integration", "LLM tooling", "workflow
    automation", "agentic workflows", "AI-powered tools".
  - Rationale: a specific tool name reads as a real resume line and
    resolves to a learning link. A category phrase reads as fluff
    and gets no link even when it survives grounding.
  - This is a TIEBREAKER, not a constraint. If a job clearly asks
    for a category and no specific tool is named, the category
    phrase is acceptable. But when the evidence names the tool,
    name it too.

HARD BLACKLIST (the validator will drop these — not a tiebreaker):

  - The following phrases are NEVER acceptable as a suggestion,
    even if perfectly cited. They are too broad to be useful as a
    single resume line. The validator will drop them silently.
    Treat this as a hard rule, not a soft preference:
    - Bare single-word AI/ML terms: "AI", "ML", "artificial
      intelligence", "machine learning", "deep learning", "neural
      networks", "data science".
    - Generic engineering categories: "programming", "coding",
      "software development", "web development", "app development".
    - Multi-word AI/ML category phrases: "AI integration", "LLM
      tooling", "AI infrastructure", "AI tooling", "AI-powered
      tools", "agentic systems", "AI systems", "AI solutions",
      "AI automation", "AI applications", "AI workflows", "AI
      experience".
    - Patterns that sound like skills but aren't tools: "RAG",
      "retrieval augmented generation", "fine-tuning", "fine
      tuning", "local LLM", "local model".
    - Vector / embedding category phrases: "vector database",
      "vector DB", "vector store", "vector search", "embeddings
      database".
    - Vendor or model names without a specific product suffix:
      "Claude" (use "Anthropic API"), "Gemini" (use "Gemini API"),
      "Hugging Face" (use "HuggingFace" or "HuggingFace
      Transformers"), "Google AI" (use "Gemini API"). The bare
      vendor name is too vague — what specifically are we
      suggesting the candidate learn?
  - When you would otherwise have suggested one of these, name a
    concrete alternative instead:
    - "AI" / "AI infrastructure" / "AI integration" -> name the
      provider/framework (OpenAI API, Anthropic API, Gemini API,
      LangChain, LlamaIndex, HuggingFace).
    - "machine learning" -> name the library (scikit-learn,
      TensorFlow, PyTorch, JAX) or the task (classification,
      regression, clustering).
    - "data science" -> name the tool (pandas, NumPy, dbt,
      Snowflake, Databricks) or the technique (A/B testing,
      feature engineering, ETL).
    - "agentic systems" / "AI agents" -> name LangGraph (the
      concrete agentic framework).
    - "RAG" / "retrieval augmented generation" -> name a vector
      database (Pinecone, Chroma, Qdrant) or LangChain (which
      implements RAG).
    - "fine-tuning" -> name HuggingFace (which is the go-to
      fine-tuning library).
  - This list is enforced server-side via a validator drop. The
    only way a user ever sees these phrases is if you suggest
    them, the validator drops them, and the count of suggestions
    drops below the minimum — at which point the UI shows a
    "Refresh" affordance and the next call has a chance to do
    better. Don't make the next call have to retry.

Output shape (structured, no prose):

  - Return between 2 and 5 suggestions.
  - Each suggestion has:
      kind: "SKILL"
      text: the short noun phrase for the suggested skill
      evidence: list of {job_id, quote}, with one entry per supporting job
      why_it_matters: optional, may be null
  - The `kind` SKILL is a single tool/technology/framework. Do not
    produce BULLET suggestions or any other kind — kind is always
    "SKILL" and the validator will drop anything else.
  - Never invent job_ids. They are provided in the user message.
  - DO NOT include a `learning_link` field. The system resolves the
    learning link from a curated table based on the skill name. If you
    include `learning_link`, the system will ignore it.

Why it matters guidance (optional, set to null if not applicable):

  - 1-2 short sentences explaining why this skill is
    valuable in the context of the candidate's top job matches. Be
    concrete — tie it to the cited jobs when possible.
  - If you cannot articulate a specific reason, set why_it_matters to null.
""".strip()


# ---------------------------------------------------------------------------
# Deterministic helpers
# ---------------------------------------------------------------------------

_WORD_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9+#.-]{1,}")

# Stopwords to drop from the ALREADY_PRESENT list. These appear in nearly
# every resume and would otherwise suppress legitimate suggestions that
# happen to share the word. Acronyms ("api", "ci", "qa", "ui", "ai",
# "bi", "ml", "nlp", "etl") are intentionally NOT in this list — the
# length filter (>= 4) already removes the shortest of them, and the
# remainder are domain-specific enough that suppression is desirable.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "and", "for", "with", "from", "into", "over", "about",
        "this", "that", "these", "those", "have", "has", "had", "are",
        "was", "were", "been", "will", "would", "could", "should", "may",
        "can", "must", "shall", "their", "they", "them", "your", "yours",
        "our", "ours", "you", "who", "what", "when", "where", "which",
        "how", "why", "than", "then", "also", "just", "only", "very",
        "more", "less", "most", "least", "some", "any", "all", "each",
        "every", "both", "either", "neither", "one", "two", "three",
        "four", "five", "six", "seven", "eight", "nine", "ten",
        "work", "works", "working", "worked", "team", "teams", "company",
        "companies", "role", "roles", "job", "jobs", "year", "years",
        "month", "months", "skill", "skills", "experience", "experienced",
        "responsible", "responsibility", "responsibilities", "include",
        "includes", "including", "strong", "solid", "good", "great",
        "excellent", "plus", "must", "required", "requirement", "nice",
        "familiarity", "familiar", "knowledge", "understanding", "ability",
        "able", "using", "used", "use", "uses", "build", "built", "building",
        "design", "designed", "designing", "develop", "developed",
        "developing", "development", "implement", "implemented",
        "implementation", "deploy", "deployed", "deployment", "support",
        "supported", "supporting", "maintain", "maintained", "maintenance",
        "improve", "improved", "improvement", "improve", "collaborate",
        "collaboration", "communicate", "communication", "manage", "managed",
        "management", "lead", "led", "leading", "leadership",
    }
)


def _normalize_token(token: str) -> str:
    """Strip trailing sentence punctuation from a regex match.

    The word regex `[a-zA-Z][a-zA-Z0-9+#.-]{1,}` is greedy and
    absorbs trailing punctuation that isn't in its character class.
    A phrase like "Built apps in Next.js. Then moved to..." yields
    `next.js.` (with the trailing period glued on). Without this
    strip, the ALREADY_PRESENT token is `next.js.` and the LLM's
    filter — which compares to a clean `next.js` — fails to match.
    The LLM then re-suggests Next.js, which the user already has.

    We strip a small fixed set of sentence-end characters. We do NOT
    strip internal dots (e.g. `next.js`, `vue.js` keep their dots)
    because the regex class doesn't match `.` at internal positions
    where a space-following letter would have ended the run — it
    only grabs the trailing dot if there's no whitespace boundary.
    """
    out = token
    while out and out[-1] in ".,;:!?":
        out = out[:-1]
    return out


def extract_already_present(resume_text: str) -> list[str]:
    """Return a deduped, lowercased list of candidate-skill tokens from the
    resume. Used as the ALREADY_PRESENT filter for the prompt.

    Loosened from the previous version:
      - Token length cutoff raised from >= 3 to >= 4 (drops "api", "ci",
        "go", "js", "ai", "qa", "ui", "r", etc. that were over-suppressing
        legitimate suggestions).
      - Trailing sentence punctuation is stripped from each match so
        that "Next.js." at the end of a sentence produces the canonical
        "next.js" token. Without this, the LLM's ALREADY_PRESENT filter
        silently fails to match dotted skill names that happen to fall
        at a sentence boundary.
      - Common English stopwords + generic resume boilerplate are
        removed from the output. The previous version was producing
        "the", "and", "with", "team", "work", "skill", "experience", etc.
        in the suppression list, which made the prompt's ALREADY_PRESENT
        block noisy and ate into the 600-token cap.
    """
    seen: set[str] = set()
    for match in _WORD_PATTERN.finditer(resume_text.lower()):
        raw = match.group(0)
        token = _normalize_token(raw)
        if len(token) < 4:
            continue
        if token in _STOPWORDS:
            continue
        seen.add(token)
    # Cap to a manageable prompt size.
    return sorted(seen)[:600]


def build_cache_key(resume_text: str, top_job_ids: Iterable[str]) -> str:
    """sha256 of (resume_text + sorted top job ids). Stable across runs.

    Changing either the resume or any of the user's top job matches
    produces a new key, which invalidates the cached `resume_suggestions`
    row. The caller decides how many top jobs to include; this builder
    is agnostic to that count (works for any list passed in).
    """
    joined = ",".join(sorted(top_job_ids))
    payload = f"{resume_text}\n{joined}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _truncate_text(text: str, limit: int) -> str:
    normalized = text.strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "\n[truncated]"


def _build_user_message(
    resume_text: str,
    already_present: list[str],
    job_summaries: list[dict],
) -> str:
    """job_summaries: [{job_id, title, company, description_excerpt}]"""
    parts: list[str] = []
    parts.append(
        "ALREADY_PRESENT (skills the candidate's resume already "
        "mentions — do not suggest these):\n"
        + ", ".join(already_present)
    )
    parts.append(
        "\nRESUME:\n" + _truncate_text(resume_text, 6000)
    )
    parts.append(
        "\nPREFERRED_SKILLS (skills for which we have a curated learning "
        "link — use as a TIEBREAKER when two suggestions are equally "
        "supported by the evidence. Do NOT invent citations to match "
        "these):\n" + ", ".join(canonical_keys())
    )
    parts.append(
        "\nJOB EVIDENCE ({} jobs from the candidate's top matches — each "
        "description is bounded to a working excerpt; you may quote from "
        "this excerpt only):".format(len(job_summaries))
    )
    for summary in job_summaries:
        parts.append(
            f"\n--- JOB {summary['job_id']} ---\n"
            f"Title: {summary['title']}\n"
            f"Company: {summary['company']}\n"
            f"Description excerpt:\n{summary['description_excerpt']}"
        )
    parts.append(
        "\nReturn between 2 and 5 suggestions as a SuggestionsResponse. "
        "Do NOT include a learning_link field — the system resolves it. "
        "Optionally include why_it_matters (may be null)."
    )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# OpenAI call + validation
# ---------------------------------------------------------------------------

def _request_suggestions(
    resume_text: str,
    already_present: list[str],
    job_summaries: list[dict],
) -> SuggestionsResponse | None:
    completion = suggestions_client.beta.chat.completions.parse(
        model=SUGGESTIONS_MODEL,
        temperature=SUGGESTIONS_TEMPERATURE,
        response_format=SuggestionsResponse,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _build_user_message(
                    resume_text, already_present, job_summaries
                ),
            },
        ],
    )
    return completion.choices[0].message.parsed


def generate_resume_suggestions(
    *,
    resume_text: str,
    job_summaries: list[dict],
) -> list[Suggestion]:
    """Return validated, hallucination-guarded suggestions.

    `job_summaries` items must include `job_id`, `title`, `company`,
    `description_excerpt`, and (used in the citation-link post-process
    below) `apply_url`. The full description is also passed to the
    validator (under `job_descriptions`) so quote-substring checks run
    against the actual job text, not the truncated excerpt.
    """
    if not resume_text or not job_summaries:
        return []

    already_present = extract_already_present(resume_text)
    parsed = _request_suggestions(
        resume_text, already_present, job_summaries
    )
    if parsed is None:
        return []

    # Build the validator's lookup from the FULL description, not the
    # truncated excerpt — so a quote that exists in the source survives
    # the substring check even if it sat just past the excerpt boundary.
    job_descriptions: dict[str, str] = {
        summary["job_id"]: summary.get("description_full", "")
        or summary.get("description_excerpt", "")
        for summary in job_summaries
    }

    accepted = validate_suggestions(
        parsed, job_descriptions=job_descriptions
    )

    # Post-process: rewrite learning_link for every accepted suggestion
    # using the curated table in services/learning_links.py. The LLM is
    # not allowed to influence the URL — the prompt tells it not to
    # include learning_link, and even if it does, the lookup() result
    # wins. This is the "no hallucinated URLs" rule.
    resolved: list[Suggestion] = []
    for suggestion in accepted:
        new_link = lookup_learning_link(skill_text=suggestion.text)
        if new_link == suggestion.learning_link:
            # Most common case — the validator already set it to None
            # and the table also returns None. Reuse the object.
            resolved.append(suggestion)
        else:
            # The LLM sent a link, or the table found one. Build a new
            # Suggestion with the resolved link. Pydantic .model_copy
            # is the cleanest way to do an immutable update.
            resolved.append(
                suggestion.model_copy(update={"learning_link": new_link})
            )

    accepted = resolved

    # Defense-in-depth: drop any suggestion whose tokens are ALL
    # already in the resume. The primary filter is the LLM seeing
    # ALREADY_PRESENT in the prompt, but the LLM can slip —
    # especially on dotted names ("Next.js" re-suggested despite
    # the candidate listing it) or near-duplicates ("JavaScript"
    # suggested when only "Java" is in the resume — we want to keep
    # that one). Re-running extract_already_present on the
    # suggestion text gives us a deterministic, regex-based check
    # that uses the SAME normalizer as the prompt side, so what the
    # LLM saw is what we verify against.
    resume_tokens: set[str] = set(extract_already_present(resume_text))
    after_resume_check: list[Suggestion] = []
    for suggestion in accepted:
        suggestion_tokens = set(extract_already_present(suggestion.text))
        if not suggestion_tokens:
            # Tokenizer produced nothing for this suggestion (e.g. a
            # 3-character acronym that fails the length filter). We
            # can't decide either way — keep it.
            after_resume_check.append(suggestion)
            continue
        if suggestion_tokens.issubset(resume_tokens):
            # Every token in the suggestion is already in the resume.
            # Don't suggest skills the candidate has.
            continue
        after_resume_check.append(suggestion)

    accepted = after_resume_check

    # Post-process: stitch authoritative job context (title, company,
    # apply_url) onto each surviving Citation. Same principle as the
    # learning_link rewrite above — the LLM might send these in its
    # response (the schema allows it), but the authoritative values
    # come from the user's top matches in job_summaries. Overwriting
    # ensures the UI's "Vercel — Senior Software Engineer ↗" link
    # points to the real job posting the user is matching against,
    # not anything the LLM hallucinated.
    job_lookup: dict[str, dict] = {
        summary["job_id"]: summary
        for summary in job_summaries
        if summary.get("job_id")
    }
    with_citation_links: list[Suggestion] = []
    for suggestion in accepted:
        new_evidence = []
        evidence_changed = False
        for citation in suggestion.evidence:
            summary = job_lookup.get(citation.job_id)
            if summary is None:
                # Job isn't in the user's top matches — leave the
                # citation alone (validator already approved it, but
                # we have no authoritative context to overwrite with).
                new_evidence.append(citation)
                continue
            new_title = summary.get("title") or citation.job_title
            new_company = summary.get("company") or citation.job_company
            new_apply_url = summary.get("apply_url") or citation.apply_url
            if (
                new_title == citation.job_title
                and new_company == citation.job_company
                and new_apply_url == citation.apply_url
            ):
                # All three match — reuse the existing Citation object.
                new_evidence.append(citation)
            else:
                # At least one field changed — build a new Citation.
                # Pydantic's .model_copy keeps this immutable.
                new_evidence.append(
                    citation.model_copy(
                        update={
                            "job_title": new_title,
                            "job_company": new_company,
                            "apply_url": new_apply_url,
                        }
                    )
                )
                evidence_changed = True
        if evidence_changed:
            with_citation_links.append(
                suggestion.model_copy(update={"evidence": new_evidence})
            )
        else:
            with_citation_links.append(suggestion)

    accepted = with_citation_links

    # Best-effort: if the model produced too few valid suggestions, that's
    # fine — the UI shows "Refresh" and the user can try again. We never
    # fabricate to hit MIN_SUGGESTIONS.
    if len(accepted) < MIN_SUGGESTIONS:
        return accepted

    return accepted[:MAX_SUGGESTIONS]
