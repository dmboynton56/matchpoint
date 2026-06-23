"""Tests for the user-message builder in services/suggestions.py.

Specifically: the PREFERRED_SKILLS block that biases the LLM toward
skills we can resolve to a curated learning link. The list must be
present, must list actual keys from the table, and must NOT list
internal names that the LLM would mistake for skill suggestions.
"""

import unittest

from app.services.learning_links import FREE_DOCS_LINKS, canonical_keys
from app.services.suggestions import _build_user_message, SYSTEM_PROMPT


class PreferredSkillsBlockTests(unittest.TestCase):
    def test_user_message_contains_preferred_skills_header(self):
        msg = _build_user_message(
            resume_text="I built APIs in Python.",
            already_present=[],
            job_summaries=[],
        )
        self.assertIn("PREFERRED_SKILLS", msg)

    def test_user_message_lists_known_skill_keys(self):
        msg = _build_user_message(
            resume_text="x",
            already_present=[],
            job_summaries=[],
        )
        # Spot-check a handful of keys that should appear in the block.
        for skill in ("python", "fastapi", "postgresql", "docker", "react"):
            self.assertIn(skill, msg)

    def test_user_message_does_not_list_flatiron_strings(self):
        msg = _build_user_message(
            resume_text="x",
            already_present=[],
            job_summaries=[],
        )
        # These are internal names. The LLM should never see them
        # as candidate skills.
        self.assertNotIn("flatiron-software-engineering", msg)
        self.assertNotIn("flatiron-cybersecurity", msg)

    def test_user_message_promised_in_system_prompt(self):
        # The system prompt tells the LLM to expect a PREFERRED_SKILLS
        # block in the user message. If the system prompt ever changes
        # to remove that promise, this test fails — both pieces must
        # stay in sync.
        self.assertIn("PREFERRED_SKILLS", SYSTEM_PROMPT)
        self.assertIn("TIEBREAKER", SYSTEM_PROMPT)

    def test_system_prompt_blacklists_category_phrases(self):
        # The validator drops suggestions whose text is in
        # BANNED_SUGGESTION_TEXTS. The system prompt must tell the
        # LLM about this so it doesn't emit the phrases in the first
        # place. This is the contract between prompt and validator —
        # both sides have to agree on the same list, and this test
        # catches a future prompt edit that removes the warning.
        self.assertIn("BLACKLIST", SYSTEM_PROMPT)
        # The most common offender — "AI" alone — must be explicitly
        # named, not just implied.
        self.assertIn('"AI"', SYSTEM_PROMPT)
        # The validator-side list is the source of truth. The prompt
        # should mention every entry that's actually banned, so the
        # LLM has a chance to comply before the validator drops it.
        # We check a representative subset to avoid coupling this
        # test to every specific phrase in the list.
        from app.schemas.suggestions import BANNED_SUGGESTION_TEXTS
        for required in {"ai", "ml", "machine learning", "data science"}:
            with self.subTest(phrase=required):
                # Prompt mentions the phrase (case-insensitive).
                self.assertIn(
                    required,
                    SYSTEM_PROMPT.lower(),
                    f"banned phrase {required!r} missing from system prompt",
                )

    def test_block_lists_every_canonical_key(self):
        # Strong invariant: every key in canonical_keys() must appear
        # in the user message. If one is missing, the LLM has no idea
        # we can link to it and may pass it over.
        msg = _build_user_message(
            resume_text="x",
            already_present=[],
            job_summaries=[],
        )
        for key in canonical_keys():
            self.assertIn(
                key,
                msg,
                f"key {key!r} missing from PREFERRED_SKILLS block",
            )

    def test_block_count_matches_table_size(self):
        # Regression guard: the block is the only place the LLM learns
        # the size of our curated table. If they drift apart, the LLM
        # has a false sense of coverage.
        msg = _build_user_message(
            resume_text="x",
            already_present=[],
            job_summaries=[],
        )
        # The block lives in the "PREFERRED_SKILLS (..." section. The
        # comma-separated list of skills follows the header. Count the
        # skills in that block by splitting on ", " and comparing to
        # the table.
        block_start = msg.find("PREFERRED_SKILLS")
        block_end = msg.find("\nJOB EVIDENCE")
        block = msg[block_start:block_end]
        # Strip the header line ("PREFERRED_SKILLS (...):\n") and split.
        body = block.split(":\n", 1)[1]
        listed = [s.strip() for s in body.split(",")]
        self.assertEqual(len(listed), len(FREE_DOCS_LINKS))


if __name__ == "__main__":
    unittest.main()
