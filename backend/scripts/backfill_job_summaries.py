"""Backfill LLM browse summaries for existing Turso jobs."""

from __future__ import annotations

import argparse
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

BATCH_SIZE = 100


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Maximum number of jobs to process (default: 500).",
    )
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    if not os.getenv("TURSO_DATABASE_URL"):
        raise RuntimeError("TURSO_DATABASE_URL must be set")

    from app.db import turso
    from app.services.job_summary import (
        SUMMARY_MODEL,
        SUMMARY_WORKERS,
        description_hash,
        generate_summary,
    )

    turso.init_schema()
    seen: set[str] = set()
    total_updated = 0
    total_failed = 0
    remaining = args.limit

    def _generate(row: dict) -> str | None:
        return generate_summary(
            row.get("description") or "",
            title=row.get("title") or "",
            company=row.get("company") or "",
        )

    while remaining > 0:
        rows = turso.fetch_jobs_for_summary_backfill(
            limit=min(BATCH_SIZE, remaining),
            exclude_ids=list(seen) or None,
        )
        if not rows:
            break
        seen.update(row["id"] for row in rows)
        remaining -= len(rows)

        # Offline batch work — higher parallelism than the request path is safe.
        with ThreadPoolExecutor(
            max_workers=min(SUMMARY_WORKERS * 2, len(rows))
        ) as pool:
            summaries = list(pool.map(_generate, rows))

        generated_at = datetime.now(timezone.utc).isoformat()
        updates: list[tuple[str, dict]] = []
        for row, summary in zip(rows, summaries):
            if not summary:
                continue
            updates.append(
                (
                    row["id"],
                    {
                        "summary": summary,
                        "source_hash": description_hash(row.get("description") or ""),
                        "model": SUMMARY_MODEL,
                        "generated_at": generated_at,
                    },
                )
            )

        turso.batch_update_job_summaries(updates)
        total_updated += len(updates)
        total_failed += len(rows) - len(updates)

        print(f"  Updated {total_updated} jobs so far ({total_failed} failed)…")

    print(f"Backfill complete — {total_updated} jobs updated, {total_failed} failed.")


if __name__ == "__main__":
    main()
