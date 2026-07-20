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
  7. /coach/rewrite enforces the grounding validator's rejection
     path (502 when the rewrite fabricates a number or technology
     not in {original, answers, cited quote}, even if category
     coverage passes). This was the regression of the original
     hallucination guard; reintroduced as a hard rejection after
     the qualitative-coach v2 migration (fe2a845).
  8. /coach/start accepts a WEAK bullet with up to len(CoachCategory)
     questions (was capped at 4, which silently truncated gaps).
  9. /coach/rewrite rejects with 502 when the LLM-supplied bullet
     is missing a question for a checklist gap that wasn't skipped
     (the one-question-per-gap contract).
  10. /coach/rewrite passes when every checklist gap is in
      skipped_categories even if the rewrite adds nothing for
      those categories.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.suggestions import (
    CategoryChecklist,
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
        # Checklist drives the gap-coverage validator. Two gaps
        # (SCOPE, ARTIFACT) match the two questions below so the
        # existing tests verify the validator's happy path with
        # a populated checklist.
        checklist=CategoryChecklist(
            SPECIFICITY=True,
            SCOPE=False,
            OWNERSHIP=True,
            REPLACEMENT=True,
            CAUSE_EFFECT=True,
            ARTIFACT=False,
        ),
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
        """User skips one category; rewrite doesn't need to mention it.

        Mirrors what the frontend now sends after the suggestion-3
        fix: when the user hits 'Skip' on a category, the UI clears
        that question's answer locally (handleToggleSkip sets the
        answer key to ""), so the request carries an empty string
        for the skipped question's key. The backend validator
        should soft-skip that empty value (not fail), so the
        rewrite passes -- which is the contract the UI depends on.
        """
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
                        # After frontend suggestion-3 fix:
                        # skipping ARTIFACT also clears its answer.
                        artifact_key: "",
                    },
                    "skipped_categories": ["ARTIFACT"],
                },
            )

        self.assertEqual(response.status_code, 200, response.text)

    def test_coach_rewrite_empty_answer_soft_skip(self):
        """Regression for suggestion 1a: an empty answer to a
        non-skipped category should be treated as a soft skip (the
        validator must NOT add a reason for it) -- the request
        passes as long as the OTHER answers ground the rewrite.

        Prior to the fix, empty answers appended a reason, which
        tipped the route's 502 path even though the documented
        behavior was a soft skip. Mirrors what a partial-input
        request looks like before the new button-guard UI ships.
        """
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

            # Rewrite uses scope words but no artifact words.
            # artifact answer is empty (a soft skip).
            rewrite_text = (
                "Built a job matching platform for my cohort of 40 "
                "students end to end."
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
                        artifact_key: "",  # soft skip
                    },
                    "skipped_categories": [],
                },
            )

        # The empty answer is soft-skipped. The substantive answer
        # ("my cohort of 40 students") supplies enough grounding
        # for the SCOPE category, so the rewrite passes.
        self.assertEqual(
            response.status_code, 200, response.text
        )

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

    def test_coach_rewrite_fabricated_token_rejected(self):
        """Regression for fe2a845: even if the rewrite passes category
        coverage (it uses the user's answer words), fabricating a
        number or technology that is NOT in {original, answers,
        cited quote} must still return 502.

        The route used to log grounding failures and continue, so a
        well-formed-but-fabricated rewrite ("...99% uptime" when
        the user never said 99) would slip through whenever the
        category-coverage check happened to pass. That gate is now
        a hard rejection -- the user gets the "couldn't be grounded"
        message and the fake number never reaches the UI.
        """
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

            # Category coverage WILL pass: "cohort" and "students"
            # cover SCOPE; "matching algorithm" covers ARTIFACT.
            # The bare original ("Built a job matching platform")
            # is sourced. The fabricated "99%" is the trap --
            # digits not present in any source token.
            rewrite_text = (
                "Built a job matching platform for my cohort of 40 "
                "students using the matching algorithm with 99% "
                "uptime."
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

        self.assertEqual(
            response.status_code, 502, response.text,
        )
        body = response.json()
        # The validator surfaces its specific reason in the detail.
        # This rewrite had a fabricated "99%" so the message
        # references "substantive claims". The exact wording has
        # changed as the validator gained more nuanced reason
        # strings (job-only vs fabricated); check for the substance
        # of the failure rather than a hard-coded word.
        self.assertIn("substantive", body["detail"].lower())
        # And confirm the fabricated token name appears so the user
        # knows what to remove.
        self.assertIn("99", body["detail"])

    def test_coach_start_accepts_six_question_bullet(self):
        """Regression: WEAK bullet with >4 questions used to be
        rejected by the schema's max_length. Six questions (one per
        CoachCategory) is the legitimate upper bound -- a bullet
        can lack all six qualitative dimensions."""
        from contextlib import ExitStack

        # Build a separate start response for this scenario:
        # one WEAK bullet with 6 questions (one per category)
        # and a checklist that names every category as a gap.
        # original_text MUST be a substring of _fake_resume() so
        # validate_coach_bullet_grounding doesn't drop it.
        six_q_weak = CoachBullet(
            bullet_id="b_six_weak",
            verdict=CoachBulletVerdict.WEAK,
            original_text="Designed a code review rubric used by 12 instructors.",
            weakness_reason="No detail on any dimension.",
            citation_job_id="job-bbb",
            citation_quote="Built a job matching platform",
            checklist=CategoryChecklist(
                SPECIFICITY=False,
                SCOPE=False,
                OWNERSHIP=False,
                REPLACEMENT=False,
                CAUSE_EFFECT=False,
                ARTIFACT=False,
            ),
            questions=[
                CoachQuestion(
                    key=k,
                    category=c,
                    label=f"q-{k}",
                    type=CoachQuestionType.TEXT,
                )
                for k, c in (
                    ("specificity", CoachCategory.SPECIFICITY),
                    ("scope", CoachCategory.SCOPE),
                    ("ownership", CoachCategory.OWNERSHIP),
                    ("replacement", CoachCategory.REPLACEMENT),
                    ("cause_effect", CoachCategory.CAUSE_EFFECT),
                    ("artifact", CoachCategory.ARTIFACT),
                )
            ],
        )
        six_q_response = CoachStartResponse(
            session_id="placeholder",
            skills=[],
            bullets=[six_q_weak],
        )

        with ExitStack() as stack:
            for ctx in self._mock_dependencies():
                stack.enter_context(ctx)
            # Override the LLM response with a 6-question bullet.
            stack.enter_context(
                patch(
                    "app.services.bullet_coach_llm.start_coach_session",
                    return_value=(six_q_response.skills, six_q_response.bullets),
                )
            )

            response = self.client.post("/suggestions/coach/start")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        # The 6-question bullet must survive -- before the cap
        # lift this would have failed pydantic validation.
        weak = next(
            b for b in body["bullets"] if b["bullet_id"] == "b_six_weak"
        )
        self.assertEqual(len(weak["questions"]), 6)

    def test_coach_start_drops_bullet_with_unknown_citation_job_id(self):
        """Bug fix: the LLM sometimes picks a `citation_job_id` that
        isn't in the user's top matches (a hallucination). Before
        this fix the bullet would survive /coach/start --
        `validate_coach_citation_grounding`'s "missing description"
        branch keeps best-effort, designed for the legitimate
        "job purged from Turso" case -- then fail at rewrite with
        "citation quote is not a substring of the job description",
        because the route coerced the missing description to "".

        Now /coach/start drops WEAK bullets whose citation_job_id
        is unknown to the snapshot, with reason="citation_job_id_unknown"
        surfaced in the `dropped` field. STRONG bullets are kept
        regardless: their citation_quote is cosmetic (no rewrite
        path) and the missing-description tolerance for STRONG is
        by design.
        """
        from contextlib import ExitStack

        # WEAK bullet with citation_job_id not in _fake_matches().
        # original_text MUST be a substring of _fake_resume() so
        # validate_coach_bullet_grounding doesn't drop it -- this
        # isolates the test to the membership check.
        hallucinated_weak = CoachBullet(
            bullet_id="b_hallucinated",
            verdict=CoachBulletVerdict.WEAK,
            original_text=(
                "Designed a code review rubric used by 12 instructors."
            ),
            weakness_reason="No detail on any dimension.",
            citation_job_id="job-hallucinated",
            citation_quote="Anything goes here.",
            checklist=CategoryChecklist(
                SPECIFICITY=False,
                SCOPE=True,
                OWNERSHIP=True,
                REPLACEMENT=True,
                CAUSE_EFFECT=True,
                ARTIFACT=True,
            ),
            questions=[
                CoachQuestion(
                    key="specificity",
                    category=CoachCategory.SPECIFICITY,
                    label="q-specificity",
                    type=CoachQuestionType.TEXT,
                )
            ],
        )
        # Pair with a STRONG bullet that has a VALID job_id so we
        # verify STRONG bullets are unaffected by the new check
        # (kept even when citation_job_id is unknown -- that case
        # is covered by test_strong_bullets_skip_the_check at the
        # validator level; this test focuses on the WEAK case).
        valid_strong = CoachBullet(
            bullet_id="b_valid_strong",
            verdict=CoachBulletVerdict.STRONG,
            original_text="Reduced p99 latency by 40% for 50k MAU.",
            strength_reason="Has metric and scope.",
            citation_job_id="job-aaa",
            citation_quote="Improve p99 latency",
        )
        response_obj = CoachStartResponse(
            session_id="placeholder",
            skills=[],
            bullets=[hallucinated_weak, valid_strong],
        )

        with ExitStack() as stack:
            for ctx in self._mock_dependencies():
                stack.enter_context(ctx)
            stack.enter_context(
                patch(
                    "app.services.bullet_coach_llm.start_coach_session",
                    return_value=(response_obj.skills, response_obj.bullets),
                )
            )

            response = self.client.post("/suggestions/coach/start")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        # The hallucinated WEAK bullet must NOT appear in bullets.
        surviving_ids = {b["bullet_id"] for b in body["bullets"]}
        self.assertNotIn("b_hallucinated", surviving_ids)
        # The valid STRONG bullet must survive (it's STRONG, so the
        # membership check doesn't apply to it).
        self.assertIn("b_valid_strong", surviving_ids)
        # The dropped field must surface the hallucinated bullet
        # with the right reason so the client can show the user
        # "we couldn't ground 1 of your bullets".
        dropped_by_id = {d["bullet_id"]: d for d in body["dropped"]}
        self.assertIn("b_hallucinated", dropped_by_id)
        self.assertEqual(
            dropped_by_id["b_hallucinated"]["reason"],
            "citation_job_id_unknown",
        )
        self.assertEqual(
            dropped_by_id["b_hallucinated"]["citation_job_id"],
            "job-hallucinated",
        )
        # The valid STRONG bullet must NOT be in dropped.
        self.assertNotIn("b_valid_strong", dropped_by_id)

    def test_coach_rewrite_missing_gap_question_rejected(self):
        """Bug fix: when the LLM supplies a checklist naming more
        gaps than the questions it produced, /coach/rewrite must
        auto-skip the gap-without-question categories and let the
        rewrite proceed. The one-question-per-gap contract has
        been relaxed: bullet-coach is an experimental feature
        where slight hallucinations are accepted in exchange for
        not 502-ing the user mid-workshop, and the user can't
        answer questions that weren't generated."""
        from contextlib import ExitStack

        # Override the WEAK bullet's checklist to claim THREE gaps
        # (SCOPE, OWNERSHIP, ARTIFACT) but only produce questions
        # for SCOPE and ARTIFACT. OWNERSHIP is auto-skipped by the
        # route because it has no question, so the rewrite only
        # needs to cover SCOPE and ARTIFACT.
        gap_mismatch_weak = CoachBullet(
            bullet_id="b_weak",
            verdict=CoachBulletVerdict.WEAK,
            original_text="Built a job matching platform for the cohort.",
            weakness_reason="Missing dimensions.",
            citation_job_id="job-bbb",
            citation_quote="Built a job matching platform",
            checklist=CategoryChecklist(
                SPECIFICITY=True,
                SCOPE=False,
                OWNERSHIP=False,
                REPLACEMENT=True,
                CAUSE_EFFECT=True,
                ARTIFACT=False,
            ),
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
                    label="What's interesting?",
                    type=CoachQuestionType.TEXT,
                ),
                # NOTE: no OWNERSHIP question even though checklist
                # says OWNERSHIP is a gap.
            ],
        )
        gm_response = CoachStartResponse(
            session_id="placeholder",
            skills=[],
            bullets=[gap_mismatch_weak],
        )

        with ExitStack() as stack:
            for ctx in self._mock_dependencies():
                stack.enter_context(ctx)
            stack.enter_context(
                patch(
                    "app.services.bullet_coach_llm.start_coach_session",
                    return_value=(gm_response.skills, gm_response.bullets),
                )
            )

            start = self.client.post("/suggestions/coach/start")
            session_id = start.json()["session_id"]
            weak = next(
                b for b in start.json()["bullets"]
                if b["bullet_id"] == "b_weak"
            )
            scope_key = weak["questions"][0]["key"]
            artifact_key = weak["questions"][1]["key"]

            # Even with a perfectly-grounded rewrite that uses
            # SCOPE and ARTIFACT words, the missing OWNERSHIP
            # question means this rewrite should be rejected.
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

        self.assertEqual(
            response.status_code, 200, response.text,
        )
        body = response.json()
        # Rewriter still includes the user's answered-category
        # vocabulary ("my cohort of 40 students", "the matching
        # algorithm"). OWNERSHIP was auto-skipped by the route
        # because there's no question for it -- the user never
        # had a chance to answer, so the validator treats it as
        # implicitly skipped.

    def test_coach_rewrite_all_gaps_skipped_passes(self):
        """When the user explicitly skips every checklist gap, the
        validator accepts even a minimal rewrite -- nothing to
        ground against."""
        from contextlib import ExitStack

        all_skipped_weak = CoachBullet(
            bullet_id="b_weak",
            verdict=CoachBulletVerdict.WEAK,
            original_text="Built a job matching platform for the cohort.",
            weakness_reason="Missing dimensions.",
            citation_job_id="job-bbb",
            citation_quote="Built a job matching platform",
            checklist=CategoryChecklist(
                SPECIFICITY=True,
                SCOPE=False,
                OWNERSHIP=False,
                REPLACEMENT=True,
                CAUSE_EFFECT=True,
                ARTIFACT=False,
            ),
            questions=[
                CoachQuestion(
                    key="scope",
                    category=CoachCategory.SCOPE,
                    label="Who used it?",
                    type=CoachQuestionType.TEXT,
                ),
                CoachQuestion(
                    key="ownership",
                    category=CoachCategory.OWNERSHIP,
                    label="Did you lead?",
                    type=CoachQuestionType.TEXT,
                ),
                CoachQuestion(
                    key="artifact",
                    category=CoachCategory.ARTIFACT,
                    label="What's interesting?",
                    type=CoachQuestionType.TEXT,
                ),
            ],
        )
        as_response = CoachStartResponse(
            session_id="placeholder",
            skills=[],
            bullets=[all_skipped_weak],
        )

        with ExitStack() as stack:
            for ctx in self._mock_dependencies():
                stack.enter_context(ctx)
            stack.enter_context(
                patch(
                    "app.services.bullet_coach_llm.start_coach_session",
                    return_value=(as_response.skills, as_response.bullets),
                )
            )

            start = self.client.post("/suggestions/coach/start")
            session_id = start.json()["session_id"]

            # User skips every gap category. The rewrite can be
            # minimal -- just different from the original so it
            # doesn't trip the grounding validator's "rewrite is
            # identical to the original" rule (rule 3).
            rewrite_text = "Built a job matching platform for the cohort end to end."
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
                    # Empty answers are allowed (user can leave
                    # them blank) -- the key just needs to be
                    # present so the validator can tell the
                    # rewrite was for THESE questions.
                    "answers": {
                        "scope": "",
                        "ownership": "",
                        "artifact": "",
                    },
                    "skipped_categories": [
                        "SCOPE", "OWNERSHIP", "ARTIFACT",
                    ],
                },
            )

        self.assertEqual(
            response.status_code, 200, response.text,
        )

    def test_coach_rewrite_auto_skips_gap_categories_without_questions(self):
        """Regression: the LLM sometimes produces a checklist with N
        gaps but only M<N questions (e.g., 5 categories marked
        missing but only 2 questions generated). The user can't
        answer what wasn't asked, so /coach/rewrite auto-skips the
        gap-without-question categories and lets the rewrite
        proceed. Previously this fired the
        `rewrite skipped categories without a question or skip
        marker` 502, blocking the user mid-workshop for the
        experimental bullet-coach feature.

        Pins the behavior so future re-tightening of the
        coverage validator is a deliberate choice.
        """
        from contextlib import ExitStack

        # Build a WEAK bullet where the checklist marks 5 gaps
        # but the questions list only contains 2 (SCOPE, ARTIFACT).
        # original_text MUST be a substring of _fake_resume() so
        # validate_coach_bullet_grounding doesn't drop it.
        weak = CoachBullet(
            bullet_id="b_few_questions",
            verdict=CoachBulletVerdict.WEAK,
            original_text=(
                "Designed a code review rubric used by 12 instructors."
            ),
            weakness_reason="Lots of gaps.",
            citation_job_id="job-bbb",
            citation_quote="Built a job matching platform",
            checklist=CategoryChecklist(
                SPECIFICITY=False,
                SCOPE=False,
                OWNERSHIP=False,
                REPLACEMENT=False,
                CAUSE_EFFECT=False,
                ARTIFACT=False,
            ),
            category_gaps=[
                CoachCategory.SPECIFICITY,
                CoachCategory.OWNERSHIP,
                CoachCategory.REPLACEMENT,
                CoachCategory.CAUSE_EFFECT,
                CoachCategory.ARTIFACT,
            ],
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
        start_response = CoachStartResponse(
            session_id="placeholder",
            skills=[],
            bullets=[weak],
        )

        with ExitStack() as stack:
            for ctx in self._mock_dependencies():
                stack.enter_context(ctx)
            stack.enter_context(
                patch(
                    "app.services.bullet_coach_llm.start_coach_session",
                    return_value=(
                        start_response.skills, start_response.bullets
                    ),
                )
            )

            start = self.client.post("/suggestions/coach/start")
            self.assertEqual(start.status_code, 200, start.text)
            session_id = start.json()["session_id"]

            # LLM rewrite only needs to cover the 2 answered
            # categories (SCOPE, ARTIFACT). Other categories are
            # auto-skipped by the route because they have no
            # question.
            rewrite_text = (
                "Designed a code review rubric for my cohort of 40 "
                "students using a peer-review scoring matrix"
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
                    "bullet_id": "b_few_questions",
                    "answers": {
                        "scope": "my cohort of 40 students",
                        "artifact": "peer-review scoring matrix",
                    },
                    "skipped_categories": [],
                },
            )

        self.assertEqual(
            response.status_code, 200,
            f"rewrite should succeed under the relaxed policy "
            f"(gap-without-question categories auto-skipped); got "
            f"{response.status_code}: {response.text}",
        )

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