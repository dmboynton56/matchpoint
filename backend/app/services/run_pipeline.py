"""
run_pipeline.py — Daily job pipeline
  1. Scrape job postings from Greenhouse boards
  2. Fetch existing external_ids from Turso, filter to new-only
  3. Clean & build embedding text for new jobs only
  4. Batch-embed via OpenAI
  5. Insert new jobs into Turso
  6. Purge jobs older than 7 days

The pipeline only writes to the `jobs` table, which now lives on Turso
(libSQL). All other state (job_matches, profiles, resumes, auth) remains
on Supabase and is not touched here.
"""

import os
import sys
import time
from datetime import datetime, timezone, timedelta

try:
    from .scraper100 import scrape_all
    from .cleaning import buildCleanedText
    from .embedding import generate_embeddings_batch
    from ..db import turso
except ImportError:
    from scraper100 import scrape_all
    from cleaning import buildCleanedText
    from embedding import generate_embeddings_batch
    from db import turso


BATCH_SIZE = 100
STALE_AFTER_DAYS = 7


def chunk(lst: list, size: int):
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


def purge_stale_jobs():
    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(days=STALE_AFTER_DAYS)
    ).isoformat()

    try:
        deleted = turso.purge_older_than(cutoff)
        print(
            f"Purged {deleted} jobs older than "
            f"{STALE_AFTER_DAYS} days"
        )
    except Exception as e:
        print(f"Purge failed: {e}")
        raise


def run_pipeline():
    start = time.perf_counter()
    now = datetime.now(timezone.utc).isoformat()

    # Make sure the Turso schema is in place before any I/O.
    turso.init_schema()

    print("=== STEP 1: Scraping ===")
    jobs = scrape_all()

    if not jobs:
        print("No jobs scraped — exiting.")
        sys.exit(0)

    print("\n=== STEP 2: Filtering duplicates ===")
    existing_ids = turso.fetch_existing_external_ids()
    print(f"  {len(existing_ids)} existing external_ids in DB")

    new_jobs = [j for j in jobs if str(j["external_id"]) not in existing_ids]
    existing_jobs = [j for j in jobs if str(j["external_id"]) in existing_ids]

    skipped = len(existing_jobs)
    print(f"  Skipping {skipped} duplicates — {len(new_jobs)} new jobs to process")

    # Refresh last_seen_at for jobs still live at the endpoint so they don't get purged
    if existing_jobs:
        total_refreshed = 0
        for batch in chunk(existing_jobs, BATCH_SIZE):
            ids = [j["external_id"] for j in batch]
            total_refreshed += turso.update_last_seen(ids, now)
        print(f"  Refreshed last_seen_at for {total_refreshed} existing jobs")

    if not new_jobs:
        print("No new jobs to insert — running purge and exiting.")
        purge_stale_jobs()
        sys.exit(0)

    print("\n=== STEP 3: Building embedding texts ===")

    for job in new_jobs:
        job["description"] = buildCleanedText(job)
        job["last_seen_at"] = now

    embedding_texts = [job["description"] for job in new_jobs]

    print("\n=== STEP 4: Generating embeddings ===")
    all_embeddings: list[list[float]] = []

    for i, batch_texts in enumerate(chunk(embedding_texts, BATCH_SIZE)):
        print(f"  Embedding batch {i + 1} ({len(batch_texts)} texts)…")
        batch_embeddings = generate_embeddings_batch(batch_texts)
        all_embeddings.extend(batch_embeddings)

    print(f"{len(all_embeddings)} embeddings generated")

    print("\n=== STEP 5: Inserting new jobs ===")
    for job, embedding in zip(new_jobs, all_embeddings):
        job["embedding"] = embedding

    total_inserted = 0
    for i, batch in enumerate(chunk(new_jobs, BATCH_SIZE)):
        print(f"Inserting batch {i + 1} ({len(batch)} records)…")
        try:
            sent = turso.upsert_jobs(batch)
            total_inserted += sent
        except Exception as e:
            print(f"Batch {i + 1} failed: {e}")
            raise

    print("\n=== STEP 6: Purging stale jobs ===")
    purge_stale_jobs()

    elapsed = time.perf_counter() - start
    print(f"\nPipeline complete — {total_inserted} new jobs inserted in {elapsed:.1f}s")


if __name__ == "__main__":
    # Surface missing config early, before any partial work.
    if not os.getenv("TURSO_DATABASE_URL"):
        raise RuntimeError("TURSO_DATABASE_URL must be set")
    if not os.getenv("TURSO_AUTH_TOKEN"):
        raise RuntimeError("TURSO_AUTH_TOKEN must be set")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY must be set")

    run_pipeline()
