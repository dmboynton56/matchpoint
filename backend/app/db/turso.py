"""
turso.py — owns the `jobs` table on Turso (libSQL).

Schema is defined by `JOBS_SCHEMA_SQL` below and is applied idempotently by
`init_schema()` the first time the module is imported. We use the DB-API 2.0
client interface exposed by `libsql` (`Cursor.fetchall`, `cursor.description`,
`cursor.rowcount`, `connection.commit`, `connection.execute`).

Public surface used by the rest of the app:
    - init_schema()                          -> None
    - fetch_existing_external_ids()          -> set[str]
    - upsert_jobs(jobs: list[dict])          -> int
    - update_last_seen(external_ids, iso)    -> int
    - purge_older_than(cutoff_iso)           -> int
    - vector_search(query_embedding, limit)  -> list[dict]
    - fetch_full_jobs(ids: list[str])        -> dict[str, dict]
    - close()                                -> None
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Iterable

from dotenv import load_dotenv

try:
    import libsql
except ImportError:  # pragma: no cover - exercised only when libsql is missing
    libsql = None  # type: ignore[assignment]


load_dotenv()

TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "").strip()
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "").strip()


# -----------------------------------------------------------------------------
# Schema
# -----------------------------------------------------------------------------
# Matches the schema the team agreed on for Turso:
#   - TEXT UUID-v4 `id` (so (text)::uuid casts cleanly into the existing
#     supabase `public.job_matches.job_id uuid` column via replace_job_matches)
#   - JSON-array TEXT `embedding` for the 1536-dim OpenAI vector
#     (Turso / libSQL has no pgvector, so similarity is computed in Python)
#   - `last_seen_at` for the 7-day purge in run_pipeline
JOBS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY DEFAULT (
    lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-' || '4' || substr(lower(hex(randomblob(2))), 2) || '-' || substr('89ab', abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))), 2) || '-' || lower(hex(randomblob(6)))
  ),
  external_id TEXT UNIQUE,
  company TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  location TEXT,
  posted_at TEXT,
  apply_url TEXT,
  embedding TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_jobs_external_id ON jobs (external_id);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs (created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_last_seen_at ON jobs (last_seen_at);
"""


# -----------------------------------------------------------------------------
# Client lifecycle (singleton)
# -----------------------------------------------------------------------------
_client_lock = threading.Lock()
_client: "libsql.Connection | None" = None  # type: ignore[type-arg]


def _require_libsql() -> None:
    if libsql is None:  # pragma: no cover - import guard
        raise RuntimeError(
            "The 'libsql' package is required for Turso access. "
            "Install it with `pip install libsql`."
        )


def _open_client() -> "libsql.Connection":  # type: ignore[type-arg]
    _require_libsql()
    if not TURSO_DATABASE_URL:
        raise RuntimeError(
            "TURSO_DATABASE_URL is not set. Add it to backend/.env "
            "(e.g. libsql://matchpoint-jobs-<org>.turso.io)."
        )
    if TURSO_DATABASE_URL == ":memory:":
        # Local smoke-test path; bypass auth token.
        return libsql.connect(":memory:")
    if not TURSO_AUTH_TOKEN:
        raise RuntimeError(
            "TURSO_AUTH_TOKEN is not set. Add it to backend/.env (or Vercel/GH "
            "secrets for the daily pipeline)."
        )
    return libsql.connect(TURSO_DATABASE_URL, auth_token=TURSO_AUTH_TOKEN)


def get_client() -> "libsql.Connection":  # type: ignore[type-arg]
    """Return the process-wide Turso connection, opening it on first use."""
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is None:
            _client = _open_client()
            init_schema(_client)
        return _client


def close() -> None:
    """Close the cached connection (mainly for tests / process teardown)."""
    global _client
    with _client_lock:
        if _client is not None:
            try:
                _client.close()
            except Exception:
                pass
            _client = None


# -----------------------------------------------------------------------------
# DB-API helpers (libsql returns DB-API Cursors, not `.rows`-style results)
# -----------------------------------------------------------------------------
def _columns(cursor) -> list[str]:
    desc = cursor.description or ()
    return [col[0] for col in desc]


def _fetchall_dicts(cursor) -> list[dict]:
    cols = _columns(cursor)
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


# -----------------------------------------------------------------------------
# Schema bootstrap
# -----------------------------------------------------------------------------
def _split_statements(sql: str) -> list[str]:
    """Split a multi-statement SQL string on top-level semicolons.

    The libsql HTTP backend (Hrana) rejects payloads with more than one
    statement, so we apply DDL one statement at a time. We keep this simple
    by splitting on `;` and discarding empty fragments — the JOBS_SCHEMA_SQL
    DDL doesn't contain any semicolons inside string literals.
    """
    out: list[str] = []
    buf: list[str] = []
    for raw_line in sql.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        buf.append(line)
        if line.strip().endswith(";"):
            stmt = "\n".join(buf).strip().rstrip(";").strip()
            if stmt:
                out.append(stmt)
            buf = []
    tail = "\n".join(buf).strip().rstrip(";").strip()
    if tail:
        out.append(tail)
    return out


def init_schema(client: "libsql.Connection | None" = None) -> None:  # type: ignore[type-arg]
    """Apply JOBS_SCHEMA_SQL idempotently. Safe to call repeatedly."""
    conn = client or get_client()
    # libsql's HTTP transport (Hrana) rejects multi-statement payloads, so
    # apply each DDL statement individually.
    for stmt in _split_statements(JOBS_SCHEMA_SQL):
        conn.execute(stmt)
    conn.commit()


# -----------------------------------------------------------------------------
# Embedding codec (TEXT <-> list[float])
# -----------------------------------------------------------------------------
def _embedding_to_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return json.dumps([float(x) for x in value], separators=(",", ":"))
    raise TypeError(f"Unsupported embedding type: {type(value).__name__}")


def _embedding_from_text(value: Any) -> list[float] | None:
    if value is None or value == "":
        return None
    if isinstance(value, (list, tuple)):
        return [float(x) for x in value]
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        loaded = json.loads(value)
        return [float(x) for x in loaded]
    raise TypeError(f"Unsupported embedding payload type: {type(value).__name__}")


# -----------------------------------------------------------------------------
# Job upsert / read / update / purge
# -----------------------------------------------------------------------------
def _chunks(items: list, size: int) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def upsert_jobs(jobs: list[dict]) -> int:
    """Upsert jobs by `external_id`. Returns the number of rows sent.

    ON CONFLICT(external_id) DO UPDATE keeps the original `id` stable so the
    FK-less `public.job_matches.job_id` text→uuid cast still resolves.
    """
    if not jobs:
        return 0
    conn = get_client()
    sent = 0
    sql = (
        "INSERT INTO jobs "
        "(external_id, company, title, description, location, posted_at, "
        "apply_url, embedding, last_seen_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(external_id) DO UPDATE SET "
        "company=excluded.company, "
        "title=excluded.title, "
        "description=excluded.description, "
        "location=excluded.location, "
        "posted_at=excluded.posted_at, "
        "apply_url=excluded.apply_url, "
        "embedding=excluded.embedding, "
        "last_seen_at=excluded.last_seen_at"
    )
    for job in jobs:
        conn.execute(
            sql,
            [
                job.get("external_id"),
                job.get("company"),
                job.get("title"),
                job.get("description"),
                job.get("location"),
                job.get("posted_at"),
                job.get("apply_url"),
                _embedding_to_text(job.get("embedding")),
                job.get("last_seen_at"),
            ],
        )
        sent += 1
    conn.commit()
    return sent


def fetch_existing_external_ids() -> set[str]:
    conn = get_client()
    cursor = conn.execute(
        "SELECT external_id FROM jobs WHERE external_id IS NOT NULL"
    )
    return {str(row[0]) for row in cursor.fetchall() if row and row[0] is not None}


def update_last_seen(external_ids: list[str], iso_now: str) -> int:
    if not external_ids:
        return 0
    conn = get_client()
    placeholders = ",".join(["?"] * len(external_ids))
    sql = f"UPDATE jobs SET last_seen_at = ? WHERE external_id IN ({placeholders})"
    cursor = conn.execute(sql, [iso_now, *external_ids])
    conn.commit()
    # `rowcount` after UPDATE on libsql reflects matched rows; this is a
    # best-effort return value (callers don't actually use it for branching).
    return int(getattr(cursor, "rowcount", 0) or len(external_ids))


def purge_older_than(cutoff_iso: str) -> int:
    conn = get_client()
    cursor = conn.execute(
        "DELETE FROM jobs WHERE last_seen_at < ?", [cutoff_iso]
    )
    conn.commit()
    return int(getattr(cursor, "rowcount", 0) or 0)


# -----------------------------------------------------------------------------
# Vector search (client-side cosine similarity, no pgvector in libSQL)
# -----------------------------------------------------------------------------
def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / ((na ** 0.5) * (nb ** 0.5))


def vector_search(
    query_embedding: list[float], *, limit: int
) -> list[dict]:
    """Return up to `limit` jobs ordered by cosine similarity to the query.

    Mirrors the shape that the old `supabase.rpc("match_jobs")` returned so
    the call sites in `routes/resumes.py` don't need to change:
        {id, title, company, location, apply_url, similarity}
    """
    conn = get_client()
    cursor = conn.execute(
        "SELECT id, title, company, location, apply_url, embedding "
        "FROM jobs WHERE embedding IS NOT NULL"
    )
    scored: list[tuple[float, tuple]] = []
    for row in cursor.fetchall():
        embedding = _embedding_from_text(row[5])
        if not embedding:
            continue
        sim = _cosine_similarity(query_embedding, embedding)
        scored.append((sim, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    out: list[dict] = []
    for sim, row in scored[:limit]:
        out.append(
            {
                "id": row[0],
                "title": row[1],
                "company": row[2],
                "location": row[3],
                "apply_url": row[4],
                "similarity": sim,
            }
        )
    return out


def fetch_full_jobs(job_ids: list[str]) -> dict[str, dict]:
    """Return `{job_id: {id, title, company, location, apply_url, description, posted_at}}`
    for the given ids. Preserves the dict-by-id shape that
    `routes/resumes.py.fetch_full_jobs` already used to return.
    """
    if not job_ids:
        return {}
    conn = get_client()
    placeholders = ",".join(["?"] * len(job_ids))
    sql = (
        "SELECT id, title, company, location, apply_url, description, posted_at "
        f"FROM jobs WHERE id IN ({placeholders})"
    )
    cursor = conn.execute(sql, list(job_ids))
    return {
        str(row[0]): {
            "id": row[0],
            "title": row[1],
            "company": row[2],
            "location": row[3],
            "apply_url": row[4],
            "description": row[5],
            "posted_at": row[6],
        }
        for row in cursor.fetchall()
    }


__all__ = [
    "init_schema",
    "fetch_existing_external_ids",
    "upsert_jobs",
    "update_last_seen",
    "purge_older_than",
    "vector_search",
    "fetch_full_jobs",
    "close",
    "get_client",
]
