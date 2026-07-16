"""Pin the whole test session to an in-memory Turso database.

Why this exists
---------------
`app.db.turso` snapshots `TURSO_DATABASE_URL` at import time. Before this
file existed, a full pytest run could import `app.main` (via
test_coach_flow_integration) before job-search tests set `":memory:"`.
New tests then ran `DELETE FROM jobs` against the real libsql:// URL from
backend/.env and wiped the shared jobs table.

This conftest runs before any test module is imported. It sets env vars,
sets MATCHPOINT_PYTEST_ISOLATE_TURSO (checked in turso.get_client), and
hard-asserts the frozen module constant is :memory:.
"""

import os

os.environ["MATCHPOINT_PYTEST_ISOLATE_TURSO"] = "1"
os.environ["TURSO_DATABASE_URL"] = ":memory:"
os.environ["TURSO_AUTH_TOKEN"] = ""

import app.db.turso as turso  # noqa: E402

assert turso.TURSO_DATABASE_URL == ":memory:", (
    "Test session resolved a real Turso URL — refusing to run against a "
    "remote database."
)
