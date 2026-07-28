"""Backfill geolocation columns for existing Turso jobs.

Run once on the production server after the schema migration ships to seed
the geocode cache and populate geo_country_code / geo_city / etc. on rows
that arrived before geocoding was wired into the pipeline.

Soft-fail per-row: a bad row never aborts the whole backfill. Re-runnable:
the backfill is gated on `geo_country_code IS NULL`, so a second run is a
no-op once the cache is warm.

Usage:
    cd backend && python -m scripts.backfill_job_geo

This is intentionally NOT a cron job. The daily pipeline applies geocoding
to new rows as they arrive; this script is the once-per-cluster seed that
warms the cache for rows that already exist.
"""

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
    from app.services.geo import geocode_job_location

    turso.init_schema()
    total_updated = 0
    total_already_geo = 0

    seen_ids: set[str] = set()
    while True:
        rows = turso.fetch_jobs_for_geo_backfill(limit=BATCH_SIZE)
        if not rows:
            break

        row_ids = {row["id"] for row in rows}
        if row_ids and row_ids <= seen_ids:
            # Same rows came back again — something upstream failed to
            # persist geocoded_at. Stop instead of spinning forever.
            break
        seen_ids |= row_ids

        batch: list[tuple[str, dict]] = []
        for row in rows:
            geo = geocode_job_location(row.get("location") or "")
            if geo.get("geo_country_code"):
                total_already_geo += 1
            batch.append((row["id"], geo))

        turso.batch_update_job_geo(batch)
        total_updated += len(batch)

        print(
            f"  Processed {total_updated} rows so far "
            f"({total_already_geo} with country code, "
            f"{total_updated - total_already_geo} unresolved/macro)…"
        )

    print(
        f"Backfill complete — {total_updated} rows updated, "
        f"{total_already_geo} with country code, "
        f"{total_updated - total_already_geo} unresolved/macro."
    )


if __name__ == "__main__":
    main()
