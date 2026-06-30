"""Tests for the suggestions route helpers, focused on the
`_fetch_top_matches` function.

These tests exist because the original implementation did a Supabase
PostgREST join on a `jobs` resource that no longer exists on Supabase
(jobs moved to Turso in commit 16829d6). The function must now stitch
match rows from Supabase with full job records from Turso, mirroring
the pattern in `routes/resumes.py:fetch_vector_job_matches` +
`fetch_full_jobs`. If this test ever fails by silently returning
empty title/company/description fields, the Turso-side stitching has
regressed.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.routes.suggestions import _fetch_top_matches


SUPABASE_MATCH_ROWS = [
    # Note: no nested `jobs` key. The Supabase response only carries
    # (id, match_score, job_id) now that the jobs table lives in Turso.
    {"id": "match-1", "match_score": 0.92, "job_id": "job-aaa"},
    {"id": "match-2", "match_score": 0.81, "job_id": "job-bbb"},
    {"id": "match-3", "match_score": 0.74, "job_id": "job-ccc"},
]

TURSO_FULL_JOBS = {
    "job-aaa": {
        "id": "job-aaa",
        "title": "Senior Backend Engineer",
        "company": "Acme",
        "description": "Python, FastAPI, PostgreSQL.",
        "location": "Remote",
        "apply_url": "https://example.com/a",
        "posted_at": "2026-06-01",
    },
    "job-bbb": {
        "id": "job-bbb",
        "title": "Backend Engineer",
        "company": "Globex",
        "description": "Strong Python and FastAPI skills required.",
        "location": "NYC",
        "apply_url": "https://example.com/b",
        "posted_at": "2026-06-02",
    },
    "job-ccc": {
        "id": "job-ccc",
        "title": "Platform Engineer",
        "company": "Initech",
        "description": "Python and Kubernetes are central to our stack.",
        "location": "SF",
        "apply_url": "https://example.com/c",
        "posted_at": "2026-06-03",
    },
}


class FetchTopMatchesTests(unittest.TestCase):
    """Verifies the two-database stitch in `_fetch_top_matches`."""

    @patch("app.routes.suggestions.turso")
    @patch("app.routes.suggestions.supabase")
    def test_stitches_match_rows_with_turso_full_jobs(
        self, mock_supabase, mock_turso
    ):
        # Arrange: Supabase returns match rows (no nested jobs join).
        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = (
            SUPABASE_MATCH_ROWS
        )
        mock_turso.fetch_full_jobs.return_value = TURSO_FULL_JOBS

        # Act
        out = _fetch_top_matches("user-1", limit=3)

        # Assert: one output dict per match row, with full job data stitched in.
        self.assertEqual(len(out), 3)

        self.assertEqual(out[0]["match_id"], "match-1")
        self.assertEqual(out[0]["match_score"], 0.92)
        self.assertEqual(out[0]["job_id"], "job-aaa")
        self.assertEqual(out[0]["title"], "Senior Backend Engineer")
        self.assertEqual(out[0]["company"], "Acme")
        self.assertEqual(out[0]["description"], "Python, FastAPI, PostgreSQL.")
        self.assertEqual(out[0]["location"], "Remote")

        self.assertEqual(out[1]["title"], "Backend Engineer")
        self.assertEqual(out[2]["company"], "Initech")

        # The Turso call must have been made with the cleaned, string-typed
        # job_ids. If the cleaning step regresses (e.g. drops the str()
        # cast), this assertion catches the type drift.
        mock_turso.fetch_full_jobs.assert_called_once()
        called_with = mock_turso.fetch_full_jobs.call_args[0][0]
        self.assertEqual(
            called_with, ["job-aaa", "job-bbb", "job-ccc"]
        )
        for job_id in called_with:
            self.assertIsInstance(job_id, str)

    @patch("app.routes.suggestions.turso")
    @patch("app.routes.suggestions.supabase")
    def test_select_spec_has_no_trailing_comma_or_jobs_embed(
        self, mock_supabase, mock_turso
    ):
        # Regression guard: the original broken code used
        # "id, match_score, job_id, " + "jobs(...)" — a two-string
        # concat where the trailing comma was the join boundary. Once
        # the embed was removed, the comma became dangling and
        # PostgREST rejected the select with PGRST100. Assert the
        # exact select string to catch this kind of drift early.
        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = (
            []
        )

        _fetch_top_matches("user-1", limit=10)

        select_call = mock_supabase.table.return_value.select.call_args
        select_arg = select_call[0][0]
        self.assertEqual(select_arg, "id, match_score, job_id")
        self.assertFalse(select_arg.endswith(","))
        self.assertNotIn("jobs(", select_arg)

    @patch("app.routes.suggestions.turso")
    @patch("app.routes.suggestions.supabase")
    def test_returns_empty_list_when_no_matches(
        self, mock_supabase, mock_turso
    ):
        # No matches -> early return. Turso should not be called at all
        # (no point hitting the second DB if there's nothing to look up).
        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = (
            []
        )

        out = _fetch_top_matches("user-1", limit=10)

        self.assertEqual(out, [])
        mock_turso.fetch_full_jobs.assert_not_called()

    @patch("app.routes.suggestions.turso")
    @patch("app.routes.suggestions.supabase")
    def test_handles_missing_job_in_turso(self, mock_supabase, mock_turso):
        # Real-world case: a match's job was purged from Turso by the
        # 7-day pipeline between match creation and this call. The match
        # row stays (Supabase FK is gone), but the Turso lookup misses.
        # The function should not crash — the missing match should appear
        # with empty job fields, and the validator downstream will simply
        # reject suggestions grounded in it.
        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = (
            [
                {"id": "match-1", "match_score": 0.9, "job_id": "job-aaa"},
                {"id": "match-2", "match_score": 0.8, "job_id": "job-purged"},
            ]
        )
        # job-purged is intentionally missing.
        mock_turso.fetch_full_jobs.return_value = {
            "job-aaa": TURSO_FULL_JOBS["job-aaa"]
        }

        out = _fetch_top_matches("user-1", limit=10)

        self.assertEqual(len(out), 2)

        # First match: real data.
        self.assertEqual(out[0]["title"], "Senior Backend Engineer")
        self.assertEqual(out[0]["company"], "Acme")

        # Second match: missing job -> empty fields, but no crash.
        self.assertEqual(out[1]["job_id"], "job-purged")
        self.assertIsNone(out[1]["title"])
        self.assertIsNone(out[1]["company"])
        self.assertEqual(out[1]["description"], "")
        self.assertIsNone(out[1]["location"])

    @patch("app.routes.suggestions.turso")
    @patch("app.routes.suggestions.supabase")
    def test_skips_rows_with_null_job_id(self, mock_supabase, mock_turso):
        # Defensive: a malformed match row (job_id is None) must not be
        # sent to Turso (would break the IN clause), and must not crash
        # the stitching loop.
        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = (
            [
                {"id": "match-1", "match_score": 0.9, "job_id": "job-aaa"},
                {"id": "match-2", "match_score": 0.8, "job_id": None},
                {"id": "match-3", "match_score": 0.7},  # missing key
            ]
        )
        mock_turso.fetch_full_jobs.return_value = {
            "job-aaa": TURSO_FULL_JOBS["job-aaa"]
        }

        out = _fetch_top_matches("user-1", limit=10)

        # Three output dicts (we don't filter the output, just the lookup).
        self.assertEqual(len(out), 3)
        # But Turso only saw the one valid job_id.
        called_with = mock_turso.fetch_full_jobs.call_args[0][0]
        self.assertEqual(called_with, ["job-aaa"])

        # The bad rows are still in the output with empty job fields.
        self.assertIsNone(out[1]["title"])
        self.assertEqual(out[1]["description"], "")
        self.assertIsNone(out[2]["title"])


if __name__ == "__main__":
    unittest.main()
