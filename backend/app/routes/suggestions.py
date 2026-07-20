from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from app.db import turso
from app.db.database import supabase
from app.routes.auth import get_current_user
from app.schemas.suggestions import (
    MAX_SUGGESTIONS,
    MIN_SUGGESTIONS,
    CoachBullet,
    CoachBulletVerdict,
    CoachCategory,
    CoachRewriteRequest,
    DroppedCoachBullet,
    _citation_grounding_score,
    _quote_is_substring,
    validate_coach_rewrite_answer_keys,
    validate_coach_rewrite_category_coverage,
    validate_coach_rewrite_grounding,
)
from app.services.suggestions import (
    Suggestion,
    build_cache_key,
    generate_resume_suggestions,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# How many of the user's top matches to use as the skill-evidence source
# for the resume suggestions prompt. Deliberately wider than
# AUTHENTICATED_JOB_LIMIT in routes/resumes.py (which controls the
# retrieval path that fills `job_matches`). The retrieval path stays
# tuned to top-10 for quality; the suggestions path uses top-20 to give
# the LLM a broader evidence base for prevalence-driven suggestions.
TOP_JOB_LIMIT = 20
# Per-job description cap for the LLM prompt.
SUGGESTIONS_PROMPT_DESCRIPTION_CHAR_LIMIT = 1000
# Storage-bound cap on the number of rows we keep per user. History beyond
# this is pruned best-effort on each new generation. Set high enough that
# it never bites in normal use.
MAX_HISTORY_ROWS_PER_USER = 50


def _fetch_resume_text(user_id: str) -> str:
    response = (
        supabase.table("profiles")
        .select("resume_text")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    if response is None or not response.data:
        raise HTTPException(
            status_code=404,
            detail="No resume on file. Upload a resume first.",
        )
    text = response.data.get("resume_text") or ""
    if not text.strip():
        raise HTTPException(
            status_code=404,
            detail="No resume on file. Upload a resume first.",
        )
    return text


def _fetch_top_matches(
    user_id: str, *, limit: int
) -> list[dict]:
    """Return top `limit` matches for the user, with full job descriptions.

    Output shape (per match):
      {
        "match_id": str,
        "match_score": float,
        "job_id": str,
        "title": str,
        "company": str,
        "description": str,
        "location": str | None,
        "apply_url": str | None,
      }
    """
    matching_response = (
        supabase.table("job_matches")
        .select(
            "id, match_score, job_id"
        )
        .eq("user_id", user_id)
        .order("match_score", desc=True)
        .limit(limit)
        .execute()
    )
    rows = matching_response.data or []
    if not rows:
        return []

    job_ids = []
    for row in rows:
        job_id = row.get("job_id")
        if not job_id:
            continue
        job_ids.append(str(job_id))

    full_jobs = turso.fetch_full_jobs(job_ids)

    out: list[dict] = []
    for row in rows:
        job_id = row.get("job_id")
        job = full_jobs.get(str(job_id)) or {}
        out.append(
            {
                "match_id": row.get("id"),
                "match_score": row.get("match_score"),
                "job_id": job_id,
                "title": job.get("title"),
                "company": job.get("company"),
                "description": job.get("description") or "",
                "location": job.get("location"),
                "apply_url": job.get("apply_url"),
            })

    return out


def _persist_suggestions(
    user_id: str, cache_key: str, suggestions: list[dict]
) -> None:
    if not suggestions:
        return
    supabase.table("resume_suggestions").insert(
        {
            "user_id": user_id,
            "cache_key": cache_key,
            "suggestions": suggestions,
        }
    ).execute()


def _prune_history(user_id: str) -> None:
    """Keep only the most recent MAX_HISTORY_ROWS_PER_USER rows for the user."""
    try:
        response = (
            supabase.table("resume_suggestions")
            .select("id, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .range(MAX_HISTORY_ROWS_PER_USER, MAX_HISTORY_ROWS_PER_USER + 100)
            .execute()
        )
        rows = response.data or []
        if not rows:
            return
        stale_ids = [row["id"] for row in rows]
        supabase.table("resume_suggestions").delete().in_(
            "id", stale_ids
        ).execute()
    except Exception:  # noqa: BLE001
        # Pruning is best-effort. Log and move on.
        logger.exception("Failed to prune resume_suggestions history")


def _fetch_latest_for_cache_key(
    user_id: str, cache_key: str
) -> dict | None:
    response = (
        supabase.table("resume_suggestions")
        .select("id, suggestions, created_at, cache_key")
        .eq("user_id", user_id)
        .eq("cache_key", cache_key)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


@router.get("/suggestions/me")
async def get_my_suggestions(
    current_user=Depends(get_current_user),
):
    """Return the latest cached suggestions for the current (resume + top
    matches) state, or 404 if none exist for the current cache key.
    """
    user_id = current_user.id
    try:
        resume_text = _fetch_resume_text(user_id)
        top_matches = _fetch_top_matches(user_id, limit=TOP_JOB_LIMIT)
        if not top_matches:
            raise HTTPException(
                status_code=404,
                detail="No matches yet. Upload a resume to generate matches.",
            )
        cache_key = build_cache_key(
            resume_text, (m["job_id"] for m in top_matches)
        )
        row = _fetch_latest_for_cache_key(user_id, cache_key)
        if not row:
            raise HTTPException(
                status_code=404,
                detail="No suggestions cached for current resume and matches.",
            )
        return {
            "id": row["id"],
            "cache_key": row["cache_key"],
            "created_at": row["created_at"],
            "suggestions": row["suggestions"],
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("get_my_suggestions failed")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load suggestions: {exc}",
        ) from exc


@router.post("/suggestions/refresh")
async def refresh_suggestions(
    current_user=Depends(get_current_user),
):
    """Force a fresh LLM generation. Always re-runs the call (does not
    consult the cache). Persists a new row and returns it.
    """
    user_id = current_user.id
    try:
        resume_text = _fetch_resume_text(user_id)
        top_matches = _fetch_top_matches(user_id, limit=TOP_JOB_LIMIT)
        if not top_matches:
            raise HTTPException(
                status_code=404,
                detail="No matches yet. Upload a resume to generate matches.",
            )

        job_summaries = _build_job_summaries(top_matches)

        accepted = generate_resume_suggestions(
            resume_text=resume_text,
            job_summaries=job_summaries,
        )

        if not accepted:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Could not generate grounded suggestions. "
                    "Try again, or refresh your resume."
                ),
            )

        suggestions_json = [
            s.model_dump() for s in accepted[:MAX_SUGGESTIONS]
        ]
        cache_key = build_cache_key(
            resume_text, (m["job_id"] for m in top_matches)
        )
        _persist_suggestions(user_id, cache_key, suggestions_json)
        _prune_history(user_id)

        return {
            "cache_key": cache_key,
            "count": len(suggestions_json),
            "suggestions": suggestions_json,
            "below_minimum": len(suggestions_json) < MIN_SUGGESTIONS,
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("refresh_suggestions failed")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate suggestions: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# Bullet-coach flow
# ---------------------------------------------------------------------------
# Conversational rewrite of weak resume bullets. The LLM identifies
# weak bullets + asks targeted questions in step 1; the user supplies
# the facts; the LLM rewrites the bullet grounded only in those facts
# in step 2. Session state lives in services/bullet_coach.py (in-memory,
# 1-hour TTL). See that module's docstring for the tradeoffs and the
# migration path to persistent storage.
# ---------------------------------------------------------------------------


def _build_job_summaries(top_matches: list[dict]) -> list[dict]:
    """Project the route's top_matches into the job_summaries shape the
    service layer expects. Pulled out of refresh_suggestions so the
    coach endpoints share the exact same shape (apply_url flows
    through to citation stitching).
    """
    return [
        {
            "job_id": m["job_id"],
            "title": m["title"],
            "company": m["company"],
            "apply_url": m.get("apply_url"),
            "description_full": m["description"],
            "description_excerpt": m["description"][
                :SUGGESTIONS_PROMPT_DESCRIPTION_CHAR_LIMIT
            ],
        }
        for m in top_matches
        if m.get("job_id")
    ]


def _apply_citation_enrichment(
    suggestions: list[Suggestion], job_summaries: list[dict]
) -> list[Suggestion]:
    """Stitch authoritative job_title / job_company / apply_url onto
    each surviving Citation. Mirrors the post-process in
    services/suggestions.py:generate_resume_suggestions so the coach
    flow's SKILL suggestions render the same 'Vercel — Senior Software
    Engineer ↗' link as the one-shot flow.
    """
    # Local import to avoid the cross-module cycle at module load time.
    from app.services.suggestions import generate_resume_suggestions

    job_lookup: dict[str, dict] = {
        summary["job_id"]: summary
        for summary in job_summaries
        if summary.get("job_id")
    }
    enriched: list[Suggestion] = []
    for suggestion in suggestions:
        new_evidence = []
        evidence_changed = False
        for citation in suggestion.evidence:
            summary = job_lookup.get(citation.job_id)
            if summary is None:
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
                new_evidence.append(citation)
            else:
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
            enriched.append(
                suggestion.model_copy(update={"evidence": new_evidence})
            )
        else:
            enriched.append(suggestion)
    # Touch the import so static analyzers don't drop it (the function
    # is imported lazily above; the local reference keeps it real).
    _ = generate_resume_suggestions
    return enriched


def _attach_bullet_enrichment(
    bullets: list[CoachBullet], job_summaries: list[dict]
) -> list[CoachBullet]:
    """Same citation-link enrichment for the coach bullets, using their
    own citation_job_id / citation_apply_url fields rather than the
    nested Citation object the SKILL flow uses.
    """
    job_lookup: dict[str, dict] = {
        summary["job_id"]: summary
        for summary in job_summaries
        if summary.get("job_id")
    }
    enriched: list[CoachBullet] = []
    for bullet in bullets:
        summary = job_lookup.get(bullet.citation_job_id)
        if summary is None:
            enriched.append(bullet)
            continue
        new_title = summary.get("title") or bullet.citation_job_title
        new_company = summary.get("company") or bullet.citation_job_company
        new_apply_url = (
            summary.get("apply_url") or bullet.citation_apply_url
        )
        if (
            new_title == bullet.citation_job_title
            and new_company == bullet.citation_job_company
            and new_apply_url == bullet.citation_apply_url
        ):
            enriched.append(bullet)
        else:
            enriched.append(
                bullet.model_copy(
                    update={
                        "citation_job_title": new_title,
                        "citation_job_company": new_company,
                        "citation_apply_url": new_apply_url,
                    }
                )
            )
    return enriched


def _record_coach_drops(
    before: list[CoachBullet],
    after: list[CoachBullet],
    dropped_bullets: list[DroppedCoachBullet],
    *,
    reason: str,
) -> None:
    """Log + record any bullets in `before` that aren't in `after`.

    `reason` is a stable short string from the documented set on
    `DroppedCoachBullet` -- used both for the WARN log and for the
    `reason` field on each appended `DroppedCoachBullet`. Called
    once in `/coach/start` after the citation_job_id membership
    check (reason="citation_job_id_unknown"). Substring-based
    drops are intentionally not tracked -- the start-side policy
    accepts paraphrased quotes (see
    `validate_coach_citation_grounding`'s docstring).
    """
    after_ids = {b.bullet_id for b in after}
    before_by_id = {b.bullet_id: b for b in before}
    for bullet_id, dropped in before_by_id.items():
        if bullet_id in after_ids:
            continue
        logger.warning(
            "coach_start dropped bullet: bullet_id=%s citation_job_id=%s "
            "reason=%s quote=%r",
            dropped.bullet_id,
            dropped.citation_job_id,
            reason,
            dropped.citation_quote,
        )
        dropped_bullets.append(
            DroppedCoachBullet(
                bullet_id=dropped.bullet_id,
                citation_job_id=dropped.citation_job_id,
                citation_quote=dropped.citation_quote,
                original_text=dropped.original_text,
                reason=reason,
            )
        )


@router.post("/suggestions/coach/start")
async def coach_start(
    current_user=Depends(get_current_user),
):
    """Start a coach session.

    One LLM call: returns up to 5 SKILL suggestions AND up to 4 weak
    bullets with targeted questions, all keyed to the user's top job
    matches. The server allocates a session_id (in-memory, 1-hour
    TTL) and returns it with the response. The client passes it back
    when requesting a rewrite.
    """
    # Local imports — the LLM service imports schemas that would
    # otherwise need a forward reference.
    from app.schemas.suggestions import (
        reclassify_overstrong_bullets,
        validate_coach_bullet_grounding,
        validate_coach_citation_grounding,
    )
    from app.services.bullet_coach import create_session
    from app.services.bullet_coach_llm import start_coach_session
    from app.services.resume_parser import parse_resume
    from app.services.suggestions import extract_already_present

    user_id = current_user.id
    try:
        resume_text = _fetch_resume_text(user_id)
        top_matches = _fetch_top_matches(user_id, limit=TOP_JOB_LIMIT)
        if not top_matches:
            raise HTTPException(
                status_code=404,
                detail="No matches yet. Upload a resume to generate matches.",
            )

        job_summaries = _build_job_summaries(top_matches)
        already_present = extract_already_present(resume_text)
        # Parse the resume into sections -> entries so the LLM
        # can pick bullets from a structured view rather than
        # re-parsing the raw text. The parser is best-effort;
        # when it fails to find structure, the LLM still gets
        # the raw text in the user message and falls back to
        # its own sentence-picking.
        parsed_doc = parse_resume(resume_text)
        parsed_resume_payload = parsed_doc.model_dump()
        skills, bullets = start_coach_session(
            resume_text=resume_text,
            already_present=already_present,
            job_summaries=job_summaries,
            parsed_resume=parsed_resume_payload,
        )

        # Stitch authoritative title/company/apply_url onto both
        # lists so the UI can render the standard citation link.
        skills = _apply_citation_enrichment(skills, job_summaries)
        bullets = _attach_bullet_enrichment(bullets, job_summaries)

        # Drop any bullets whose original_text doesn't substring-
        # match a parsed-resume entry. The LLM promises a verbatim
        # substring in the prompt; this is the structural check.
        bullets = validate_coach_bullet_grounding(
            bullets, parsed_resume_payload
        )

        # Snapshot the description of every job the start call
        # saw. The rewrite call uses this instead of re-fetching
        # from Supabase + Turso on every bullet (a roundtrip we
        # can't afford on a fast user-driven flow).
        job_descriptions = {
            s["job_id"]: s.get("description_full") or ""
            for s in job_summaries
        }

        # Drop WEAK bullets whose citation_job_id isn't in the
        # snapshot. Catches the LLM-hallucinated-job_id case:
        # without this drop the bullet would survive start --
        # `validate_coach_citation_grounding`'s "missing
        # description" branch keeps best-effort, designed for the
        # legitimate "job purged from Turso" case -- and then
        # fail at rewrite with "citation quote is not a substring
        # of the job description", because the route coerces the
        # missing description to "" and the substring check
        # returns False for any non-empty quote. STRONG bullets
        # are kept: their citation_quote is cosmetic (no rewrite
        # path) and the "missing description" tolerance for STRONG
        # already exists by design.
        known_job_ids = set(job_descriptions.keys())
        before_membership = list(bullets)
        bullets = [
            b for b in bullets
            if b.verdict == CoachBulletVerdict.STRONG
            or b.citation_job_id in known_job_ids
        ]

        # Citation grounding at start is intentionally permissive:
        # `validate_coach_citation_grounding` is a no-op under the
        # experimental bullet-coach policy (see its docstring --
        # paraphrased / lightly fabricated quotes are accepted in
        # exchange for not 502-ing the user mid-workshop). The
        # call is kept as a defense-in-depth seam so re-tightening
        # the policy only requires re-enabling the check inside
        # that function, not rewiring this route.
        bullets = validate_coach_citation_grounding(
            bullets, job_descriptions
        )

        # Track only membership drops (citation_job_id_unknown).
        # Substring-based drops are intentionally NOT tracked:
        # the policy above accepts paraphrased quotes, so a
        # `citation_quote_not_substring` reason would never fire
        # and would be misleading telemetry. If the policy flips,
        # re-introduce a `before_substring` snapshot here and a
        # second `_record_coach_drops` call -- see git history for
        # the pre-relaxed wiring.
        dropped_bullets: list[DroppedCoachBullet] = []
        _record_coach_drops(
            before_membership,
            bullets,
            dropped_bullets,
            reason="citation_job_id_unknown",
        )
        # Server-side safety net: gpt-4o-mini over-classifies
        # STRONG for thin bullets, leaving the user with no
        # workshop content. reclassify_overstrong_bullets demotes
        # any STRONG bullet whose original_text clearly fails the
        # qualitative-coverage heuristic, synthesizing one
        # question per missing-strict category. Idempotent on
        # sessions where STRONG classification looks genuine.
        bullets = reclassify_overstrong_bullets(bullets)

        session_id = create_session(
            user_id=user_id,
            skills=[skill.model_dump() for skill in skills],
            bullets=[bullet.model_dump() for bullet in bullets],
            job_descriptions=job_descriptions,
        )
        return {
            "session_id": session_id,
            "skills": skills,
            "bullets": bullets,
            "dropped": dropped_bullets,
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("coach_start failed")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start coach session: {exc}",
        ) from exc


@router.post("/suggestions/coach/rewrite")
async def coach_rewrite(
    request: CoachRewriteRequest,
    current_user=Depends(get_current_user),
):
    """Rewrite a single bullet given the candidate's answers.

    The server looks up the session (in-memory, TTL'd), finds the
    bullet, runs the grounding validator (no fabricated tokens), and
    returns the rewritten bullet alongside the citation the UI needs
    to render the job link.
    """
    from app.services.bullet_coach import (
        get_bullet,
        get_citation_description,
        get_session,
        save_answers,
    )
    from app.services.bullet_coach_llm import rewrite_bullet

    user_id = current_user.id
    try:
        session = get_session(request.session_id)
        if session is None or session.get("user_id") != user_id:
            raise HTTPException(
                status_code=404,
                detail="Coach session not found or expired. "
                       "Start a new session.",
            )

        bullet = get_bullet(
            request.session_id, bullet_id=request.bullet_id
        )
        if bullet is None:
            raise HTTPException(
                status_code=404,
                detail="Bullet not found in this session.",
            )

        # STRONG bullets have no questions to answer -- the UI shows
        # "Already strong" and offers no Rewrite affordance. Reject
        # early with a clear message so a stale UI or scripted client
        # gets an actionable error instead of a 502 from the LLM.
        if bullet.get("verdict") == "STRONG":
            raise HTTPException(
                status_code=400,
                detail=(
                    "This bullet is already strong and has no "
                    "questions to answer."
                ),
            )

        requested_keys = [
            question["key"]
            for question in bullet.get("questions", [])
            if isinstance(question, dict) and question.get("key")
        ]
        missing = validate_coach_rewrite_answer_keys(
            requested_keys, request.answers
        )
        if missing:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Missing answers for these questions: "
                    + ", ".join(missing)
                ),
            )

        # Persist the user's answers before the LLM call so a retry
        # sees the same state.
        save_answers(
            request.session_id,
            bullet_id=request.bullet_id,
            answers=request.answers,
        )

        # Re-fetch the bullet (now with answers attached) so the
        # rewrite call has the full picture.
        bullet = get_bullet(
            request.session_id, bullet_id=request.bullet_id
        )

        # Use the description cached on the session (snapshotted
        # at start time) instead of re-fetching from Turso. The
        # validator only needs the full description text to do
        # the substring check on the citation quote; the LLM
        # call itself only needs the quote.
        cited_job_id = bullet.get("citation_job_id", "")
        citation_quote = bullet.get("citation_quote", "")
        citation_description = (
            get_citation_description(
                request.session_id, job_id=cited_job_id
            )
            or ""
        )

        # Build a category-for-key map so the rewrite prompt can
        # label each answer with its category name (SCOPE,
        # ARTIFACT, etc.) instead of its key. The LLM reasons
        # better about categories than keys.
        category_for_key: dict[str, str] = {}
        question_categories: set[CoachCategory] = set()
        for question in bullet.get("questions", []):
            if not isinstance(question, dict):
                continue
            key = question.get("key")
            category = question.get("category")
            if key and category:
                category_for_key[key] = (
                    category.value if hasattr(category, "value") else str(category)
                )
            if category is not None:
                if isinstance(category, CoachCategory):
                    question_categories.add(category)
                elif isinstance(category, str):
                    try:
                        question_categories.add(
                            CoachCategory(category.strip().upper())
                        )
                    except ValueError:
                        pass

        # Skipped categories come from the request; the validator
        # treats them as "do not invent content for these".
        skipped_categories = request.skipped_categories or []

        # Derive category_gaps here (used to be after the LLM
        # call, but we need it before to compute auto-skip below).
        # The prompt asks for `checklist` (six booleans); the
        # Pydantic model also has an explicit `category_gaps`
        # field the LLM may override -- prefer that when
        # populated.
        category_gaps: list[CoachCategory] = []
        raw_gaps = bullet.get("category_gaps")
        if isinstance(raw_gaps, list) and raw_gaps:
            for g in raw_gaps:
                if isinstance(g, CoachCategory):
                    category_gaps.append(g)
                elif isinstance(g, str):
                    try:
                        category_gaps.append(CoachCategory(g.strip().upper()))
                    except ValueError:
                        pass
        if not category_gaps:
            checklist = bullet.get("checklist")
            if isinstance(checklist, dict):
                for cat in CoachCategory:
                    if not checklist.get(cat.value, True):
                        category_gaps.append(cat)
            elif checklist is not None:
                for cat in CoachCategory:
                    if not getattr(checklist, cat.value, True):
                        category_gaps.append(cat)

        # Auto-skip gap categories that don't have a question.
        # The LLM sometimes produces a checklist with N gaps but
        # only M<N questions (e.g., 5 categories marked missing
        # but only 2 questions generated). The user can't answer
        # what wasn't asked, so we treat those gap categories as
        # implicitly skipped rather than 502-ing the request via
        # validate_coach_rewrite_category_coverage's
        # missing-question rule. Categories that DO have
        # questions still go through the per-question coverage
        # check below. Combined with `skipped_categories` to
        # produce the effective skip list passed to both
        # rewrite_bullet (so the LLM doesn't try to invent for
        # them) and the validator.
        auto_skipped: list[CoachCategory] = [
            gap for gap in category_gaps
            if gap not in question_categories
        ]
        effective_skipped_categories: list[CoachCategory] = (
            list(skipped_categories) + auto_skipped
        )
        # Filter answers to only those whose categories are NOT
        # in effective_skipped_categories. The LLM prompt omits
        # skipped-category answers entirely (see the loop in
        # `_build_rewrite_user_message`) so the validator should
        # be consistent with what the LLM saw, and rule 4's
        # job-only attribution shouldn't surface terms the user
        # explicitly opted out of. `category_for_key` stores
        # category names as strings (already `.value`-coerced at
        # build time above), so compare against the string form
        # of effective_skipped_categories for a clean set check.
        effective_skipped_str: set[str] = {
            c.value if hasattr(c, "value") else str(c)
            for c in effective_skipped_categories
        }
        non_skipped_answers: dict[str, str] = {
            key: value
            for key, value in request.answers.items()
            if category_for_key.get(key) not in effective_skipped_str
        }

        rewritten_text = rewrite_bullet(
            original_text=bullet.get("original_text", ""),
            answers=non_skipped_answers,
            citation_quote=citation_quote,
            skipped_categories=[
                c.value if hasattr(c, "value") else c
                for c in effective_skipped_categories
            ],
            category_for_key=category_for_key,
        )

        is_grounded, reasons = validate_coach_rewrite_grounding(
            rewritten_text,
            original_text=bullet.get("original_text", ""),
            answers=non_skipped_answers,
            citation_quote=citation_quote,
            citation_description=citation_description,
        )
        # Diagnostic log: record what the validator saw so the
        # developer can confirm whether a 502 is the citation-
        # grounding rule or a fabrication / coverage rule, and so
        # they can see the actual stored quote when debugging
        # paraphrased citations. DEBUG by default -- enable
        # `logging.getLogger(...).setLevel(DEBUG)` to see every
        # rewrite call. Both the strict-substring match and the
        # relaxed stem-overlap score are computed so logs show
        # the full picture (e.g. "substring=False but score=0.6
        # -- paraphrase was accepted by the relaxed check" or
        # "substring=False, score=0.2 -- genuine fabrication").
        quote_substring_match = _quote_is_substring(
            citation_quote, citation_description
        )
        quote_grounding_score = _citation_grounding_score(
            citation_quote, citation_description
        )
        logger.debug(
            "coach_rewrite grounding check: bullet_id=%s "
            "quote_substring_match=%s quote_grounding_score=%.2f "
            "citation_quote=%r",
            request.bullet_id,
            quote_substring_match,
            quote_grounding_score,
            citation_quote,
        )
        if not is_grounded:
            logger.warning(
                "coach_rewrite grounding failed: %s | bullet_id=%s "
                "quote_substring_match=%s quote_grounding_score=%.2f "
                "citation_quote=%r",
                "; ".join(reasons),
                request.bullet_id,
                quote_substring_match,
                quote_grounding_score,
                citation_quote,
            )
            # Hallucination guard (rules 1-3 of
            # validate_coach_rewrite_grounding). Restored after the
            # qualitative-coach v2 migration (fe2a845): the route
            # previously only logged this, so fabricated numbers,
            # technologies, or ungrounded citations could slip
            # through whenever category coverage passed. Run BEFORE
            # the category-coverage check so fabrication is a hard
            # stop -- coverage is a retry-able soft failure and its
            # 502 message is more actionable for the user.
            #
            # Surface the validator's specific reason so the user
            # gets the action hint -- e.g. "PyTorch appears only in
            # the cited job" beats the generic "rewrite couldn't be
            # grounded". Reasons may be empty (defensive) so we keep
            # a generic fallback.
            detail = (
                reasons[0]
                if reasons
                else "The rewrite couldn't be grounded in your "
                "answers and the cited job. Try rephrasing your "
                "answers, or pick a different bullet."
            )
            raise HTTPException(
                status_code=502,
                detail=detail,
            )

        # Category-coverage check (qualitative-coach v2): every
        # non-skipped gap category must either have a question
        # answered (with at least one answer token in the rewrite)
        # OR be explicitly skipped. Gap categories that lack a
        # question are auto-skipped earlier (see above) so this
        # rule's missing-question branch doesn't fire on them.
        # Categories that DO have questions still go through the
        # per-question coverage check below.
        question_dicts = bullet.get("questions", [])
        category_ok, coverage_reasons = validate_coach_rewrite_category_coverage(
            rewritten_text,
            questions=[
                {
                    "key": q.get("key"),
                    "category": q.get("category"),
                }
                for q in question_dicts
                if isinstance(q, dict)
            ],
            answers=request.answers,
            skipped_categories=effective_skipped_categories,
            category_gaps=category_gaps or None,
        )
        if not category_ok:
            logger.warning(
                "coach_rewrite category coverage failed: %s | bullet_id=%s",
                "; ".join(coverage_reasons),
                request.bullet_id,
            )
            # Surface the validator's specific reason in the user-facing
            # message. The qualitative-coach v2 upgrade means the most
            # actionable signal is WHICH gap or category was missed --
            # "the rewrite didn't reflect your answers" is too generic
            # to act on. The validator's reasons list already names the
            # offending category(ies), so we prepend them.
            detail = (
                coverage_reasons[0]
                if coverage_reasons
                else "The rewrite didn't reflect your answers for every category."
            )
            raise HTTPException(
                status_code=502,
                detail=detail,
            )

        return {
            "bullet_id": bullet.get("bullet_id", ""),
            "original_text": bullet.get("original_text", ""),
            "rewritten_text": rewritten_text,
            "citation_job_id": cited_job_id,
            "citation_job_title": bullet.get("citation_job_title"),
            "citation_job_company": bullet.get("citation_job_company"),
            "citation_apply_url": bullet.get("citation_apply_url"),
            "citation_quote": citation_quote,
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("coach_rewrite failed")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to rewrite bullet: {exc}",
        ) from exc