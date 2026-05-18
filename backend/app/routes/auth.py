from fastapi import Request, HTTPException, Depends

async def get_current_user(request: Request):
    # The frontend will send the JWT in the Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(status_code=401, detail="Missing auth token")
    
    token = auth_header.split(" ")[1]
    
    # Verify the token against Supabase Auth
    try:
        user = supabase.auth.get_user(token)
        return user
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
