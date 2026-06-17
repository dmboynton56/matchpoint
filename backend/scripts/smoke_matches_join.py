"""End-to-end test of the cross-database join path used in routes/matches.py.

We stub out the supabase client to return a synthetic job_matches response,
then verify the merged result matches the contract the frontend expects.
"""
import math
import os
import sys

os.environ["TURSO_DATABASE_URL"] = ":memory:"
os.environ["TURSO_AUTH_TOKEN"] = ""

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

# Stub the supabase client BEFORE importing routes
class _FakeQuery:
    def __init__(self, table, rows, *, order_desc=False):
        self._table = table
        self._rows = rows
        self._order_desc = order_desc
        self._filters = {}
    def eq(self, col, val):
        self._filters[col] = val
        return self
    def in_(self, col, vals):
        self._filters[col] = set(vals)
        return self
    def order(self, col, desc=False):
        self._order_desc = desc
        return self
    def execute(self):
        def matches_filters(row):
            for key, value in self._filters.items():
                if isinstance(value, set):
                    if row.get(key) not in value:
                        return False
                elif row.get(key) != value:
                    return False
            return True

        rows = [r for r in self._rows if matches_filters(r)]
        if self._order_desc:
            rows = sorted(rows, key=lambda r: r.get("match_score") or 0, reverse=True)
        return type("R", (), {"data": rows})()

class _FakeTable:
    def __init__(self, name, rows):
        self._name = name
        self._rows = rows
    def select(self, _cols, **kwargs):
        return _FakeQuery(self._name, self._rows)
    def update(self, _vals):
        return _FakeQuery(self._name, self._rows)
    def delete(self):
        return _FakeQuery(self._name, self._rows)

class _FakeSupabaseClient:
    def __init__(self, tables):
        self._tables = tables
    def table(self, name):
        return _FakeTable(name, self._tables[name])

# Synthetic job_matches rows
SYNTH_MATCHES = [
    {
        "id": "match-1",
        "job_id": "11111111-2222-4333-8444-555555555555",
        "user_id": "user-1",
        "match_score": 0.92,
        "is_viewed": False,
        "is_favorited": True,
        "is_applied": False,
        "created_at": "2026-06-10T00:00:00Z",
        "match_notes": [{"text": "Great match", "is_warning": False}],
        "match_highlights": ["Python", "Backend"],
        "match_concerns": [],
        "interview_likelihood": 0.8,
        "skills_fit": 0.9,
        "experience_fit": 0.85,
        "seniority_fit": 0.9,
        "location_fit": 0.7,
        "pay_fit": 0.8,
        "role_fit": 0.9,
        "preference_fit": 0.85,
        "location_reason": None,
        "location_evidence": None,
        "pay_reason": None,
        "pay_evidence": None,
        "role_reason": None,
        "role_evidence": None,
        "job_facts": None,
    },
    {
        "id": "match-2",
        "job_id": "99999999-8888-4777-8666-555555555555",
        "user_id": "user-1",
        "match_score": 0.75,
        "is_viewed": True,
        "is_favorited": False,
        "is_applied": False,
        "created_at": "2026-06-09T00:00:00Z",
        "match_notes": [{"text": "OK match", "is_warning": False}],
        "match_highlights": ["ML"],
        "match_concerns": ["Junior role"],
        "interview_likelihood": 0.6,
        "skills_fit": 0.7,
        "experience_fit": 0.6,
        "seniority_fit": 0.7,
        "location_fit": 0.5,
        "pay_fit": 0.6,
        "role_fit": 0.8,
        "preference_fit": 0.7,
        "location_reason": None,
        "location_evidence": None,
        "pay_reason": None,
        "pay_evidence": None,
        "role_reason": None,
        "role_evidence": None,
        "job_facts": None,
    },
]

# Insert matching jobs into turso
import app.db.turso as turso
# Reset the in-memory client from any previous test run so we start clean.
turso.close()
turso.init_schema()
v1 = [1.0] + [0.0] * 1535
v2 = [0.0, 1.0] + [0.0] * 1534
turso.upsert_jobs([
    {
        "external_id": "ext-1",
        "company": "Stripe",
        "title": "Senior Python Engineer",
        "description": "long description...",
        "location": "Remote",
        "posted_at": "2026-06-08T00:00:00+00:00",
        "apply_url": "https://stripe.com/jobs/1",
        "embedding": v1,
        "last_seen_at": "2026-06-10T00:00:00+00:00",
    },
    {
        "external_id": "ext-2",
        "company": "Datadog",
        "title": "ML Engineer",
        "description": "another description",
        "location": "NYC",
        "posted_at": "2026-06-07T00:00:00+00:00",
        "apply_url": "https://datadog.com/jobs/2",
        "embedding": v2,
        "last_seen_at": "2026-06-10T00:00:00+00:00",
    },
])

# Read the assigned ids and inject them into the synthetic match rows
ids = sorted(
    r[0] for r in turso.get_client().execute("SELECT id FROM jobs").fetchall()
)
# match-1 is the higher score -> should rank first; pair it with whichever
# job has the bigger id (or just assign in order — _format_match doesn't care)
SYNTH_MATCHES[0]["job_id"] = ids[0]
SYNTH_MATCHES[1]["job_id"] = ids[1]

# Now run the matches route logic
import app.db.database as db_module
import app.routes.matches as matches_route
# The matches route did `from app.db.database import supabase` at import
# time, so its module-level `supabase` is its OWN binding. Patch both.
db_module.supabase = _FakeSupabaseClient({
    "job_matches": SYNTH_MATCHES,
    "user_saved_jobs": [],
})
matches_route.supabase = db_module.supabase

raw = matches_route._get_user_matches(
    user_id="user-1", viewed=None, favorited=None, applied=None
)
formatted = [matches_route._format_match(m) for m in raw]
assert len(formatted) == 2, formatted
# Sorted desc by match_score
assert formatted[0]["match_score"] == 0.92
assert formatted[1]["match_score"] == 0.75
# Hydrated job fields (look up by title rather than by id ordering, since
# the test's external_id -> uuid mapping depends on SQLite's generator).
titles_to_companies = {f["job"]["title"]: f["job"]["company"] for f in formatted}
assert "Senior Python Engineer" in titles_to_companies, titles_to_companies
assert "ML Engineer" in titles_to_companies, titles_to_companies
assert titles_to_companies["Senior Python Engineer"] == "Stripe"
assert titles_to_companies["ML Engineer"] == "Datadog"
# match_id is preserved on each formatted match
match_ids = {f["match_id"] for f in formatted}
assert match_ids == {"match-1", "match-2"}, match_ids
# The first job (sorted by score) should still expose the URL we inserted
first_job = formatted[0]["job"]
assert first_job["apply_url"] in {"https://stripe.com/jobs/1", "https://datadog.com/jobs/2"}, first_job
assert first_job["posted_at"] is not None
assert first_job["description"]
# is_favorited and is_applied propagate
fav = {f["match_id"]: f["is_favorited"] for f in formatted}
applied = {f["match_id"]: f["is_applied"] for f in formatted}
assert fav["match-1"] is True
assert fav["match-2"] is False
assert applied["match-1"] is False
assert applied["match-2"] is False
# And the job id is a string
assert isinstance(first_job["id"], str)
print("PASS  matches route hydrates jobs from turso and returns the same shape the frontend expects")
print(f"Sample formatted[0]: title={first_job['title']!r} company={first_job['company']!r} score={formatted[0]['match_score']}")
print(f"Sample formatted[1]: title={formatted[1]['job']['title']!r} company={formatted[1]['job']['company']!r} score={formatted[1]['match_score']}")

# Now also test the resume upload path's vector_search + fetch_full_jobs
results = turso.vector_search([1.0] + [0.0] * 1535, limit=5)
assert len(results) == 2
full = turso.fetch_full_jobs([r["id"] for r in results])
assert len(full) == 2
# The shape used in score_job_matches is the same:
for jid, j in full.items():
    for k in ("id", "title", "company", "location", "apply_url", "description"):
        assert k in j, f"missing {k} in {j}"
print("PASS  resume upload vector_search + fetch_full_jobs return the same shape score_job_matches needs")

print("\nALL CROSS-DB JOIN TESTS PASSED")
