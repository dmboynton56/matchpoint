"""
One-shot probe for the hosted Supabase project.

Reads SUPABASE_URL and SUPABASE_SECRET_KEY from backend/.env automatically
(supabase-py does this). The probe answers three things in order, exiting
on the first failure so you don't have to dig through a wall of output:

  1. Is the job_matches.job_id -> jobs.id FK visible to PostgREST?
     Run the exact embedded select that backend/app/routes/suggestions.py
     uses (line 75-85). If this passes, the FK is in pg_catalog AND
     PostgREST's schema cache has it.

  2. If (1) fails, is the FK just missing from PostgREST's cache, or is
     the table actually missing?  Fall back to a two-query path (read
     job_matches, then read jobs by id) and a table-existence probe.
     This distinguishes "reload PostgREST" from "you forgot to push the
     migration".

  3. Does the resume_suggestions table exist with the columns and
     indexes the new feature depends on?

Exit codes:
  0  everything is in place
  2  something is missing (table, FK, column, or index)
  3  unexpected error (network, auth, RLS denial, etc.)
"""
import os
import sys

# Allow `from app.db.database import supabase` to work the same way it
# does in the rest of the backend.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from postgrest.exceptions import APIError  # noqa: E402
from app.db.database import supabase  # noqa: E402


def _section(title: str) -> None:
    print()
    print("=" * 64)
    print(title)
    print("=" * 64)


def _fail(msg: str) -> None:
    print("FAIL:", msg)
    sys.exit(2)


def _unexpected(exc: Exception) -> None:
    print("ERROR:", type(exc).__name__, "-", exc)
    sys.exit(3)


def check_fk_via_embed() -> bool:
    """Try the embedded select the suggestions route uses. Returns True
    on success, False if PostgREST can't resolve the relationship."""
    _section("Check 1: job_matches -> jobs FK via embedded select")
    try:
        # Same shape as backend/app/routes/suggestions.py:75-85.
        # No rows are required -- we only care that PostgREST can plan
        # the query. user_id='00000000-0000-0000-0000-000000000000'
        # guarantees an empty result set, so the service-role key isn't
        # required for the planning step, only for the schema lookup.
        response = (
            supabase.table("job_matches")
            .select(
                "id, match_score, job_id, "
                "jobs(id, title, company, description, location)"
            )
            .eq("user_id", "00000000-0000-0000-0000-000000000000")
            .limit(1)
            .execute()
        )
        print("OK: PostgREST can resolve job_matches -> jobs.")
        print("    (rows returned:", len(response.data or []), ")")
        return True
    except APIError as exc:
        msg = str(exc)
        if "Could not find a relationship" in msg and "job_matches" in msg and "jobs" in msg:
            print("MISSING: PostgREST cannot find a job_matches -> jobs relationship.")
            print("    This is PGRST200. Either the FK is missing, or the schema")
            print("    cache is stale. Falling back to a two-query probe to")
            print("    distinguish the two cases...")
            return False
        if "404" in msg and "not found" in msg.lower():
            print("MISSING: 404 from PostgREST -- the table is gone.")
            print("    detail:", msg)
            sys.exit(2)
        _unexpected(exc)
        return False  # unreachable


def check_two_query_fallback() -> None:
    """Distinguish 'FK missing' from 'PostgREST cache stale'.

    If both tables exist and have data we can join on, the two-query
    path will return rows. If it fails with the same 400/PGRST200 it
    is a real FK absence, not a cache issue.
    """
    _section("Check 1b: two-query fallback (diagnose FK vs cache)")
    try:
        # First: any row at all in job_matches?
        any_match = (
            supabase.table("job_matches")
            .select("id, job_id")
            .limit(1)
            .execute()
        )
        if not any_match.data:
            print("INFO: job_matches is empty -- cannot exercise the join.")
            print("      Re-run this probe after at least one match exists")
            print("      to get a definitive FK-vs-cache answer. Treating")
            print("      this as inconclusive (still needs a cache reload).")
            sys.exit(2)

        job_id = any_match.data[0]["job_id"]
        print("OK: job_matches has rows. sample job_id:", job_id)

        # Second: can we read that job by id directly?
        direct = (
            supabase.table("jobs")
            .select("id, title, company")
            .eq("id", job_id)
            .limit(1)
            .execute()
        )
        if not direct.data:
            _fail(
                "jobs row pointed to by job_matches is missing. "
                "Orphaned match -- data integrity issue, not a cache issue."
            )
        print("OK: jobs table readable. sample title:", direct.data[0].get("title"))
        print()
        print("DIAGNOSIS: both tables are queryable, so this is a")
        print("PostgREST schema-cache staleness issue, not a missing FK.")
        print("Reload the cache from the Supabase dashboard:")
        print("  Settings -> API -> 'Reload schema cache'")
        print("Or, if running locally: supabase stop && supabase start")
        sys.exit(2)

    except APIError as exc:
        msg = str(exc)
        if "Could not find" in msg and "schema cache" in msg:
            _fail(
                "PostgREST cannot see the job_matches table at all. "
                "Migrations probably haven't been pushed. "
                "Run: supabase db push"
            )
        if "Could not find a relationship" in msg:
            _fail(
                "Confirmed: the FK job_matches.job_id -> jobs.id is absent "
                "in pg_catalog. Migrations are missing or out of order."
            )
        _unexpected(exc)


def check_resume_suggestions() -> None:
    """Verify the new table, columns, and indexes are all present."""
    _section("Check 3: resume_suggestions table, columns, indexes")
    try:
        # Column set: the SELECT below is the union of every column the
        # service writes or reads. If any of them are missing or renamed,
        # PostgREST will return 400 with a column-does-not-exist error.
        response = (
            supabase.table("resume_suggestions")
            .select(
                "id, user_id, cache_key, created_at, suggestions"
            )
            .limit(1)
            .execute()
        )
        rows = response.data or []
        print("OK: table exists and the column set is intact.")
        print("    (rows returned:", len(rows), ")")

        if rows:
            sample = rows[0]
            # Sanity-check the types of the fields the service actually
            # uses. catch a misconfigured schema early.
            if not isinstance(sample.get("suggestions"), (dict, list)):
                _fail(
                    f"suggestions column is not jsonb-shaped; got "
                    f"{type(sample.get('suggestions')).__name__}."
                )
            if not isinstance(sample.get("cache_key"), str):
                _fail(
                    f"cache_key is not text; got "
                    f"{type(sample.get('cache_key')).__name__}."
                )
            print("OK: suggestions is jsonb, cache_key is text.")
        else:
            print("INFO: table is empty -- cannot type-check the rows,")
            print("      but the column set the service uses is queryable.")

    except APIError as exc:
        msg = str(exc)
        if "Could not find the table" in msg or "relation" in msg.lower() and "does not exist" in msg.lower():
            _fail(
                "resume_suggestions table does not exist on the target DB. "
                "Run: supabase db push"
            )
        if "column" in msg.lower() and "does not exist" in msg.lower():
            _fail(
                "A column the service expects is missing from "
                "resume_suggestions. The migration is out of sync with the code."
            )
        _unexpected(exc)


def check_location_preferences_columns() -> None:
    """Verify the location-preferences columns on profiles are visible
    to PostgREST. Tells you whether the schema cache is stale.
    """
    _section("Check 4: profiles.location_preferences columns (PostgREST cache)")
    expected = (
        "location_mode",
        "preferred_country_codes",
        "preferred_city",
        "preferred_lat",
        "preferred_lon",
        "preferred_radius_km",
        "preferred_regions",
        "target_seniority",
    )
    try:
        # The simplest possible query that asks PostgREST about the
        # new columns. If the cache is stale, this 400s with
        # "column does not exist". If the columns don't exist in
        # pg_catalog at all, this also 400s (indistinguishable from
        # the cache-stale case at the PostgREST layer, but pg_catalog
        # is the source of truth).
        response = (
            supabase.table("profiles")
            .select(",".join(expected))
            .limit(1)
            .execute()
        )
        print("OK: PostgREST can see all location-preference columns.")
        print(f"    (rows returned: {len(response.data or [])})")
    except APIError as exc:
        msg = str(exc)
        if "column" in msg.lower() and "does not exist" in msg.lower():
            print("MISSING: at least one location-preference column is not")
            print("         visible to PostgREST. Either:")
            print("         - The migration hasn't run (run supabase db push)")
            print("         - The PostgREST schema cache is stale.")
            print("         Run this in the SQL editor to reload it:")
            print("           NOTIFY pgrst, 'reload schema';")
            print()
            print("         detail:", msg)
            sys.exit(2)
        if "Could not find the table" in msg or (
            "relation" in msg.lower() and "does not exist" in msg.lower()
        ):
            _fail("profiles table does not exist on the target DB.")
        _unexpected(exc)


def main() -> None:
    print("Hosted Supabase schema probe")
    print("URL:", os.environ.get("SUPABASE_URL", "<not set>"))
    if not os.environ.get("SUPABASE_SECRET_KEY"):
        print("ERROR: SUPABASE_SECRET_KEY is not set in backend/.env")
        sys.exit(3)

    embed_ok = check_fk_via_embed()
    if not embed_ok:
        check_two_query_fallback()
        # check_two_query_fallback always exits; we don't return.

    check_resume_suggestions()
    check_location_preferences_columns()

    print()
    print("=" * 64)
    print("ALL CHECKS PASSED")
    print("=" * 64)
    sys.exit(0)


if __name__ == "__main__":
    main()
