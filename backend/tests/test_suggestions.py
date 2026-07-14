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

    def test_invented_tech_name_rejected(self):
        ok, reasons = self._check(
            "Built the matching algorithm in Rust and Python.",
            "Built the matching algorithm.",
            "matching algorithm",
            {"artifact": "the matching algorithm"},
        )
        self.assertFalse(ok)
        joined = " ".join(reasons)
        self.assertIn("rust", joined.lower())

    def test_user_mentioned_tech_passes(self):
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

    def test_invented_camelcase_rejected(self):
        ok, reasons = self._check(
            "Built the API in FastAPI and Kafka.",
            "Built the API.",
            "design a FastAPI service",
            {"artifact": "FastAPI"},
        )
        self.assertFalse(ok)
        joined = " ".join(reasons)
        self.assertIn("kafka", joined.lower())





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

    def test_drops_bullet_with_fabricated_quote(self):
        # The bug from production: the LLM echoed the user's
        # answer ("frontier AI labs to train LLMs") as the
        # citation quote, but the cited job description is
        # about backend APIs and doesn't mention frontier AI.
        from app.schemas.suggestions import validate_coach_citation_grounding

        bullet = self._weak(
            citation_job_id="job-aaa",
            citation_quote="frontier AI labs to train LLMs",
        )
        job_descriptions = {
            "job-aaa": "Looking for an engineer to design REST APIs.",
        }
        accepted = validate_coach_citation_grounding(
            [bullet], job_descriptions
        )
        self.assertEqual(accepted, [])

    def test_keeps_bullet_with_real_quote(self):
        from app.schemas.suggestions import validate_coach_citation_grounding

        bullet = self._weak(
            citation_job_id="job-aaa",
            citation_quote="Built a job matching platform",
        )
        job_descriptions = {
            "job-aaa": "Looking for someone. Built a job matching platform for internal use.",
        }
        accepted = validate_coach_citation_grounding(
            [bullet], job_descriptions
        )
        self.assertEqual([b.bullet_id for b in accepted], ["b1"])

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

    def test_quote_matching_is_case_insensitive_and_whitespace_tolerant(self):
        # _quote_is_substring normalizes both sides (lowercase +
        # whitespace-collapsed). Verify the check tolerates the
        # common case where the LLM reformatted the quote slightly.
        from app.schemas.suggestions import validate_coach_citation_grounding

        bullet = self._weak(
            citation_job_id="job-aaa",
            citation_quote="Built  a  JOB matching platform",  # extra spaces + caps
        )
        job_descriptions = {
            "job-aaa": "Built a job matching platform for internal use.",
        }
        accepted = validate_coach_citation_grounding(
            [bullet], job_descriptions
        )
        self.assertEqual([b.bullet_id for b in accepted], ["b1"])



if __name__ == "__main__":
    unittest.main()
