from typing import Optional

from fastapi import HTTPException, Request

from app.db.database import supabase


def _parse_bearer_token(request: Request) -> Optional[str]:
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return None

    parts = auth_header.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid auth header")

    return parts[1]


async def get_optional_user(request: Request):
    token = _parse_bearer_token(request)
    if not token:
        return None

    try:
        response = supabase.auth.get_user(token)
        if not response or not response.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return response.user
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user(request: Request):
    user = await get_optional_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Missing auth token")
    return user
