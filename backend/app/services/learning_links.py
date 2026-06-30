"""
learning_links.py — curated skill -> learning-link lookup for the
resume-suggestions feature.

Why this file exists
--------------------
The OpenAI call earlier let the LLM generate `learning_link` values. That
allowed plausible-looking but wrong URLs to ship. The fix is structural:
the LLM never gets a vote on URLs. It only returns a skill name. The
backend resolves the skill against this curated table on the way out.

Every URL in this file has been verified to return HTTP 200 with
`_verify_learning_links.py` / `_verify_flatiron.py`. If you add a new
entry, re-run those scripts (or write a test) to confirm. A wrong link
in this file is a wrong link the user sees — treat additions as
schema changes, not casual edits.

Public surface
--------------
- `lookup(skill_text: str)` -> LearningLink | None
- `FREE_DOCS_LINKS`   : the canonical 48 free / official-docs entries
- `PAID_BOOTCAMP_LINKS`: the 2 Flatiron School bootcamp entries
- `ALIASES`           : input -> canonical key, applied before lookup
"""

from __future__ import annotations

from app.schemas.suggestions import LearningLink


# ---------------------------------------------------------------------------
# Section 1: Free / official-docs learning links
# ---------------------------------------------------------------------------
# Keyed by the normalized (lowercased, whitespace-stripped, collapsed)
# form of the skill. The 48 entries below all returned HTTP 200 from a
# fetch on the day they were added. If a URL rots, the right move is to
# replace it with another verified URL — not to delete the entry and
# leave a hole, because the resolution order below depends on these
# keys existing.

FREE_DOCS_LINKS: dict[str, LearningLink] = {
    # --- Backend languages ---
    "python": LearningLink(
        label="Python getting started",
        url="https://www.python.org/about/gettingstarted/",
    ),
    "javascript": LearningLink(
        label="MDN JavaScript",
        url="https://developer.mozilla.org/en-US/docs/Web/JavaScript",
    ),
    "typescript": LearningLink(
        label="TypeScript docs",
        url="https://www.typescriptlang.org/docs/",
    ),
    "java": LearningLink(
        label="dev.java learn",
        url="https://dev.java/learn/",
    ),
    "go": LearningLink(
        label="Go learn",
        url="https://go.dev/learn/",
    ),
    "rust": LearningLink(
        label="Rust learn",
        url="https://www.rust-lang.org/learn",
    ),
    "ruby": LearningLink(
        label="Ruby docs",
        url="https://www.ruby-lang.org/en/documentation/",
    ),
    "c#": LearningLink(
        label="Microsoft Learn C#",
        url="https://learn.microsoft.com/en-us/dotnet/csharp/",
    ),
    # --- Backend frameworks ---
    "fastapi": LearningLink(
        label="FastAPI tutorial",
        url="https://fastapi.tiangolo.com/tutorial/",
    ),
    "django": LearningLink(
        label="Django tutorial",
        url="https://docs.djangoproject.com/en/stable/intro/tutorial01/",
    ),
    "express": LearningLink(
        label="Express docs",
        url="https://expressjs.com/en/starter/installing.html",
    ),
    "spring boot": LearningLink(
        label="Spring guides",
        url="https://spring.io/guides",
    ),
    "node.js": LearningLink(
        label="Node.js learn",
        url="https://nodejs.org/en/learn",
    ),
    "rails": LearningLink(
        label="Rails getting started",
        url="https://guides.rubyonrails.org/getting_started.html",
    ),
    "laravel": LearningLink(
        label="Laravel docs",
        url="https://laravel.com/docs",
    ),
    "nestjs": LearningLink(
        label="NestJS docs",
        url="https://docs.nestjs.com/",
    ),
    # --- Frontend ---
    "react": LearningLink(
        label="React learn",
        url="https://react.dev/learn",
    ),
    "vue": LearningLink(
        label="Vue guide",
        url="https://vuejs.org/guide/introduction.html",
    ),
    "angular": LearningLink(
        label="Angular learn",
        url="https://angular.dev/learn",
    ),
    "svelte": LearningLink(
        label="Svelte tutorial",
        url="https://svelte.dev/tutorial",
    ),
    "next.js": LearningLink(
        label="Next.js learn",
        url="https://nextjs.org/learn",
    ),
    "tailwind css": LearningLink(
        label="Tailwind docs",
        url="https://tailwindcss.com/docs/installation",
    ),
    "vercel": LearningLink(
        label="Vercel docs",
        url="https://vercel.com/docs",
    ),
    "html": LearningLink(
        label="MDN HTML",
        url="https://developer.mozilla.org/en-US/docs/Learn/HTML",
    ),
    "css": LearningLink(
        label="MDN CSS",
        url="https://developer.mozilla.org/en-US/docs/Learn/CSS",
    ),
    # --- Databases ---
    "postgresql": LearningLink(
        label="PostgreSQL tutorial",
        url="https://www.postgresql.org/docs/current/tutorial.html",
    ),
    # MySQL: dev.mysql.com returns HTTP 403 to all scripted clients
    # (Oracle's bot policy blocks any non-browser User-Agent), so the
    # verifier can't confirm the official docs URL is live. Rather
    # than leave MySQL with no link at all, we use the w3schools
    # MySQL tutorial as a verified-working fallback. w3schools is
    # not the canonical source but it is a high-quality,
    # beginner-friendly reference that covers the same ground.
    # If Oracle's bot policy ever changes and a future verifier run
    # can reach dev.mysql.com, swap this entry back to the official
    # URL.
    "mysql": LearningLink(
        label="MySQL tutorial (w3schools)",
        url="https://www.w3schools.com/mysql/",
    ),
    "mongodb": LearningLink(
        label="MongoDB University",
        url="https://learn.mongodb.com/",
    ),
    "redis": LearningLink(
        label="Redis learn",
        url="https://redis.io/learn/",
    ),
    "elasticsearch": LearningLink(
        label="Elastic docs",
        url="https://www.elastic.co/docs/get-started",
    ),
    "dynamodb": LearningLink(
        label="DynamoDB getting started",
        url="https://aws.amazon.com/dynamodb/getting-started/",
    ),
    # --- DevOps / Cloud ---
    "aws": LearningLink(
        label="AWS training",
        url="https://aws.amazon.com/training/",
    ),
    "azure": LearningLink(
        label="Microsoft Learn Azure",
        url="https://learn.microsoft.com/en-us/azure/",
    ),
    "google cloud": LearningLink(
        label="Google Cloud training",
        url="https://cloud.google.com/training",
    ),
    # --- Cloud platforms (PaaS / serverless) ---
    # Each entry is the official docs landing page. Aliases below
    # route common naming variants (URL-as-skill, sub-service names)
    # to the canonical entry.
    "cloudflare": LearningLink(
        label="Cloudflare developer docs",
        url="https://developers.cloudflare.com/",
    ),
    "netlify": LearningLink(
        label="Netlify docs",
        url="https://docs.netlify.com/",
    ),
    "heroku": LearningLink(
        label="Heroku Dev Center",
        url="https://devcenter.heroku.com/",
    ),
    "render": LearningLink(
        label="Render docs",
        url="https://docs.render.com/",
    ),
    "railway": LearningLink(
        label="Railway docs",
        url="https://docs.railway.app/",
    ),
    "fly.io": LearningLink(
        label="Fly.io docs",
        url="https://fly.io/docs/",
    ),
    "digitalocean": LearningLink(
        label="DigitalOcean docs",
        url="https://docs.digitalocean.com/",
    ),
    "hetzner": LearningLink(
        label="Hetzner docs",
        url="https://docs.hetzner.com/",
    ),
    "vultr": LearningLink(
        label="Vultr docs",
        url="https://www.vultr.com/docs/",
    ),
    # --- Backend-as-a-Service ---
    # These are common "cloud platform" mentions on resumes.
    "supabase": LearningLink(
        label="Supabase docs",
        url="https://supabase.com/docs",
    ),
    "firebase": LearningLink(
        label="Firebase docs",
        url="https://firebase.google.com/docs",
    ),
    "aws amplify": LearningLink(
        label="AWS Amplify",
        url="https://aws.amazon.com/amplify/",
    ),
    "docker": LearningLink(
        label="Docker getting started",
        url="https://docs.docker.com/get-started/",
    ),
    "terraform": LearningLink(
        label="Terraform tutorials",
        url="https://developer.hashicorp.com/terraform/tutorials",
    ),
    "jenkins": LearningLink(
        label="Jenkins getting started",
        url="https://www.jenkins.io/doc/pipeline/tour/getting-started/",
    ),
    "github actions": LearningLink(
        label="GitHub Actions docs",
        url="https://docs.github.com/en/actions/learn-github-actions",
    ),
    "nginx": LearningLink(
        label="Nginx docs",
        url="https://nginx.org/en/docs/",
    ),
    "git": LearningLink(
        label="Git docs",
        url="https://git-scm.com/doc",
    ),
    # --- Data / ML ---
    "pandas": LearningLink(
        label="Pandas 10-min guide",
        url="https://pandas.pydata.org/docs/user_guide/10min.html",
    ),
    "numpy": LearningLink(
        label="NumPy absolute beginners",
        url="https://numpy.org/doc/stable/user/absolute_beginners.html",
    ),
    "tensorflow": LearningLink(
        label="TensorFlow learn ML",
        url="https://www.tensorflow.org/resources/learn-ml",
    ),
    "scikit-learn": LearningLink(
        label="scikit-learn getting started",
        url="https://scikit-learn.org/stable/getting_started.html",
    ),
    "spark": LearningLink(
        label="Spark quick start",
        url="https://spark.apache.org/docs/latest/quick-start.html",
    ),
    "airflow": LearningLink(
        label="Airflow tutorial",
        url="https://airflow.apache.org/docs/apache-airflow/stable/tutorial/",
    ),
    "dbt": LearningLink(
        label="dbt docs",
        url="https://docs.getdbt.com/docs/introduction",
    ),
    "kafka": LearningLink(
        label="Kafka docs",
        url="https://kafka.apache.org/documentation/",
    ),
    "graphql": LearningLink(
        label="GraphQL learn",
        url="https://graphql.org/learn/",
    ),
    "snowflake": LearningLink(
        label="Snowflake getting started",
        url="https://docs.snowflake.com/en/user-guide-getting-started",
    ),
    "databricks": LearningLink(
        label="Databricks docs",
        url="https://docs.databricks.com/en/index.html",
    ),
    "helm": LearningLink(
        label="Helm chart template guide",
        url="https://helm.sh/docs/chart_template_guide/",
    ),
    "prometheus": LearningLink(
        label="Prometheus getting started",
        url="https://prometheus.io/docs/prometheus/latest/getting_started/",
    ),
    # --- AI / LLM tooling ---
    # These exist to catch the category phrases ("ai integration",
    # "agentic workflows", "workflow automation") the LLM keeps
    # generating. Each entry is the official docs landing page of one
    # concrete tool — the goal is to teach the LLM that "the specific
    # tool" is the suggestion text, and the category phrase is the
    # background. If the LLM still says "ai integration" verbatim the
    # lookup() will hit one of these via the ALIASES below; if it says
    # "OpenAI" or "LangChain" specifically, the alias routes to the
    # same canonical entry.
    "openai api": LearningLink(
        label="OpenAI API quickstart",
        url="https://platform.openai.com/docs/quickstart",
    ),
    "langchain": LearningLink(
        label="LangChain introduction",
        url="https://docs.langchain.com/oss/python/langchain/overview",
    ),
    "n8n": LearningLink(
        label="n8n docs",
        url="https://docs.n8n.io/",
    ),
    "langgraph": LearningLink(
        label="LangGraph docs",
        url="https://langchain-ai.github.io/langgraph/",
    ),
    # --- LLM provider SDKs ---
    # Each one is a concrete vendor's docs landing page. Aliases below
    # route category phrases ("foundation models", "claude", "gemini",
    # etc.) to the right concrete entry.
    "anthropic api": LearningLink(
        label="Anthropic API docs",
        url="https://docs.anthropic.com/en/docs/intro",
    ),
    "cohere": LearningLink(
        label="Cohere platform docs",
        url="https://docs.cohere.com/docs/the-cohere-platform",
    ),
    "gemini api": LearningLink(
        label="Gemini API quickstart",
        url="https://ai.google.dev/gemini-api/docs/quickstart",
    ),
    # --- LLM / ML development tools ---
    "huggingface": LearningLink(
        label="Hugging Face docs",
        url="https://huggingface.co/docs",
    ),
    "huggingface transformers": LearningLink(
        label="Transformers docs",
        url="https://huggingface.co/docs/transformers/index",
    ),
    "llamaindex": LearningLink(
        label="LlamaIndex docs",
        url="https://docs.llamaindex.ai/en/stable/",
    ),
    "dspy": LearningLink(
        label="DSPy docs",
        url="https://dspy.ai/",
    ),
    "guidance": LearningLink(
        label="Guidance (GitHub)",
        url="https://github.com/guidance-ai/guidance",
    ),
    # --- Vector databases ---
    "pinecone": LearningLink(
        label="Pinecone docs",
        url="https://docs.pinecone.io/guides/get-started/overview",
    ),
    "chroma": LearningLink(
        label="Chroma docs",
        url="https://docs.trychroma.com/",
    ),
    "qdrant": LearningLink(
        label="Qdrant docs",
        url="https://qdrant.tech/documentation/",
    ),
    # --- Local LLM runtimes ---
    "ollama": LearningLink(
        label="Ollama",
        url="https://ollama.com/",
    ),
    # --- Numerical computing ---
    "jax": LearningLink(
        label="JAX quickstart",
        url="https://docs.jax.dev/en/latest/quickstart.html",
    ),
}


# ---------------------------------------------------------------------------
# Section 2: Paid bootcamps / vendor programs
# ---------------------------------------------------------------------------
# These are a different category from the free / official-docs entries
# above. They are intentionally grouped separately and reached only when
# the candidate skill falls into one of the explicit FLATIRON_*_SKILLS
# allowlists below. The user sees a "Learn it" link the same way as the
# free entries, but the label clearly says "Flatiron School ..." so
# there's no surprise about cost.

PAID_BOOTCAMP_LINKS: dict[str, LearningLink] = {
    "flatiron-software-engineering": LearningLink(
        label="Flatiron School — Software Engineering",
        url="https://flatironschool.com/courses/software-engineering/",
    ),
    "flatiron-cybersecurity": LearningLink(
        label="Flatiron School — Cybersecurity",
        url="https://flatironschool.com/courses/cybersecurity/",
    ),
}


# ---------------------------------------------------------------------------
# Section 3: Domain allowlists for the paid-bootcamp fallback
# ---------------------------------------------------------------------------
# When a SKILL has no entry in FREE_DOCS_LINKS, we ask: "does this
# skill plausibly fit one of the Flatiron bootcamps?" If yes, link to
# the bootcamp. These sets are the source of truth — keep them small
# and explicit. Adding a skill here means "Flatiron teaches this and
# we are willing to point candidates there."

FLATIRON_SE_SKILLS: frozenset[str] = frozenset({
    "python", "javascript", "typescript", "react",
    "node.js", "ruby", "java", "html", "css", "sql",
    "postgresql", "mongodb", "redis", "git", "docker", "aws",
    "rest api", "rest api design", "express",
})

FLATIRON_CYBER_SKILLS: frozenset[str] = frozenset({
    "kubernetes", "linux", "networking", "security",
    "owasp", "encryption", "iam", "siem",
    "cybersecurity", "information security", "network security",
})


# ---------------------------------------------------------------------------
# Section 4: Aliases
# ---------------------------------------------------------------------------
# Applied BEFORE the table lookups so that "py" -> "python" -> table hit.
# Keep this map small and obvious. If you find yourself wanting to add
# 50 entries here, the right move is probably to extend the table
# itself, not the alias map.

ALIASES: dict[str, str] = {
    "py": "python",
    "python3": "python",
    "js": "javascript",
    "node": "node.js",
    "ts": "typescript",
    "postgres": "postgresql",
    "pg": "postgresql",
    "k8s": "kubernetes",
    "react.js": "react",
    "reactjs": "react",
    "vue.js": "vue",
    "vuejs": "vue",
    "nextjs": "next.js",
    "go-lang": "go",
    "golang": "go",
    "csharp": "c#",
    "c sharp": "c#",
    # --- AI / LLM category-phrase aliases ---
    # When the LLM emits a category phrase instead of a specific tool,
    # route it to the best-matching tool's URL. The prompt also nudges
    # it toward specific names, but this is the safety net for the
    # suggestions that slip through.
    "openai": "openai api",
    "openai api": "openai api",
    "gpt": "openai api",
    "chatgpt api": "openai api",
    "ai integration": "openai api",
    "ai integrations": "openai api",
    "llm integration": "openai api",
    "llm integrations": "openai api",
    "ai-powered tools": "langchain",
    "ai adoption": "langchain",
    "llm tooling": "langchain",
    "ai tooling": "langchain",
    "llm tools": "langchain",
    "workflow automation": "n8n",
    "automated workflow": "n8n",
    "automated workflows": "n8n",
    "workflow automations": "n8n",
    "agentic workflows": "langgraph",
    "agentic workflow": "langgraph",
    "agentic ai": "langgraph",
    "ai agents": "langgraph",
    "ai agent": "langgraph",
    # "ai sdk" / "ai infrastructure" are category phrases, not specific
    # tools. Route them to a concrete entry so the user gets a real
    # link rather than None, instead of expanding the table with vague
    # top-level entries. openai api is the canonical first AI SDK most
    # candidates encounter; langchain is the closest concrete tool to
    # the "AI infrastructure" category (it bundles models, vector
    # stores, retrieval, agents — the building blocks of an AI app).
    "ai sdk": "openai api",
    "ai infrastructure": "langchain",
    # Anthropic / Claude: candidates often say "claude" or "claude api"
    # when they mean the Anthropic SDK. Route to the vendor docs.
    "claude": "anthropic api",
    "claude api": "anthropic api",
    "anthropic": "anthropic api",
    "anthropic claude": "anthropic api",
    # Google Gemini: candidates say "gemini" or "google ai" or
    # "google gemini". Route to the Gemini API docs (the modern entry
    # point — Google rebranded their AI offerings to Gemini).
    "gemini": "gemini api",
    "google ai": "gemini api",
    "google gemini": "gemini api",
    "google ai studio": "gemini api",
    # Hugging Face naming variants. "hf" is the common short form.
    "hugging face": "huggingface",
    "hf": "huggingface",
    # LlamaIndex: common alternate spacing.
    "llama index": "llamaindex",
    "llama-index": "llamaindex",
    "llamaindex": "llamaindex",
    # Vector database category phrases. Pinecone is the canonical
    # first-choice vendor; "vector store" / "vector search" route to
    # the same place.
    "vector database": "pinecone",
    "vector databases": "pinecone",
    "vector db": "pinecone",
    "vector store": "pinecone",
    "vector search": "pinecone",
    "embeddings database": "pinecone",
    # RAG (retrieval-augmented generation) is a pattern, not a tool,
    # but the canonical implementation in the wild is LangChain. Route
    # the category phrase there so the user gets a real link.
    "rag": "langchain",
    "retrieval augmented generation": "langchain",
    # Fine-tuning: Hugging Face is the go-to for fine-tuning open-source
    # models, so route the category phrase there.
    "fine-tuning": "huggingface",
    "finetuning": "huggingface",
    "fine tuning": "huggingface",
    # Local LLM: Ollama is the most common local LLM runtime.
    "local llm": "ollama",
    "local model": "ollama",
    # Vercel naming variants. "now.sh" was the brand before the
    # rebrand; resumes from 2019-2020 sometimes still use it.
    # "vercel.com" is the URL-as-skill pattern. (We don't alias
    # bare "now" — it's a common English word, and a stray LLM
    # emission of "now" is degenerate output that should be
    # dropped, not routed to Vercel.)
    "vercel.com": "vercel",
    "now.sh": "vercel",
    # Cloud platform URL-as-skill patterns (resumes often write the
    # domain as the skill). Each routes to the canonical entry.
    "cloudflare.com": "cloudflare",
    "netlify.com": "netlify",
    "heroku.com": "heroku",
    "render.com": "render",
    "railway.app": "railway",
    "digitalocean.com": "digitalocean",
    "supabase.com": "supabase",
    "firebase.com": "firebase",
    # Cloudflare sub-services — all live under developers.cloudflare.com.
    "cloudflare workers": "cloudflare",
    "cloudflare pages": "cloudflare",
    "cloudflare r2": "cloudflare",
    "cloudflare d1": "cloudflare",
    # Fly.io naming variant. Bare "fly" is intentionally NOT
    # aliased — it's a common English word, and a stray LLM
    # emission of "fly" is degenerate output that should be
    # dropped, not routed to Fly.io.
    "flyio": "fly.io",
    # AWS Amplify — keep the canonical form as the only key; this is
    # an identity alias so the table is robust to whitespace variants.
    "awsamplify": "aws amplify",
}


# ---------------------------------------------------------------------------
# Section 5: lookup()
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Lowercase, strip, collapse internal whitespace. Matches the
    normalization used elsewhere in the suggestions feature so that
    'Fast API', 'fastapi', and 'fastapi\\n' all resolve the same way.
    """
    return " ".join(text.lower().split())


def lookup(skill_text: str) -> LearningLink | None:
    """Resolve a skill to a learning link, or None.

    Resolution order (explicit, in this order):
      1. Empty / whitespace input -> None.
      2. Normalize the input (lowercase, strip, collapse whitespace).
      3. Apply ALIASES (if "py" -> "python", retry from step 2 with
         the canonical key). One level of aliasing is enough; the
         alias values themselves are canonical keys.
      4. Direct lookup in FREE_DOCS_LINKS. Hit -> return it.
      5. Domain check: does the canonical key fall under the Flatiron
         software-engineering or cybersecurity allowlist? Hit -> return
         the matching PAID_BOOTCAMP_LINKS entry.
      6. Otherwise -> None.

    The function never raises. A None result is the expected outcome
    for skills we don't have a curated resource for.

    The `kind` parameter that used to be accepted here (SKILL | BULLET)
    was removed when the BULLET suggestion kind was retired: bullet
    rewriting is now an interactive Q&A flow (the bullet coach), and
    the one-shot suggestion path only emits single tool / technology /
    framework names. lookup() is the skill resolver for that path.
    """
    # Step 1
    if not skill_text or not skill_text.strip():
        return None

    # Step 2
    key = _normalize(skill_text)

    # Step 3: one-shot alias resolution. We re-normalize the alias value
    # too in case someone added "  Python  " to the map.
    aliased = ALIASES.get(key)
    if aliased is not None:
        key = _normalize(aliased)

    # Step 4: free / official-docs.
    direct_hit = FREE_DOCS_LINKS.get(key)
    if direct_hit is not None:
        return direct_hit

    # Step 5: paid-bootcamp domain fallback. Two explicit allowlists.
    if key in FLATIRON_SE_SKILLS:
        return PAID_BOOTCAMP_LINKS["flatiron-software-engineering"]
    if key in FLATIRON_CYBER_SKILLS:
        return PAID_BOOTCAMP_LINKS["flatiron-cybersecurity"]

    # Step 6
    return None


def canonical_keys() -> list[str]:
    """Return a sorted list of skill keys we have curated learning
    links for. Used to build the PREFERRED_SKILLS block in the
    suggestions prompt so the LLM can bias toward skills we can
    actually link to.

    This is a *soft* signal in the prompt — the grounding contract
    (citation must be a real substring of the cited job) is still
    what owns correctness. The LLM is told to PREFER these skills
    when the evidence is otherwise even, not to invent them. The
    validator still drops any suggestion whose citation is fabricated.
    """
    keys: set[str] = set(FREE_DOCS_LINKS.keys())
    # The Flatiron bootcamps are reachability-fallbacks, not direct
    # skill names. Listing them as "preferred skills" would confuse
    # the LLM (it'd try to suggest "flatiron-software-engineering"
    # as a suggestion text). The domain allowlists FLATIRON_SE_SKILLS
    # and FLATIRON_CYBER_SKILLS are NOT included here for the same
    # reason — they're the gate, not the destination. We only list
    # the actual skill names that map 1:1 to a link via the table.
    return sorted(keys)
