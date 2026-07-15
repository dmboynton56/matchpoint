"""Backfill browse metadata columns for existing Turso jobs."""

from __future__ import annotations

import os
import sys

BATCH_SIZE = 100


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    if not os.getenv("TURSO_DATABASE_URL"):
        raise RuntimeError("TURSO_DATABASE_URL must be set")

    from app.db import turso
    from app.services.job_metadata import derive_browse_metadata

    turso.init_schema()
    total_updated = 0

    while True:
        rows = turso.fetch_jobs_for_metadata_backfill(limit=BATCH_SIZE)
        if not rows:
            break

        batch: list[tuple[str, dict]] = []
        for row in rows:
            metadata = derive_browse_metadata(
                title=row.get("title") or "",
                location=row.get("location"),
                description=row.get("description"),
            )
            batch.append((row["id"], metadata))

        turso.batch_update_job_metadata(batch)
        total_updated += len(batch)

        print(f"  Updated {total_updated} jobs so far…")

    print(f"Backfill complete — {total_updated} jobs updated.")


if __name__ == "__main__":
    main()
