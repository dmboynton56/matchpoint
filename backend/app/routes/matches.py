from fastapi import APIRouter, Depends, HTTPException
from app.db import turso
from app.db.database import supabase
from app.routes.auth import get_current_user
from app.services.cleaning import resolve_job_location

router = APIRouter()

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
        .select(
            "id, job_id, match_score, is_viewed, is_favorited, is_applied, "
            "created_at, match_notes, match_highlights, match_concerns, "
            "interview_likelihood, skills_fit, experience_fit, seniority_fit, "
            "location_fit, pay_fit, role_fit, preference_fit, location_reason, "
            "location_evidence, pay_reason, pay_evidence, role_reason, "
            "role_evidence, job_facts"
        )
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

    job_ids = sorted({str(m["job_id"]) for m in matches if m.get("job_id") is not None})
    jobs_by_id = turso.fetch_full_jobs(job_ids)

    hydrated_matches = []
    orphan_job_ids: set[str] = set()
    for match in matches:
        job_id = str(match.get("job_id")) if match.get("job_id") is not None else None
        job = jobs_by_id.get(job_id) if job_id else None
        if not job:
            if job_id:
                orphan_job_ids.add(job_id)
            continue
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
            print(f"Orphan job_matches cleanup failed: {cleanup_err}")

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
        raw = _get_user_matches(current_user.id, viewed, favorited, applied)
        matches = [_format_match(m) for m in raw]
        return {
            "count": len(matches),
            "matches": matches,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch matches: {str(e)}") from e


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

        supabase.table("job_matches").update({"is_viewed": True}).eq("id", match_id).execute()
        return {"success": True, "match_id": match_id, "is_viewed": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update match: {str(e)}") from e


@router.patch("/matches/{match_id}/favorite")
async def toggle_favorite(
    match_id: str,
    current_user=Depends(get_current_user),
):
    """Toggles the is_favorited flag on a match. Verifies ownership before updating."""
    try:
        existing = (
            supabase.table("job_matches")
            .select("id, is_favorited")
            .eq("id", match_id)
            .eq("user_id", current_user.id)
            .single()
            .execute()
        )
        if not existing.data:
            raise HTTPException(status_code=404, detail="Match not found.")

        new_value = not existing.data["is_favorited"]
        supabase.table("job_matches").update({"is_favorited": new_value}).eq("id", match_id).execute()
        return {"success": True, "match_id": match_id, "is_favorited": new_value}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update match: {str(e)}") from e


@router.patch("/matches/{match_id}/applied")
async def toggle_applied(
    match_id: str,
    current_user=Depends(get_current_user),
):
    """Toggles the is_applied flag on a match. Verifies ownership before updating."""
    try:
        existing = (
            supabase.table("job_matches")
            .select("id, is_applied")
            .eq("id", match_id)
            .eq("user_id", current_user.id)
            .single()
            .execute()
        )
        if not existing.data:
            raise HTTPException(status_code=404, detail="Match not found.")

        new_value = not existing.data["is_applied"]
        supabase.table("job_matches").update({"is_applied": new_value}).eq("id", match_id).execute()
        return {"success": True, "match_id": match_id, "is_applied": new_value}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update match: {str(e)}") from e


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
        raise HTTPException(status_code=500, detail=f"Failed to delete match: {str(e)}") from e
