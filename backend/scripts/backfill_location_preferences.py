"""Backfill structured location preferences for existing profiles.

Two modes:
  1. Default (safe): does NOTHING. Existing users with no structured
     columns keep getting unfiltered matches. This is the right
     behavior for the 3-day wrap-up — the migration adds the columns,
     and users opt in by hitting the PATCH endpoint or by setting
     location_mode via the front-end.

  2. Aggressive: set BACKFILL_AGGRESSIVE=1 to populate
     preferred_country_codes from each profile's preferred_locations
     text[]. This turns the country filter ON for users who already
     had a free-text location preference. Use only after front-end
     has been updated to handle the new filtered state.

Run once on the production server after the Supabase migration lands.
The script is idempotent — it skips profiles that already have a
non-null location_mode.

Usage:
    cd backend
    python -m scripts.backfill_location_preferences            # no-op
    BACKFILL_AGGRESSIVE=1 python -m scripts.backfill_location_preferences
"""

from __future__ import annotations

import os
import sys
import time

BATCH_SIZE = 100
REQUEST_SLEEP_SECONDS = 0.05


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_SECRET_KEY"):
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SECRET_KEY must be set"
        )

    aggressive = os.getenv("BACKFILL_AGGRESSIVE") == "1"
    if not aggressive:
        print(
            "Safe mode: no changes will be made. Set "
            "BACKFILL_AGGRESSIVE=1 to populate country codes from "
            "existing preferred_locations text[] values."
        )
        return

    from app.db.database import supabase
    from app.services.geo import geocode_job_location  # noqa: F401  -- kept for future use

    # Country code resolver: a tiny lookup for the most common free-text
    # values. We avoid hitting Photon for backfill because the user
    # values are user-typed and "United States" → "US" is a lookup,
    # not a geocode. Photon is reserved for actual place strings.
    _TEXT_TO_COUNTRY = {
        "united states": "US",
        "usa": "US",
        "us": "US",
        "u.s.": "US",
        "u.s.a.": "US",
        "canada": "CA",
        "united kingdom": "GB",
        "uk": "GB",
        "germany": "DE",
        "france": "FR",
        "spain": "ES",
        "italy": "IT",
        "netherlands": "NL",
        "sweden": "SE",
        "ireland": "IE",
        "india": "IN",
        "australia": "AU",
        "new zealand": "NZ",
        "japan": "JP",
        "singapore": "SG",
        "brazil": "BR",
        "mexico": "MX",
    }

    def _country_from_text(value: str) -> str | None:
        v = (value or "").strip().lower()
        if not v:
            return None
        return _TEXT_TO_COUNTRY.get(v)

    offset = 0
    total_processed = 0
    total_updated = 0
    total_already_structured = 0

    while True:
        try:
            response = (
                supabase.table("profiles")
                .select(
                    "id, preferred_locations, location_mode, "
                    "preferred_country_codes"
                )
                .order("id")
                .range(offset, offset + BATCH_SIZE - 1)
                .execute()
            )
        except Exception as exc:
            print(f"Failed to read profiles (offset={offset}): {exc}")
            sys.exit(1)

        rows = getattr(response, "data", None) or []
        if not rows:
            break

        for row in rows:
            total_processed += 1
            user_id = row.get("id")
            if not user_id:
                continue

            # Skip users who already have a non-default location_mode
            # or any country codes set. We've already touched them.
            if row.get("location_mode") and row.get("location_mode") != "country":
                total_already_structured += 1
                continue
            existing_codes = row.get("preferred_country_codes") or []
            if existing_codes:
                total_already_structured += 1
                continue

            # Derive country codes from preferred_locations.
            preferred = row.get("preferred_locations") or []
            codes: list[str] = []
            for entry in preferred:
                code = _country_from_text(entry)
                if code and code not in codes:
                    codes.append(code)

            if not codes:
                # No country could be inferred. Leave the user alone —
                # they have no preference set, and the matching route
                # already handles "no preference" without filtering.
                continue

            try:
                supabase.table("profiles").update(
                    {"preferred_country_codes": codes}
                ).eq("id", user_id).execute()
                total_updated += 1
            except Exception as exc:
                print(f"  update failed for user {user_id}: {exc}")

            time.sleep(REQUEST_SLEEP_SECONDS)

        offset += BATCH_SIZE
        if total_processed % 200 == 0:
            print(
                f"  Processed {total_processed} profiles, "
                f"updated {total_updated}, "
                f"skipped (already structured) {total_already_structured}…"
            )

    print(
        f"Backfill complete — processed {total_processed} profiles, "
        f"updated {total_updated}, "
        f"skipped (already structured) {total_already_structured}."
    )


if __name__ == "__main__":
    main()
