import logging
from datetime import datetime, timezone

from openai import APITimeoutError
from fastapi import APIRouter, Depends, HTTPException
from app.db import turso
from app.db.database import supabase
from app.routes.auth import get_current_user
from app.routes.resumes import recalculate_job_matches_for_user
from app.services.cleaning import resolve_job_location

router = APIRouter()
logger = logging.getLogger(__name__)

MATCH_SELECT = (
    "id, job_id, match_score, is_viewed, is_favorited, is_applied, "
    "created_at, match_notes, match_highlights, match_concerns, "
    "interview_likelihood, skills_fit, experience_fit, seniority_fit, "
    "location_fit, pay_fit, role_fit, preference_fit, location_reason, "
    "location_evidence, pay_reason, pay_evidence, role_reason, "
    "role_evidence, job_facts"
)
SAVED_JOBS_TABLE = "user_saved_jobs"
SAVED_JOB_SELECT = (
    "id, user_id, job_id, source_match_id, is_favorited, is_applied, "
    "favorited_at, applied_at, updated_at, latest_match_score, "
    "job_snapshot, match_snapshot"
)


class SavedJobsTableNotConfigured(RuntimeError):
    pass


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_missing_saved_jobs_table_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "user_saved_jobs" in message and any(
        phrase in message
        for phrase in (
            "does not exist",
            "schema cache",
            "could not find",
            "relation",
            "table",
        )
    )


def _response_data(response) -> list[dict]:
    data = getattr(response, "data", None)
    return data or []


def _build_job_snapshot(job: dict) -> dict:
    return {
        "id": str(job.get("id") or ""),
        "title": job.get("title"),
        "company": job.get("company"),
        "location": resolve_job_location(
            job.get("location") or "",
            job.get("description") or "",
        ),
        "apply_url": job.get("apply_url"),
        "description": job.get("description"),
        "posted_at": job.get("posted_at"),
    }


def _build_match_snapshot(match: dict) -> dict:
    return {
        "match_id": match.get("id"),
        "job_id": str(match.get("job_id") or ""),
        "matched_at": match.get("created_at"),
        "match_score": match.get("match_score"),
        "match_notes": match.get("match_notes"),
        "match_highlights": match.get("match_highlights"),
        "match_concerns": match.get("match_concerns"),
        "interview_likelihood": match.get("interview_likelihood"),
        "skills_fit": match.get("skills_fit"),
        "experience_fit": match.get("experience_fit"),
        "seniority_fit": match.get("seniority_fit"),
        "location_fit": match.get("location_fit"),
        "pay_fit": match.get("pay_fit"),
        "role_fit": match.get("role_fit"),
        "preference_fit": match.get("preference_fit"),
        "location_reason": match.get("location_reason"),
        "location_evidence": match.get("location_evidence"),
        "pay_reason": match.get("pay_reason"),
        "pay_evidence": match.get("pay_evidence"),
        "role_reason": match.get("role_reason"),
        "role_evidence": match.get("role_evidence"),
        "job_facts": match.get("job_facts"),
    }


def _fetch_saved_jobs_by_job_ids(user_id: str, job_ids: list[str]) -> dict[str, dict]:
    if not job_ids:
        return {}
    try:
        response = (
            supabase.table(SAVED_JOBS_TABLE)
            .select(SAVED_JOB_SELECT)
            .eq("user_id", user_id)
            .in_("job_id", job_ids)
            .execute()
        )
    except Exception as exc:
        if _is_missing_saved_jobs_table_error(exc):
            logger.info("Saved jobs table is not configured yet.")
            return {}
        raise
    return {str(row["job_id"]): row for row in _response_data(response)}


def _fetch_saved_job_by_job_id(
    user_id: str, job_id: str, *, require_configured: bool = False
) -> dict | None:
    try:
        response = (
            supabase.table(SAVED_JOBS_TABLE)
            .select(SAVED_JOB_SELECT)
            .eq("user_id", user_id)
            .eq("job_id", job_id)
            .maybe_single()
            .execute()
        )
    except Exception as exc:
        if _is_missing_saved_jobs_table_error(exc):
            if require_configured:
                raise SavedJobsTableNotConfigured from exc
            logger.info("Saved jobs table is not configured yet.")
            return None
        raise
    return getattr(response, "data", None)


def _delete_saved_job(user_id: str, job_id: str) -> None:
    supabase.table(SAVED_JOBS_TABLE).delete().eq("user_id", user_id).eq(
        "job_id", job_id
    ).execute()


def _upsert_saved_job_from_match(
    *,
    user_id: str,
    match: dict,
    job: dict,
    is_favorited: bool | None = None,
    is_applied: bool | None = None,
) -> dict:
    job_id = str(match.get("job_id") or job.get("id") or "")
    if not job_id:
        raise HTTPException(status_code=400, detail="Match has no job id.")

    existing = _fetch_saved_job_by_job_id(
        user_id, job_id, require_configured=True
    )
    current_favorited = bool(
        existing.get("is_favorited") if existing else match.get("is_favorited")
    )
    current_applied = bool(
        existing.get("is_applied") if existing else match.get("is_applied")
    )
    next_favorited = current_favorited if is_favorited is None else is_favorited
    next_applied = current_applied if is_applied is None else is_applied

    if not next_favorited and not next_applied:
        _delete_saved_job(user_id, job_id)
        return {
            "job_id": job_id,
            "is_favorited": False,
            "is_applied": False,
        }

    now = _utc_now_iso()
    payload = {
        "user_id": user_id,
        "job_id": job_id,
        "source_match_id": match.get("id"),
        "is_favorited": next_favorited,
        "is_applied": next_applied,
        "favorited_at": (
            (existing or {}).get("favorited_at") if next_favorited else None
        )
        or (now if next_favorited else None),
        "applied_at": (
            (existing or {}).get("applied_at") if next_applied else None
        )
        or (now if next_applied else None),
        "updated_at": now,
        "latest_match_score": match.get("match_score"),
        "job_snapshot": _build_job_snapshot(job),
        "match_snapshot": _build_match_snapshot(match),
    }
    try:
        response = supabase.table(SAVED_JOBS_TABLE).upsert(
            payload, on_conflict="user_id,job_id"
        ).execute()
    except Exception as exc:
        if _is_missing_saved_jobs_table_error(exc):
            raise SavedJobsTableNotConfigured from exc
        raise
    data = _response_data(response)
    return data[0] if data else payload


def _update_saved_job_flag(
    *,
    user_id: str,
    job_id: str,
    flag: str,
) -> bool:
    existing = _fetch_saved_job_by_job_id(
        user_id, job_id, require_configured=True
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Saved job not found.")

    if flag not in ("is_favorited", "is_applied"):
        raise ValueError(f"Unsupported saved job flag: {flag}")

    next_value = not bool(existing.get(flag))
    other_flag = "is_applied" if flag == "is_favorited" else "is_favorited"
    if not next_value and not bool(existing.get(other_flag)):
        _delete_saved_job(user_id, job_id)
    else:
        now = _utc_now_iso()
        update_payload = {
            flag: next_value,
            "updated_at": now,
        }
        if flag == "is_favorited":
            update_payload["favorited_at"] = now if next_value else None
        else:
            update_payload["applied_at"] = now if next_value else None
        supabase.table(SAVED_JOBS_TABLE).update(update_payload).eq(
            "user_id", user_id
        ).eq("job_id", job_id).execute()

    # Keep any current match row in sync for immediate current-list reads.
    supabase.table("job_matches").update({flag: next_value}).eq(
        "user_id", user_id
    ).eq("job_id", job_id).execute()
    return next_value


def _format_saved_match(row: dict) -> dict:
    job_snapshot = row.get("job_snapshot") or {}
    match_snapshot = row.get("match_snapshot") or {}
    return {
        "id": row.get("id"),
        "job_id": row.get("job_id"),
        "match_score": row.get("latest_match_score")
        if row.get("latest_match_score") is not None
        else match_snapshot.get("match_score"),
        "match_notes": match_snapshot.get("match_notes"),
        "match_highlights": match_snapshot.get("match_highlights"),
        "match_concerns": match_snapshot.get("match_concerns"),
        "interview_likelihood": match_snapshot.get("interview_likelihood"),
        "skills_fit": match_snapshot.get("skills_fit"),
        "experience_fit": match_snapshot.get("experience_fit"),
        "seniority_fit": match_snapshot.get("seniority_fit"),
        "location_fit": match_snapshot.get("location_fit"),
        "pay_fit": match_snapshot.get("pay_fit"),
        "role_fit": match_snapshot.get("role_fit"),
        "preference_fit": match_snapshot.get("preference_fit"),
        "location_reason": match_snapshot.get("location_reason"),
        "location_evidence": match_snapshot.get("location_evidence"),
        "pay_reason": match_snapshot.get("pay_reason"),
        "pay_evidence": match_snapshot.get("pay_evidence"),
        "role_reason": match_snapshot.get("role_reason"),
        "role_evidence": match_snapshot.get("role_evidence"),
        "job_facts": match_snapshot.get("job_facts"),
        "is_viewed": False,
        "is_favorited": row.get("is_favorited"),
        "is_applied": row.get("is_applied"),
        "created_at": row.get("updated_at")
        or row.get("favorited_at")
        or row.get("applied_at"),
        "jobs": {
            "id": job_snapshot.get("id") or row.get("job_id"),
            "title": job_snapshot.get("title"),
            "company": job_snapshot.get("company"),
            "location": job_snapshot.get("location"),
            "apply_url": job_snapshot.get("apply_url"),
            "description": job_snapshot.get("description"),
            "posted_at": job_snapshot.get("posted_at"),
        },
    }


def _get_saved_matches(
    user_id: str,
    *,
    favorited: bool | None = None,
    applied: bool | None = None,
) -> list[dict]:
    try:
        query = (
            supabase.table(SAVED_JOBS_TABLE)
            .select(SAVED_JOB_SELECT)
            .eq("user_id", user_id)
            .order("updated_at", desc=True)
        )
        if favorited is not None:
            query = query.eq("is_favorited", favorited)
        if applied is not None:
            query = query.eq("is_applied", applied)
        response = query.execute()
    except Exception as exc:
        if _is_missing_saved_jobs_table_error(exc):
            logger.info("Saved jobs table is not configured yet.")
            raise SavedJobsTableNotConfigured from exc
        raise
    return [_format_saved_match(row) for row in _response_data(response)]


def _toggle_current_match_flag_by_job_id(
    user_id: str, job_id: str, flag: str
) -> bool:
    existing = (
        supabase.table("job_matches")
        .select(f"id, {flag}")
        .eq("user_id", user_id)
        .eq("job_id", job_id)
        .maybe_single()
        .execute()
    )
    match = getattr(existing, "data", None)
    if not match:
        raise HTTPException(status_code=404, detail="Current match not found.")

    next_value = not bool(match.get(flag))
    supabase.table("job_matches").update({flag: next_value}).eq(
        "user_id", user_id
    ).eq("job_id", job_id).execute()
    return next_value


def _get_current_match_with_job(user_id: str, match_id: str) -> tuple[dict, dict]:
    response = (
        supabase.table("job_matches")
        .select(MATCH_SELECT)
        .eq("id", match_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    match = getattr(response, "data", None)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found.")

    job_id = str(match.get("job_id") or "")
    job = turso.fetch_full_jobs([job_id]).get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return match, job


def _get_user_matches(
    user_id: str,
    viewed: bool | None,
    favorited: bool | None,
    applied: bool | None,
) -> list[dict]:
    # `job_matches` lives in Supabase; `jobs` lives in Turso now, so we
    # can't do the join in SQL anymore. Pull matches first, then hydrate
    # the embedded job from Turso.
    query = (
        supabase.table("job_matches")
        .select(MATCH_SELECT)
        .eq("user_id", user_id)
        .order("match_score", desc=True)
    )

    if viewed is not None:
        query = query.eq("is_viewed", viewed)
    if favorited is not None:
        query = query.eq("is_favorited", favorited)
    if applied is not None:
        query = query.eq("is_applied", applied)

    response = query.execute()
    matches = response.data or []

    job_ids = sorted(
        {str(m["job_id"]) for m in matches if m.get("job_id") is not None}
    )
    jobs_by_id = turso.fetch_full_jobs(job_ids)
    saved_jobs_by_id = _fetch_saved_jobs_by_job_ids(user_id, job_ids)

    hydrated_matches = []
    orphan_job_ids: set[str] = set()
    for match in matches:
        job_id = str(match.get("job_id")) if match.get("job_id") is not None else None
        job = jobs_by_id.get(job_id) if job_id else None
        if not job:
            if job_id:
                orphan_job_ids.add(job_id)
            continue
        saved_job = saved_jobs_by_id.get(job_id)
        if saved_job:
            match["is_favorited"] = bool(saved_job.get("is_favorited"))
            match["is_applied"] = bool(saved_job.get("is_applied"))
        match["jobs"] = job
        hydrated_matches.append(match)

    # Best-effort cleanup: drop this user's job_matches rows pointing at jobs
    # that no longer exist in Turso. Single batched Supabase DELETE, scoped to
    # the caller — Supabase (not Turso) is the write side here, so we don't
    # add write load to the read-DB. Failures are logged, never propagated:
    # the read result above is already correct.
    if orphan_job_ids:
        try:
            supabase.table("job_matches").delete().eq(
                "user_id", user_id
            ).in_("job_id", list(orphan_job_ids)).execute()
        except Exception as cleanup_err:
            logger.warning("Orphan job_matches cleanup failed: %s", cleanup_err)

    return hydrated_matches


def _format_match(match: dict) -> dict:
    job = match.get("jobs") or {}
    return {
        "match_id": match["id"],
        "match_score": match["match_score"],
        "match_notes": match.get("match_notes"),
        "match_highlights": match.get("match_highlights"),
        "match_concerns": match.get("match_concerns"),
        "interview_likelihood": match.get("interview_likelihood"),
        "skills_fit": match.get("skills_fit"),
        "experience_fit": match.get("experience_fit"),
        "seniority_fit": match.get("seniority_fit"),
        "location_fit": match.get("location_fit"),
        "pay_fit": match.get("pay_fit"),
        "role_fit": match.get("role_fit"),
        "preference_fit": match.get("preference_fit"),
        "location_reason": match.get("location_reason"),
        "location_evidence": match.get("location_evidence"),
        "pay_reason": match.get("pay_reason"),
        "pay_evidence": match.get("pay_evidence"),
        "role_reason": match.get("role_reason"),
        "role_evidence": match.get("role_evidence"),
        "job_facts": match.get("job_facts"),
        "is_viewed": match["is_viewed"],
        "is_favorited": match["is_favorited"],
        "is_applied": match["is_applied"],
        "matched_at": match["created_at"],
        "job": {
            "id": job.get("id"),
            "title": job.get("title"),
            "company": job.get("company"),
            "location": resolve_job_location(
                job.get("location") or "",
                job.get("description") or "",
            ),
            "apply_url": job.get("apply_url"),
            "description": job.get("description"),
            "posted_at": job.get("posted_at"),
        },
    }


@router.get("/matches/me")
async def get_my_matches(
    viewed: bool | None = None,
    favorited: bool | None = None,
    applied: bool | None = None,
    current_user=Depends(get_current_user),
):
    """
    Returns all job matches for the current user, sorted by match score.
    Optionally filter by is_viewed, is_favorited, or is_applied.
    """
    try:
        if favorited is True or applied is True:
            try:
                saved_raw = _get_saved_matches(
                    current_user.id,
                    favorited=favorited,
                    applied=applied,
                )
                current_raw = _get_user_matches(
                    current_user.id, viewed, favorited, applied
                )
                saved_job_ids = {
                    str(match.get("job_id"))
                    for match in saved_raw
                    if match.get("job_id") is not None
                }
                raw = saved_raw + [
                    match
                    for match in current_raw
                    if str(match.get("job_id")) not in saved_job_ids
                ]
            except SavedJobsTableNotConfigured:
                raw = _get_user_matches(current_user.id, viewed, favorited, applied)
        else:
            raw = _get_user_matches(current_user.id, viewed, favorited, applied)
        matches = [_format_match(m) for m in raw]
        return {
            "count": len(matches),
            "matches": matches,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch matches: {str(e)}"
        ) from e


@router.post("/matches/recalculate")
async def recalculate_my_matches(
    current_user=Depends(get_current_user),
):
    """
    Re-runs matching from the stored resume text and current profile preferences.
    """
    try:
        jobs = recalculate_job_matches_for_user(current_user.id)
        return {
            "message": "Matches recalculated.",
            "jobs": jobs,
        }
    except HTTPException:
        raise
    except APITimeoutError as e:
        raise HTTPException(
            status_code=504,
            detail="Match recalculation timed out. Try again in a moment.",
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Internal server error recalculating matches",
        ) from e


@router.patch("/matches/{match_id}/viewed")
async def mark_match_viewed(
    match_id: str,
    current_user=Depends(get_current_user),
):
    """Marks a match as viewed. Verifies ownership before updating."""
    try:
        existing = (
            supabase.table("job_matches")
            .select("id")
            .eq("id", match_id)
            .eq("user_id", current_user.id)
            .single()
            .execute()
        )
        if not existing.data:
            raise HTTPException(status_code=404, detail="Match not found.")

        supabase.table("job_matches").update({"is_viewed": True}).eq(
            "id", match_id
        ).execute()
        return {"success": True, "match_id": match_id, "is_viewed": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to update match: {str(e)}"
        ) from e


@router.patch("/matches/{match_id}/favorite")
async def toggle_favorite(
    match_id: str,
    current_user=Depends(get_current_user),
):
    """Toggles the is_favorited flag on a match. Verifies ownership before updating."""
    try:
        match, job = _get_current_match_with_job(current_user.id, match_id)
        job_id = str(match["job_id"])
        saved_jobs_enabled = True
        try:
            saved_job = _fetch_saved_job_by_job_id(
                current_user.id, job_id, require_configured=True
            )
        except SavedJobsTableNotConfigured:
            saved_jobs_enabled = False
            saved_job = None
        new_value = not bool(
            saved_job.get("is_favorited") if saved_job else match["is_favorited"]
        )
        supabase.table("job_matches").update({"is_favorited": new_value}).eq(
            "id", match_id
        ).execute()
        if saved_jobs_enabled:
            try:
                _upsert_saved_job_from_match(
                    user_id=current_user.id,
                    match=match,
                    job=job,
                    is_favorited=new_value,
                )
            except SavedJobsTableNotConfigured:
                logger.info("Saved jobs table is not configured yet.")
        return {"success": True, "match_id": match_id, "is_favorited": new_value}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to update match: {str(e)}"
        ) from e


@router.patch("/matches/{match_id}/applied")
async def toggle_applied(
    match_id: str,
    current_user=Depends(get_current_user),
):
    """Toggles the is_applied flag on a match. Verifies ownership before updating."""
    try:
        match, job = _get_current_match_with_job(current_user.id, match_id)
        job_id = str(match["job_id"])
        saved_jobs_enabled = True
        try:
            saved_job = _fetch_saved_job_by_job_id(
                current_user.id, job_id, require_configured=True
            )
        except SavedJobsTableNotConfigured:
            saved_jobs_enabled = False
            saved_job = None
        new_value = not bool(
            saved_job.get("is_applied") if saved_job else match["is_applied"]
        )
        supabase.table("job_matches").update({"is_applied": new_value}).eq(
            "id", match_id
        ).execute()
        if saved_jobs_enabled:
            try:
                _upsert_saved_job_from_match(
                    user_id=current_user.id,
                    match=match,
                    job=job,
                    is_applied=new_value,
                )
            except SavedJobsTableNotConfigured:
                logger.info("Saved jobs table is not configured yet.")
        return {"success": True, "match_id": match_id, "is_applied": new_value}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to update match: {str(e)}"
        ) from e


@router.patch("/saved-jobs/{job_id}/favorite")
async def toggle_saved_job_favorite(
    job_id: str,
    current_user=Depends(get_current_user),
):
    """Toggles favorite state from the durable saved jobs table."""
    try:
        new_value = _update_saved_job_flag(
            user_id=current_user.id,
            job_id=job_id,
            flag="is_favorited",
        )
        return {"success": True, "job_id": job_id, "is_favorited": new_value}
    except SavedJobsTableNotConfigured:
        new_value = _toggle_current_match_flag_by_job_id(
            current_user.id, job_id, "is_favorited"
        )
        return {"success": True, "job_id": job_id, "is_favorited": new_value}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to update saved job: {str(e)}"
        ) from e


@router.patch("/saved-jobs/{job_id}/applied")
async def toggle_saved_job_applied(
    job_id: str,
    current_user=Depends(get_current_user),
):
    """Toggles applied state from the durable saved jobs table."""
    try:
        new_value = _update_saved_job_flag(
            user_id=current_user.id,
            job_id=job_id,
            flag="is_applied",
        )
        return {"success": True, "job_id": job_id, "is_applied": new_value}
    except SavedJobsTableNotConfigured:
        new_value = _toggle_current_match_flag_by_job_id(
            current_user.id, job_id, "is_applied"
        )
        return {"success": True, "job_id": job_id, "is_applied": new_value}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to update saved job: {str(e)}"
        ) from e


@router.delete("/matches/{match_id}")
async def delete_match(
    match_id: str,
    current_user=Depends(get_current_user),
):
    #Removes a match from the user's list. Verifies ownership before deleting.
    try:
        existing = (
            supabase.table("job_matches")
            .select("id")
            .eq("id", match_id)
            .eq("user_id", current_user.id)
            .single()
            .execute()
        )
        if not existing.data:
            raise HTTPException(status_code=404, detail="Match not found.")

        supabase.table("job_matches").delete().eq("id", match_id).execute()
        return {"success": True, "match_id": match_id, "deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to delete match: {str(e)}"
        ) from e
