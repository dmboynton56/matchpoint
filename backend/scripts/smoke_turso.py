"""End-to-end smoke test for backend/app/db/turso.py against an in-memory
libSQL instance. Verifies:
  - JOBS_SCHEMA_SQL applies idempotently
  - upsert_jobs / fetch_existing_external_ids round-trip
  - vector_search returns top-k by cosine similarity
  - fetch_full_jobs returns the expected shape with posted_at
  - update_last_seen and purge_older_than work
  - The user-provided UUID-v4 generator produces canonical UUID v4 strings
    that cast cleanly through PostgreSQL's (text)::uuid
"""
import math
import os
import sys
import uuid as _uuid

# Force in-memory mode + skip real env loading.
os.environ["TURSO_DATABASE_URL"] = ":memory:"
os.environ["TURSO_AUTH_TOKEN"] = ""
# Ensure we don't pick up a real .env
os.environ.setdefault("OPENAI_API_KEY", "fake-for-test")
os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:54321")
os.environ.setdefault("SUPABASE_SECRET_KEY", "fake-for-test")

# Make sure the backend package is importable
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # backend/ on path

import app.db.turso as turso  # noqa: E402

# ---------------------------------------------------------------------------
# 1) init_schema (idempotent)
# ---------------------------------------------------------------------------
turso.init_schema()
turso.init_schema()  # second call should be a no-op
print("PASS  init_schema idempotent")

# ---------------------------------------------------------------------------
# 2) Verify the user-provided UUID-v4 generator matches Python's uuid4
# ---------------------------------------------------------------------------
conn = turso.get_client()
# Generate 50 ids and ensure they all parse as canonical UUID v4
sample = conn.execute(
    "SELECT lower(hex(randomblob(4))) || '-' || "
    "lower(hex(randomblob(2))) || '-' || '4' || "
    "substr(lower(hex(randomblob(2))), 2) || '-' || "
    "substr('89ab', abs(random()) % 4 + 1, 1) || "
    "substr(lower(hex(randomblob(2))), 2) || '-' || "
    "lower(hex(randomblob(6)))"
).fetchall()
for row in sample:
    s = str(row[0])
    parsed = _uuid.UUID(s)  # raises if not canonical
    assert parsed.version == 4, f"not v4: {s}"
    assert str(parsed) == s, f"non-canonical: {s} vs {parsed}"
print(f"PASS  UUID-v4 generator produced {len(sample)} canonical v4 strings")

# ---------------------------------------------------------------------------
# 3) Insert three jobs and upsert one of them with new content
# ---------------------------------------------------------------------------
def make_job(ext, company, title, location, embedding):
    return {
        "external_id": ext,
        "company": company,
        "title": title,
        "description": f"desc for {title}",
        "location": location,
        "posted_at": "2026-06-10T00:00:00+00:00",
        "apply_url": f"https://example.com/{ext}",
        "embedding": embedding,
        "last_seen_at": "2026-06-10T00:00:00+00:00",
    }

# Orthogonal unit-ish vectors for deterministic ranking.
v_eng = [1.0] + [0.0] * 1535
v_data = [0.0, 1.0] + [0.0] * 1534
v_pm = [0.0, 0.0, 1.0] + [0.0] * 1533

sent = turso.upsert_jobs([
    make_job("ext-1", "Stripe", "Engineer", "Remote", v_eng),
    make_job("ext-2", "Datadog", "Data Scientist", "NYC", v_data),
    make_job("ext-3", "Figma", "Product Manager", "SF", v_pm),
])
assert sent == 3, sent
print(f"PASS  upsert_jobs inserted {sent} rows")

# Re-upsert ext-1 with different content -> row count stays the same, content updates
v_eng2 = [0.9, 0.1] + [0.0] * 1534
sent2 = turso.upsert_jobs([
    make_job("ext-1", "Stripe", "Senior Engineer (updated)", "Remote (updated)", v_eng2),
])
assert sent2 == 1, sent2
rows = conn.execute("SELECT COUNT(*) FROM jobs").fetchall()
assert rows[0][0] == 3, f"expected 3 rows after upsert, got {rows[0][0]}"
row = conn.execute("SELECT title, location FROM jobs WHERE external_id = ?", ["ext-1"]).fetchall()[0]
assert row[0] == "Senior Engineer (updated)", row
assert row[1] == "Remote (updated)", row
# And the id should be stable (NOT regenerated on conflict)
prev_id = conn.execute("SELECT id FROM jobs WHERE external_id = ?", ["ext-1"]).fetchall()[0][0]
# Re-upsert and ensure id unchanged
turso.upsert_jobs([make_job("ext-1", "Stripe", "Senior Engineer (v3)", "X", v_eng2)])
new_id = conn.execute("SELECT id FROM jobs WHERE external_id = ?", ["ext-1"]).fetchall()[0][0]
assert new_id == prev_id, f"id changed on re-upsert: {prev_id} -> {new_id}"
print("PASS  upsert updates content and preserves id")

# ---------------------------------------------------------------------------
# 4) fetch_existing_external_ids
# ---------------------------------------------------------------------------
ids = turso.fetch_existing_external_ids()
assert ids == {"ext-1", "ext-2", "ext-3"}, ids
print(f"PASS  fetch_existing_external_ids -> {sorted(ids)}")

# ---------------------------------------------------------------------------
# 5) vector_search returns top-k by cosine similarity
# ---------------------------------------------------------------------------
def unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]

# Query = nearly identical to v_eng, should rank ext-1 first.
q = unit([0.99, 0.01] + [0.0] * 1534)
results = turso.vector_search(q, limit=2)
assert len(results) == 2, results
assert results[0]["id"] == prev_id, f"expected ext-1 first, got {results[0]}"
assert results[1]["id"] != prev_id, f"ext-1 should be unique top-1, got {results[1]}"
# Cosine similarity should be close to 1 for the first result
assert results[0]["similarity"] > 0.99, results[0]
# And the second result should be lower
assert results[1]["similarity"] < results[0]["similarity"], results
# Shape matches the old `match_jobs` RPC response
expected_keys = {"id", "title", "company", "location", "apply_url", "similarity"}
assert expected_keys.issubset(results[0].keys()), results[0].keys()
print(f"PASS  vector_search top-1 = ext-1 (sim={results[0]['similarity']:.4f})")

# ---------------------------------------------------------------------------
# 6) fetch_full_jobs returns dict-by-id with posted_at
# ---------------------------------------------------------------------------
all_jobs = turso.fetch_full_jobs([str(r["id"]) for r in results])
assert len(all_jobs) == 2, all_jobs
for jid, job in all_jobs.items():
    assert job["id"] == jid
    assert {"id", "title", "company", "location", "apply_url", "description", "posted_at"}.issubset(job.keys()), job.keys()
    assert job["posted_at"] == "2026-06-10T00:00:00+00:00", job["posted_at"]
# Empty input -> empty dict
assert turso.fetch_full_jobs([]) == {}
print("PASS  fetch_full_jobs returns expected shape with posted_at")

# ---------------------------------------------------------------------------
# 7) update_last_seen + purge_older_than
# ---------------------------------------------------------------------------
# Backdate ext-2 to 30 days ago
old = "2026-05-01T00:00:00+00:00"
turso.update_last_seen(["ext-2"], old)
cutoff = "2026-06-01T00:00:00+00:00"
deleted = turso.purge_older_than(cutoff)
assert deleted == 1, f"expected 1 deleted, got {deleted}"
remaining = {r[0] for r in conn.execute("SELECT external_id FROM jobs").fetchall()}
assert remaining == {"ext-1", "ext-3"}, remaining
print(f"PASS  purge removed ext-2, remaining = {sorted(remaining)}")

# ---------------------------------------------------------------------------
# 8) Make sure the embedding TEXT column actually round-trips through JSON
#    (this protects against float precision issues from the libsql binding)
# ---------------------------------------------------------------------------
v = [0.1 * i for i in range(1536)]
turso.upsert_jobs([make_job("ext-vec", "TestCo", "Vector Round-Trip", "X", v)])
matches = turso.vector_search(v, limit=1)
assert matches[0]["id"]  # found it
assert abs(matches[0]["similarity"] - 1.0) < 1e-9, matches[0]["similarity"]
print("PASS  embedding round-trip is exact (similarity == 1.0)")

# ---------------------------------------------------------------------------
# 9) NULL embedding should be skipped by vector_search
# ---------------------------------------------------------------------------
turso.upsert_jobs([{
    "external_id": "ext-no-embed",
    "company": "NoCo",
    "title": "Null Embedding",
    "description": "no vec",
    "location": "?",
    "posted_at": None,
    "apply_url": None,
    "embedding": None,
    "last_seen_at": "2026-06-10T00:00:00+00:00",
}])
results = turso.vector_search(v, limit=10)
assert all(r["id"] != [r2[0] for r2 in conn.execute("SELECT id FROM jobs WHERE external_id='ext-no-embed'").fetchall()][0] for r in results), results
print("PASS  vector_search skips NULL embeddings")

print("\nALL TURSO SMOKE TESTS PASSED")
