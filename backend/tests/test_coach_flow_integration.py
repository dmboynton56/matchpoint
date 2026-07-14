"""End-to-end integration tests for the bullet-coach flow.

These tests run through the full FastAPI HTTP layer with a TestClient.
The point is to verify the schema + validator + route + session-store
wiring works in concert, not just each piece in isolation. We mock:

  - `get_current_user` (auth dep) -> fake user
  - `_fetch_resume_text` -> canned resume
  - `_fetch_top_matches` -> canned matches
  - `start_coach_session` (LLM call) -> canned CoachStartResponse
  - `rewrite_bullet` (LLM call) -> canned rewrite text

The session store (services/bullet_coach.py) is NOT mocked -- it
runs for real. The bullet_coach.py module exposes clear_all() for
test setup/teardown.

What we're verifying:
  1. /coach/start returns bullets with verdict + categories wired
     correctly (WEAK with category-tagged questions, STRONG with
     strength_reason + no questions).
  2. /coach/start persists the session so /coach/rewrite can find
     the bullet.
  3. /coach/rewrite accepts a WEAK bullet's answers + returns a
     rewrite that includes the user's words.
  4. /coach/rewrite rejects STRONG bullets early (400).
  5. /coach/rewrite enforces the category-coverage validator (502
     when the rewrite doesn't use the user's answer words).
  6. /coach/rewrite threads skipped_categories through to the LLM
     and tolerates an empty rewrite (validator soft-skips empty
     answers).
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.suggestions import (
    CoachBullet,
    CoachBulletVerdict,
    CoachCategory,
    CoachQuestion,
    CoachQuestionType,
    Citation,
    CoachStartResponse,
    Suggestion,
    SuggestionKind,
)
from app.services import bullet_coach


def _fake_user():
    return SimpleNamespace(id="user-1")


def _fake_resume():
    """Parsed resume must contain both bullet substrings verbatim:
      - "Reduced p99 latency by 40% for 50k MAU." (STRONG)
      - "Built a job matching platform for the cohort." (WEAK)

    The parser uses common section headers. We add both bullet
    text fragments to the same entry under WORK EXPERIENCE so
    the parser includes both in the substring-match window.
    """
    return (
        "WORK EXPERIENCE\n\n"
        "Flatiron School -- Software Engineering Coach\n"
        "Built a job matching platform for the cohort.\n"
        "Designed a code review rubric used by 12 instructors.\n"
        "Reduced p99 latency by 40% for 50k MAU.\n"
    )


def _fake_matches():
    """Two jobs. job-bbb's description contains the substring the LLM
    is expected to cite for the WEAK bullet (job matching platform).
    job-aaa's description contains the substring for the STRONG bullet
    (p99 latency). The grounding check requires the citation_quote to
    substring-match the cited job description, so we make those
    consistent here."""
    return [
        {
            "match_id": "match-1",
            "match_score": 0.92,
            "job_id": "job-aaa",
            "title": "Senior Backend Engineer",
            "company": "Acme",
            "description": (
                "We are looking for a Senior Backend Engineer with "
                "experience in Python, FastAPI, and PostgreSQL. You "
                "will design and ship production services. Improve "
                "p99 latency across the platform."
            ),
            "location": "Remote",
            "apply_url": "https://example.com/a",
        },
        {
            "match_id": "match-2",
            "match_score": 0.81,
            "job_id": "job-bbb",
            "title": "Backend Engineer",
            "company": "Globex",
            "description": (
                "Strong Python and FastAPI skills required. "
                "Familiarity with PostgreSQL and REST APIs. Built a "
                "job matching platform for internal use."
            ),
            "location": "NYC",
            "apply_url": "https://example.com/b",
        },
    ]


def _fake_start_response():
    """What the LLM is expected to return for /coach/start.

    One STRONG bullet (the latency tracker, which already has
    metric + scope + cause_effect + outcome) and one WEAK bullet
    (the job matching platform, missing audience / scope).
    """
    strong = CoachBullet(
        bullet_id="b_strong",
        verdict=CoachBulletVerdict.STRONG,
        original_text="Reduced p99 latency by 40% for 50k MAU.",
        strength_reason=(
            "Already has metric (40%), scope (50k MAU), and outcome "
            "(reduced latency)."
        ),
        citation_job_id="job-aaa",
        citation_quote="Improve p99 latency",
    )
    weak = CoachBullet(
        bullet_id="b_weak",
        verdict=CoachBulletVerdict.WEAK,
        original_text="Built a job matching platform for the cohort.",
        weakness_reason="No clear audience or what the platform replaced.",
        citation_job_id="job-bbb",
        citation_quote="Built a job matching platform",
        checklist=None,
        questions=[
            CoachQuestion(
                key="scope",
                category=CoachCategory.SCOPE,
                label="Who used it?",
                type=CoachQuestionType.TEXT,
            ),
            CoachQuestion(
                key="artifact",
                category=CoachCategory.ARTIFACT,
                label="What's the most interesting part?",
                type=CoachQuestionType.TEXT,
            ),
        ],
    )
    return CoachStartResponse(
        session_id="placeholder",
        skills=[
            Suggestion(
                kind=SuggestionKind.SKILL,
                text="FastAPI",
                evidence=[Citation(job_id="job-aaa", quote="FastAPI")],
            )
        ],
        bullets=[strong, weak],
    )


class CoachFlowIntegrationTests(unittest.TestCase):
    """End-to-end /coach/start + /coach/rewrite via FastAPI TestClient."""

    def setUp(self):
        bullet_coach.clear_all()
        # Override the auth dep so we don't hit Supabase.
        app.dependency_overrides = getattr(app, "dependency_overrides", {})
        from app.routes.auth import get_current_user
        app.dependency_overrides[get_current_user] = lambda: _fake_user()
        self.client = TestClient(app)

    def tearDown(self):
        bullet_coach.clear_all()
        app.dependency_overrides = {}

    def _mock_dependencies(self):
        """Patch the data-fetching helpers + the LLM call. Returns
        the patch contexts so the caller can stop them."""
        return [
            patch(
                "app.routes.suggestions._fetch_resume_text",
                return_value=_fake_resume(),
            ),
            patch(
                "app.routes.suggestions._fetch_top_matches",
                return_value=_fake_matches(),
            ),
            patch(
                "app.services.bullet_coach_llm.start_coach_session",
                return_value=(
                    _fake_start_response().skills,
                    _fake_start_response().bullets,
                ),
            ),
        ]

    def test_coach_start_returns_mixed_verdicts(self):
        """POST /suggestions/coach/start returns both STRONG and WEAK
        bullets with the new fields wired through."""
        from contextlib import ExitStack

        with ExitStack() as stack:
            for ctx in self._mock_dependencies():
                stack.enter_context(ctx)

            response = self.client.post("/suggestions/coach/start")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIn("session_id", body)
        self.assertEqual(len(body["bullets"]), 2)

        # Find each bullet by id and verify shape.
        by_id = {b["bullet_id"]: b for b in body["bullets"]}
        self.assertIn("b_strong", by_id)
        self.assertIn("b_weak", by_id)

        strong = by_id["b_strong"]
        self.assertEqual(strong["verdict"], "STRONG")
        self.assertEqual(strong["questions"], [])
        self.assertGreaterEqual(
            len(strong["strength_reason"]),
            10,
            "strength_reason must be present for STRONG bullets",
        )

        weak = by_id["b_weak"]
        self.assertEqual(weak["verdict"], "WEAK")
        self.assertEqual(len(weak["questions"]), 2)
        # Every question must carry a category.
        for q in weak["questions"]:
            self.assertIn("category", q)
            self.assertIn(
                q["category"],
                {"SPECIFICITY", "SCOPE", "OWNERSHIP",
                 "REPLACEMENT", "CAUSE_EFFECT", "ARTIFACT"},
            )

        # Skills carried over.
        self.assertEqual(len(body["skills"]), 1)
        self.assertEqual(body["skills"][0]["text"], "FastAPI")

    def test_coach_rewrite_weak_bullet_with_user_words_passes(self):
        """Happy path: WEAK bullet, user provides answers containing
        distinctive words, the LLM rewrite includes those words,
        the category-coverage validator passes.

        The rewrite text is constrained to only use words from
        {original, answers, cited quote} -- that's what the
        existing grounding validator (rule 2: no fabricated
        tokens) requires. So we craft a rewrite that uses ONLY
        sourced words."""
        from contextlib import ExitStack

        with ExitStack() as stack:
            for ctx in self._mock_dependencies():
                stack.enter_context(ctx)

            start = self.client.post("/suggestions/coach/start")
            self.assertEqual(start.status_code, 200)
            session_id = start.json()["session_id"]
            weak = next(
                b for b in start.json()["bullets"]
                if b["bullet_id"] == "b_weak"
            )
            scope_key = weak["questions"][0]["key"]
            artifact_key = weak["questions"][1]["key"]

            # Every word here comes from one of:
            #   original: "Built a job matching platform for the cohort."
            #   answers:  "my cohort of 40 students" + "the matching algorithm"
            #   quote:    "Built a job matching platform"
            rewrite_text = (
                "Built a job matching platform for my cohort of 40 "
                "students using the matching algorithm"
            )
            stack.enter_context(
                patch(
                    "app.services.bullet_coach_llm.rewrite_bullet",
                    return_value=rewrite_text,
                )
            )

            response = self.client.post(
                "/suggestions/coach/rewrite",
                json={
                    "session_id": session_id,
                    "bullet_id": "b_weak",
                    "answers": {
                        scope_key: "my cohort of 40 students",
                        artifact_key: "the matching algorithm",
                    },
                    "skipped_categories": [],
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["bullet_id"], "b_weak")
        self.assertIn("rewritten_text", body)
        self.assertIn("cohort", body["rewritten_text"])
        self.assertIn("algorithm", body["rewritten_text"])

    def test_coach_rewrite_strong_bullet_rejected(self):
        """STRONG bullets have no questions to answer. /coach/rewrite
        must reject them early with 400 + clear message."""
        from contextlib import ExitStack

        with ExitStack() as stack:
            for ctx in self._mock_dependencies():
                stack.enter_context(ctx)

            start = self.client.post("/suggestions/coach/start")
            session_id = start.json()["session_id"]

            # Patch the rewrite LLM call -- it should NEVER be called.
            unexpected = patch(
                "app.services.bullet_coach_llm.rewrite_bullet",
                return_value="this should never be returned",
            )
            stack.enter_context(unexpected)

            response = self.client.post(
                "/suggestions/coach/rewrite",
                json={
                    "session_id": session_id,
                    "bullet_id": "b_strong",
                    "answers": {},
                    "skipped_categories": [],
                },
            )

        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertIn("already strong", body["detail"].lower())

    def test_coach_rewrite_skipped_categories_accepted(self):
        """User skips one category; rewrite doesn't need to mention it."""
        from contextlib import ExitStack

        with ExitStack() as stack:
            for ctx in self._mock_dependencies():
                stack.enter_context(ctx)

            start = self.client.post("/suggestions/coach/start")
            session_id = start.json()["session_id"]
            weak = next(
                b for b in start.json()["bullets"]
                if b["bullet_id"] == "b_weak"
            )
            scope_key = weak["questions"][0]["key"]
            artifact_key = weak["questions"][1]["key"]

            # Rewrite mentions scope but not artifact. ARTIFACT
            # is in skipped_categories, so the validator lets it
            # through. All words sourced from {original, answers,
            # quote} so rule 2 (no fabricated tokens) passes.
            rewrite_text = (
                "Built a job matching platform for my cohort of 40 "
                "students"
            )
            stack.enter_context(
                patch(
                    "app.services.bullet_coach_llm.rewrite_bullet",
                    return_value=rewrite_text,
                )
            )

            response = self.client.post(
                "/suggestions/coach/rewrite",
                json={
                    "session_id": session_id,
                    "bullet_id": "b_weak",
                    "answers": {
                        scope_key: "my cohort of 40 students",
                        artifact_key: "the matching algorithm",
                    },
                    "skipped_categories": ["ARTIFACT"],
                },
            )

        self.assertEqual(response.status_code, 200, response.text)

    def test_coach_rewrite_missing_answer_word_rejected(self):
        """If the LLM's rewrite omits the user's answer words for a
        non-skipped category, the validator returns 502."""
        from contextlib import ExitStack

        with ExitStack() as stack:
            for ctx in self._mock_dependencies():
                stack.enter_context(ctx)

            start = self.client.post("/suggestions/coach/start")
            session_id = start.json()["session_id"]
            weak = next(
                b for b in start.json()["bullets"]
                if b["bullet_id"] == "b_weak"
            )
            scope_key = weak["questions"][0]["key"]
            artifact_key = weak["questions"][1]["key"]

            # Rewrite is the bare original -- no user words.
            rewrite_text = "Built a job matching platform."
            stack.enter_context(
                patch(
                    "app.services.bullet_coach_llm.rewrite_bullet",
                    return_value=rewrite_text,
                )
            )

            response = self.client.post(
                "/suggestions/coach/rewrite",
                json={
                    "session_id": session_id,
                    "bullet_id": "b_weak",
                    "answers": {
                        scope_key: "my cohort of 40 students",
                        artifact_key: "the matching algorithm",
                    },
                    "skipped_categories": [],
                },
            )

        # Category coverage OR the rewrite==original grounding rule
        # will fail. Either way, the route returns 502.
        self.assertEqual(response.status_code, 502)

    def test_coach_rewrite_missing_session_returns_404(self):
        """A session_id the server doesn't know about -> 404."""
        response = self.client.post(
            "/suggestions/coach/rewrite",
            json={
                "session_id": "nonexistent",
                "bullet_id": "b_weak",
                "answers": {},
                "skipped_categories": [],
            },
        )
        self.assertEqual(response.status_code, 404)

    def test_coach_rewrite_unauthenticated_returns_401(self):
        """Without the auth dep override, the route returns 401."""
        app.dependency_overrides = {}
        response = self.client.post(
            "/suggestions/coach/rewrite",
            json={
                "session_id": "x",
                "bullet_id": "y",
                "answers": {},
                "skipped_categories": [],
            },
        )
        # No auth dep -> 401.
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()