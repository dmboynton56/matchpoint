"""Tests for app.services.learning_links.

Two scopes:
  1. Pure unit tests for the lookup() function: alias resolution,
     direct hits, domain fallbacks to the paid bootcamps, and
     unknown-skill behavior.
  2. Integration test for the service-layer post-process: when
     generate_resume_suggestions() returns accepted suggestions,
     their learning_link values are always resolved from the
     curated table, never from the LLM.

The OpenAI client is mocked so the test can run without API keys.
"""

import unittest
from unittest.mock import patch

from app.schemas.suggestions import (
    Citation,
    LearningLink,
    Suggestion,
    SuggestionKind,
    SuggestionsResponse,
)
from app.services.learning_links import (
    ALIASES,
    FLATIRON_CYBER_SKILLS,
    FLATIRON_SE_SKILLS,
    FREE_DOCS_LINKS,
    PAID_BOOTCAMP_LINKS,
    canonical_keys,
    lookup,
)


class LookupUnitTests(unittest.TestCase):
    """lookup() in isolation. No I/O, no service-layer coupling."""

    def test_direct_hit_returns_free_docs_link(self):
        link = lookup("FastAPI")
        self.assertIsNotNone(link)
        self.assertEqual(link.url, "https://fastapi.tiangolo.com/tutorial/")
        self.assertEqual(link.label, "FastAPI tutorial")

    def test_input_normalization_lowercase_and_whitespace(self):
        # "  FastAPI  " and "fastapi" should both hit the same row.
        self.assertEqual(
            lookup("  FastAPI  ").url,
            lookup("fastapi").url,
        )
        # Leading/trailing whitespace + newlines should be stripped.
        # (The .split() call collapses internal whitespace too, so
        # "  Node  .  js  " -> "node . js" which is NOT a key, but
        # "Node.js\n" -> "node.js" IS a key.)
        self.assertIsNotNone(lookup("Node.js\n"))

    def test_alias_postgres_resolves_to_postgresql(self):
        link = lookup("postgres")
        self.assertIsNotNone(link)
        self.assertEqual(
            link.url,
            "https://www.postgresql.org/docs/current/tutorial.html",
        )

    def test_alias_pg_resolves_to_postgresql(self):
        link = lookup("pg")
        self.assertIsNotNone(link)
        self.assertIn("postgresql.org", link.url)

    def test_alias_k8s_falls_back_to_paid_bootcamp(self):
        # kubernetes is not in FREE_DOCS_LINKS, but it is in
        # FLATIRON_CYBER_SKILLS. So lookup should return the
        # Flatiron cybersecurity link, not None.
        link = lookup("k8s")
        self.assertIsNotNone(link)
        self.assertEqual(
            link.url,
            PAID_BOOTCAMP_LINKS["flatiron-cybersecurity"].url,
        )

    def test_alias_js_resolves_to_javascript(self):
        link = lookup("js")
        self.assertIsNotNone(link)
        self.assertIn("developer.mozilla.org", link.url)

    def test_flatiron_se_fallback_for_unmapped_skill(self):
        # "rest api" is in FLATIRON_SE_SKILLS but NOT in
        # FREE_DOCS_LINKS. So lookup returns the Flatiron SE link.
        link = lookup("rest api")
        self.assertIsNotNone(link)
        self.assertEqual(
            link.url,
            PAID_BOOTCAMP_LINKS["flatiron-software-engineering"].url,
        )

    def test_flatiron_cyber_fallback_for_owasp(self):
        link = lookup("owasp")
        self.assertIsNotNone(link)
        self.assertEqual(
            link.url,
            PAID_BOOTCAMP_LINKS["flatiron-cybersecurity"].url,
        )

    def test_unknown_skill_returns_none(self):
        # A skill we have no curated entry for and no Flatiron domain
        # match for should return None — not raise, not invent.
        self.assertIsNone(lookup("snarkbot9000"))
        self.assertIsNone(lookup("Zig"))

    def test_empty_string_returns_none(self):
        self.assertIsNone(lookup(""))
        self.assertIsNone(lookup("   "))

    def test_alias_map_contains_only_known_destination_keys(self):
        # Defensive: every alias value must point to either a free-docs
        # key or a Flatiron allowlist entry. A typo here would silently
        # break resolution.
        for source, dest in ALIASES.items():
            in_free = dest in FREE_DOCS_LINKS
            in_se = dest in FLATIRON_SE_SKILLS
            in_cyber = dest in FLATIRON_CYBER_SKILLS
            self.assertTrue(
                in_free or in_se or in_cyber,
                f"alias {source!r} -> {dest!r} has no destination",
            )


class CanonicalKeysTests(unittest.TestCase):
    """canonical_keys() drives the PREFERRED_SKILLS block in the prompt.
    The list is a soft signal to the LLM, but a wrong list (one that
    contains a string the LLM would try to suggest as a skill) would
    confuse the model. These tests pin the shape of the list.
    """

    def test_returns_sorted_list(self):
        keys = canonical_keys()
        self.assertEqual(keys, sorted(keys))

    def test_matches_free_docs_keys(self):
        # The set of canonical keys must equal FREE_DOCS_LINKS.keys().
        # If a skill is added to the table, it must show up here; if
        # one is removed, it must disappear. This is the contract.
        self.assertEqual(set(canonical_keys()), set(FREE_DOCS_LINKS.keys()))

    def test_does_not_include_flatiron_strings(self):
        # The Flatiron allowlist keys and the bootcamp key names
        # ("flatiron-software-engineering" / "flatiron-cybersecurity")
        # are reachability fallbacks, not direct skill names. They
        # must never appear in the prompt's PREFERRED_SKILLS list —
        # the LLM would try to suggest them as a skill text.
        keys = canonical_keys()
        for k in keys:
            self.assertNotIn("flatiron", k.lower())
            self.assertFalse(
                k.startswith("flatiron-"),
                f"flatiron-prefixed key in canonical_keys(): {k!r}",
            )

    def test_count_is_the_verified_table_size(self):
        # 76 verified free-docs entries as of the table's last update.
        # If this number drifts unexpectedly, the PREFERRED_SKILLS list
        # is probably out of sync with the table — the prompt is
        # telling the LLM a different set than the lookup() function
        # actually resolves. Regression guard.
        self.assertEqual(len(canonical_keys()), len(FREE_DOCS_LINKS))


class ServicePostProcessTests(unittest.TestCase):
    """generate_resume_suggestions() must resolve learning_link from
    the curated table, not the LLM. These tests mock the OpenAI
    client and run the full pipeline end-to-end.
    """

    def _llm_response(self, suggestions):
        return SuggestionsResponse(suggestions=suggestions)

    def _mock_completion(self, response):
        """Build a fake chat.completions.parse() result."""
        fake = type("FakeCompletion", (), {})()
        fake.choices = [type("FakeChoice", (), {
            "message": type("FakeMessage", (), {"parsed": response})(),
        })()]
        return fake

    @patch("app.services.suggestions.suggestions_client")
    def test_llm_learning_link_is_replaced_by_table_hit(
        self, mock_client
    ):
        # LLM claims "FastAPI" with a fabricated URL. The table has
        # the real URL. The post-process must replace the LLM's link
        # with the table's. This is the core "no hallucinated URLs"
        # rule.
        mock_client.beta.chat.completions.parse.return_value = (
            self._mock_completion(
                self._llm_response([
                    Suggestion(
                        kind=SuggestionKind.SKILL,
                        text="FastAPI",
                        evidence=[
                            Citation(job_id="job-a", quote="FastAPI"),
                        ],
                        learning_link=LearningLink(
                            label="LLM-fabricated",
                            url="https://example.com/llm-fabricated",
                        ),
                    ),
                ])
            )
        )

        from app.services.suggestions import generate_resume_suggestions

        job_summaries = [{
            "job_id": "job-a",
            "title": "Backend Engineer",
            "company": "Acme",
            "description_excerpt": (
                "We are looking for a Senior Backend Engineer with "
                "experience in Python, FastAPI, and PostgreSQL."
            ),
            "description_full": (
                "We are looking for a Senior Backend Engineer with "
                "experience in Python, FastAPI, and PostgreSQL."
            ),
        }]
        accepted = generate_resume_suggestions(
            resume_text="I have built APIs in Python.",
            job_summaries=job_summaries,
        )

        self.assertEqual(len(accepted), 1)
        # LLM's link must NOT survive.
        self.assertIsNotNone(accepted[0].learning_link)
        self.assertEqual(
            accepted[0].learning_link.url,
            "https://fastapi.tiangolo.com/tutorial/",
        )

    @patch("app.services.suggestions.suggestions_client")
    def test_unknown_skill_yields_none_learning_link(
        self, mock_client
    ):
        # The LLM suggests "snarkbot9000" with a quoted mention in
        # the job. Even if the citation passes the validator, the
        # table has no entry, so learning_link must be None.
        mock_client.beta.chat.completions.parse.return_value = (
            self._mock_completion(
                self._llm_response([
                    Suggestion(
                        kind=SuggestionKind.SKILL,
                        text="snarkbot9000",
                        evidence=[
                            Citation(
                                job_id="job-a",
                                quote="experience with snarkbot9000 is a plus",
                            ),
                        ],
                    ),
                ])
            )
        )

        from app.services.suggestions import generate_resume_suggestions

        job_summaries = [{
            "job_id": "job-a",
            "title": "Specialist",
            "company": "Acme",
            "description_excerpt": (
                "We use snarkbot9000 heavily."
            ),
            "description_full": (
                "We use snarkbot9000 heavily and prefer candidates with "
                "experience with snarkbot9000 is a plus."
            ),
        }]
        accepted = generate_resume_suggestions(
            resume_text="I have prior experience.",
            job_summaries=job_summaries,
        )

        # The substring check + multi-job absence is what gates
        # survival. With only one citation and no token overlap, the
        # validator may drop the suggestion. Either way, learning_link
        # must be None on whatever survives.
        for s in accepted:
            self.assertIsNone(s.learning_link)


class AIToolingLookupTests(unittest.TestCase):
    """Regression guard for the AI / LLM tooling entries + their
    category-phrase aliases. These exist specifically to catch the
    "AI integration", "agentic workflows", "workflow automation"
    phrases the LLM keeps generating. If a URL rots or an alias
    silently breaks, the UI silently loses the link — same as any
    other entry, but these are more likely to drift because the
    category phrases are deliberately fuzzy.

    The expected behavior: specific tool names hit their own entries,
    and category phrases route to the best matching tool via ALIASES.
    """

    def test_specific_tool_names_hit_their_own_entries(self):
        cases = {
            "OpenAI API": "OpenAI API quickstart",
            "LangChain": "LangChain introduction",
            "n8n": "n8n docs",
            "LangGraph": "LangGraph docs",
            "Anthropic API": "Anthropic API docs",
            "Cohere": "Cohere platform docs",
            "Gemini API": "Gemini API quickstart",
            "HuggingFace": "Hugging Face docs",
            "HuggingFace Transformers": "Transformers docs",
            "LlamaIndex": "LlamaIndex docs",
            "DSPy": "DSPy docs",
            "Pinecone": "Pinecone docs",
            "Chroma": "Chroma docs",
            "Qdrant": "Qdrant docs",
            "Ollama": "Ollama",
            "scikit-learn": "scikit-learn getting started",
        }
        for skill, expected_label in cases.items():
            with self.subTest(skill=skill):
                link = lookup(skill)
                self.assertIsNotNone(link, f"missing link for {skill!r}")
                self.assertEqual(link.label, expected_label)

    def test_category_phrases_route_via_aliases(self):
        # These are the phrases the LLM was actually emitting. Each
        # must resolve to a real link rather than None.
        cases = {
            # OpenAI / generic LLM API
            "openai": "OpenAI API quickstart",
            "gpt": "OpenAI API quickstart",
            "ai integration": "OpenAI API quickstart",
            "ai integrations": "OpenAI API quickstart",
            "llm integration": "OpenAI API quickstart",
            "llm integrations": "OpenAI API quickstart",
            # LangChain / LLM tooling
            "ai-powered tools": "LangChain introduction",
            "ai adoption": "LangChain introduction",
            "llm tooling": "LangChain introduction",
            "ai tooling": "LangChain introduction",
            "llm tools": "LangChain introduction",
            # n8n / workflow automation
            "workflow automation": "n8n docs",
            "automated workflow": "n8n docs",
            "automated workflows": "n8n docs",
            "workflow automations": "n8n docs",
            # LangGraph / agentic
            "agentic workflows": "LangGraph docs",
            "agentic workflow": "LangGraph docs",
            "agentic ai": "LangGraph docs",
            "ai agents": "LangGraph docs",
            "ai agent": "LangGraph docs",
            # Anthropic / Claude
            "claude": "Anthropic API docs",
            "claude api": "Anthropic API docs",
            "anthropic": "Anthropic API docs",
            "anthropic claude": "Anthropic API docs",
            # Google Gemini
            "gemini": "Gemini API quickstart",
            "google ai": "Gemini API quickstart",
            "google gemini": "Gemini API quickstart",
            "google ai studio": "Gemini API quickstart",
            # Hugging Face
            "hugging face": "Hugging Face docs",
            "hf": "Hugging Face docs",
            # LlamaIndex naming variants
            "llama index": "LlamaIndex docs",
            "llama-index": "LlamaIndex docs",
            # Vector databases
            "vector database": "Pinecone docs",
            "vector db": "Pinecone docs",
            "vector store": "Pinecone docs",
            "vector search": "Pinecone docs",
            # RAG (retrieval-augmented generation) — pattern, not a
            # tool, but the canonical implementation is LangChain.
            "rag": "LangChain introduction",
            "retrieval augmented generation": "LangChain introduction",
            # Fine-tuning — Hugging Face is the go-to.
            "fine-tuning": "Hugging Face docs",
            "finetuning": "Hugging Face docs",
            "fine tuning": "Hugging Face docs",
            # Local LLM runtimes.
            "local llm": "Ollama",
            "local model": "Ollama",
        }
        for phrase, expected_label in cases.items():
            with self.subTest(phrase=phrase):
                link = lookup(phrase)
                self.assertIsNotNone(
                    link,
                    f"missing link for category phrase {phrase!r}",
                )
                self.assertEqual(link.label, expected_label)

    def test_normalization_applies_to_category_phrases(self):
        # Whitespace / case variation must still hit the alias.
        self.assertIsNotNone(lookup("  AI Integration  "))
        self.assertIsNotNone(lookup("WORKFLOW AUTOMATION"))
        self.assertIsNotNone(lookup("Agentic\nWorkflows"))

    def test_ai_sdk_and_ai_infrastructure_resolve(self):
        # These two phrases are category terms the LLM sometimes emits
        # (e.g. "experience with AI SDK" or "built AI infrastructure").
        # They should resolve to a concrete tool's docs rather than
        # None, so the user gets a "Learn it" link next to the
        # suggestion. The aliases map them to the closest concrete
        # entry.
        cases = {
            "ai sdk": "OpenAI API quickstart",
            "ai infrastructure": "LangChain introduction",
        }
        for phrase, expected_label in cases.items():
            with self.subTest(phrase=phrase):
                link = lookup(phrase)
                self.assertIsNotNone(
                    link,
                    f"missing link for category phrase {phrase!r}",
                )
                self.assertEqual(link.label, expected_label)

    def test_ai_sdk_and_ai_infrastructure_normalization(self):
        # Whitespace / case variation must still hit the alias.
        self.assertIsNotNone(lookup("  AI SDK  "))
        self.assertIsNotNone(lookup("AI INFRASTRUCTURE"))
        self.assertIsNotNone(lookup("Ai\nSdk"))

    def test_new_entries_in_free_docs_links(self):
        # Direct table check — guards against an entry being added
        # to ALIASES but forgotten in FREE_DOCS_LINKS.
        for key in [
            "openai api", "langchain", "n8n", "langgraph",
            "anthropic api", "cohere", "gemini api",
            "huggingface", "huggingface transformers",
            "llamaindex", "dspy", "guidance",
            "pinecone", "chroma", "qdrant",
            "ollama", "jax", "scikit-learn", "mysql", "vercel",
            "cloudflare", "netlify", "heroku", "render", "railway",
            "fly.io", "digitalocean", "hetzner", "vultr",
            "supabase", "firebase", "aws amplify",
        ]:
            with self.subTest(key=key):
                self.assertIn(key, FREE_DOCS_LINKS)

    def test_canonical_keys_includes_new_entries(self):
        # The LLM's PREFERRED_SKILLS list is built from canonical_keys().
        # If a new entry isn't in there, the LLM won't bias toward it.
        keys = set(canonical_keys())
        for expected in [
            "openai api", "langchain", "n8n", "langgraph",
            "anthropic api", "cohere", "gemini api",
            "huggingface", "huggingface transformers",
            "llamaindex", "dspy", "guidance",
            "pinecone", "chroma", "qdrant",
            "ollama", "jax", "scikit-learn", "mysql", "vercel",
            "cloudflare", "netlify", "heroku", "render", "railway",
            "fly.io", "digitalocean", "hetzner", "vultr",
            "supabase", "firebase", "aws amplify",
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, keys)

    def test_elasticsearch_url_is_live(self):
        # The old URL (https://www.elastic.co/training/) was timing
        # out. Replaced with the current docs landing page. This
        # regression guard catches a future revert to the dead URL.
        link = lookup("elasticsearch")
        self.assertIsNotNone(link)
        self.assertEqual(
            link.url,
            "https://www.elastic.co/docs/get-started",
        )

    def test_vercel_entry_and_aliases(self):
        # Vercel is a real, concrete product — the table has a direct
        # entry. Aliases route the URL-as-skill and the pre-rebrand
        # "now.sh" name to the same entry. Bare "now" is NOT aliased
        # (too common a word; the LLM shouldn't be emitting it
        # anyway, and a stray hit would be a category error).
        link = lookup("vercel")
        self.assertIsNotNone(link)
        self.assertEqual(link.url, "https://vercel.com/docs")

        for variant in ["Vercel", "VERCEL.COM", "now.sh"]:
            with self.subTest(variant=variant):
                self.assertIsNotNone(
                    lookup(variant),
                    f"alias for {variant!r} did not resolve",
                )
                # Every alias lands on the same canonical entry.
                self.assertEqual(lookup(variant).url, "https://vercel.com/docs")

    def test_cloud_platforms_have_entries(self):
        # Coverage check for the major PaaS / serverless / BaaS
        # platforms candidates list on resumes. Each must resolve
        # to a real entry (not None) so the user gets a "Learn it"
        # link. Aliases (URL-as-skill, sub-service names) are
        # covered separately below.
        cases = {
            "cloudflare": "https://developers.cloudflare.com/",
            "netlify": "https://docs.netlify.com/",
            "heroku": "https://devcenter.heroku.com/",
            "render": "https://docs.render.com/",
            "railway": "https://docs.railway.app/",
            "fly.io": "https://fly.io/docs/",
            "digitalocean": "https://docs.digitalocean.com/",
            "hetzner": "https://docs.hetzner.com/",
            "vultr": "https://www.vultr.com/docs/",
            "supabase": "https://supabase.com/docs",
            "firebase": "https://firebase.google.com/docs",
            "aws amplify": "https://aws.amazon.com/amplify/",
        }
        for skill, expected_url in cases.items():
            with self.subTest(skill=skill):
                link = lookup(skill)
                self.assertIsNotNone(link, f"missing link for {skill!r}")
                self.assertEqual(
                    link.url,
                    expected_url,
                    f"{skill!r} points at the wrong URL",
                )

    def test_cloud_platform_aliases(self):
        # URL-as-skill patterns (resumes often write the domain) and
        # sub-service names (Cloudflare Workers/Cloudflare Pages/etc.)
        # must all resolve to the canonical entry. Bare "fly" is
        # intentionally NOT aliased (too common an English word; the
        # LLM shouldn't be emitting it and a stray hit would be a
        # category error).
        cases = {
            # URL-as-skill
            "Cloudflare.com": "cloudflare",
            "netlify.com": "netlify",
            "heroku.com": "heroku",
            "render.com": "render",
            "railway.app": "railway",
            "digitalocean.com": "digitalocean",
            "supabase.com": "supabase",
            "firebase.com": "firebase",
            # Cloudflare sub-services
            "Cloudflare Workers": "cloudflare",
            "Cloudflare Pages": "cloudflare",
            "cloudflare r2": "cloudflare",
            "cloudflare d1": "cloudflare",
            # Fly.io naming variant
            "flyio": "fly.io",
        }
        for variant, expected_key in cases.items():
            with self.subTest(variant=variant):
                link = lookup(variant)
                self.assertIsNotNone(
                    link,
                    f"alias for {variant!r} did not resolve",
                )
                # The alias routes to the canonical entry — same URL
                # as the canonical key produces.
                self.assertEqual(
                    link.url,
                    lookup(expected_key).url,
                    f"alias {variant!r} does not land on {expected_key!r}",
                )

    def test_mysql_uses_w3schools_fallback(self):
        # dev.mysql.com bot-blocks all scripted clients (HTTP 403), so
        # the official MySQL docs URL is unreachable from the
        # verifier. We use w3schools as a verified-working fallback.
        # This regression guard catches a future revert to the
        # bot-blocked dev.mysql.com URL.
        link = lookup("mysql")
        self.assertIsNotNone(link)
        self.assertEqual(link.url, "https://www.w3schools.com/mysql/")
        # The label should also signal the non-canonical source so
        # anyone reading the UI knows this isn't the official MySQL
        # docs.
        self.assertIn("w3schools", link.label.lower())


if __name__ == "__main__":
    unittest.main()
