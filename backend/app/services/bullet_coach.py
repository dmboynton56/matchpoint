"""In-memory session store for the bullet-coach flow.

Why this file exists
--------------------
The bullet-coach flow is conversational: the user starts a session,
gets a list of weak bullets + questions, answers the questions, then
asks for a rewrite. Between those steps, the backend needs to remember:
  - which bullets the LLM identified
  - what questions it asked for each
  - the original bullet text + cited job quote (so the rewrite can be
    grounded in those facts even though the LLM is the one writing)
  - what answers the user supplied (if any)

We hold all of that in a server-side dictionary keyed by session_id.
This is intentionally simple for the MVP:

  - One FastAPI process = one Python process = one `_sessions` dict.
  - Locked for thread safety (FastAPI runs requests on a thread pool).
  - 1-hour idle TTL — a session idle that long is dropped on next
    access, and we prune on every operation to keep memory bounded.

What this isn't
---------------
- Multi-process safe. If you scale to >1 worker behind a load balancer,
  each worker has its own dict and the user can land on a different
  one between calls. The migration path is to swap `_sessions` for a
  Supabase table; the public API below doesn't change.
- Persistent. Restart the server = lose all in-flight sessions. Users
  see a 404 on their next call, the UI re-starts the flow. Acceptable
  for a coach session (max ~5 minutes of interaction), unlike cached
  suggestions which we DO persist.

Public surface
--------------
- `create_session(user_id, skills, bullets)` -> session_id (str)
- `get_session(session_id)` -> dict | None  (None when expired/missing)
- `save_answers(session_id, bullet_id, answers)` -> bool
- `prune_expired()` -> int (count pruned, for tests)
"""

from __future__ import annotations

import secrets
import threading
import time
from typing import Any


SESSION_TTL_SECONDS: int = 60 * 60  # 1 hour idle TTL

# Process-wide lock. FastAPI dispatches sync endpoints on a thread
# pool; without this lock, two threads racing on the same session
# can corrupt the dict (e.g. answers overwritten by an older payload).
_lock = threading.Lock()

# session_id -> session dict. See module docstring for what we hold.
_sessions: dict[str, dict[str, Any]] = {}


def _now() -> float:
    """Single point of indirection for the clock so tests can patch it."""
    return time.time()


def _is_expired(session: dict[str, Any]) -> bool:
    return (_now() - session["last_touched_at"]) > SESSION_TTL_SECONDS


def _prune_if_expired(session_id: str) -> None:
    """Caller must hold `_lock`."""
    session = _sessions.get(session_id)
    if session is not None and _is_expired(session):
        del _sessions[session_id]


def create_session(
    *,
    user_id: str,
    skills: list[dict[str, Any]],
    bullets: list[dict[str, Any]],
    job_descriptions: dict[str, str] | None = None,
) -> str:
    """Allocate a new session and return its id.

    The session stores:
      - user_id (so we can verify ownership on later calls; the route
        layer compares against the authenticated user)
      - created_at, last_touched_at (for the TTL)
      - skills (the LLM's skill suggestions, frozen for this session
        — refreshing the one-shot flow after a coach session is fine,
        it just creates a new session)
      - bullets (list of dicts mirroring CoachBullet, plus a per-bullet
        `answers` slot that fills in as the user submits them)
      - job_descriptions (a {job_id: description} snapshot, cached
        at start time so the rewrite call doesn't have to re-fetch
        the user's top matches from Supabase + Turso)
    """
    session_id = secrets.token_urlsafe(16)
    now = _now()
    with _lock:
        _sessions[session_id] = {
            "user_id": user_id,
            "created_at": now,
            "last_touched_at": now,
            "skills": list(skills),
            "bullets": [
                {**bullet, "answers": None}
                for bullet in bullets
            ],
            # Snapshot of the descriptions the start call saw.
            # Cached so /coach/rewrite can run grounding checks
            # without re-fetching from Turso. Bounded: only the
            # jobs the start call referenced end up here.
            "job_descriptions": dict(job_descriptions or {}),
        }
    return session_id


def get_session(session_id: str) -> dict[str, Any] | None:
    """Return the session dict, or None if missing / expired.

    Touches `last_touched_at` on success so active sessions don't
    expire while the user is mid-flow.
    """
    with _lock:
        _prune_if_expired(session_id)
        session = _sessions.get(session_id)
        if session is None:
            return None
        session["last_touched_at"] = _now()
        return dict(session)  # shallow copy — caller can't mutate state


def save_answers(
    session_id: str, *, bullet_id: str, answers: dict[str, str]
) -> dict[str, Any] | None:
    """Attach user answers to a single bullet within the session.

    Returns a shallow-copied snapshot of the updated bullet (so the
    caller can read what was just stored) or None when the session
    or bullet doesn't exist / is expired.
    """
    with _lock:
        _prune_if_expired(session_id)
        session = _sessions.get(session_id)
        if session is None:
            return None
        for bullet in session["bullets"]:
            if bullet.get("bullet_id") == bullet_id:
                bullet["answers"] = dict(answers)
                session["last_touched_at"] = _now()
                return dict(bullet)
        return None


def get_bullet(
    session_id: str, *, bullet_id: str
) -> dict[str, Any] | None:
    """Return a shallow copy of a single bullet from a session, or None."""
    with _lock:
        _prune_if_expired(session_id)
        session = _sessions.get(session_id)
        if session is None:
            return None
        for bullet in session["bullets"]:
            if bullet.get("bullet_id") == bullet_id:
                session["last_touched_at"] = _now()
                return dict(bullet)
        return None


def get_citation_description(
    session_id: str, *, job_id: str
) -> str | None:
    """Return the cached description for `job_id`, or None.

    The descriptions are snapshotted into the session at start
    time so the rewrite call doesn't need to re-fetch from
    Supabase + Turso. Returns None when the job isn't in the
    snapshot (which means: either the start call never saw it,
    or the session is missing/expired).
    """
    with _lock:
        _prune_if_expired(session_id)
        session = _sessions.get(session_id)
        if session is None:
            return None
        descriptions = session.get("job_descriptions") or {}
        return descriptions.get(job_id)


def prune_expired() -> int:
    """Drop every expired session. Returns the count pruned.

    Mostly for tests; the lazy-prune-on-access path is what production
    relies on. Calling this periodically (e.g. from a background task)
    keeps memory bounded even when no traffic flows.
    """
    with _lock:
        expired_ids = [
            sid for sid, session in _sessions.items()
            if _is_expired(session)
        ]
        for sid in expired_ids:
            del _sessions[sid]
        return len(expired_ids)


def clear_all() -> None:
    """Test helper. Wipes every session. Never call from production."""
    with _lock:
        _sessions.clear()