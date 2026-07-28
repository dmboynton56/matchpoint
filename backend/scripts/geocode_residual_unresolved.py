"""Re-geocode rows that the offline path couldn't resolve, using Photon.

This script is for the operator (you) to run by hand from a non-cloud
host — your laptop, not Vercel or a CI runner. Photon's public instance
blocks cloud / serverless IPs, so this would just fail if run from
Vercel. Run it from your dev machine where the IP isn't a known
datacenter range.

The output goes into the same geocode_cache table the pipeline reads
from, so once you've run this once, the pipeline benefits from the
better results without further intervention.

Usage:
    cd backend
    python -m scripts.geocode_residual_unresolved

    # Or to limit to N rows so you can spot-check the first batch:
    python -m scripts.geocode_residual_unresolved --limit 20
"""

from __future__ import annotations

import argparse
import os
import sys
import time


PHOTON_REQUEST_SLEEP_SECONDS = 1.0  # be polite on a public instance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=200,
        help="Maximum number of distinct unresolved locations to fetch (default 200)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be re-geocoded without making any HTTP calls",
    )
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    if not os.getenv("TURSO_DATABASE_URL"):
        raise RuntimeError("TURSO_DATABASE_URL must be set")
    if not os.getenv("TURSO_AUTH_TOKEN"):
        raise RuntimeError("TURSO_AUTH_TOKEN must be set")

    from app.db import turso
    from app.services.geo import geocode_via_photon_manual

    turso.init_schema()

    # Find distinct job locations whose offline geocoding returned
    # "unresolved". These are the rows the operator wants a human (or
    # a non-cloud Photon call) to look at.
    conn = turso.get_client()
    cursor = conn.execute(
        "SELECT DISTINCT location FROM jobs "
        "WHERE location IS NOT NULL AND location != '' "
        "AND geo_source = 'unresolved' "
        "ORDER BY location LIMIT ?",
        [args.limit],
    )
    targets = [str(row[0]) for row in cursor.fetchall() if row and row[0]]

    if not targets:
        print("No unresolved locations to process. Done.")
        return

    print(f"Found {len(targets)} distinct unresolved locations.")

    if args.dry_run:
        print("\n-- DRY RUN: would re-geocode the following strings --")
        for s in targets:
            print(f"  {s!r}")
        return

    print(f"\nCalling Photon for {len(targets)} locations "
          f"({PHOTON_REQUEST_SLEEP_SECONDS}s polite sleep between calls)…")
    total_updated = 0
    total_still_unresolved = 0
    for i, location in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] {location!r}", end=" ", flush=True)
        try:
            result = geocode_via_photon_manual(location)
        except Exception as exc:
            print(f"ERROR ({type(exc).__name__}): {exc}")
            continue
        if result.get("geo_source") == "unresolved" or not result.get("geo_country_code"):
            print(f"still unresolved (source={result.get('geo_source')})")
            total_still_unresolved += 1
        else:
            print(
                f"-> country={result['geo_country_code']!r} "
                f"city={result.get('geo_city')!r}"
            )
            total_updated += 1
            # Update jobs that had this exact location string.
            try:
                conn.execute(
                    "UPDATE jobs SET geo_country_code = ?, geo_city = ?, "
                    "geo_region = ?, geo_lat = ?, geo_lon = ?, "
                    "geo_confidence = ?, geo_source = ?, geocoded_at = ? "
                    "WHERE location = ? AND geo_source = 'unresolved'",
                    [
                        result.get("geo_country_code"),
                        result.get("geo_city"),
                        result.get("geo_region"),
                        result.get("geo_lat"),
                        result.get("geo_lon"),
                        result.get("geo_confidence"),
                        result.get("geo_source"),
                        result.get("geocoded_at"),
                        location,
                    ],
                )
                conn.commit()
            except Exception as exc:
                print(f"  DB update failed: {exc}")
        # Polite sleep — Photon's public instance is rate-limited
        # informally and we don't want to get blocked mid-batch.
        time.sleep(PHOTON_REQUEST_SLEEP_SECONDS)

    print(
        f"\nDone. {total_updated} updated, "
        f"{total_still_unresolved} still unresolved."
    )


if __name__ == "__main__":
    main()
