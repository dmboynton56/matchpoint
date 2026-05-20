from fastapi import APIRouter, Depends, HTTPException
from app.db.database import supabase
from app.routes.auth import get_current_user

router = APIRouter()

def _get_user_matches(user_id: str, viewed: bool | None, favorited: bool | None) -> list[dict]:
    query = (
        supabase.table("job_matches")
        .select(
            "id, match_score, is_viewed, is_favorited, created_at, "
            "jobs(id, title, company, location, apply_url, description, posted_at)"
        )
        .eq("user_id", user_id)
        .order("match_score", desc=True)
    )

    if viewed is not None:
        query = query.eq("is_viewed", viewed)
    if favorited is not None:
        query = query.eq("is_favorited", favorited)

    response = query.execute()
    return response.data or []


def _format_match(match: dict) -> dict:
    job = match.get("jobs") or {}
    return {
        "match_id": match["id"],
        "match_score": match["match_score"],
        "is_viewed": match["is_viewed"],
        "is_favorited": match["is_favorited"],
        "matched_at": match["created_at"],
        "job": {
            "id": job.get("id"),
            "title": job.get("title"),
            "company": job.get("company"),
            "location": job.get("location"),
            "apply_url": job.get("apply_url"),
            "description": job.get("description"),
            "posted_at": job.get("posted_at"),
        },
    }


@router.get("/matches/me")
async def get_my_matches(
    viewed: bool | None = None,
    favorited: bool | None = None,
    current_user=Depends(get_current_user),
):
    """
    Returns all job matches for the current user, sorted by match score.
    Optionally filter by is_viewed or is_favorited.
    """
    try:
        raw = _get_user_matches(current_user.id, viewed, favorited)
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