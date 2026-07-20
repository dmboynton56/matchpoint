import unittest
from unittest.mock import patch

from app.schemas.suggestions import (
    BANNED_SUGGESTION_TEXTS,
    Citation,
    CoachBullet,
    CoachBulletVerdict,
    CoachCategory,
    CoachQuestion,
    CoachQuestionType,
    CategoryChecklist,
    LearningLink,
    MAX_COACH_BULLETS_PER_SESSION,
    MIN_SUGGESTIONS,
    Suggestion,
    SuggestionKind,
    SuggestionsResponse,
    MIN_STRENGTH_REASON_LEN,
    validate_coach_bullet_grounding,
    validate_coach_rewrite_category_coverage,
    validate_coach_start_request,
    validate_suggestions,
)
from app.services.learning_links import lookup
from app.services.suggestions import (
    extract_already_present,
    generate_resume_suggestions,
)


JOB_DESCRIPTIONS = {
    "job-a": (
        "We are looking for a Senior Backend Engineer with experience in "
        "Python, FastAPI, and PostgreSQL. You will design and ship "
        "production services. Experience with Kubernetes is a plus."
    ),
    "job-b": (
        "Backend Engineer role. Strong Python and FastAPI skills required. "
        "Familiarity with PostgreSQL and REST APIs. Nice to have: AWS."
    ),
    "job-c": (
        "Platform Engineer. Python and Kubernetes are central to our stack. "
        "Postgres experience is a bonus."
    ),
    "job-d": (
        "Frontend Engineer. React and TypeScript. GraphQL nice to have."
    ),
}


class ValidateSuggestionsTests(unittest.TestCase):
    def test_accepts_skill_with_substring_quote(self):
        response = SuggestionsResponse(
            suggestions=[
                Suggestion(
                    kind=SuggestionKind.SKILL,
                    text="FastAPI",
                    evidence=[
                        Citation(job_id="job-a", quote="FastAPI"),
                        Citation(job_id="job-b", quote="FastAPI"),
                    ],
                )
            ]
        )
        accepted = validate_suggestions(
            response, job_descriptions=JOB_DESCRIPTIONS
        )
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0].text, "FastAPI")
        self.assertEqual(len(accepted[0].evidence), 2)

    def test_drops_fabricated_quote(self):
        # LLM claims Python came from job-d, but job-d says nothing about
        # Python. The validator must drop that citation AND the suggestion
        # if no citations survive.
        response = SuggestionsResponse(
            suggestions=[
                Suggestion(
                    kind=SuggestionKind.SKILL,
                    text="Python",
                    evidence=[Citation(job_id="job-d", quote="Python")],
                )
            ]
        )
        accepted = validate_suggestions(
            response, job_descriptions=JOB_DESCRIPTIONS
        )
        self.assertEqual(accepted, [])

    def test_drops_when_token_overlap_fails_single_job(self):
        # Single-job case: a fabricated quote is impossible (the substring
        # check would catch it). But the looser rule now also requires
        # token overlap for the single-citation case. Here the quote
        # exists in job-a but the suggestion ("Rust") shares no token
        # with it — so the suggestion should be dropped. (Was a
        # KEYWORD-suggestion in the previous version; converted to
        # SKILL after the KEYWORD kind was removed.)
        response = SuggestionsResponse(
            suggestions=[
                Suggestion(
                    kind=SuggestionKind.SKILL,
                    text="Rust",
                    evidence=[
                        Citation(
                            job_id="job-a",
                            quote="Python, FastAPI, and PostgreSQL",
                        )
                    ],
                )
            ]
        )
        accepted = validate_suggestions(
            response, job_descriptions=JOB_DESCRIPTIONS
        )
        self.assertEqual(accepted, [])

    def test_accepts_multi_job_even_when_token_overlap_is_weak(self):
        # New relaxed rule: when a suggestion is grounded in 2+ jobs, the
        # token-overlap defense-in-depth is waived. Cross-job prevalence
        # is the signal. This is the "loosened validator" behaviour.
        # "Postgres" doesn't appear in the quote "Python and FastAPI
        # skills required" verbatim in job-b (it appears as "PostgreSQL"),
        # but the substring check accepts job-a's "PostgreSQL" quote and
        # the multi-job rule accepts the suggestion on that basis.
        response = SuggestionsResponse(
            suggestions=[
                Suggestion(
                    kind=SuggestionKind.SKILL,
                    text="Postgres",
                    evidence=[
                        Citation(
                            job_id="job-a", quote="PostgreSQL"
                        ),
                        Citation(
                            job_id="job-b",
                            quote="PostgreSQL and REST APIs",
                        ),
                    ],
                )
            ]
        )
        accepted = validate_suggestions(
            response, job_descriptions=JOB_DESCRIPTIONS
        )
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0].text, "Postgres")

    def test_drops_duplicate_suggestions(self):
        response = SuggestionsResponse(
            suggestions=[
                Suggestion(
                    kind=SuggestionKind.SKILL,
                    text="FastAPI",
                    evidence=[Citation(job_id="job-a", quote="FastAPI")],
                ),
                Suggestion(
                    kind=SuggestionKind.SKILL,
                    text="fastapi",  # case-insensitive duplicate
                    evidence=[Citation(job_id="job-b", quote="FastAPI")],
                ),
            ]
        )
        accepted = validate_suggestions(
            response, job_descriptions=JOB_DESCRIPTIONS
        )
        self.assertEqual(len(accepted), 1)

    def test_schema_rejects_empty_evidence(self):
        # Defense-in-depth: the Pydantic model on Suggestion.evidence
        # already enforces min_length=1, so an LLM response with no
        # citations can never reach validate_suggestions as a valid
        # Suggestion object. We test the schema guard directly.
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            Suggestion(
                kind=SuggestionKind.SKILL,
                text="Kubernetes",
                evidence=[],
            )

    def test_validator_drops_suggestion_when_all_citations_invalid(self):
        # All citations are present (pass the schema) but none survive
        # the substring check, so the validator must drop the whole
        # suggestion. This exercises the "no surviving quotes" branch.
        response = SuggestionsResponse(
            suggestions=[
                Suggestion(
                    kind=SuggestionKind.SKILL,
                    text="Kubernetes",
                    # job-d's description mentions "GraphQL" and
                    # "React", nothing about Kubernetes — fabricated
                    # quote, will fail the substring check.
                    evidence=[Citation(job_id="job-d", quote="Kubernetes")],
                )
            ]
        )
        accepted = validate_suggestions(
            response, job_descriptions=JOB_DESCRIPTIONS
        )
        self.assertEqual(accepted, [])

    def test_min_suggestions_constant_relaxed_to_two(self):
        # The UI accepts below-minimum output and shows a "Refresh"
        # affordance. Setting MIN_SUGGESTIONS=2 means even a sparse
        # evidence set can produce useful output instead of an empty
        # list. Regression guard: this is the contract for the relaxed
        # validator.
        self.assertEqual(MIN_SUGGESTIONS, 2)

    def test_drops_banned_category_phrases(self):
        # The prompt tells the LLM never to suggest broad category
        # phrases like "AI" or "machine learning". The validator
        # drops them as a last-line defense in case the LLM slips.
        # This is independent of grounding — a perfectly-cited "AI"
        # suggestion is still dropped.
        #
        # Each phrase is tested with case variations AND with a
        # valid-looking citation that would have passed the
        # grounding checks. The blacklist drop must fire BEFORE
        # the grounding check would have accepted it.
        banned_phrases = [
            # Bare single-word AI/ML terms.
            "AI", "ML", "Artificial Intelligence", "Machine Learning",
            "Deep Learning", "Neural Networks", "Data Science",
            # Generic engineering categories.
            "Programming", "Coding", "Software Development",
            # Multi-word AI/ML category phrases.
            "AI Integration", "LLM Tooling", "AI Infrastructure",
            "AI Tooling", "AI-Powered Tools", "Agentic Systems",
            "AI Systems", "AI Solutions", "AI Automation",
            "AI Applications", "AI Workflows", "AI Experience",
            # Patterns that sound like skills but aren't tools.
            "RAG", "Retrieval Augmented Generation", "Fine-Tuning",
            "Fine Tuning", "Local LLM", "Local Model",
            # Vector / embedding category phrases.
            "Vector Database", "Vector DB", "Vector Store",
            "Vector Search", "Embeddings Database",
            # Vendor / model nicknames without product suffix.
            "Claude", "Anthropic", "Gemini", "Google AI",
            "Hugging Face", "HF",
        ]
        for phrase in banned_phrases:
            with self.subTest(phrase=phrase):
                response = SuggestionsResponse(
                    suggestions=[
                        Suggestion(
                            kind=SuggestionKind.SKILL,
                            text=phrase,
                            # The citation is valid — the substring
                            # check would pass. The blacklist drop
                            # has to fire BEFORE the grounding check
                            # would have accepted it.
                            evidence=[
                                Citation(
                                    job_id="job-a",
                                    # Pad the quote to be >= 3 chars
                                    # and share tokens with the phrase
                                    # so the token-overlap fallback
                                    # would have accepted it.
                                    quote=(
                                        f"Strong {phrase.lower()} "
                                        "experience required"
                                    ),
                                ),
                            ],
                        ),
                    ]
                )
                accepted = validate_suggestions(
                    response, job_descriptions=JOB_DESCRIPTIONS
                )
                self.assertEqual(
                    accepted,
                    [],
                    f"banned phrase {phrase!r} was not dropped",
                )

        def test_banned_phrases_constant_includes_known_phrase_set(self):
            # Regression guard: the prompt's HARD BLACKLIST section names
            # specific phrases the LLM is told never to suggest. The
            # validator's BANNED_SUGGESTION_TEXTS must include every
            # phrase the prompt lists. If a future refactor drops an
            # entry from either side, this fails first.
            for required in {
                # Bare single-word.
                "ai", "ml", "machine learning", "data science",
                # Multi-word AI/ML category phrases (from the prompt).
                "ai integration", "llm tooling", "ai infrastructure",
                "ai tooling", "agentic systems",
                # Patterns.
                "rag", "fine-tuning", "local llm",
                # Vector / embedding.
                "vector database", "vector db",
                # Vendor nicknames.
                "claude", "anthropic", "gemini", "hugging face",
            }:
                with self.subTest(phrase=required):
                    self.assertIn(
                        required,
                        BANNED_SUGGESTION_TEXTS,
                        f"banned phrase {required!r} missing from "
                        f"BANNED_SUGGESTION_TEXTS",
                    )

    def test_optional_fields_pass_through_unchanged(self):
        # learning_link and why_it_matters are value-add, not part of
        # the grounding contract. Whatever the LLM produces (or None)
        # survives validation verbatim.
        response = SuggestionsResponse(
            suggestions=[
                Suggestion(
                    kind=SuggestionKind.SKILL,
                    text="FastAPI",
                    evidence=[Citation(job_id="job-a", quote="FastAPI")],
                    learning_link=LearningLink(
                        label="FastAPI tutorial",
                        url="https://fastapi.tiangolo.com/tutorial/",
                    ),
                    why_it_matters=(
                        "Two of your top matches ask for FastAPI "
                        "experience by name."
                    ),
                )
            ]
        )
        accepted = validate_suggestions(
            response, job_descriptions=JOB_DESCRIPTIONS
        )
        self.assertEqual(len(accepted), 1)
        self.assertIsNotNone(accepted[0].learning_link)
        self.assertEqual(accepted[0].learning_link.label, "FastAPI tutorial")
        self.assertEqual(
            accepted[0].learning_link.url,
            "https://fastapi.tiangolo.com/tutorial/",
        )
        self.assertIsNotNone(accepted[0].why_it_matters)
        self.assertIn("FastAPI", accepted[0].why_it_matters)

    def test_optional_fields_default_to_none(self):
        # The LLM is allowed to omit both enrichment fields. The
        # validator must accept those suggestions and they must
        # remain None in the accepted output. (The service-layer
        # post-process that resolves learning_link from the curated
        # table is tested separately in test_learning_links.py.)
        response = SuggestionsResponse(
            suggestions=[
                Suggestion(
                    kind=SuggestionKind.SKILL,
                    text="FastAPI",
                    evidence=[Citation(job_id="job-a", quote="FastAPI")],
                )
            ]
        )
        accepted = validate_suggestions(
            response, job_descriptions=JOB_DESCRIPTIONS
        )
        self.assertEqual(len(accepted), 1)
        self.assertIsNone(accepted[0].learning_link)
        self.assertIsNone(accepted[0].why_it_matters)

    def test_validator_passes_through_llm_learning_link_unchanged(self):
        # The validator itself does NOT consult the curated table —
        # it stays pure (no I/O, no service deps). The table lookup
        # happens in services/suggestions.py:generate_resume_suggestions
        # as a post-process step, which is tested in
        # test_learning_links.py. This test documents the validator's
        # contract: whatever the LLM sent is preserved verbatim.
        # If you change this contract, update test_learning_links.py
        # to assert the new behavior end-to-end.
        response = SuggestionsResponse(
            suggestions=[
                Suggestion(
                    kind=SuggestionKind.SKILL,
                    text="FastAPI",
                    evidence=[Citation(job_id="job-a", quote="FastAPI")],
                    learning_link=LearningLink(
                        label="Some LLM-guessed label",
                        url="https://example.com/llm-guessed",
                    ),
                )
            ]
        )
        accepted = validate_suggestions(
            response, job_descriptions=JOB_DESCRIPTIONS
        )
        self.assertEqual(len(accepted), 1)
        self.assertIsNotNone(accepted[0].learning_link)
        self.assertEqual(accepted[0].learning_link.url, "https://example.com/llm-guessed")

    def test_passes_through_job_context_enrichment_fields(self):
        # Citation.job_title / job_company / apply_url are value-add
        # enrichment fields. The validator must pass them through
        # verbatim so the service-layer post-process in
        # services/suggestions.py can use them as a fallback (see
        # CitationLinkStitchTests below).
        response = SuggestionsResponse(
            suggestions=[
                Suggestion(
                    kind=SuggestionKind.SKILL,
                    text="FastAPI",
                    evidence=[
                        Citation(
                            job_id="job-a",
                            quote="FastAPI",
                            job_title="LLM-sent title",
                            job_company="LLM-sent company",
                            apply_url="https://llm.example/",
                        )
                    ],
                )
            ]
        )
        accepted = validate_suggestions(
            response, job_descriptions=JOB_DESCRIPTIONS
        )
        self.assertEqual(len(accepted), 1)
        citation = accepted[0].evidence[0]
        self.assertEqual(citation.job_title, "LLM-sent title")
        self.assertEqual(citation.job_company, "LLM-sent company")
        self.assertEqual(citation.apply_url, "https://llm.example/")


def _mock_parsed_response(parsed: SuggestionsResponse):
    """Build the mock OpenAI completion object shape that
    `generate_resume_suggestions` reads from
    `completion.choices[0].message.parsed`."""
    return type("Completion", (), {
        "choices": [type("Choice", (), {
            "message": type("Msg", (), {"parsed": parsed})()
        })()]
    })()


class CitationLinkStitchTests(unittest.TestCase):
    """Verifies that `generate_resume_suggestions` overwrites the
    LLM-supplied (or validator-default) job_title / job_company /
    apply_url on each surviving Citation with the authoritative values
    from the user's top matches (the `job_summaries` input).

    The whole point of this post-process is so the UI can render
    "Vercel — Senior Software Engineer ↗" linking to the real job
    posting. If this test ever fails, the UI silently loses the link.
    """

    @patch("app.services.suggestions.suggestions_client")
    def test_overwrites_llm_sent_job_context_with_authoritative_values(
        self, mock_client
    ):
        # Arrange: LLM sends its own (wrong) title/company/apply_url
        # on a citation. The post-process must replace them with the
        # authoritative values from job_summaries.
        mock_response = SuggestionsResponse(
            suggestions=[
                Suggestion(
                    kind=SuggestionKind.SKILL,
                    text="FastAPI",
                    evidence=[
                        Citation(
                            job_id="job-a",
                            quote="FastAPI",
                            job_title="LLM-hallucinated title",
                            job_company="LLM-hallucinated company",
                            apply_url="https://llm-made-this-up.example/",
                        )
                    ],
                )
            ]
        )
        mock_client.beta.chat.completions.parse.return_value = (
            _mock_parsed_response(mock_response)
        )

        job_summaries = [
            {
                "job_id": "job-a",
                "title": "Senior Backend Engineer",
                "company": "Acme",
                "apply_url": "https://acme.example/jobs/123",
                "description_full": "Python, FastAPI, and PostgreSQL.",
                "description_excerpt": "Python, FastAPI, and PostgreSQL.",
            }
        ]

        out = generate_resume_suggestions(
            resume_text="Built APIs in Python.",
            job_summaries=job_summaries,
        )

        self.assertEqual(len(out), 1)
        self.assertEqual(len(out[0].evidence), 1)
        citation = out[0].evidence[0]
        self.assertEqual(citation.job_id, "job-a")
        self.assertEqual(citation.job_title, "Senior Backend Engineer")
        self.assertEqual(citation.job_company, "Acme")
        self.assertEqual(citation.apply_url, "https://acme.example/jobs/123")

    @patch("app.services.suggestions.suggestions_client")
    def test_falls_back_to_llm_values_when_job_not_in_summaries(
        self, mock_client
    ):
        # Edge case: validator approved a citation for a job_id that
        # somehow isn't in our job_summaries (the substring check should
        # usually catch this, but defense-in-depth: the post-process
        # must leave the LLM's values alone rather than wiping them to
        # None when we have nothing authoritative to substitute).
        # We mock validate_suggestions to skip the substring check
        # entirely so we can isolate the post-process behavior.
        with patch(
            "app.services.suggestions.validate_suggestions"
        ) as mock_validate:
            mock_validate.return_value = [
                Suggestion(
                    kind=SuggestionKind.SKILL,
                    text="FastAPI",
                    evidence=[
                        Citation(
                            job_id="job-unknown",
                            quote="FastAPI",
                            job_title="LLM title",
                            job_company="LLM company",
                            apply_url="https://llm.example/",
                        )
                    ],
                )
            ]
            # job_summaries does NOT contain job-unknown — the
            # service-layer job_lookup can't find it.
            job_summaries = [
                {
                    "job_id": "job-a",
                    "title": "Other Job",
                    "company": "Other Co",
                    "apply_url": "https://other.example/",
                    "description_full": "Stuff.",
                    "description_excerpt": "Stuff.",
                }
            ]
            out = generate_resume_suggestions(
                resume_text="Built APIs in Python.",
                job_summaries=job_summaries,
            )
            self.assertEqual(len(out), 1)
            citation = out[0].evidence[0]
            # All three fields preserved as the LLM sent them.
            self.assertEqual(citation.job_title, "LLM title")
            self.assertEqual(citation.job_company, "LLM company")
            self.assertEqual(citation.apply_url, "https://llm.example/")

    @patch("app.services.suggestions.suggestions_client")
    def test_populates_job_context_when_validator_left_it_none(
        self, mock_client
    ):
        # Common case: validator strips everything it can't verify.
        # The post-process then fills in title/company/apply_url from
        # job_summaries so the UI link is present.
        mock_response = SuggestionsResponse(
            suggestions=[
                Suggestion(
                    kind=SuggestionKind.SKILL,
                    text="FastAPI",
                    evidence=[Citation(job_id="job-a", quote="FastAPI")],
                )
            ]
        )
        mock_client.beta.chat.completions.parse.return_value = (
            _mock_parsed_response(mock_response)
        )

        job_summaries = [
            {
                "job_id": "job-a",
                "title": "Senior Backend Engineer",
                "company": "Acme",
                "apply_url": "https://acme.example/jobs/123",
                "description_full": "Python, FastAPI, and PostgreSQL.",
                "description_excerpt": "Python, FastAPI, and PostgreSQL.",
            }
        ]

        out = generate_resume_suggestions(
            resume_text="Built APIs in Python.",
            job_summaries=job_summaries,
        )
        self.assertEqual(len(out), 1)
        citation = out[0].evidence[0]
        self.assertEqual(citation.job_title, "Senior Backend Engineer")
        self.assertEqual(citation.job_company, "Acme")
        self.assertEqual(citation.apply_url, "https://acme.example/jobs/123")

    def test_bullet_coach_grounding_drops_fabricated(self):
        # The LLM's original_text must substring-match one of
        # the parsed-resume entry texts. A bullet pointing at
        # text the LLM invented should be dropped.
        parsed = {
            "sections": [
                {
                    "title": "Work Experience",
                    "entries": [
                        {
                            "title": "Acme Corp",
                            "text": "Built a job matching platform for 5,000 students.",
                        }
                    ],
                }
            ]
        }
        good = CoachBullet(
                bullet_id="b1",
                verdict=CoachBulletVerdict.WEAK,
                original_text="Built a job matching platform",
                weakness_reason="no scale",
                citation_job_id="j1",
                citation_quote="Built a job matching platform",
                questions=[
                    CoachQuestion(
                        key="scale",
                        category=CoachCategory.SCOPE,
                        label="How many?",
                        type=CoachQuestionType.TEXT,
                    )
                ],
            )
        bad = good.model_copy(update={
            "bullet_id": "b2",
            "original_text": "Some completely fabricated bullet",
        })
        accepted = validate_coach_bullet_grounding([good, bad], parsed)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0].bullet_id, "b1")

    def test_bullet_coach_grounding_normalizes_whitespace(self):
        # Whitespace and case differences shouldn't cause
        # legitimate substrings to fail the check.
        parsed = {
            "sections": [
                {
                    "title": "Work Experience",
                    "entries": [
                        {
                            "title": "Acme Corp",
                            "text": "Built a Job Matching Platform.",
                        }
                    ],
                }
            ]
        }
        bullet = CoachBullet(
                bullet_id="b1",
                verdict=CoachBulletVerdict.WEAK,
                original_text="BUILT a job matching platform.",
                weakness_reason="no scale",
                citation_job_id="j1",
                citation_quote="quote",
                questions=[
                    CoachQuestion(
                        key="k",
                        category=CoachCategory.SCOPE,
                        label="L",
                        type=CoachQuestionType.TEXT,
                    )
                ],
            )
        accepted = validate_coach_bullet_grounding([bullet], parsed)
        self.assertEqual(len(accepted), 1)


class StripRewriteResponseTests(unittest.TestCase):
    """The rewrite LLM call uses plain chat.completions (not
    structured outputs) for speed, so the response can come back
    in a few shapes. _strip_rewrite_response handles them all."""

    def test_extracts_from_clean_json(self):
        from app.services.bullet_coach_llm import _strip_rewrite_response
        raw = '{"rewritten_text": "Built X for 5,000 users."}'
        self.assertEqual(
            _strip_rewrite_response(raw, fallback="orig"),
            "Built X for 5,000 users.",
        )

    def test_extracts_from_json_with_prose_around_it(self):
        from app.services.bullet_coach_llm import _strip_rewrite_response
        raw = (
            "Sure! Here you go:\n"
            '{"rewritten_text": "Built X for 5,000 users."}\n'
            "Hope that helps."
        )
        self.assertEqual(
            _strip_rewrite_response(raw, fallback="orig"),
            "Built X for 5,000 users.",
        )

    def test_strips_code_fences(self):
        from app.services.bullet_coach_llm import _strip_rewrite_response
        raw = "```\nBuilt X for 5,000 users.\n```"
        self.assertEqual(
            _strip_rewrite_response(raw, fallback="orig"),
            "Built X for 5,000 users.",
        )

    def test_strips_json_code_fence(self):
        from app.services.bullet_coach_llm import _strip_rewrite_response
        raw = '```json\n{"rewritten_text": "Built X."}\n```'
        self.assertEqual(
            _strip_rewrite_response(raw, fallback="orig"),
            "Built X.",
        )

    def test_returns_raw_bullet_when_no_fences_or_json(self):
        from app.services.bullet_coach_llm import _strip_rewrite_response
        raw = "Built X for 5,000 users using React and Python."
        self.assertEqual(
            _strip_rewrite_response(raw, fallback="orig"),
            "Built X for 5,000 users using React and Python.",
        )

    def test_falls_back_to_original_on_empty(self):
        from app.services.bullet_coach_llm import _strip_rewrite_response
        self.assertEqual(
            _strip_rewrite_response("", fallback="orig bullet"),
            "orig bullet",
        )
        self.assertEqual(
            _strip_rewrite_response("   \n  ", fallback="orig bullet"),
            "orig bullet",
        )


class ExtractAlreadyPresentTests(unittest.TestCase):
    """extract_already_present() builds the prompt's ALREADY_PRESENT
    list. Bugs here cause the LLM to re-suggest skills the candidate
    already has — the original Next.js bug. These tests pin the
    normalizer's behavior so the prompt-side and post-process-side
    check agree on the same tokens."""

    def test_strips_trailing_sentence_period(self):
        # The original bug: "Built apps in Next.js." produced the token
        # "next.js." (with the trailing period from sentence-end glued
        # on). The LLM's filter then failed to match "Next.js" against
        # "next.js." and re-suggested Next.js.
        out = extract_already_present("Built apps in Next.js.")
        self.assertIn("next.js", out)
        self.assertNotIn("next.js.", out)

    def test_strips_trailing_punctuation_variants(self):
        # Periods, commas, semicolons, colons, exclamation, and
        # question marks at the end of a sentence should all be
        # stripped. (Comma is rare at sentence-end but it does happen
        # in resume lines like "Skills: Python, TypeScript, React,".)
        for punct in ".,;:!?":
            with self.subTest(punct=punct):
                token = f"postgresql{punct}"
                text = f"Built apps in {token}"
                out = extract_already_present(text)
                self.assertIn("postgresql", out, f"failed to strip {punct!r}")
                self.assertNotIn(
                    f"postgresql{punct}",
                    out,
                    f"trailing {punct!r} not stripped",
                )

    def test_preserves_internal_dots(self):
        # The word regex `[a-zA-Z][a-zA-Z0-9+#.-]{1,}` matches internal
        # dots, so "next.js" comes through as a single token. The
        # normalizer must NOT collapse internal dots — only strip
        # trailing sentence punctuation.
        out = extract_already_present(
            "Built apps in Next.js, Vue.js, and React.js."
        )
        self.assertIn("next.js", out)
        self.assertIn("vue.js", out)
        self.assertIn("react.js", out)

    def test_handles_repeated_dotted_skill(self):
        # Repetition must not break the dedup.
        out = extract_already_present("Next.js, Next.js, and Next.js again.")
        self.assertEqual(out.count("next.js"), 1)  # set-based dedup

    def test_drops_short_tokens(self):
        # Length filter is still in place — "js" from "Next.js" should
        # not leak in on its own. (Actually the regex captures "next.js"
        # whole, not "next" + "js" — verify both behaviors.)
        out = extract_already_present("Next.js expert")
        # The whole token "next.js" passes; "js" alone would be filtered
        # by length but isn't actually captured by the regex here
        # because the regex is greedy and matches "next.js" first.
        self.assertIn("next.js", out)
        self.assertNotIn("js", out)  # would-be standalone "js" is < 4 chars

    def test_drops_stopwords(self):
        # Generic resume boilerplate like "team" / "work" / "skill"
        # must stay filtered out — the prompt has limited tokens.
        out = extract_already_present(
            "Strong team player with work experience and skill in Python."
        )
        for stop in ["team", "work", "skill", "strong"]:
            self.assertNotIn(stop, out)
        self.assertIn("python", out)


class AlreadyInResumeDefenseTests(unittest.TestCase):
    """End-to-end check: even if the LLM emits a skill that's
    already in the resume (e.g. the prompt-side filter slipped,
    or the LLM is being creative), the post-process in
    generate_resume_suggestions drops it. This is defense-in-depth
    against the Next.js class of bug.

    We mock the OpenAI client to send a fixed suggestion list and
    assert that suggestions overlapping with the resume are dropped
    while non-overlapping ones survive.
    """

    def _mock_openai(self, suggestions):
        """Return a context manager that mocks the LLM to return
        the given suggestions list."""
        from contextlib import contextmanager

        @contextmanager
        def _patch():
            with patch(
                "app.services.suggestions.suggestions_client"
                ".beta.chat.completions.parse"
            ) as mocked:
                from app.schemas.suggestions import (
                    SuggestionsResponse as SR,
                )

                mocked.return_value.choices = [
                    type(
                        "Choice",
                        (),
                        {"message": type("Msg", (), {"parsed": SR(suggestions=suggestions)})()},
                    )()
                ]
                yield mocked

        return _patch()

    def test_drops_skill_already_in_resume(self):
        # The classic Next.js bug. Resume says "Next.js."; LLM
        # somehow suggests Next.js anyway. The post-process drops it.
        from app.schemas.suggestions import Citation, Suggestion

        resume = "Built dashboards in Next.js and TypeScript."
        job = {
            "job_id": "job-x",
            "title": "Frontend Engineer",
            "company": "Acme",
            "apply_url": "https://acme.example/jobs/x",
            "description_excerpt": (
                "We use Next.js, React, and Tailwind CSS for styling."
            ),
            "description_full": (
                "We use Next.js, React, and Tailwind CSS for styling."
            ),
        }
        # LLM suggests Next.js (already in resume) plus Tailwind CSS
        # (NOT in resume — should survive). Each suggestion's quote
        # is a substring of the job description, and the quote
        # shares tokens with the suggestion text so the single-cite
        # token-overlap fallback accepts it.
        suggestions = [
            Suggestion(
                kind=SuggestionKind.SKILL,
                text="Next.js",
                evidence=[
                    Citation(
                        job_id="job-x",
                        quote="We use Next.js, React, and Tailwind CSS for styling.",
                    )
                ],
            ),
            Suggestion(
                kind=SuggestionKind.SKILL,
                text="Tailwind CSS",
                evidence=[
                    Citation(
                        job_id="job-x",
                        quote="Tailwind CSS for styling.",
                    )
                ],
            ),
        ]

        with self._mock_openai(suggestions):
            out = generate_resume_suggestions(
                resume_text=resume,
                job_summaries=[job],
            )

        surviving = [s.text for s in out]
        self.assertNotIn("Next.js", surviving, "Next.js slipped through despite being in resume")
        self.assertIn("Tailwind CSS", surviving, "Tailwind CSS should have survived")

    def test_keeps_near_duplicates_that_are_not_subsets(self):
        # Java in resume, JavaScript suggested. "javascript" is NOT
        # in the resume's ALREADY_PRESENT set, so we MUST keep it.
        # Subset matching is per-token, not per-string.
        from app.schemas.suggestions import Citation, Suggestion

        resume = "Senior engineer with 10 years of Java and Spring Boot."
        job = {
        "job_id": "job-x",
        "title": "Backend Engineer",
        "company": "Acme",
        "apply_url": "https://acme.example/jobs/x",
        "description_excerpt": (
            "We use JavaScript, Java, and Kotlin."
        ),
        "description_full": (
            "We use JavaScript, Java, and Kotlin."
        ),
        }
        suggestions = [
        Suggestion(
            kind=SuggestionKind.SKILL,
            text="JavaScript",
            evidence=[
                Citation(
                    job_id="job-x",
                    quote="We use JavaScript, Java, and Kotlin.",
                )
            ],
        ),
        Suggestion(
            kind=SuggestionKind.SKILL,
            text="Kotlin",
            evidence=[
                Citation(
                    job_id="job-x",
                    quote="We use JavaScript, Java, and Kotlin.",
                )
            ],
        ),
        ]

        with self._mock_openai(suggestions):
            out = generate_resume_suggestions(
                resume_text=resume,
                job_summaries=[job],
            )

        surviving = [s.text for s in out]
        self.assertIn("JavaScript", surviving, "JavaScript should survive even when Java is in resume")
        self.assertIn("Kotlin", surviving)

    def test_drops_sentence_end_dotted_skill(self):
        # Direct test of the trailing-period bug. Resume ends a
        # sentence with "Next.js."; LLM suggests "Next.js"; the
        # post-process must catch it because extract_already_present
        # now normalizes "Next.js." to "next.js".
        from app.schemas.suggestions import Citation, Suggestion

        resume = "Senior frontend engineer. Built apps in Next.js."
        job = {
            "job_id": "job-x",
            "title": "Frontend Engineer",
            "company": "Acme",
            "apply_url": "https://acme.example/jobs/x",
            "description_excerpt": "We use Next.js and React.",
            "description_full": "We use Next.js and React.",
        }
        suggestions = [
            Suggestion(
                kind=SuggestionKind.SKILL,
                text="Next.js",
                evidence=[
                    Citation(job_id="job-x", quote="We use Next.js and React.")
                ],
            ),
        ]

        with self._mock_openai(suggestions):
            out = generate_resume_suggestions(
                resume_text=resume,
                job_summaries=[job],
            )

        self.assertEqual(
            [s.text for s in out],
            [],
            "Next.js (already in resume ending with '.') should have been dropped",
        )





class SubstantiveGroundingTests(unittest.TestCase):
    """The v2 grounding contract: numbers and tech names must be
    sourced; English glue (verbs, articles, prepositions) is free.

    Before this change the validator rejected every natural rewrite
    that used verb conjugations of sourced words ("replacing",
    "enabling", "shipping") or capitalized tech names ("Rust",
    "Python"). The validator now only rejects tokens that look
    like substantive claims -- digits, CamelCase/dot-notation,
    and titlecase tokens that didn't appear in any source.
    """

    def _check(self, rewrite, original, quote, answers, description=None):
        from app.schemas.suggestions import validate_coach_rewrite_grounding
        return validate_coach_rewrite_grounding(
            rewrite,
            original_text=original,
            answers=answers,
            citation_quote=quote,
            citation_description=description or quote,
        )

    def test_verb_conjugations_pass(self):
        ok, reasons = self._check(
            "Owned the rewrite of the auth layer, replacing the "
            "legacy session cookies with JWT and unblocking the "
            "mobile team.",
            "Owned the rewrite of the auth layer.",
            "migrate from session cookies to JWT",
            {
                "replacement": "the legacy session cookies",
                "artifact": "JWT",
                "cause_effect": "unblocking the mobile team",
            },
        )
        self.assertTrue(ok, f"verb conjugation rejected: {reasons}")

    def test_invented_metric_rejected(self):
        ok, reasons = self._check(
            "Reduced latency by 99% across 50k users.",
            "Reduced latency.",
            "improve latency",
            {"scope": "50 users"},
        )
        self.assertFalse(ok)
        joined = " ".join(reasons)
        self.assertIn("99", joined)
        self.assertIn("50k", joined)

    def test_invented_camelcase_tech_name_rejected(self):
        """Fabricated CamelCase tech names (no source match) must
        be flagged. Replaces the older 'Rust and Python' variant
        which relied on the single-word Capitalized scan that was
        removed (it false-positived on past-tense verbs like
        'Developed')."""
        ok, reasons = self._check(
            # PureTech is fabricated -- not in original, not in
            # the quote, not in any answer. FakeTech is in the
            # quote and would normally ground it; we moved it to
            # the user's answer so the test isolates the
            # fabricated case. Both are CamelCase so the scan
            # catches them.
            "Built the matching algorithm in PureTech and FakeTech.",
            "Built the matching algorithm.",
            "matching algorithm",
            {"artifact": "FakeTech"},
        )
        self.assertFalse(ok)
        joined = " ".join(reasons)
        self.assertIn("puretech", joined.lower())

    def test_user_mentioned_tech_passes(self):
        # Single-word tech name (Rust) mentioned in the user's
        # answer. CamelCase scan doesn't catch this and the
        # category-coverage validator catches fabricated single-
        # word tech names used to fill category answers. This
        # test verifies the user-grounded path still works.
        ok, reasons = self._check(
            "Built the matching algorithm in Rust.",
            "Built the matching algorithm.",
            "matching algorithm",
            {"artifact": "Rust"},
        )
        self.assertTrue(ok, f"user-mentioned tech rejected: {reasons}")

    def test_camelcase_tech_passes_when_sourced(self):
        ok, reasons = self._check(
            "Built the API in FastAPI and PostgreSQL.",
            "Built the API.",
            "design a FastAPI service",
            {
                "artifact": "FastAPI",
                "specificity": "PostgreSQL schema",
            },
        )
        self.assertTrue(
            ok, f"sourced CamelCase tech rejected: {reasons}"
        )

    def test_mid_sentence_capitalized_verb_not_flagged(self):
        """Regression for the user's most recent report: a past-
        tense verb in mid-sentence ('Developed', 'Designed')
        used to be flagged as fabricated because the single-word
        Capitalized scan couldn't distinguish it from a tech name.

        After removing that scan, only true CamelCase tokens
        (with mid-word uppercase) get flagged. Plain mid-sentence
        verbs pass through without grounding checks -- they're
        connective content, not substantive claims.
        """
        ok, reasons = self._check(
            "Built a thing for our cohort, developed end to end "
            "during the cohort's run, designed to scale.",
            "Built a thing.",
            "build a thing for a cohort",
            {"scope": "our cohort"},
        )
        self.assertTrue(
            ok, f"mid-sentence past-tense verb wrongly rejected: "
            f"{reasons}"
        )

    def test_invented_camelcase_rejected(self):
        """A CamelCase name that appears in NEITHER the original
        nor the user's answers (only in the cited quote is NOT
        enough -- see the job-only check for that path) gets
        flagged as fabricated.

        Original test fixture used 'FastAPI' (which the user
        mentioned in their answer -- fabricated-name check would
        not fire) and 'Kafka' (single-word, no longer in scope
        post single-word Capitalized-scan removal). Both replaced
        with CamelCase fabricated names so the scan catches them.
        """
        ok, reasons = self._check(
            "Built the API in CoreLib and SideLib streams.",
            "Built the API.",
            "design a FastAPI service",
            {"artifact": "FastAPI"},  # FastAPI in answer grounds it
        )
        self.assertFalse(ok)
        joined = " ".join(reasons)
        # Both fabricated names should be flagged.
        self.assertIn("corelib", joined.lower())
        self.assertIn("sidelib", joined.lower())

    def test_mid_sentence_tech_from_job_only_quote_flagged(self):
        """Regression for the user's recent report: the LLM took a
        tech name (PyTorch) from the cited job quote and appended
        it to a rewrite where the candidate never used PyTorch.
        Before this fix, tokenization lowercased the CamelCase
        token and the rewrite-side substance check missed it
        entirely -- the rewrite was returned with a fabricated
        claim the user couldn't catch from the UI.

        After the fix: PyTorch is detected via raw-text CamelCase
        scan, classified as "job-only" (in the cited quote but
        not in the user's answers or original bullet), and the
        validator surfaces it with a specific reason so the UI can
        tell the user which tech name came from the job posting
        rather than their experience.
        """
        ok, reasons = self._check(
            # CamelCase "PyTorch" mid-sentence, only in the cited
            # quote -- not in the original bullet, not in any user
            # answer.
            "Built the matching algorithm for students while "
            "optimizing PyTorch models end to end.",
            "Built a thing.",  # original bullet, no tech
            "designing, reviewing, and optimizing PyTorch models",  # quote
            {
                "scope": "students",
                "artifact": "the matching algorithm",
            },
        )
        self.assertFalse(ok, f"rewrite slipped through: {reasons}")
        joined = " ".join(reasons)
        # Specific reason naming the fabrication mode.
        self.assertIn("pytorch", joined.lower())
        # Validator explicitly calls out job-vs-user sourcing.
        self.assertIn("cited job", joined.lower())

    def test_user_mentioned_pytorch_passes(self):
        """Negative test for the user's report: if the user MENTIONS
        PyTorch in their answer (or original bullet), the rewrite
        using PyTorch must pass. The split into user-supplied vs
        job-supplied stems means a rewrite-token-stem in
        user_supplied_stems is grounded -- not flagged as
        job-only."""
        ok, reasons = self._check(
            "Built the matching algorithm using PyTorch for the cohort.",
            "Built a thing.",
            "designing, reviewing, and optimizing PyTorch models",
            {
                "scope": "students",
                "artifact": "the matching algorithm using PyTorch",
            },
        )
        self.assertTrue(
            ok, f"user-grounded tech rejected: {reasons}"
        )

    def test_sentence_initial_verb_not_flagged(self):
        """Negative test for the position-filter heuristic: a
        rewrite that starts with a verb ("Built") should not
        flag "built" as a fabricated substantive token. The
        previous validator fired on every verb-led rewrite; this
        test guards against regressing to that behavior.
        """
        ok, reasons = self._check(
            "Built the matching platform end to end for our cohort.",
            "Designed a thing.",
            "build a matching platform",
            {"scope": "our cohort"},
        )
        self.assertTrue(
            ok, f"verb-led rewrite wrongly rejected: {reasons}"
        )

    def test_sentence_initial_ensured_not_flagged(self):
        """Regression for the user-reported 502 on `/coach/rewrite`:
        the LLM occasionally opens a rewrite with "Ensured [the
        team]..." -- a common resume-bullet verb. "Ensured" matched
        the single-word-Cap regex, fell through to rule 2's
        source-bucket check, and was flagged as fabricated because
        it didn't appear in {original, citation_quote, answers}.
        Now in `_ENGLISH_PAST_PARTICIPLES` so it never reaches the
        substantive token set. To revert: drop "ensured" from the
        safelist and this test fails.
        """
        ok, reasons = self._check(
            "Ensured the cohort had a working pipeline.",
            "Built a thing.",
            "Looking for someone to design pipelines.",
            {"scope": "the cohort"},
        )
        fabrication_reasons = [
            r for r in reasons
            if "substantive claims" in r
        ]
        self.assertEqual(
            fabrication_reasons,
            [],
            f"rewrite opening with 'Ensured' should not trigger "
            f"rule 2's substantive-claims fabrication flag; "
            f"got reasons: {reasons}",
        )

    def test_sentence_initial_inflected_verbs_filtered_by_stem_match(self):
        """Regression: the user reported a 502 with 'Creating'
        after the 'ensured' fix landed. Per-verb additions to the
        safelist are whack-a-mole -- the LLM uses many verb
        forms. The matcher now does a STEM-MATCH fallback against
        `_ENGLISH_PAST_PARTICIPLE_STEMS` so a single past-participle
        entry (e.g. 'created') catches 'creates', 'created', and
        'creating' (all stem to 'creat'). This test pins the
        systemic coverage for the three common inflections across
        several verbs the LLM commonly leads sentences with.
        To revert: drop the `_ENGLISH_PAST_PARTICIPLE_STEMS`
        block + the stem-match check in `_detect_tech_tokens`,
        and these failures come back.
        """
        cases = [
            ("Creating", "Created the matching platform"),
            ("Manages", "Managed the auth layer end to end"),
            ("Designing", "Designed the data model from scratch"),
            ("Deploys", "Deployed the service to production"),
            ("Testing", "Tested the pipeline under load"),
            ("Building", "Built the API in 2 weeks"),
            ("Leading", "Led the migration off the legacy system"),
        ]
        for led_verb, source_phrase in cases:
            with self.subTest(verb=led_verb):
                # Construct a rewrite that opens with the verb
                # form, and a source set where the past-participle
                # variant is sourced but the led-verb form isn't.
                rewrite = f"{led_verb} the {source_phrase.lower()}."
                ok, reasons = self._check(
                    rewrite,
                    source_phrase + ".",
                    "Looking for someone to do work.",
                    {"scope": "the team"},
                )
                fabrication_reasons = [
                    r for r in reasons
                    if "substantive claims" in r
                ]
                self.assertEqual(
                    fabrication_reasons,
                    [],
                    f"rewrite opening with '{led_verb}' should "
                    f"not trigger rule 2's substantive-claims "
                    f"fabrication flag (stem of {led_verb!r} "
                    f"should match the past-participle entry in "
                    f"the safelist). Got reasons: {reasons}",
                )


class CategoryCoverageSubstantiveOverlapTests(unittest.TestCase):
    """The category-coverage validator's overlap rule uses stems
    (not exact tokens) and filters out structural / glue words
    before comparing. This class verifies the v2 behavior:

      - "customer" in answer satisfies "customers" in rewrite
        (stem match).
      - Pure structural answers ("the and of") don't count as a
        fingerprint, but also don't fail the check (soft skip).
      - Empty answers are a soft skip (not a hard failure) since
        the UI button guards against this in normal flow.

    These three together closed a UX gap where the validator
    rejected answers that contained only common-English words,
    and accepted rewrites that happened to share a single
    article like "the".
    """

    def _check(
        self,
        rewrite_text,
        *,
        questions,
        answers,
        skipped=None,
        category_gaps=None,
    ):
        from app.schemas.suggestions import (
            validate_coach_rewrite_category_coverage,
        )
        return validate_coach_rewrite_category_coverage(
            rewrite_text,
            questions=questions,
            answers=answers,
            skipped_categories=skipped or [],
            category_gaps=category_gaps,
        )

    def _q(self, key, category):
        from app.schemas.suggestions import (
            CoachQuestion, CoachCategory,
        )
        return CoachQuestion(
            key=key,
            category=category,
            label=f"label-{key}",
        )

    def test_inflection_in_answer_matches_rewrite(self):
        """'customers' in answer satisfies 'customers' stem in
        the rewrite (stem-match handles plurals)."""
        from app.schemas.suggestions import CoachCategory
        questions = [self._q("scope", CoachCategory.SCOPE)]
        ok, reasons = self._check(
            "Built a platform for customers at the cohort.",
            questions=questions,
            answers={"scope": "customers at our cohort"},
        )
        self.assertTrue(
            ok, f"inflection rejected: {reasons}"
        )

    def test_inflection_in_rewrite_matches_answer(self):
        """'customer' in answer satisfies 'customers' stem in the
        rewrite -- the stem path goes both ways."""
        from app.schemas.suggestions import CoachCategory
        questions = [self._q("scope", CoachCategory.SCOPE)]
        ok, reasons = self._check(
            "Built a platform for customers at the cohort.",
            questions=questions,
            answers={"scope": "customer"},
        )
        self.assertTrue(
            ok, f"inflection (answer=plural, rewrite=singular) "
            f"rejected: {reasons}"
        )

    def test_structural_only_answer_is_soft_skip(self):
        """A pure-structural answer ('the and of') has no
        substantive fingerprint. The validator must NOT fail on
        this -- it's an empty-fingerprint case, not a fabrication.
        This is the documented behavior: empty / all-structural
        answers are soft-skipped."""
        from app.schemas.suggestions import CoachCategory
        questions = [self._q("scope", CoachCategory.SCOPE)]
        ok, reasons = self._check(
            "Built a thing for the cohort.",
            questions=questions,
            answers={"scope": "the and of"},
            category_gaps=[CoachCategory.SCOPE],
        )
        self.assertTrue(
            ok, f"structural-only answer wrongly rejected: "
            f"{reasons}"
        )

    def test_empty_answer_is_soft_skip(self):
        """Empty answer string is a documented soft skip --
        validator must not reject the rewrite, even when
        category_gaps requires the category to have content."""
        from app.schemas.suggestions import CoachCategory
        questions = [self._q("scope", CoachCategory.SCOPE)]
        ok, reasons = self._check(
            "Built a thing.",
            questions=questions,
            answers={"scope": ""},  # empty string
            category_gaps=[CoachCategory.SCOPE],
        )
        self.assertTrue(
            ok, f"empty answer wrongly rejected: {reasons}"
        )

    def test_substantive_answer_with_structural_match_alone_rejected(
        self,
    ):
        """A substantive answer ('inventory dashboard') that
        shares ONLY structural / glue words with the rewrite is
        a real coverage failure -- the LLM didn't echo the
        user's substantive terms. This is the case stem-based
        + structural-filter was designed to catch."""
        from app.schemas.suggestions import CoachCategory
        questions = [self._q("artifact", CoachCategory.ARTIFACT)]
        ok, reasons = self._check(
            "Built a thing end-to-end.",  # nothing about dashboard
            questions=questions,
            answers={"artifact": "the inventory dashboard"},
        )
        self.assertFalse(
            ok, "substantive answer must fail when rewrite has "
            "no overlapping non-structural stems"
        )

    def test_substantive_overlap_passes(self):
        from app.schemas.suggestions import CoachCategory
        questions = [self._q("artifact", CoachCategory.ARTIFACT)]
        ok, reasons = self._check(
            "Built the inventory dashboard for ops.",
            questions=questions,
            answers={"artifact": "inventory dashboard"},
        )
        self.assertTrue(
            ok, f"substantive overlap rejected: {reasons}"
        )





class CitationGroundingTests(unittest.TestCase):
    """Drop WEAK bullets whose citation_quote isn't a substring of
    the cited job's description. This catches the LLM's habit of
    fabricating a quote -- typically by echoing the user's answer
    rather than pulling from the job posting.

    Without this check, the bad quote lands in the session and
    surfaces as a confusing 502 on /coach/rewrite, AFTER the user
    has invested time answering the questions. Better to drop the
    bullet at /coach/start.
    """

    def _weak(self, citation_job_id, citation_quote):
        from app.schemas.suggestions import (
            CoachBullet, CoachBulletVerdict, CoachQuestion,
            CoachCategory, CoachQuestionType,
        )
        return CoachBullet(
            bullet_id="b1",
            verdict=CoachBulletVerdict.WEAK,
            original_text="Built a job matching platform for the cohort.",
            weakness_reason="No audience detail",
            citation_job_id=citation_job_id,
            citation_quote=citation_quote,
            questions=[
                CoachQuestion(
                    key="scope",
                    category=CoachCategory.SCOPE,
                    label="Who used it?",
                    type=CoachQuestionType.TEXT,
                )
            ],
        )

    def _strong(self, citation_job_id, citation_quote):
        from app.schemas.suggestions import (
            CoachBullet, CoachBulletVerdict,
        )
        return CoachBullet(
            bullet_id="b1",
            verdict=CoachBulletVerdict.STRONG,
            original_text="Reduced p99 latency by 40% across 50k MAU.",
            strength_reason="Already has metric and scope.",
            citation_job_id=citation_job_id,
            citation_quote=citation_quote,
        )

    def test_unrelated_quote_fails_grounding_helpers(self):
        # Grounding-behavior test for the lower-level helpers.
        # An unrelated quote ("frontier AI labs to train LLMs")
        # against a backend-engineer JD with no AI-lab language
        # must NOT pass the strict-substring check, must score 0
        # on the relaxed stem-overlap ratio, and must therefore
        # fail `_citation_is_grounded` at any sane threshold. The
        # route-level validator currently keeps such bullets as a
        # deliberate experimental-feature policy, so this test
        # pins the helpers themselves so they remain correct --
        # any future re-tightening of the route to drop
        # fabricated quotes will reuse these helpers and they
        # must still do the right thing.
        from app.schemas.suggestions import (
            _quote_is_substring,
            _citation_grounding_score,
            _citation_is_grounded,
        )

        quote = "frontier AI labs to train LLMs"
        description = "Looking for an engineer to design REST APIs."

        self.assertFalse(
            _quote_is_substring(quote, description),
            "unrelated quote should not substring-match the JD",
        )
        self.assertEqual(
            _citation_grounding_score(quote, description),
            0.0,
            "unrelated quote should score 0 on the stem-overlap "
            "ratio (no shared content vocabulary)",
        )
        self.assertFalse(
            _citation_is_grounded(quote, description),
            "unrelated quote must not be considered grounded by "
            "the relaxed check -- the helper behaves correctly "
            "even though the route currently chooses not to gate "
            "on it",
        )

    def test_real_quote_passes_substring_helper(self):
        from app.schemas.suggestions import _quote_is_substring

        quote = "Built a job matching platform"
        description = (
            "Looking for someone. Built a job matching platform "
            "for internal use."
        )
        self.assertTrue(
            _quote_is_substring(quote, description),
            "verbatim substring of the JD should pass the helper",
        )

    def test_strong_bullets_skip_the_check(self):
        # STRONG bullets don't go through /coach/rewrite, so a
        # bad citation_quote there is cosmetic. The validator
        # should NOT drop STRONG bullets -- the user still sees
        # the "✓ Already strong" positive feedback.
        from app.schemas.suggestions import validate_coach_citation_grounding

        bullet = self._strong(
            citation_job_id="job-aaa",
            citation_quote="some made-up quote that isn't in any job",
        )
        job_descriptions = {
            "job-aaa": "Looking for a backend engineer with Python.",
        }
        accepted = validate_coach_citation_grounding(
            [bullet], job_descriptions
        )
        self.assertEqual([b.bullet_id for b in accepted], ["b1"])

    def test_missing_job_description_keeps_bullet(self):
        # Best-effort: if we don't have the cited job's description
        # (e.g. job purged from Turso), we can't prove fabrication
        # either way. Keep the bullet.
        from app.schemas.suggestions import validate_coach_citation_grounding

        bullet = self._weak(
            citation_job_id="job-missing",
            citation_quote="any quote",
        )
        job_descriptions = {}  # job-missing not present
        accepted = validate_coach_citation_grounding(
            [bullet], job_descriptions
        )
        self.assertEqual([b.bullet_id for b in accepted], ["b1"])

    def test_normalized_substring_tolerates_case_and_whitespace(self):
        # _quote_is_substring normalizes both sides (lowercase +
        # whitespace-collapsed) before the substring check, so
        # a quote with extra spaces and uppercase letters
        # still matches a JD that uses the canonical form.
        from app.schemas.suggestions import _quote_is_substring

        # Original case + spacing on the JD side; LLM-returned
        # quote with extra spaces and uppercase on the other.
        quote = "Built  a  JOB matching platform"
        description = "Built a job matching platform for internal use."
        self.assertTrue(
            _quote_is_substring(quote, description),
            "case + whitespace differences should not block the "
            "substring check",
        )
        # And the inverse direction is also normalized: quote in
        # the canonical form, description with extra spaces.
        quote2 = "Built a job matching platform"
        description2 = "Built  a  job  matching platform for internal use."
        self.assertTrue(
            _quote_is_substring(quote2, description2),
            "extra whitespace on the JD side should not block "
            "either -- normalization is symmetric",
        )

    def test_normalized_substring_tolerates_unicode_and_trailing_punct(self):
        """Regression for the user's reported 502: same quote
        logic at start and rewrite time should produce the same
        result. When it didn't, the underlying cause was that
        _normalize didn't handle either of two legitimate
        variations:

        (1) Unicode: the LLM produces smart quotes (\u2019, \u201c)
            and em-dashes, while job descriptions scraped from
            career sites often have straight quotes and hyphens.
            Same visual text, different code points -- substring
            check fails.
        (2) Trailing period: the LLM quotes a sentence with a
            period; the matching source text doesn't have that
            trailing period (it might be mid-sentence where the
            quote was lifted from).

        Both are now folded by _normalize's NFKC + side-punct
        strip before substring matching.
        """
        from app.schemas.suggestions import _quote_is_substring

        # (1) Smart-quote + em-dash in the quote; straight-quote +
        # ASCII hyphens in the source. _normalize applies NFKC +
        # manual em-dash replacement to make these comparable.
        quote_unicode = "we \u201cbuild\u201d with care \u2014 the team."
        description_ascii = 'we "build" with care -- the team'
        self.assertTrue(
            _quote_is_substring(quote_unicode, description_ascii),
            "smart quotes + em-dash should match straight quotes "
            "+ ASCII hyphens via NFKC + manual punctuation fold",
        )
        # Inverse: ASCII quote with curly-quote + em-dash source.
        self.assertTrue(
            _quote_is_substring(
                'we "build" with care -- the team',
                "we \u201cbuild\u201d with care \u2014 the team.",
            ),
            "normalization is symmetric across both sides",
        )

        # (2) Trailing period in the quote; no period at the
        # matching point in source. Side-punct strip handles this
        # without affecting the rest of the string.
        quote_with_period = "Built a job matching platform."
        description_without_period = (
            "Looking for engineers. Built a job matching platform "
            "for internal use."
        )
        self.assertTrue(
            _quote_is_substring(quote_with_period, description_without_period),
            "trailing-period mismatch should not fail the substring check",
        )

    def test_paraphrase_with_high_overlap_passes_relaxed_helper(self):
        """A quote that paraphrases the JD but preserves its
        vocabulary should score well on the relaxed stem-overlap
        ratio and pass `_citation_is_grounded` at the current
        CITATION_GROUNDING_THRESHOLD. Pins the helper behavior so
        future threshold changes don't silently regress the
        relaxed-policy path.
        """
        from app.schemas.suggestions import (
            _citation_grounding_score,
            _citation_is_grounded,
            CITATION_GROUNDING_THRESHOLD,
        )

        # Quote paraphrases the JD's substance but isn't a verbatim
        # substring. Stem overlap is high.
        quote = (
            "Annotated and validated machine learning datasets "
            "while maintaining high labeling accuracy and "
            "adherence to QA guidelines across hundreds of "
            "annotations."
        )
        description = (
            "We are hiring an ML Data Operations specialist to "
            "annotate and validate machine learning datasets. "
            "You will maintain high labeling accuracy, adhere to "
            "QA guidelines, and review annotations across "
            "hundreds of examples per day."
        )
        score = _citation_grounding_score(quote, description)
        self.assertGreaterEqual(
            score,
            CITATION_GROUNDING_THRESHOLD,
            f"sanity: a genuine paraphrase should score at or "
            f"above the relaxed threshold (got {score:.2f}, "
            f"threshold {CITATION_GROUNDING_THRESHOLD:.2f}). "
            f"If this drops, the diagnostic log on /coach/rewrite "
            f"loses signal and the helpers no longer distinguish "
            f"paraphrase from fabrication.",
        )
        self.assertTrue(
            _citation_is_grounded(quote, description),
            "high-overlap paraphrase should pass the relaxed "
            "check at the configured threshold",
        )

    def test_fabricated_quote_fails_relaxed_helper(self):
        """A quote fabricated from thin air (no shared content
        vocabulary with the JD) must score 0 on the relaxed
        stem-overlap ratio and therefore fail
        `_citation_is_grounded` at any sane threshold. The
        route-level validator currently keeps such bullets as a
        deliberate experimental-feature policy, so this test pins
        the helper behavior -- any future re-tightening of the
        route to drop fabricated quotes will reuse these helpers
        and they must still do the right thing.
        """
        from app.schemas.suggestions import (
            _citation_grounding_score,
            _citation_is_grounded,
        )

        # Quote is fabricated from thin air -- no shared content
        # vocabulary with the JD.
        quote = (
            "Frontier AI labs to train LLMs on cutting edge "
            "research with novel architectures."
        )
        description = (
            "We are hiring a backend engineer to design REST "
            "APIs and maintain PostgreSQL databases."
        )
        self.assertEqual(
            _citation_grounding_score(quote, description),
            0.0,
            "fabricated quote must score 0 (no shared content stems)",
        )
        self.assertFalse(
            _citation_is_grounded(quote, description),
            "fabricated quote must not be considered grounded by "
            "the relaxed check -- the helper stays correct even "
            "though the route currently chooses not to gate on it",
        )


class OverstrongClassificationTests(unittest.TestCase):
    """Server-side safety net for gpt-4o-mini over-classifying
    STRONG. When the LLM returns all-STRONG for a thin resume,
    the user has no WEAK bullets to workshop on. The heuristic
    reclassify_overstrong_bullets demotes thin STRONG bullets
    server-side, synthesizing fallback questions."""

    def _strong(self, bullet_id, original_text):
        from app.schemas.suggestions import (
            CoachBullet, CoachBulletVerdict,
        )
        return CoachBullet(
            bullet_id=bullet_id,
            verdict=CoachBulletVerdict.STRONG,
            original_text=original_text,
            strength_reason="Already a strong bullet.",
            citation_job_id="job-aaa",
            citation_quote="a verbatim substring of job description",
        )

    def _weak(self, bullet_id, original_text, questions):
        from app.schemas.suggestions import (
            CoachBullet, CoachBulletVerdict, CoachQuestion,
            CoachQuestionType, CoachCategory,
        )
        return CoachBullet(
            bullet_id=bullet_id,
            verdict=CoachBulletVerdict.WEAK,
            original_text=original_text,
            weakness_reason="Missing dimensions.",
            questions=questions,
            citation_job_id="job-aaa",
            citation_quote="a verbatim substring of job description",
        )

    def test_thin_strong_bullet_demoted(self):
        from app.schemas.suggestions import reclassify_overstrong_bullets
        # No audience, no outcome, no ownership, no artifact --
        # the LLM marked it STRONG anyway. Server should demote.
        bullets = [self._strong(
            "b1",
            "Built a job matching platform.",
        )]
        out = reclassify_overstrong_bullets(bullets)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].verdict.value, "WEAK")
        # Synthesizes at least one fallback question.
        self.assertGreater(len(out[0].questions), 0)

    def test_genuinely_strong_bullet_untouched(self):
        from app.schemas.suggestions import reclassify_overstrong_bullets
        # Has artifact (API), audience (users), ownership (built),
        # outcome (cutting ticket time). PASSES heuristic.
        bullets = [self._strong(
            "b1",
            "Built the matching API serving 5k users, cutting "
            "ticket resolution time by 30% for internal teams.",
        )]
        out = reclassify_overstrong_bullets(bullets)
        self.assertEqual(out[0].verdict.value, "STRONG")

    def test_weak_bullets_passthrough(self):
        from app.schemas.suggestions import (
            reclassify_overstrong_bullets,
            CoachCategory, CoachQuestion, CoachQuestionType,
        )
        # Healthy mix: at least one WEAK. Heuristic leaves both
        # STRONG and WEAK alone.
        q = CoachQuestion(
            key="scope", category=CoachCategory.SCOPE,
            label="Who used it?", type=CoachQuestionType.TEXT,
        )
        bullets = [
            self._weak("b1", "Built a thing.", [q]),
            self._strong(
                "b2",
                "Built the matching API serving 5k users, "
                "cutting ticket time 30%.",
            ),
        ]
        out = reclassify_overstrong_bullets(bullets)
        verdicts = sorted([b.verdict.value for b in out])
        self.assertEqual(verdicts, ["STRONG", "WEAK"])
        # WEAK bullet keeps its original question.
        self.assertEqual(out[0].questions[0].key, "scope")

    def test_falls_back_to_ownership_when_no_checklist(self):
        from app.schemas.suggestions import reclassify_overstrong_bullets
        # No checklist on the bullet -- heuristic picks
        # OWNERSHIP as the highest-leverage missing category.
        bullets = [self._strong(
            "b1",
            "Built something internally.",
        )]
        out = reclassify_overstrong_bullets(bullets)
        cats = [q.category.value for q in out[0].questions]
        self.assertEqual(len(cats), len(set(cats)),
                         "synthesized questions should have unique categories")


if __name__ == "__main__":
    unittest.main()
