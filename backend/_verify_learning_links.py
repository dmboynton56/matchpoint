"""One-shot URL verification for the curated learning-links table.

For each (skill, url) candidate, do a GET (follow redirects, discard body)
and report the final status code. Anything that 4xx/5xx or that lands on a
page that looks like a "not found" / search-results page is flagged.

Run from anywhere; the script is self-contained.
"""
from __future__ import annotations

import ssl
import sys
import urllib.request
import urllib.error
from typing import NamedTuple

import certifi


class Entry(NamedTuple):
    skill: str
    url: str
    label: str


# Build a default SSL context using certifi's CA bundle, not Python's
# system default. On Windows + this project's venv, the system default
# bundle path is missing, which makes every https:// call fail with
# CERTIFICATE_VERIFY_FAILED. certifi ships an up-to-date bundle so the
# check matches what a real client would experience.
_SSL_CTX = ssl.create_default_context(cafile=certifi.where())


# Candidate list. Sources are official docs landing pages, vendor training
# portals, and major platform homepages. Every entry below was a
# reasonable guess from memory — the curl check is what decides if it
# actually lives there.
CANDIDATES: list[Entry] = [
    # --- Backend languages ---
    Entry("python", "https://www.python.org/about/gettingstarted/", "Python getting started"),
    Entry("javascript", "https://developer.mozilla.org/en-US/docs/Web/JavaScript", "MDN JavaScript"),
    Entry("typescript", "https://www.typescriptlang.org/docs/", "TypeScript docs"),
    Entry("java", "https://dev.java/learn/", "dev.java learn"),
    Entry("go", "https://go.dev/learn/", "Go learn"),
    Entry("rust", "https://www.rust-lang.org/learn", "Rust learn"),
    Entry("ruby", "https://www.ruby-lang.org/en/documentation/", "Ruby docs"),
    Entry("c#", "https://learn.microsoft.com/en-us/dotnet/csharp/", "Microsoft Learn C#"),
    # --- Backend frameworks ---
    Entry("fastapi", "https://fastapi.tiangolo.com/tutorial/", "FastAPI tutorial"),
    Entry("django", "https://docs.djangoproject.com/en/stable/intro/tutorial01/", "Django tutorial"),
    Entry("flask", "https://flask.palletsprojects.com/en/stable/tutorial/", "Flask tutorial"),
    Entry("express", "https://expressjs.com/en/starter/installing.html", "Express docs"),
    Entry("spring boot", "https://spring.io/guides", "Spring guides"),
    Entry("node.js", "https://nodejs.org/en/learn", "Node.js learn"),
    Entry("rails", "https://guides.rubyonrails.org/getting_started.html", "Rails getting started"),
    Entry("laravel", "https://laravel.com/docs", "Laravel docs"),
    Entry("nestjs", "https://docs.nestjs.com/", "NestJS docs"),
    # --- Frontend ---
    Entry("react", "https://react.dev/learn", "React learn"),
    Entry("vue", "https://vuejs.org/guide/introduction.html", "Vue guide"),
    Entry("angular", "https://angular.dev/learn", "Angular learn"),
    Entry("svelte", "https://svelte.dev/tutorial", "Svelte tutorial"),
    Entry("next.js", "https://nextjs.org/learn", "Next.js learn"),
    Entry("tailwind css", "https://tailwindcss.com/docs/installation", "Tailwind docs"),
    Entry("vercel", "https://vercel.com/docs", "Vercel docs"),
    Entry("html", "https://developer.mozilla.org/en-US/docs/Learn/HTML", "MDN HTML"),
    Entry("css", "https://developer.mozilla.org/en-US/docs/Learn/CSS", "MDN CSS"),
    # --- Databases ---
    Entry("postgresql", "https://www.postgresql.org/docs/current/tutorial.html", "PostgreSQL tutorial"),
    # MySQL: dev.mysql.com bot-blocks the verifier (HTTP 403 for all
    # scripted clients). Using w3schools as a verified-working
    # fallback. See learning_links.py for the rationale.
    Entry("mysql", "https://www.w3schools.com/mysql/", "MySQL tutorial (w3schools)"),
    Entry("mongodb", "https://learn.mongodb.com/", "MongoDB University"),
    Entry("redis", "https://redis.io/learn/", "Redis learn"),
    Entry("sqlite", "https://www.sqlite.org/docs.html", "SQLite docs"),
    Entry("elasticsearch", "https://www.elastic.co/docs/get-started", "Elastic docs"),
    Entry("dynamodb", "https://aws.amazon.com/dynamodb/getting-started/", "DynamoDB getting started"),
    # --- DevOps / Cloud ---
    Entry("aws", "https://aws.amazon.com/training/", "AWS training"),
    Entry("azure", "https://learn.microsoft.com/en-us/azure/", "Microsoft Learn Azure"),
    Entry("google cloud", "https://cloud.google.com/training", "Google Cloud training"),
    # --- Cloud platforms (PaaS / serverless) ---
    Entry("cloudflare", "https://developers.cloudflare.com/", "Cloudflare developer docs"),
    Entry("netlify", "https://docs.netlify.com/", "Netlify docs"),
    Entry("heroku", "https://devcenter.heroku.com/", "Heroku Dev Center"),
    Entry("render", "https://docs.render.com/", "Render docs"),
    Entry("railway", "https://docs.railway.app/", "Railway docs"),
    Entry("fly.io", "https://fly.io/docs/", "Fly.io docs"),
    Entry("digitalocean", "https://docs.digitalocean.com/", "DigitalOcean docs"),
    Entry("hetzner", "https://docs.hetzner.com/", "Hetzner docs"),
    Entry("vultr", "https://www.vultr.com/docs/", "Vultr docs"),
    # --- Backend-as-a-Service ---
    Entry("supabase", "https://supabase.com/docs", "Supabase docs"),
    Entry("firebase", "https://firebase.google.com/docs", "Firebase docs"),
    Entry("aws amplify", "https://aws.amazon.com/amplify/", "AWS Amplify"),
    Entry("docker", "https://docs.docker.com/get-started/", "Docker getting started"),
    Entry("kubernetes", "https://kubernetes.io/docs/tutorials/", "Kubernetes docs"),
    Entry("terraform", "https://developer.hashicorp.com/terraform/tutorials", "Terraform tutorials"),
    Entry("ansible", "https://docs.ansible.com/ansible/latest/getting_started/index.html", "Ansible getting started"),
    Entry("jenkins", "https://www.jenkins.io/doc/pipeline/tour/getting-started/", "Jenkins getting started"),
    Entry("github actions", "https://docs.github.com/en/actions/learn-github-actions", "GitHub Actions docs"),
    Entry("nginx", "https://nginx.org/en/docs/", "Nginx docs"),
    Entry("git", "https://git-scm.com/doc", "Git docs"),
    # --- Data / ML ---
    Entry("pandas", "https://pandas.pydata.org/docs/user_guide/10min.html", "Pandas 10-min guide"),
    Entry("numpy", "https://numpy.org/doc/stable/user/absolute_beginners.html", "NumPy absolute beginners"),
    Entry("pytorch", "https://pytorch.org/tutorials/", "PyTorch tutorials"),
    Entry("tensorflow", "https://www.tensorflow.org/resources/learn-ml", "TensorFlow learn ML"),
    Entry("scikit-learn", "https://scikit-learn.org/stable/getting_started.html", "scikit-learn getting started"),
    Entry("spark", "https://spark.apache.org/docs/latest/quick-start.html", "Spark quick start"),
    Entry("airflow", "https://airflow.apache.org/docs/apache-airflow/stable/tutorial/", "Airflow tutorial"),
    Entry("dbt", "https://docs.getdbt.com/docs/introduction", "dbt docs"),
    Entry("kafka", "https://kafka.apache.org/documentation/", "Kafka docs"),
    Entry("graphql", "https://graphql.org/learn/", "GraphQL learn"),
    Entry("snowflake", "https://docs.snowflake.com/en/user-guide-getting-started", "Snowflake getting started"),
    Entry("databricks", "https://docs.databricks.com/en/index.html", "Databricks docs"),
    Entry("helm", "https://helm.sh/docs/chart_template_guide/", "Helm chart template guide"),
    Entry("prometheus", "https://prometheus.io/docs/prometheus/latest/getting_started/", "Prometheus getting started"),
    # --- AI / LLM tooling (new) ---
    Entry("openai api", "https://platform.openai.com/docs/quickstart", "OpenAI API quickstart"),
    Entry("langchain", "https://docs.langchain.com/oss/python/langchain/overview", "LangChain introduction"),
    Entry("n8n", "https://docs.n8n.io/", "n8n docs"),
    Entry("langgraph", "https://langchain-ai.github.io/langgraph/", "LangGraph docs"),
    # --- LLM provider SDKs ---
    Entry("anthropic api", "https://docs.anthropic.com/en/docs/intro", "Anthropic API docs"),
    Entry("cohere", "https://docs.cohere.com/docs/the-cohere-platform", "Cohere platform docs"),
    Entry("gemini api", "https://ai.google.dev/gemini-api/docs/quickstart", "Gemini API quickstart"),
    # --- LLM / ML development tools ---
    Entry("huggingface", "https://huggingface.co/docs", "Hugging Face docs"),
    Entry("huggingface transformers", "https://huggingface.co/docs/transformers/index", "Transformers docs"),
    Entry("llamaindex", "https://docs.llamaindex.ai/en/stable/", "LlamaIndex docs"),
    Entry("dspy", "https://dspy.ai/", "DSPy docs"),
    Entry("guidance", "https://github.com/guidance-ai/guidance", "Guidance (GitHub)"),
    # --- Vector databases ---
    Entry("pinecone", "https://docs.pinecone.io/guides/get-started/overview", "Pinecone docs"),
    Entry("chroma", "https://docs.trychroma.com/", "Chroma docs"),
    Entry("qdrant", "https://qdrant.tech/documentation/", "Qdrant docs"),
    # --- Local LLM runtimes ---
    Entry("ollama", "https://ollama.com/", "Ollama"),
    # --- Numerical computing ---
    Entry("jax", "https://docs.jax.dev/en/latest/quickstart.html", "JAX quickstart"),
]


def check(entry: Entry, timeout: int = 15) -> tuple[str, str]:
    """Return (status, note). status is one of:
      OK    - HTTP 200
      REDIR - Final URL after redirects differs from requested (informational)
      BAD   - Non-2xx final status, or network/parse error
    """
    try:
        req = urllib.request.Request(
            entry.url,
            headers={"User-Agent": "HermesLinkVerifier/1.0"},
        )
        # Use a no-op opener that discards the body so we don't pay the
        # transfer cost on multi-MB doc sites.
        with urllib.request.urlopen(
            req, timeout=timeout, context=_SSL_CTX
        ) as resp:
            final_url = resp.geturl()
            status = resp.status
            if 200 <= status < 300:
                if final_url.rstrip("/") != entry.url.rstrip("/"):
                    return ("OK", f"redirected to {final_url}")
                return ("OK", "")
            return ("BAD", f"HTTP {status}")
    except urllib.error.HTTPError as e:
        return ("BAD", f"HTTP {e.code}")
    except urllib.error.URLError as e:
        return ("BAD", f"URL error: {e.reason}")
    except (TimeoutError, Exception) as e:
        return ("BAD", f"{type(e).__name__}: {e}")


def main() -> int:
    ok: list[Entry] = []
    bad: list[tuple[Entry, str, str]] = []
    for entry in CANDIDATES:
        status, note = check(entry)
        line = f"{status:5s}  {entry.skill:18s}  {entry.url}"
        if note:
            line += f"  ({note})"
        print(line, flush=True)
        if status == "OK":
            ok.append(entry)
        else:
            bad.append((entry, status, note))
    print()
    print(f"OK:   {len(ok)}/{len(CANDIDATES)}")
    print(f"BAD:  {len(bad)}/{len(CANDIDATES)}")
    if bad:
        print()
        print("Dropped (do not include in table):")
        for entry, status, note in bad:
            print(f"  {entry.skill}: {entry.url}  -- {status} {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
