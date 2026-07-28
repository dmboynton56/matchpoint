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

import gzip
import io
import json
import os
import pathlib
import threading
from datetime import datetime, timedelta, timezone
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


def _configured_database_url() -> str:
    """Read Turso URL at call time so pytest can override before connect."""
    return os.getenv("TURSO_DATABASE_URL", TURSO_DATABASE_URL).strip()


def _configured_auth_token() -> str:
    return os.getenv("TURSO_AUTH_TOKEN", TURSO_AUTH_TOKEN).strip()


def _assert_safe_test_database() -> None:
    """Refuse remote Turso when the process is running tests.

    Pytest sets PYTEST_CURRENT_TEST per test; conftest sets
    MATCHPOINT_PYTEST_ISOLATE_TURSO before any app import. Either signal
    means destructive fixtures must not hit libsql:// URLs from .env.
    """
    if not (
        os.getenv("PYTEST_CURRENT_TEST")
        or os.getenv("MATCHPOINT_PYTEST_ISOLATE_TURSO")
    ):
        return
    url = _configured_database_url()
    if url and url != ":memory:":
        raise RuntimeError(
            "Refusing to open remote Turso during tests "
            f"({url!r}). Tests must use TURSO_DATABASE_URL=':memory:' "
            "(see backend/tests/conftest.py)."
        )


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

BROWSE_EXTRA_COLUMNS: list[tuple[str, str]] = [
    ("summary", "TEXT"),
    ("summary_source_hash", "TEXT"),
    ("summary_model", "TEXT"),
    ("summary_generated_at", "TEXT"),
    ("workplace_type", "TEXT"),
    ("pay_min", "INTEGER"),
    ("pay_max", "INTEGER"),
    ("pay_currency", "TEXT"),
    ("experience_level", "TEXT"),
    ("job_type", "TEXT"),
    ("metadata_derived_at", "TEXT"),
    # Geolocation columns — populated by services/geo.py at pipeline time.
    # Stored as ISO 3166-1 alpha-2 country code (e.g. "US") so the read path
    # can do structured country-set comparisons against profile preferences.
    ("geo_country_code", "TEXT"),
    ("geo_city", "TEXT"),
    ("geo_region", "TEXT"),
    ("geo_lat", "REAL"),
    ("geo_lon", "REAL"),
    ("geo_confidence", "REAL"),
    ("geo_source", "TEXT"),
    ("geocoded_at", "TEXT"),
]

BROWSE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_jobs_posted_at ON jobs (posted_at)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_workplace_type ON jobs (workplace_type)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_experience_level ON jobs (experience_level)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_job_type ON jobs (job_type)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_pay_min ON jobs (pay_min)",
    # Country-code index lets the read path filter candidate jobs by the
    # user's preferred_country_codes set without a full scan. libSQL supports
    # indexed TEXT equality, which is all we need here.
    "CREATE INDEX IF NOT EXISTS idx_jobs_geo_country_code ON jobs (geo_country_code)",
]

# Geocode cache: keyed by a SHA-256 of the normalized input string. Place
# strings don't change meaning over time, so we never expire entries — the
# table grows slowly (one row per unique location string ever seen) and is
# the difference between "one Photon call per job per day" and "one Photon
# call per unique location string ever." Permanent by design.
GEOCODE_CACHE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS geocode_cache (
    location_key TEXT PRIMARY KEY,
    location_raw TEXT NOT NULL,
    geo_country_code TEXT,
    geo_city TEXT,
    geo_region TEXT,
    geo_lat REAL,
    geo_lon REAL,
    geo_confidence REAL,
    geo_source TEXT,
    geocoded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_geocode_cache_country ON geocode_cache (geo_country_code);
"""


# Reference data: GeoNames cities15000.txt. ~25k cities, public domain,
# one-time build via scripts/build_geonames_cache.py. The pipeline
# reads from this table to geocode job location strings — no live
# network calls. `name_lower` is the lookup key; `country_code` and
# `admin1` are disambiguation when multiple cities share a name
# (e.g. Portland, OR vs Portland, ME). `population` is a tiebreaker
# so the most-likely-intended city wins for ambiguous names.
GEOCITIES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS geo_cities (
    name_lower TEXT NOT NULL,
    country_code TEXT NOT NULL,
    admin1 TEXT,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    population INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (name_lower, country_code, admin1)
);
CREATE INDEX IF NOT EXISTS idx_geo_cities_name ON geo_cities (name_lower);
CREATE INDEX IF NOT EXISTS idx_geo_cities_country ON geo_cities (country_code);
"""

DATE_POSTED_WINDOW_DAYS: dict[str, int] = {
    "24h": 1,
    "3d": 3,
    "7d": 7,
    "14d": 14,
    "30d": 30,
}

BROWSE_LIST_COLUMNS = (
    "id, title, company, location, apply_url, posted_at, summary, "
    "job_type, experience_level, workplace_type, pay_min, pay_max, pay_currency"
)


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
    _assert_safe_test_database()
    database_url = _configured_database_url()
    auth_token = _configured_auth_token()
    if not database_url:
        raise RuntimeError(
            "TURSO_DATABASE_URL is not set. Add it to backend/.env "
            "(e.g. libsql://matchpoint-jobs-<org>.turso.io)."
        )
    if database_url == ":memory:":
        # Local smoke-test path; bypass auth token.
        return libsql.connect(":memory:")
    if not auth_token:
        raise RuntimeError(
            "TURSO_AUTH_TOKEN is not set. Add it to backend/.env (or Vercel/GH "
            "secrets for the daily pipeline)."
        )
    return libsql.connect(database_url, auth_token=auth_token)


def get_client() -> "libsql.Connection":  # type: ignore[type-arg]
    """Return the process-wide Turso connection, opening it on first use."""
    global _client
    _assert_safe_test_database()
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
        _ensure_browse_columns(conn)
        _ensure_geocode_cache_table(conn)
        _ensure_geo_cities_table(conn)
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
    _ensure_browse_columns(conn)
    _ensure_geocode_cache_table(conn)
    _ensure_geo_cities_table(conn)
    conn.commit()


def _ensure_browse_columns(conn) -> None:
    """Idempotently add browse/search columns and indexes."""
    cursor = conn.execute("PRAGMA table_info(jobs)")
    existing = {row[1] for row in cursor.fetchall()}
    for name, col_type in BROWSE_EXTRA_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {col_type}")
    for stmt in BROWSE_INDEXES_SQL:
        conn.execute(stmt)


def _ensure_geocode_cache_table(conn) -> None:
    """Idempotently create the geocode_cache table. Safe to call repeatedly.

    The DDL is a single CREATE TABLE + INDEX pair split into two statements
    because the Hrana HTTP transport rejects multi-statement payloads,
    matching the pattern used elsewhere in this module. We swallow exceptions
    so a stale or sandboxed libsql build never blocks the rest of the schema
    migration — the table is best-effort, and the geocoding path falls back
    to "unresolved" entries if the cache is missing.
    """
    for stmt in _split_statements(GEOCODE_CACHE_SCHEMA_SQL):
        try:
            conn.execute(stmt)
        except Exception as exc:
            print(
                f"[init_schema] geocode_cache DDL skipped "
                f"({type(exc).__name__}): {exc}"
            )


def _ensure_geo_cities_table(conn) -> None:
    """Idempotently create the geo_cities reference table.

    Mirrors the geocode_cache pattern: DDL is best-effort and split into
    one-statement-per-line because the Hrana HTTP transport rejects
    multi-statement payloads. The table starts empty after a fresh
    migration — populate it with scripts/build_geonames_cache.py.
    """
    for stmt in _split_statements(GEOCITIES_SCHEMA_SQL):
        try:
            conn.execute(stmt)
        except Exception as exc:
            print(
                f"[init_schema] geo_cities DDL skipped "
                f"({type(exc).__name__}): {exc}"
            )



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
        "apply_url, source, embedding, last_seen_at, summary, summary_source_hash, "
        "summary_model, summary_generated_at, workplace_type, pay_min, pay_max, "
        "pay_currency, experience_level, job_type, metadata_derived_at, "
        "geo_country_code, geo_city, geo_region, geo_lat, geo_lon, "
        "geo_confidence, geo_source, geocoded_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(external_id) DO UPDATE SET "
        "company=excluded.company, "
        "title=excluded.title, "
        "description=excluded.description, "
        "location=excluded.location, "
        "posted_at=excluded.posted_at, "
        "apply_url=excluded.apply_url, "
        "source=excluded.source, "
        "embedding=excluded.embedding, "
        "last_seen_at=excluded.last_seen_at, "
        "summary=CASE WHEN excluded.summary IS NOT NULL THEN excluded.summary "
        "ELSE jobs.summary END, "
        "summary_source_hash=CASE WHEN excluded.summary_source_hash IS NOT NULL "
        "THEN excluded.summary_source_hash ELSE jobs.summary_source_hash END, "
        "summary_model=CASE WHEN excluded.summary_model IS NOT NULL "
        "THEN excluded.summary_model ELSE jobs.summary_model END, "
        "summary_generated_at=CASE WHEN excluded.summary_generated_at IS NOT NULL "
        "THEN excluded.summary_generated_at ELSE jobs.summary_generated_at END, "
        "workplace_type=CASE WHEN excluded.workplace_type IS NOT NULL "
        "THEN excluded.workplace_type ELSE jobs.workplace_type END, "
        "pay_min=CASE WHEN excluded.pay_min IS NOT NULL "
        "THEN excluded.pay_min ELSE jobs.pay_min END, "
        "pay_max=CASE WHEN excluded.pay_max IS NOT NULL "
        "THEN excluded.pay_max ELSE jobs.pay_max END, "
        "pay_currency=CASE WHEN excluded.pay_currency IS NOT NULL "
        "THEN excluded.pay_currency ELSE jobs.pay_currency END, "
        "experience_level=CASE WHEN excluded.experience_level IS NOT NULL "
        "THEN excluded.experience_level ELSE jobs.experience_level END, "
        "job_type=CASE WHEN excluded.job_type IS NOT NULL "
        "THEN excluded.job_type ELSE jobs.job_type END, "
        "metadata_derived_at=CASE WHEN excluded.metadata_derived_at IS NOT NULL "
        "THEN excluded.metadata_derived_at ELSE jobs.metadata_derived_at END, "
        # Geo columns use the same first-write-wins semantics as the other
        # derived columns: once a row has been geocoded, a re-scraped job
        # without geo fields should NOT blank out the existing values. The
        # backfill script is the only path that ever overwrites these.
        "geo_country_code=CASE WHEN excluded.geo_country_code IS NOT NULL "
        "THEN excluded.geo_country_code ELSE jobs.geo_country_code END, "
        "geo_city=CASE WHEN excluded.geo_city IS NOT NULL "
        "THEN excluded.geo_city ELSE jobs.geo_city END, "
        "geo_region=CASE WHEN excluded.geo_region IS NOT NULL "
        "THEN excluded.geo_region ELSE jobs.geo_region END, "
        "geo_lat=CASE WHEN excluded.geo_lat IS NOT NULL "
        "THEN excluded.geo_lat ELSE jobs.geo_lat END, "
        "geo_lon=CASE WHEN excluded.geo_lon IS NOT NULL "
        "THEN excluded.geo_lon ELSE jobs.geo_lon END, "
        "geo_confidence=CASE WHEN excluded.geo_confidence IS NOT NULL "
        "THEN excluded.geo_confidence ELSE jobs.geo_confidence END, "
        "geo_source=CASE WHEN excluded.geo_source IS NOT NULL "
        "THEN excluded.geo_source ELSE jobs.geo_source END, "
        "geocoded_at=CASE WHEN excluded.geocoded_at IS NOT NULL "
        "THEN excluded.geocoded_at ELSE jobs.geocoded_at END"
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
                job.get("summary"),
                job.get("summary_source_hash"),
                job.get("summary_model"),
                job.get("summary_generated_at"),
                job.get("workplace_type"),
                job.get("pay_min"),
                job.get("pay_max"),
                job.get("pay_currency"),
                job.get("experience_level"),
                job.get("job_type"),
                job.get("metadata_derived_at"),
                job.get("geo_country_code"),
                job.get("geo_city"),
                job.get("geo_region"),
                job.get("geo_lat"),
                job.get("geo_lon"),
                job.get("geo_confidence"),
                job.get("geo_source"),
                job.get("geocoded_at"),
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
# Geocode cache (services/geo.py)
# -----------------------------------------------------------------------------
# Permanent cache, keyed by hash of the normalized location string. Lookups
# hit the primary key (single-row read), writes are upserts. The cache table
# is created lazily by init_schema() so it is always present by the time a
# geocoding call happens.
GEOCODE_CACHE_COLUMNS = (
    "geo_country_code", "geo_city", "geo_region",
    "geo_lat", "geo_lon", "geo_confidence", "geo_source", "geocoded_at",
)


# In-memory cache of the geo_cities dataset, loaded from the
# data-cache branch on first read. The structure is:
#   _geo_cities_cache: dict[str, list[dict]] mapping name_lower ->
#   list of city records, sorted by population DESC.
_geo_cities_cache = None
_geo_cities_load_error = None
_geo_cities_loaded = False
_geo_cities_lock = threading.Lock()


def _load_geo_cities_from_github():
    """Fetch the gzipped geo_cities JSON from the data-cache branch."""
    if not GITHUB_REPO_OWNER or not GITHUB_REPO_NAME:
        return None
    api_url = (
        f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}"
        f"/git/ref/heads/{EMBEDDINGS_BRANCH_REF}"
    )
    try:
        with httpx.Client(timeout=EMBEDDINGS_FETCH_TIMEOUT_SECONDS,
                          follow_redirects=True) as client:
            resp = client.get(
                api_url,
                headers={"Accept": "application/vnd.github+json"},
            )
            if resp.status_code == 404:
                print(
                    f"[geo_cities] branch {EMBEDDINGS_BRANCH_REF!r} not "
                    f"found on {GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME} "
                    f"(404). Has build_geonames_cache been run yet?"
                )
                return None
            resp.raise_for_status()
            sha = resp.json()["object"]["sha"]
            base = (
                f"https://raw.githubusercontent.com/{GITHUB_REPO_OWNER}/"
                f"{GITHUB_REPO_NAME}/{sha}/data/geo_cities"
            )
            file_resp = client.get(f"{base}/cities.json.gz")
            file_resp.raise_for_status()
    except Exception as exc:
        print(
            f"[geo_cities] data-cache fetch failed "
            f"({type(exc).__name__}): {exc}"
        )
        return None
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(file_resp.content)) as gz:
            raw = gz.read()
        records = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        print(
            f"[geo_cities] failed to parse gzipped JSON "
            f"({type(exc).__name__}): {exc}"
        )
        return None
    by_name = {}
    for r in records:
        nl = r.get("name_lower")
        if not nl:
            continue
        by_name.setdefault(nl, []).append({
            "country_code": r.get("country_code"),
            "admin1": r.get("admin1") or "",
            "lat": r.get("lat"),
            "lon": r.get("lon"),
            "population": r.get("population") or 0,
        })
    print(f"[geo_cities] loaded {len(records)} records "
          f"({len(by_name)} unique names) from data-cache")
    return by_name


def _load_geo_cities_from_local():
    """Load the gzipped JSON from a local file path. Used in tests."""
    from app.services.git_data_cache import GEO_CITIES_REL_PATH
    local_dir = pathlib.Path(EMBEDDINGS_LOCAL_PATH)
    file_path = local_dir / pathlib.Path(GEO_CITIES_REL_PATH).name
    if not file_path.exists():
        return None
    try:
        with gzip.GzipFile(file_path, "rb") as gz:
            raw = gz.read()
        records = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        print(f"[geo_cities] local load failed: {exc}")
        return None
    by_name = {}
    for r in records:
        nl = r.get("name_lower")
        if not nl:
            continue
        by_name.setdefault(nl, []).append({
            "country_code": r.get("country_code"),
            "admin1": r.get("admin1") or "",
            "lat": r.get("lat"),
            "lon": r.get("lon"),
            "population": r.get("population") or 0,
        })
    return by_name


def _get_geo_cities_cache():
    """Lazy-load the in-memory geo_cities dict, once per process."""
    global _geo_cities_cache, _geo_cities_loaded, _geo_cities_load_error
    if _geo_cities_loaded:
        return _geo_cities_cache
    with _geo_cities_lock:
        if _geo_cities_loaded:
            return _geo_cities_cache
        source = EMBEDDINGS_SOURCE.lower()
        cache = None
        if source == "github":
            cache = _load_geo_cities_from_github()
        elif source == "local":
            cache = _load_geo_cities_from_local()
        if cache is None and source != "turso":
            if source == "github":
                cache = _load_geo_cities_from_local()
            elif source == "local":
                cache = _load_geo_cities_from_github()
        if cache is None:
            _geo_cities_load_error = (
                f"data-cache unavailable (source={source!r}); "
                f"falling back to Turso SQL"
            )
            print(f"[geo_cities] {_geo_cities_load_error}")
        _geo_cities_cache = cache
        _geo_cities_loaded = True
        return cache


def _lookup_geo_cities_sql(name_lower):
    """SQL fallback. Used only when the data-cache is unavailable."""
    try:
        conn = get_client()
        cursor = conn.execute(
            "SELECT country_code, admin1, lat, lon, population "
            "FROM geo_cities WHERE name_lower = ? "
            "ORDER BY population DESC",
            [name_lower],
        )
    except Exception as exc:
        print(f"[geo_cities] SQL read failed ({type(exc).__name__}): {exc}")
        return []
    return [
        {
            "country_code": row[0],
            "admin1": row[1],
            "lat": row[2],
            "lon": row[3],
            "population": row[4],
        }
        for row in cursor.fetchall()
    ]


def lookup_geo_cities(name_lower):
    """Return all cities matching ``name_lower``.

    Primary path: in-memory dict loaded from the data-cache branch.
    Fallback path: SQL against the geo_cities table in Turso.
    """
    if not name_lower:
        return []
    cache = _get_geo_cities_cache()
    if cache is not None:
        return cache.get(name_lower, [])
    return _lookup_geo_cities_sql(name_lower)


def upsert_geo_cities_batch(rows: list[dict]) -> int:
    """Bulk insert into geo_cities. ON CONFLICT replaces existing rows.

    Used by the one-time build script. ``rows`` is a list of dicts with
    keys: name_lower, country_code, admin1, lat, lon, population.

    Performance note: a single multi-row INSERT with 500 value groups
    is ~16x faster than 500 individual executes against libSQL's Hrana
    transport. We use the multi-row form here.

    Resilience: the build script inserts 193k rows in 387 batches. Turso's
    HTTP transport occasionally drops the connection mid-batch with
    "Connection reset by peer." When that happens we reconnect and retry
    the failed batch, so a transient network blip doesn't lose the whole
    run.
    """
    if not rows:
        return 0
    BATCH_SIZE = 500
    sent = 0
    for i in range(0, len(rows), BATCH_SIZE):
        chunk = rows[i:i + BATCH_SIZE]
        # Build a single multi-row INSERT. 500 rows × 6 params = 3000
        # placeholders, ~24KB SQL — well under the 1MB Hrana limit.
        placeholders = ",".join(["(?, ?, ?, ?, ?, ?)"] * len(chunk))
        sql = (
            "INSERT INTO geo_cities "
            "(name_lower, country_code, admin1, lat, lon, population) "
            f"VALUES {placeholders} "
            "ON CONFLICT(name_lower, country_code, admin1) DO UPDATE SET "
            "lat=excluded.lat, lon=excluded.lon, population=excluded.population"
        )
        flat: list = []
        for row in chunk:
            flat.append(row.get("name_lower"))
            flat.append(row.get("country_code"))
            flat.append(row.get("admin1") or "")
            flat.append(row.get("lat"))
            flat.append(row.get("lon"))
            flat.append(row.get("population") or 0)
        # Retry loop: on connection reset, reconnect and try again.
        # On any other exception, propagate — we don't want to silently
        # skip bad data.
        for attempt in range(3):
            try:
                conn = get_client()
                conn.execute(sql, flat)
                conn.commit()
                sent += len(chunk)
                break
            except Exception as exc:
                err_str = str(exc).lower()
                is_transient = (
                    "connection reset" in err_str
                    or "connection error" in err_str
                    or "timeout" in err_str
                    or "remote disconnected" in err_str
                    or "broken pipe" in err_str
                )
                if not is_transient or attempt == 2:
                    raise
                print(
                    f"[upsert_geo_cities_batch] transient error on batch "
                    f"{i // BATCH_SIZE + 1}, retrying: {exc}"
                )
                # Force a fresh connection on the next attempt.
                close()
    return sent


def count_geo_cities() -> int:
    """Return the row count of geo_cities. Used by the build script to
    confirm the table is populated."""
    try:
        conn = get_client()
        cursor = conn.execute("SELECT COUNT(*) FROM geo_cities")
        return int(cursor.fetchone()[0] or 0)
    except Exception:
        return 0


def get_cached_geocode(location_key: str) -> dict | None:
    """Return the cached geocode result for a normalized location key.

    Returns None if the key is missing or the cache table is unreadable. The
    geocoding path treats None as "not cached, go to Photon."
    """
    if not location_key:
        return None
    try:
        conn = get_client()
        cursor = conn.execute(
            "SELECT geo_country_code, geo_city, geo_region, geo_lat, geo_lon, "
            "geo_confidence, geo_source, geocoded_at FROM geocode_cache "
            "WHERE location_key = ?",
            [location_key],
        )
    except Exception as exc:
        # Cache table missing or transient read failure — treat as miss.
        print(f"[geocode_cache] read failed ({type(exc).__name__}): {exc}")
        return None
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "geo_country_code": row[0],
        "geo_city": row[1],
        "geo_region": row[2],
        "geo_lat": row[3],
        "geo_lon": row[4],
        "geo_confidence": row[5],
        "geo_source": row[6],
        "geocoded_at": row[7],
    }


def set_cached_geocode(location_key: str, location_raw: str, result: dict) -> None:
    """Write-through upsert a geocode result. Exceptions are logged, not raised.

    The cache is a write-through accelerator, not a source of truth — callers
    always accept the result regardless of whether the write succeeded. The
    `geocoded_at` is set by the caller's clock (UTC ISO) so the cache column
    reflects when the geocoding actually happened.
    """
    if not location_key:
        return
    try:
        conn = get_client()
        conn.execute(
            "INSERT INTO geocode_cache "
            "(location_key, location_raw, geo_country_code, geo_city, geo_region, "
            "geo_lat, geo_lon, geo_confidence, geo_source, geocoded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(location_key) DO UPDATE SET "
            "location_raw=excluded.location_raw, "
            "geo_country_code=excluded.geo_country_code, "
            "geo_city=excluded.geo_city, "
            "geo_region=excluded.geo_region, "
            "geo_lat=excluded.geo_lat, "
            "geo_lon=excluded.geo_lon, "
            "geo_confidence=excluded.geo_confidence, "
            "geo_source=excluded.geo_source, "
            "geocoded_at=excluded.geocoded_at",
            [
                location_key,
                location_raw,
                result.get("geo_country_code"),
                result.get("geo_city"),
                result.get("geo_region"),
                result.get("geo_lat"),
                result.get("geo_lon"),
                result.get("geo_confidence"),
                result.get("geo_source"),
                result.get("geocoded_at"),
            ],
        )
        conn.commit()
    except Exception as exc:
        print(f"[geocode_cache] write failed ({type(exc).__name__}): {exc}")


def _experience_level_filter_sql(levels: list[str]) -> tuple[str, list[Any]]:
    from app.services.job_metadata import experience_level_filter_sql

    return experience_level_filter_sql(levels)


def _job_type_filter_sql(types: list[str]) -> tuple[str, list[Any]]:
    from app.services.job_metadata import job_type_filter_sql

    return job_type_filter_sql(types)


def _workplace_type_filter_sql(types: list[str]) -> tuple[str, list[Any]]:
    from app.services.job_metadata import workplace_type_filter_sql

    return workplace_type_filter_sql(types)


def _build_search_where(
    *,
    keywords: str = "",
    locations: list[str] | None = None,
    experience_levels: list[str] | None = None,
    job_types: list[str] | None = None,
    workplace_types: list[str] | None = None,
    pay_min: int | None = None,
    pay_max: int | None = None,
    date_posted: str = "any",
) -> tuple[str, list[Any], list[str]]:
    """Return (WHERE clause, params, keyword terms) for browse search."""
    conditions = ["1=1"]
    params: list[Any] = []
    haystack = (
        "LOWER(COALESCE(title, '') || ' ' || COALESCE(company, '') || ' ' "
        "|| COALESCE(description, ''))"
    )

    terms = [term for term in keywords.strip().lower().split() if term]
    for term in terms:
        conditions.append(f"{haystack} LIKE ?")
        params.append(f"%{term}%")

    if locations:
        loc_parts = []
        for location in locations:
            loc_parts.append("LOWER(COALESCE(location, '')) LIKE ?")
            params.append(f"%{location.lower()}%")
        conditions.append(f"({' OR '.join(loc_parts)})")

    if experience_levels:
        fragment, level_params = _experience_level_filter_sql(experience_levels)
        conditions.append(fragment)
        params.extend(level_params)

    if job_types:
        fragment, type_params = _job_type_filter_sql(job_types)
        conditions.append(fragment)
        params.extend(type_params)

    if workplace_types:
        fragment, workplace_params = _workplace_type_filter_sql(workplace_types)
        conditions.append(fragment)
        params.extend(workplace_params)

    if pay_min is not None:
        conditions.append("pay_max >= ?")
        params.append(pay_min)
    if pay_max is not None:
        conditions.append("pay_min <= ?")
        params.append(pay_max)

    if date_posted != "any" and date_posted in DATE_POSTED_WINDOW_DAYS:
        days = DATE_POSTED_WINDOW_DAYS[date_posted]
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()
        conditions.append("posted_at >= ?")
        params.append(cutoff)

    return " AND ".join(conditions), params, terms


def _build_search_order(
    *,
    sort: str,
    terms: list[str],
    haystack: str,
) -> tuple[str, list[Any]]:
    """Return (ORDER BY clause, extra params for relevance scoring)."""
    if sort == "newest" or (sort == "relevance" and not terms):
        return (
            "CASE WHEN posted_at IS NULL THEN 0 ELSE 1 END DESC, posted_at DESC",
            [],
        )

    score_parts: list[str] = []
    order_params: list[Any] = []
    for term in terms:
        pattern = f"%{term}%"
        score_parts.append(
            "(CASE WHEN LOWER(COALESCE(title, '')) LIKE ? THEN 3 ELSE 0 END)"
        )
        order_params.append(pattern)
        score_parts.append(
            "(CASE WHEN LOWER(COALESCE(company, '')) LIKE ? THEN 2 ELSE 0 END)"
        )
        order_params.append(pattern)
        score_parts.append(f"(CASE WHEN {haystack} LIKE ? THEN 1 ELSE 0 END)")
        order_params.append(pattern)

    relevance_expr = " + ".join(score_parts) if score_parts else "0"
    return (
        f"({relevance_expr}) DESC, "
        "CASE WHEN posted_at IS NULL THEN 0 ELSE 1 END DESC, posted_at DESC",
        order_params,
    )


def search_jobs(
    *,
    keywords: str = "",
    locations: list[str] | None = None,
    experience_levels: list[str] | None = None,
    job_types: list[str] | None = None,
    workplace_types: list[str] | None = None,
    pay_min: int | None = None,
    pay_max: int | None = None,
    date_posted: str = "any",
    sort: str = "relevance",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """Browse/search jobs with filters. Returns (rows, total_count)."""
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    offset = (page - 1) * page_size

    where, params, terms = _build_search_where(
        keywords=keywords,
        locations=locations,
        experience_levels=experience_levels,
        job_types=job_types,
        workplace_types=workplace_types,
        pay_min=pay_min,
        pay_max=pay_max,
        date_posted=date_posted,
    )
    haystack = (
        "LOWER(COALESCE(title, '') || ' ' || COALESCE(company, '') || ' ' "
        "|| COALESCE(description, ''))"
    )
    order_by, order_params = _build_search_order(
        sort=sort, terms=terms, haystack=haystack
    )

    conn = get_client()
    count_cursor = conn.execute(
        f"SELECT COUNT(*) FROM jobs WHERE {where}", params
    )
    total = int(count_cursor.fetchone()[0])

    select_params = [*params, *order_params, page_size, offset]
    cursor = conn.execute(
        f"SELECT {BROWSE_LIST_COLUMNS} FROM jobs WHERE {where} "
        f"ORDER BY {order_by} LIMIT ? OFFSET ?",
        select_params,
    )
    return _fetchall_dicts(cursor), total


def update_job_summary(
    job_id: str,
    *,
    summary: str,
    source_hash: str,
    model: str,
    generated_at: str,
) -> None:
    conn = get_client()
    conn.execute(
        "UPDATE jobs SET summary = ?, summary_source_hash = ?, "
        "summary_model = ?, summary_generated_at = ? "
        "WHERE id = ? AND (summary_source_hash IS NULL OR summary_source_hash = ?)",
        [summary, source_hash, model, generated_at, job_id, source_hash],
    )
    conn.commit()


def batch_update_job_summaries(updates: list[tuple[str, dict]]) -> None:
    """Update generated summaries for many jobs with a single commit."""
    if not updates:
        return
    conn = get_client()
    sql = (
        "UPDATE jobs SET summary = ?, summary_source_hash = ?, "
        "summary_model = ?, summary_generated_at = ? "
        "WHERE id = ? AND (summary_source_hash IS NULL OR summary_source_hash = ?)"
    )
    for job_id, summary_data in updates:
        source_hash = summary_data["source_hash"]
        conn.execute(
            sql,
            [
                summary_data["summary"],
                source_hash,
                summary_data["model"],
                summary_data["generated_at"],
                job_id,
                source_hash,
            ],
        )
    conn.commit()


def fetch_job_text(job_ids: list[str]) -> list[dict]:
    """Return title/location/description text for browse-row enrichment."""
    if not job_ids:
        return []
    conn = get_client()
    placeholders = ",".join(["?"] * len(job_ids))
    cursor = conn.execute(
        "SELECT id, title, company, location, description "
        f"FROM jobs WHERE id IN ({placeholders})",
        list(job_ids),
    )
    return _fetchall_dicts(cursor)


def fetch_jobs_for_metadata_backfill(*, limit: int = 100) -> list[dict]:
    conn = get_client()
    cursor = conn.execute(
        "SELECT id, title, location, description FROM jobs "
        "WHERE metadata_derived_at IS NULL LIMIT ?",
        [limit],
    )
    return _fetchall_dicts(cursor)


def fetch_jobs_for_summary_backfill(
    *, limit: int = 100, exclude_ids: list[str] | None = None
) -> list[dict]:
    conn = get_client()
    conditions = [
        "(summary IS NULL OR summary = '')",
        "description IS NOT NULL",
    ]
    params: list[Any] = []
    if exclude_ids:
        placeholders = ",".join(["?"] * len(exclude_ids))
        conditions.append(f"id NOT IN ({placeholders})")
        params.extend(exclude_ids)
    params.append(limit)
    cursor = conn.execute(
        "SELECT id, title, company, description FROM jobs "
        f"WHERE {' AND '.join(conditions)} LIMIT ?",
        params,
    )
    return _fetchall_dicts(cursor)


def update_job_metadata(job_id: str, metadata: dict) -> None:
    conn = get_client()
    conn.execute(
        "UPDATE jobs SET workplace_type = ?, pay_min = ?, pay_max = ?, "
        "pay_currency = ?, experience_level = ?, job_type = ?, "
        "metadata_derived_at = ? WHERE id = ?",
        [
            metadata.get("workplace_type"),
            metadata.get("pay_min"),
            metadata.get("pay_max"),
            metadata.get("pay_currency"),
            metadata.get("experience_level"),
            metadata.get("job_type"),
            metadata.get("metadata_derived_at"),
            job_id,
        ],
    )
    conn.commit()


def batch_update_job_metadata(updates: list[tuple[str, dict]]) -> None:
    """Update browse metadata for many jobs in one transaction."""
    if not updates:
        return
    conn = get_client()
    sql = (
        "UPDATE jobs SET workplace_type = ?, pay_min = ?, pay_max = ?, "
        "pay_currency = ?, experience_level = ?, job_type = ?, "
        "metadata_derived_at = ? WHERE id = ?"
    )
    for job_id, metadata in updates:
        conn.execute(
            sql,
            [
                metadata.get("workplace_type"),
                metadata.get("pay_min"),
                metadata.get("pay_max"),
                metadata.get("pay_currency"),
                metadata.get("experience_level"),
                metadata.get("job_type"),
                metadata.get("metadata_derived_at"),
                job_id,
            ],
        )
    conn.commit()


# -----------------------------------------------------------------------------
# Geolocation backfill helpers
# -----------------------------------------------------------------------------
# Mirrors the metadata-backfill pattern: the backfill script fetches rows
# that are still missing geo, calls geocode_job_location() per row, and
# writes the result back in a single batched UPDATE. The pipeline also
# calls these helpers on every new row before the upsert goes through.
JOB_GEO_COLUMNS = (
    "geo_country_code", "geo_city", "geo_region",
    "geo_lat", "geo_lon", "geo_confidence", "geo_source", "geocoded_at",
)


def fetch_jobs_for_geo_backfill(*, limit: int = 100) -> list[dict]:
    """Return jobs that have a location but have never been geocoded.

    The gate is ``geocoded_at IS NULL`` — not ``geo_country_code IS NULL`` —
    because we want to skip macro/unresolved rows on subsequent runs too.
    Without this, a row resolving to "Remote" would be re-fetched every
    iteration of the backfill loop forever, since the macro path always
    leaves geo_country_code NULL. The backfill only runs once per cluster,
    but the seed/install path can be re-invoked to retry a Photon outage
    without re-doing the unresolved work.
    """
    conn = get_client()
    cursor = conn.execute(
        "SELECT id, location FROM jobs "
        "WHERE location IS NOT NULL AND trim(location) != '' "
        "AND geocoded_at IS NULL LIMIT ?",
        [limit],
    )
    return _fetchall_dicts(cursor)


def update_job_geo(job_id: str, geo: dict) -> None:
    """Write the geo_* columns for a single job. ``id`` is the Turso UUID."""
    conn = get_client()
    conn.execute(
        "UPDATE jobs SET geo_country_code = ?, geo_city = ?, geo_region = ?, "
        "geo_lat = ?, geo_lon = ?, geo_confidence = ?, geo_source = ?, "
        "geocoded_at = ? WHERE id = ?",
        [
            geo.get("geo_country_code"),
            geo.get("geo_city"),
            geo.get("geo_region"),
            geo.get("geo_lat"),
            geo.get("geo_lon"),
            geo.get("geo_confidence"),
            geo.get("geo_source"),
            geo.get("geocoded_at"),
            job_id,
        ],
    )
    conn.commit()


def batch_update_job_geo(updates: list[tuple[str, dict]]) -> None:
    """Batched version of update_job_geo. One transaction, N rows."""
    if not updates:
        return
    conn = get_client()
    sql = (
        "UPDATE jobs SET geo_country_code = ?, geo_city = ?, geo_region = ?, "
        "geo_lat = ?, geo_lon = ?, geo_confidence = ?, geo_source = ?, "
        "geocoded_at = ? WHERE id = ?"
    )
    for job_id, geo in updates:
        conn.execute(
            sql,
            [
                geo.get("geo_country_code"),
                geo.get("geo_city"),
                geo.get("geo_region"),
                geo.get("geo_lat"),
                geo.get("geo_lon"),
                geo.get("geo_confidence"),
                geo.get("geo_source"),
                geo.get("geocoded_at"),
                job_id,
            ],
        )
    conn.commit()


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

def _fetch_ids_by_country_codes(country_codes: set[str]) -> set[str]:
    """Return the set of job ids whose geo_country_code is in `country_codes`.

    Cheap id-only SELECT, uses idx_jobs_geo_country_code. Used to restrict
    the in-memory embedding matrix to a geographically relevant subset
    before running cosine similarity.
    """
    if not country_codes:
        return set()
    conn = get_client()
    placeholders = ",".join(["?"] * len(country_codes))
    cursor = conn.execute(
        f"SELECT id FROM jobs WHERE geo_country_code IN ({placeholders})",
        list(country_codes),
    )
    return {str(row[0]) for row in cursor.fetchall()}


def vector_search_filtered(
    query_embedding: list[float], *, limit: int, country_codes: set[str]
) -> list[dict]:
    """Same contract as vector_search, but restricted to jobs whose
    geo_country_code is in `country_codes`.

    Retrieval in vector_search is pure text similarity across the whole
    corpus — it has no awareness of geography. That means a user's
    preferred country only ever acts as a *re-ranking* signal on whichever
    jobs happened to win on similarity against the full corpus, which can
    starve out a real, well-matched local job (e.g. Seattle/Twitch) if
    other regions' postings are more numerous or more keyword-dense.

    This runs the identical fast-path matmul, just over a pre-filtered
    subset of the (matrix, ids) artifact, so the user's chosen country
    is guaranteed a fair shot at retrieval instead of only surviving on
    global similarity rank.

    Falls back to an empty list (not the legacy per-row scan) if the
    fast-path matrix is unavailable — the caller already has a full,
    unfiltered vector_search result to merge with, so a filtered-empty
    result here just means "no extra local candidates found," not
    "retrieval broke."
    """
    if not country_codes:
        return []
    cached = _get_matrix_and_ids()
    if cached is None:
        return []
    matrix, ids = cached

    allowed_ids = _fetch_ids_by_country_codes(country_codes)
    if not allowed_ids:
        return []

    keep_indices = [i for i, job_id in enumerate(ids) if job_id in allowed_ids]
    if not keep_indices:
        return []

    sub_matrix = matrix[keep_indices]
    sub_ids = [ids[i] for i in keep_indices]

    from app.services.embedding_matrix import top_k_ids
    top = top_k_ids(sub_matrix, sub_ids, query_embedding, limit)
    if not top:
        return []

    top_ids = [job_id for job_id, _ in top]
    meta_by_id = _fetch_metadata_for_ids(top_ids)
    out: list[dict] = []
    for job_id, sim in top:
        meta = meta_by_id.get(job_id)
        if not meta:
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
    """Return `{job_id: {id, title, company, location, apply_url, description, posted_at, geo_*}}`
    for the given ids. Preserves the dict-by-id shape that
    `routes/resumes.py.fetch_full_jobs` already used to return, plus the
    geo_* columns so the read path can compare against user preferences
    without a second round-trip.
    """
    if not job_ids:
        return {}
    conn = get_client()
    placeholders = ",".join(["?"] * len(job_ids))
    sql = (
        "SELECT id, title, company, location, apply_url, description, posted_at, "
        "geo_country_code, geo_city, geo_region, geo_lat, geo_lon, "
        "geo_confidence, geo_source, geocoded_at "
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
            "geo_country_code": row[7],
            "geo_city": row[8],
            "geo_region": row[9],
            "geo_lat": row[10],
            "geo_lon": row[11],
            "geo_confidence": row[12],
            "geo_source": row[13],
            "geocoded_at": row[14],
        }
        for row in cursor.fetchall()
    }


__all__ = [
    "init_schema",
    "fetch_existing_external_ids",
    "upsert_jobs",
    "update_last_seen",
    "purge_older_than",
    "search_jobs",
    "update_job_summary",
    "batch_update_job_summaries",
    "fetch_job_text",
    "fetch_jobs_for_metadata_backfill",
    "fetch_jobs_for_summary_backfill",
    "fetch_jobs_for_geo_backfill",
    "update_job_metadata",
    "batch_update_job_metadata",
    "update_job_geo",
    "batch_update_job_geo",
    "JOB_GEO_COLUMNS",
    "lookup_geo_cities",
    "upsert_geo_cities_batch",
    "count_geo_cities",
    "vector_search",
    "vector_search_filtered",
    "fetch_full_jobs",
    "close",
    "get_client",
]
