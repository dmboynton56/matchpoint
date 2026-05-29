"""
run_pipeline.py — Daily job pipeline
  1. Scrape job postings from Greenhouse boards
  2. Fetch existing external_ids from Supabase, filter to new-only
  3. Clean & build embedding text for new jobs only
  4. Batch-embed via OpenAI
  5. Insert new jobs into Supabase
  6. Purge jobs older than 7 days
"""

import os
import sys
import time
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from supabase import create_client, Client

from .scraper100 import scrape_all
from .cleaning import buildCleanedText
from .embedding import generate_embeddings_batch

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")

if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_SECRET_KEY must be set")

BATCH_SIZE = 100 # OpenAI supports up to 2048
STALE_AFTER_DAYS = 7 # Time of existing after which should be removed


def chunk(lst: list, size: int):
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


def fetch_existing_ids(supabase: Client) -> set[str]:
    #Return the set of external_ids already in the database
    existing = set()
    offset = 0
    page_size = 1000
    while True:
        result = (
            supabase.table("jobs")
            .select("external_id")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = result.data or []
        for row in rows:
            existing.add(str(row["external_id"]))
        if len(rows) < page_size:
            break
        offset += page_size
    return existing


def purge_stale_jobs(supabase: Client):
    # Delete any job whose created_at is older than STALE_AFTER_DAYS
    cutoff = (datetime.now(timezone.utc) - timedelta(days=STALE_AFTER_DAYS)).isoformat()
    try:
        result = (
            supabase.table("jobs")
            .delete()
            .lt("created_at", cutoff)
            .execute()
        )
        deleted = len(result.data) if result.data else 0
        print(f"Purged {deleted} jobs older than {STALE_AFTER_DAYS} days")
    except Exception as e:
        print(f"Purge failed: {e}")


def run_pipeline():
    start = time.perf_counter()

    print("=== STEP 1: Scraping ===")
    jobs = scrape_all()

    if not jobs:
        print("No jobs scraped — exiting.")
        sys.exit(0)

    print("\n=== STEP 2: Filtering duplicates ===")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)
    existing_ids = fetch_existing_ids(supabase)
    print(f"  {len(existing_ids)} existing external_ids in DB")

    new_jobs = [j for j in jobs if str(j["external_id"]) not in existing_ids]
    skipped = len(jobs) - len(new_jobs)
    print(f"  Skipping {skipped} duplicates — {len(new_jobs)} new jobs to process")

    if not new_jobs:
        print("No new jobs to insert — running purge and exiting.")
        purge_stale_jobs(supabase)
        sys.exit(0)

    print("\n=== STEP 3: Building embedding texts ===")
    for job in new_jobs:
        job["description"] = buildCleanedText(job)

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
            supabase.table("jobs").upsert(
                batch,
                on_conflict="external_id",
                ignore_duplicates=True,
            ).execute()
            total_inserted += len(batch)
        except Exception as e:
            print(f"Batch {i + 1} failed: {e}")
    
    for job in batch:
        print(f"  + {job['company']} — {job['title']} ({job['location']})")

    print("\n=== STEP 6: Purging stale jobs ===")
    purge_stale_jobs(supabase)

    elapsed = time.perf_counter() - start
    print(f"\nPipeline complete — {total_inserted} new jobs inserted in {elapsed:.1f}s")


if __name__ == "__main__":
    run_pipeline()