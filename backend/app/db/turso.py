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
import pathlib
import threading
from typing import Any, Iterable

import httpx
import numpy as np
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
  external_id TEXT NOT NULL UNIQUE,
  company TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  location TEXT,
  posted_at TEXT,
  apply_url TEXT,
  source TEXT NOT NULL DEFAULT 'greenhouse',
  embedding TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_jobs_external_id ON jobs (external_id);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs (created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_last_seen_at ON jobs (last_seen_at);
"""
# NOTE: idx_jobs_source is intentionally NOT in JOBS_SCHEMA_SQL. On a fresh
# install CREATE TABLE above creates the `source` column, but on a migration
# run the table already exists without it — running CREATE INDEX against a
# missing column raises "no such column: source". The idx_jobs_source index
# is created by init_schema() after the column-add migration step below,
# so it always runs against a table that has the column it indexes.


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
    """Apply JOBS_SCHEMA_SQL idempotently. Safe to call repeatedly.

    On a warm connection (table already present and external_id already NOT
    NULL) this is a single sqlite_master probe — no DDL, no migration. The
    cold path applies the schema and the one-shot external_id NOT NULL
    migration, both best-effort and idempotent.
    """
    conn = client or get_client()
    try:
        warm = _schema_is_warm(conn)
    except Exception:
        # If the probe itself fails (e.g. :memory: race during smoke tests),
        # fall back to the legacy always-apply path.
        warm = False
    if warm:
        return
    # libsql's HTTP transport (Hrana) rejects multi-statement payloads, so
    # apply each DDL statement individually. Wrap each in try/except so a
    # statement that references a column missing on a pre-migration table
    # (e.g. the idx_jobs_source CREATE INDEX when `source` hasn't been ADDed
    # yet) doesn't abort the whole migration. Indexes are best-effort — the
    # app works without them, just slower. The column-ADD step below runs
    # unconditionally afterward, and CREATE INDEX IF NOT EXISTS is a no-op
    # if it landed successfully the first time.
    for stmt in _split_statements(JOBS_SCHEMA_SQL):
        try:
            conn.execute(stmt)
        except Exception as e:
            # Surface the failure in the pipeline log but don't abort —
            # init_schema() is idempotent and we want every migration step
            # to have a chance to apply. The most common cause here is
            # CREATE INDEX against a column that doesn't exist on this
            # schema version; the ADD COLUMN below will provide it.
            print(f"[init_schema] skipped DDL ({type(e).__name__}): {e}")
    # One-shot migration: external_id is now NOT NULL (it is the upsert
    # conflict key and dedupe key, so NULLs bypass ON CONFLICT). Pre-migration
    # rows that already have external_id IS NULL are orphans — they bypass
    # the dedupe path and would block the constraint. Drop them, then enforce.
    # Both statements are idempotent: re-running on a clean schema is a no-op.
    # Skip the ALTER if the column is already NOT NULL on the live table —
    # `ALTER ... SET NOT NULL` is not supported on every libSQL build, and
    # `try/except` would silently swallow that as "already enforced". Probe
    # PRAGMA table_info so we know which case we're in.
    try:
        conn.execute("DELETE FROM jobs WHERE external_id IS NULL")
    except Exception:
        pass
    if not _external_id_is_not_null(conn):
        try:
            conn.execute(
                "ALTER TABLE jobs ALTER COLUMN external_id SET NOT NULL"
            )
        except Exception:
            # libsql < 3.35, or column is already NOT NULL by another path —
            # both are fine. The Python-side `upsert_jobs` validation is the
            # real safety net.
            pass
    # Add the `source` column on tables that predate it. The CREATE TABLE
    # above already includes it for fresh installs; this branch only runs
    # when init_schema() is called against an existing prod table.
    source_added = False
    if not _column_exists(conn, "jobs", "source"):
        try:
            conn.execute(
                "ALTER TABLE jobs ADD COLUMN source TEXT NOT NULL "
                "DEFAULT 'greenhouse'"
            )
            source_added = True
        except Exception:
            # Older libsql without ADD COLUMN DEFAULT support — fall back to
            # a plain ADD COLUMN and backfill. Both are best-effort; existing
            # upsert calls default missing 'source' to 'greenhouse' in Python.
            try:
                conn.execute("ALTER TABLE jobs ADD COLUMN source TEXT")
                # Backfill any existing rows so future NOT NULL would work
                # if a future migration tightens the constraint.
                conn.execute(
                    "UPDATE jobs SET source = 'greenhouse' WHERE source IS NULL"
                )
                source_added = True
            except Exception as inner_exc:
                # Oldest libsql without even plain ADD COLUMN support. We
                # can't add the column from Python — log loudly so operators
                # see this in pipeline output rather than discovering it as
                # a silent outage the next time `source` is queried.
                print(
                    f"[init_schema] fallback ADD COLUMN source also failed: "
                    f"{type(inner_exc).__name__}: {inner_exc}"
                )
    # Index the source column for fast per-source filtering. Always run
    # idempotently — fresh installs hit this after CREATE TABLE above,
    # migration installs hit it after the ALTER ADD COLUMN above. Either
    # way the column exists by the time we get here.
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs (source)"
        )
    except Exception as e:
        # Index creation is best-effort. The app works without it, just
        # slower on per-source queries. Don't fail init_schema over an
        # index problem.
        print(f"[init_schema] could not create idx_jobs_source: {e}")
    if source_added:
        print(
            "[init_schema] migration: added `source` column to existing jobs "
            "table (defaulted to 'greenhouse' for legacy rows)"
        )
    conn.commit()


def _schema_is_warm(conn) -> bool:
    """True iff `jobs` exists, `external_id` is NOT NULL, and `source` exists.

    Lets warm `get_client()` calls skip the DDL+migration cost. We require
    `source` to exist so the column-add migration runs on cold path for any
    pre-2026-07-13 tables.
    """
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'"
    )
    if not cursor.fetchone():
        return False
    if not _external_id_is_not_null(conn):
        return False
    if not _column_exists(conn, "jobs", "source"):
        return False
    return True


def _column_exists(conn, table: str, column: str) -> bool:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    for row in cursor.fetchall():
        # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk
        if row[1] == column:
            return True
    return False


def _external_id_is_not_null(conn) -> bool:
    cursor = conn.execute("PRAGMA table_info(jobs)")
    for row in cursor.fetchall():
        # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk
        if row[1] == "external_id" and int(row[3] or 0) == 1:
            return True
    return False


# -----------------------------------------------------------------------------
# Embedding codec (TEXT <-> list[float])
# -----------------------------------------------------------------------------
def _embedding_to_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return json.dumps([float(x) for x in value], separators=(",", ":"))
    if isinstance(value, str):
        # Accept a pre-serialized JSON array string and re-canonicalize it so
        # what hits the DB is always a tight, validated JSON list. Anything
        # else (a bare number, an object, malformed JSON) raises — the call
        # site is the write boundary, so we'd rather fail loudly here than
        # store garbage that crashes vector_search later.
        loaded = json.loads(value)
        if not isinstance(loaded, (list, tuple)):
            raise TypeError("Embedding string must decode to a JSON array")
        return json.dumps([float(x) for x in loaded], separators=(",", ":"))
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
        "apply_url, source, embedding, last_seen_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(external_id) DO UPDATE SET "
        "company=excluded.company, "
        "title=excluded.title, "
        "description=excluded.description, "
        "location=excluded.location, "
        "posted_at=excluded.posted_at, "
        "apply_url=excluded.apply_url, "
        "source=excluded.source, "
        "embedding=excluded.embedding, "
        "last_seen_at=excluded.last_seen_at"
    )
    for job in jobs:
        external_id = job.get("external_id")
        if external_id in (None, ""):
            raise ValueError("upsert_jobs requires non-empty external_id")
        # Default to 'greenhouse' so older rows pre-dating the column stay
        # valid even if a future code path forgets to pass source.
        source = job.get("source") or "greenhouse"
        conn.execute(
            sql,
            [
                external_id,
                job.get("company"),
                job.get("title"),
                job.get("description"),
                job.get("location"),
                job.get("posted_at"),
                job.get("apply_url"),
                source,
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
# -----------------------------------------------------------------------------
# Embedding matrix cache (data-cache branch on GitHub, local file, or Turso)
# -----------------------------------------------------------------------------
# Read path for vector_search can source the precomputed (matrix, ids) artifact
# from three places, controlled by EMBEDDINGS_SOURCE env var:
#
#   "github"  — fetch the latest commit SHA from the GitHub API, then pull
#                matrix.npy + matrix_ids.json from raw.githubusercontent.com.
#                This is the default in production. ~1–3s on cold start, sub-10ms
#                warm. Repo must be public.
#   "local"   — read from a local file path. Used for testing the codec and
#                matmul without touching GitHub. Set EMBEDDINGS_LOCAL_PATH.
#   "turso"   — disable the cache entirely. Falls back to the legacy
#                SELECT-embedding path below. This is the rollback mode.
#
# If EMBEDDINGS_SOURCE is unset, default to "github".
# Any failure during fetch/load/validate falls back to the Turso path with a
# logged warning. This is intentional: the cache must never break the request.
# -----------------------------------------------------------------------------
EMBEDDINGS_SOURCE = os.getenv("EMBEDDINGS_SOURCE", "github").strip().lower()
GITHUB_REPO_OWNER = os.getenv("GITHUB_REPO_OWNER", "").strip()
GITHUB_REPO_NAME = os.getenv("GITHUB_REPO_NAME", "").strip()
EMBEDDINGS_BRANCH_REF = os.getenv("EMBEDDINGS_BRANCH_REF", "data-cache").strip()
EMBEDDINGS_LOCAL_PATH = os.getenv("EMBEDDINGS_LOCAL_PATH", "").strip()
_timeout_raw = os.getenv("EMBEDDINGS_FETCH_TIMEOUT_SECONDS", "10")
try:
    EMBEDDINGS_FETCH_TIMEOUT_SECONDS = float(_timeout_raw)
except ValueError:
    EMBEDDINGS_FETCH_TIMEOUT_SECONDS = 10.0
    print(
        f"[embeddings] invalid EMBEDDINGS_FETCH_TIMEOUT_SECONDS={_timeout_raw!r}; "
        f"defaulting to 10.0"
    )

_matrix_cache: "np.ndarray | None" = None  # type: ignore[type-arg]
_ids_cache: "list[str] | None" = None
_matrix_lock = threading.Lock()
_matrix_loaded: bool = False
_matrix_load_error: str | None = None


def _get_matrix_and_ids() -> tuple["np.ndarray", "list[str]"] | None:  # type: ignore[type-arg]
    """Return (matrix, ids) from the configured source, or None if the
    source is disabled or the load failed (in which case the caller falls
    back to the Turso SELECT path)."""
    global _matrix_cache, _ids_cache, _matrix_loaded, _matrix_load_error
    if EMBEDDINGS_SOURCE == "turso":
        return None
    if _matrix_loaded:
        if _matrix_cache is None or _ids_cache is None:
            return None
        return _matrix_cache, _ids_cache
    with _matrix_lock:
        if _matrix_loaded:
            if _matrix_cache is None or _ids_cache is None:
                return None
            return _matrix_cache, _ids_cache
        # Import the codec in its own try block so that a failed import
        # (e.g., syntax error in embedding_matrix.py) doesn't leave
        # `EmbeddingMatrixError` unbound and crash the except clause with
        # UnboundLocalError before the fallback can run.
        try:
            from app.services.embedding_matrix import (
                EmbeddingMatrixError,
                MATRIX_FILENAME,
                IDS_FILENAME,
                decode as decode_matrix,
            )
        except Exception as import_exc:
            _matrix_load_error = f"import: {type(import_exc).__name__}: {import_exc}"
            print(
                f"[embeddings] failed to import embedding_matrix module, "
                f"falling back to Turso: {type(import_exc).__name__}: {import_exc}"
            )
            # Do NOT set _matrix_loaded = True here. A transient import
            # error (e.g., the module was edited mid-deploy) should not
            # permanently disable the cache for this process.
            return None
        try:
            if EMBEDDINGS_SOURCE == "local":
                matrix, ids = _load_matrix_from_local(
                    decode_matrix, MATRIX_FILENAME, IDS_FILENAME
                )
            elif EMBEDDINGS_SOURCE == "github":
                matrix, ids = _load_matrix_from_github(
                    decode_matrix, MATRIX_FILENAME, IDS_FILENAME
                )
            else:
                print(
                    f"[embeddings] Unknown EMBEDDINGS_SOURCE={EMBEDDINGS_SOURCE!r}; "
                    f"valid values are 'github', 'local', 'turso'. Falling back to Turso."
                )
                _matrix_loaded = True
                _matrix_cache = None
                _ids_cache = None
                _matrix_load_error = f"unknown source: {EMBEDDINGS_SOURCE}"
                return None
            _matrix_cache = matrix
            _ids_cache = ids
            _matrix_loaded = True
            _matrix_load_error = None
            print(
                f"[embeddings] loaded matrix from {EMBEDDINGS_SOURCE}: "
                f"shape={matrix.shape} dtype={matrix.dtype} ids={len(ids)}"
            )
            return matrix, ids
        except EmbeddingMatrixError as e:
            # Do NOT set _matrix_loaded = True. A transient bad-matrix
            # condition (e.g., a force-push that the SHA lookup raced
            # against) should not disable the cache for the process
            # lifetime. The next call will retry.
            _matrix_load_error = f"validation: {e}"
            print(f"[embeddings] matrix validation failed, falling back to Turso: {e}")
            return None
        except Exception as e:
            # Same reasoning: transient fetch/load errors should retry.
            _matrix_load_error = f"load: {type(e).__name__}: {e}"
            print(
                f"[embeddings] failed to load matrix from {EMBEDDINGS_SOURCE}, "
                f"falling back to Turso: {type(e).__name__}: {e}"
            )
            return None


def _load_matrix_from_local(decode, matrix_filename: str, ids_filename: str):
    if not EMBEDDINGS_LOCAL_PATH:
        raise RuntimeError(
            "EMBEDDINGS_SOURCE=local requires EMBEDDINGS_LOCAL_PATH to be set"
        )
    base = pathlib.Path(EMBEDDINGS_LOCAL_PATH)
    matrix_path = base / matrix_filename
    ids_path = base / ids_filename
    if not matrix_path.exists() or not ids_path.exists():
        raise RuntimeError(
            f"local matrix files not found at {base} "
            f"(expected {matrix_filename} and {ids_filename})"
        )
    return decode(matrix_path.read_bytes(), ids_path.read_bytes())


def _load_matrix_from_github(decode, matrix_filename: str, ids_filename: str):
    if not GITHUB_REPO_OWNER or not GITHUB_REPO_NAME:
        raise RuntimeError(
            "EMBEDDINGS_SOURCE=github requires GITHUB_REPO_OWNER and "
            "GITHUB_REPO_NAME env vars"
        )
    api_url = (
        f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}"
        f"/git/ref/heads/{EMBEDDINGS_BRANCH_REF}"
    )
    timeout = EMBEDDINGS_FETCH_TIMEOUT_SECONDS
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        # 1. Resolve the commit SHA so we never see a stale CDN-cached file.
        resp = client.get(
            api_url,
            headers={"Accept": "application/vnd.github+json"},
        )
        if resp.status_code == 404:
            raise RuntimeError(
                f"branch {EMBEDDINGS_BRANCH_REF!r} not found on "
                f"{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME} (404). "
                f"Has the pipeline pushed to it yet?"
            )
        resp.raise_for_status()
        sha = resp.json()["object"]["sha"]

        # 2. Fetch the matrix + ids at the resolved SHA. raw.githubusercontent.com
        #    serves the file with the SHA in the path, bypassing any CDN cache
        #    of the branch ref.
        base = (
            f"https://raw.githubusercontent.com/{GITHUB_REPO_OWNER}/"
            f"{GITHUB_REPO_NAME}/{sha}/data/embeddings"
        )
        matrix_resp = client.get(f"{base}/{matrix_filename}")
        matrix_resp.raise_for_status()
        ids_resp = client.get(f"{base}/{ids_filename}")
        ids_resp.raise_for_status()

    return decode(matrix_resp.content, ids_resp.content)


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

    Fast path: a precomputed (matrix, ids) artifact is loaded once per
    process from EMBEDDINGS_SOURCE (github | local). The artifact is
    L2-normalized so cosine sim is a single matmul.

    Slow path: if the artifact is unavailable, missing, or fails validation,
    fall back to the legacy per-row Turso SELECT. This path is correct but
    ~100× slower; it exists as a safety net, not a primary route.
    """
    cached = _get_matrix_and_ids()
    if cached is not None:
        matrix, ids = cached
        # Need metadata for the top-k. Two options:
        #   (a) Pull it from the matrix's ids and let the caller fetch_full_jobs
        #   (b) Pull title/company/location/apply_url here via a single SELECT
        # We do (b) so the call site doesn't need to know whether the fast or
        # slow path was taken. The SELECT is keyed on the matched ids only,
        # not the whole table.
        from app.services.embedding_matrix import top_k_ids
        top = top_k_ids(matrix, ids, query_embedding, limit)
        if not top:
            return []
        top_ids = [job_id for job_id, _ in top]
        meta_by_id = _fetch_metadata_for_ids(top_ids)
        out: list[dict] = []
        for job_id, sim in top:
            meta = meta_by_id.get(job_id)
            if not meta:
                # Race: matrix has the id but Turso no longer does. Skip.
                continue
            out.append(
                {
                    "id": job_id,
                    "title": meta["title"],
                    "company": meta["company"],
                    "location": meta["location"],
                    "apply_url": meta["apply_url"],
                    "similarity": sim,
                }
            )
        return out

    # Slow path: legacy behavior. Full table scan + per-row Python cosine.
    return _vector_search_legacy(query_embedding, limit=limit)


def _fetch_metadata_for_ids(job_ids: list[str]) -> dict[str, dict]:
    """Cheap SELECT for title/company/location/apply_url keyed on the
    matched ids. No embedding column — small payload, fast round-trip."""
    if not job_ids:
        return {}
    conn = get_client()
    placeholders = ",".join(["?"] * len(job_ids))
    sql = (
        "SELECT id, title, company, location, apply_url "
        f"FROM jobs WHERE id IN ({placeholders})"
    )
    cursor = conn.execute(sql, list(job_ids))
    return {
        str(row[0]): {
            "title": row[1],
            "company": row[2],
            "location": row[3],
            "apply_url": row[4],
        }
        for row in cursor.fetchall()
    }


def _vector_search_legacy(
    query_embedding: list[float], *, limit: int
) -> list[dict]:
    conn = get_client()
    cursor = conn.execute(
        "SELECT id, title, company, location, apply_url, embedding "
        "FROM jobs WHERE embedding IS NOT NULL"
    )
    scored: list[tuple[float, tuple]] = []
    for row in cursor.fetchall():
        try:
            embedding = _embedding_from_text(row[5])
        except (TypeError, ValueError, json.JSONDecodeError):
            # A malformed embedding row would otherwise take the whole
            # request path down. Skip it; the next upsert (or manual
            # cleanup) will overwrite it.
            continue
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
