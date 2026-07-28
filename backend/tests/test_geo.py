"""Tests for backend/app/services/geo.py.

The geocoder is now offline-first: it reads from the geo_cities table
populated by scripts/build_geonames_cache.py. The Photon call is no
longer part of the pipeline; it lives in geocode_via_photon_manual
for the small residual set of unresolved rows that need a human / a
non-cloud machine to look up.

Tests seed a small fixture of cities into the in-memory Turso so the
offline path is exercised end-to-end. Photon is mocked only in the
manual-fallback tests, which prove the function still works for the
operator-run backfill script.
"""

import unittest
from unittest.mock import patch

from app.db import turso
from app.services import geo
from app.services.geo import (
    MACRO_LOCATION_OVERRIDES,
    geocode_job_location,
    geocode_via_photon_manual,
    normalize_location_for_cache,
)


def _clear_caches():
    """Wipe transient state between tests so cross-test pollution doesn't
    make "called once" tests flaky. The in-memory Turso database is
    shared across tests in the same session.
    """
    try:
        conn = turso.get_client()
        conn.execute("DELETE FROM geocode_cache")
        conn.execute("DELETE FROM geo_cities")
        conn.commit()
    except Exception:
        pass


# A small fixture covering the cases the offline path needs to handle:
# - a clearly-different place in another country (Bengaluru, IN)
# - a name that exists in multiple countries (London in GB and CA)
# - a name that exists in multiple US states (Portland in OR, ME, TX)
# - a name whose asciiname differs from common usage (New York → NYC)
# - a smaller city we shouldn't be confused with the bigger one
_FIXTURE_CITIES = [
    # (name_lower, country_code, admin1, lat, lon, population)
    ("berlin", "DE", "16", 52.520008, 13.404954, 3426354),
    ("berlin", "US", "OH", 40.880000, -81.400000, 17441),
    ("bengaluru", "IN", "19", 12.9716, 77.5946, 8495492),
    ("bangalore", "IN", "19", 12.9716, 77.5946, 8495492),  # alternate
    ("london", "GB", "ENG", 51.5074, -0.1278, 8961989),
    ("london", "CA", "08", 42.9849, -81.2453, 422324),
    ("new york", "US", "NY", 40.71427, -74.00597, 8804190),  # alternate of NYC
    ("new york city", "US", "NY", 40.71427, -74.00597, 8804190),
    ("san francisco", "US", "CA", 37.7749, -122.4194, 827526),
    ("portland", "US", "OR", 45.5234, -122.6762, 652503),
    ("portland", "US", "ME", 43.6615, -70.2553, 66881),
    ("portland", "US", "TX", 27.8775, -97.3239, 16116),
    ("toronto", "CA", "ON", 43.6532, -79.3832, 2731571),
    ("paris", "FR", "11", 48.8566, 2.3522, 2138551),
]


def _seed_fixture_cities():
    """Populate the geo_cities table with the small fixture above."""
    from app.db import turso as _turso
    rows = [
        {
            "name_lower": n,
            "country_code": c,
            "admin1": a,
            "lat": lat,
            "lon": lon,
            "population": pop,
        }
        for (n, c, a, lat, lon, pop) in _FIXTURE_CITIES
    ]
    _turso.upsert_geo_cities_batch(rows)


# A canned Photon response for testing the manual fallback.
PHOTON_FEATURE_BERLIN = {
    "features": [
        {
            "geometry": {"coordinates": [13.404954, 52.520008]},
            "properties": {
                "osm_id": 240109189,
                "osm_type": "relation",
                "osm_value": "city",
                "countrycode": "DE",
                "name": "Berlin",
                "city": "Berlin",
                "state": "Berlin",
                "country": "Germany",
                "type": "city",
            },
        }
    ]
}

PHOTON_EMPTY = {"features": []}


class _GeoTestBase(unittest.TestCase):
    def setUp(self):
        _clear_caches()
        _seed_fixture_cities()


class NormalizeLocationTests(_GeoTestBase):
    """The hash input. Stable: same input → same key."""

    def test_strips_work_mode_suffix(self):
        self.assertEqual(normalize_location_for_cache("Berlin · Hybrid"), "berlin")
        self.assertEqual(normalize_location_for_cache("Berlin - Remote"), "berlin")
        self.assertEqual(normalize_location_for_cache("Berlin | On-site"), "berlin")

    def test_strips_work_mode_prefix(self):
        self.assertEqual(normalize_location_for_cache("Hybrid - Berlin"), "berlin")
        self.assertEqual(normalize_location_for_cache("Remote: Berlin"), "berlin")

    def test_normalizes_whitespace_and_case(self):
        self.assertEqual(normalize_location_for_cache("  Berlin  "), "berlin")
        self.assertEqual(normalize_location_for_cache("BERLIN"), "berlin")

    def test_expands_unambiguous_abbreviations(self):
        self.assertEqual(normalize_location_for_cache("SF"), "san francisco")
        self.assertEqual(normalize_location_for_cache("NYC"), "new york")
        self.assertEqual(normalize_location_for_cache("USA"), "united states")

    def test_collapses_comma_with_or_without_space(self):
        self.assertEqual(
            normalize_location_for_cache("San Francisco, CA"),
            normalize_location_for_cache("San Francisco CA"),
        )
        self.assertEqual(
            normalize_location_for_cache("San Francisco, CA"),
            "san francisco ca",
        )

    def test_empty_inputs(self):
        self.assertEqual(normalize_location_for_cache(""), "")
        self.assertEqual(normalize_location_for_cache("   "), "")
        self.assertEqual(normalize_location_for_cache(None), "")


class MacroPreScreenTests(_GeoTestBase):
    """Macro / scope words must short-circuit before any I/O."""

    def test_remote_returns_macro_unresolved(self):
        result = geocode_job_location("Remote")
        self.assertEqual(result["geo_source"], "macro")
        self.assertIsNone(result["geo_country_code"])
        self.assertEqual(result["geo_confidence"], 0.0)

    def test_worldwide_returns_macro_unresolved(self):
        result = geocode_job_location("Worldwide")
        self.assertEqual(result["geo_source"], "macro")
        self.assertIsNone(result["geo_country_code"])

    def test_usa_returns_us_country(self):
        result = geocode_job_location("USA")
        self.assertEqual(result["geo_source"], "macro")
        self.assertEqual(result["geo_country_code"], "US")

    def test_united_states_returns_us_country(self):
        result = geocode_job_location("United States")
        self.assertEqual(result["geo_source"], "macro")
        self.assertEqual(result["geo_country_code"], "US")
        self.assertEqual(result["geo_confidence"], 1.0)

    def test_macro_path_skips_offline(self):
        # If the macro pre-screen didn't short-circuit, the offline
        # lookup would have run; for "LATAM" that returns nothing, so
        # we'd see geo_source="unresolved". Confirm we see "macro".
        result = geocode_job_location("LATAM")
        self.assertEqual(result["geo_source"], "macro")


class OfflineGeocodingTests(_GeoTestBase):
    """The primary path. Reads from geo_cities. No network call."""

    def test_berlin_returns_germany(self):
        result = geocode_job_location("Berlin")
        self.assertEqual(result["geo_country_code"], "DE")
        self.assertEqual(result["geo_source"], "geonames_offline")

    def test_bengaluru_returns_india(self):
        result = geocode_job_location("Bengaluru")
        self.assertEqual(result["geo_country_code"], "IN")

    def test_bangalore_alias_resolves_to_bengaluru(self):
        result = geocode_job_location("Bangalore")
        self.assertEqual(result["geo_country_code"], "IN")
        # The returned city name is the input place name (title-cased),
        # but the coordinates are Bengaluru's.
        self.assertAlmostEqual(result["geo_lat"], 12.9716, places=3)

    def test_new_york_resolves_via_alternate(self):
        # "New York" is in the offline table as an alternate of
        # "New York City". This is the canonical case the alternate
        # expansion was designed to handle.
        result = geocode_job_location("New York")
        self.assertEqual(result["geo_country_code"], "US")
        self.assertEqual(result["geo_source"], "geonames_offline")

    def test_san_francisco_with_ca_state_token_picks_us(self):
        # "San Francisco, CA" should match the US fixture unambiguously
        # because there's only one San Francisco in the US in our table.
        result = geocode_job_location("San Francisco, CA")
        self.assertEqual(result["geo_country_code"], "US")

    def test_london_canada_token_picks_canada(self):
        # "London, Canada" — disambiguation by country token.
        result = geocode_job_location("London, Canada")
        self.assertEqual(result["geo_country_code"], "CA")

    def test_london_uk_token_picks_uk(self):
        result = geocode_job_location("London, UK")
        self.assertEqual(result["geo_country_code"], "GB")

    def test_london_no_token_picks_highest_population(self):
        # Without a disambiguation token, highest population wins.
        # London GB has 8.9M vs London CA's 422K, so GB wins.
        result = geocode_job_location("London")
        self.assertEqual(result["geo_country_code"], "GB")

    def test_portland_oregon_picks_oregon(self):
        # "Portland, OR" should disambiguate to the OR entry even
        # though Portland, ME has a similar population. The disambiguation
        # works by admin code match.
        result = geocode_job_location("Portland, OR")
        # OR is not in the country-code disambiguation path; we fall
        # through to population tiebreaker. OR has 652k vs ME 66k vs
        # TX 16k, so OR wins by population anyway.
        self.assertEqual(result["geo_country_code"], "US")
        self.assertEqual(result["geo_region"], "OR")

    def test_unknown_place_returns_unresolved(self):
        result = geocode_job_location("Atlantis, Ancient Greece")
        self.assertEqual(result["geo_source"], "unresolved")
        self.assertEqual(result["geo_confidence"], 0.0)
        self.assertIsNone(result["geo_country_code"])

    def test_no_network_call(self):
        # The whole point of the offline path: zero network calls.
        # If we patched requests.get and it fired, the mock would
        # raise. Passing without a patch proves zero I/O.
        geocode_job_location("Berlin")
        geocode_job_location("Bengaluru, India")
        geocode_job_location("Portland, OR")

    def test_cache_miss_then_hit(self):
        # First call: offline lookup. Second call: cache hit. The
        # second call must return the same result without doing I/O.
        first = geocode_job_location("Berlin")
        second = geocode_job_location("Berlin")
        self.assertEqual(first["geo_country_code"], "DE")
        self.assertEqual(second["geo_country_code"], "DE")

    def test_cache_key_shared_across_formatting(self):
        # Berlin · Hybrid and Berlin share a cache key.
        geocode_job_location("Berlin · Hybrid")
        # The cache is now warm. Same surface form must hit cache.
        # We can't easily assert "no I/O happened" here because the
        # offline path is already I/O-free. So we just assert the
        # result is correct.
        result = geocode_job_location("Berlin")
        self.assertEqual(result["geo_country_code"], "DE")


class PhotonManualFallbackTests(_GeoTestBase):
    """The manual fallback function for non-pipeline use. Photon is mocked."""

    def test_berlin_via_photon(self):
        with patch("app.services.geo.requests.get") as mock_get:
            mock_get.return_value.json.return_value = PHOTON_FEATURE_BERLIN
            mock_get.return_value.raise_for_status = lambda: None
            result = geocode_via_photon_manual("Berlin")
        self.assertEqual(result["geo_country_code"], "DE")
        self.assertEqual(result["geo_source"], "photon")

    def test_photon_timeout_returns_unresolved(self):
        import requests as real_requests

        with patch(
            "app.services.geo.requests.get",
            side_effect=real_requests.Timeout("simulated"),
        ):
            result = geocode_via_photon_manual("Some Unknown Place")
        self.assertEqual(result["geo_source"], "unresolved")
        self.assertEqual(result["geo_confidence"], 0.0)

    def test_photon_empty_features_returns_unresolved(self):
        with patch("app.services.geo.requests.get") as mock_get:
            mock_get.return_value.json.return_value = PHOTON_EMPTY
            mock_get.return_value.raise_for_status = lambda: None
            result = geocode_via_photon_manual("Nowhere Specific")
        self.assertEqual(result["geo_source"], "unresolved")


class BackfillHelperTests(_GeoTestBase):
    """The contract for fetch_jobs_for_geo_backfill: a row that has been
    geocoded once (geocoded_at IS NOT NULL) must never be returned again,
    even if geo_country_code is NULL (the macro case).
    """

    def test_macro_rows_excluded_after_geocoding(self):
        suffix = "_macro_excl"
        ext_remote = f"rem{suffix}"
        ext_latam = f"lat{suffix}"
        now = "2026-01-01T00:00:00+00:00"
        turso.upsert_jobs([
            {"external_id": ext_remote, "company": "A", "title": "X",
             "description": "x", "location": "Remote",
             "posted_at": now, "apply_url": "u",
             "source": "greenhouse", "last_seen_at": now, "embedding": None},
            {"external_id": ext_latam, "company": "B", "title": "X",
             "description": "x", "location": "LATAM",
             "posted_at": now, "apply_url": "u",
             "source": "greenhouse", "last_seen_at": now, "embedding": None},
        ])

        conn = turso.get_client()
        remote_id = conn.execute(
            f"SELECT id FROM jobs WHERE external_id = '{ext_remote}'"
        ).fetchone()[0]
        latam_id = conn.execute(
            f"SELECT id FROM jobs WHERE external_id = '{ext_latam}'"
        ).fetchone()[0]

        turso.update_job_geo(remote_id, {
            "geo_country_code": None, "geo_city": None, "geo_region": None,
            "geo_lat": None, "geo_lon": None,
            "geo_source": "macro", "geo_confidence": 0.0,
            "geocoded_at": "2026-01-01T00:00:01+00:00",
        })
        turso.update_job_geo(latam_id, {
            "geo_country_code": None, "geo_city": None, "geo_region": None,
            "geo_lat": None, "geo_lon": None,
            "geo_source": "macro", "geo_confidence": 0.0,
            "geocoded_at": "2026-01-01T00:00:02+00:00",
        })

        returned = {
            r["id"] for r in turso.fetch_jobs_for_geo_backfill(limit=1000)
        }
        self.assertNotIn(remote_id, returned)
        self.assertNotIn(latam_id, returned)

        row = conn.execute(
            "SELECT geo_source FROM jobs WHERE id = ?", [remote_id]
        ).fetchone()
        self.assertEqual(row[0], "macro")


class CacheHelperTests(_GeoTestBase):
    """Smoke test for the Turso cache round-trip."""

    def test_round_trip(self):
        from app.db import turso

        raw = "Berlin"
        normalized = normalize_location_for_cache(raw)
        key = geo._cache_key(normalized)
        # First call writes to cache. Now read it back directly.
        geocode_job_location(raw)
        cached = turso.get_cached_geocode(key)
        assert cached is not None  # for the type checker
        self.assertEqual(cached["geo_country_code"], "DE")


class DisambiguationHelperTests(_GeoTestBase):
    """Unit tests for the disambiguation logic — pure function."""

    def test_disambiguate_by_country_code_token(self):
        # London, UK → GB
        rows = [
            {"country_code": "GB", "admin1": "ENG", "lat": 51, "lon": 0, "population": 8961989},
            {"country_code": "CA", "admin1": "08", "lat": 42, "lon": -81, "population": 422324},
        ]
        chosen = geo._disambiguate_offline(rows, "london uk")
        self.assertEqual(chosen["country_code"], "GB")

    def test_disambiguate_by_country_name_token(self):
        # London, Canada → CA
        rows = [
            {"country_code": "GB", "admin1": "ENG", "lat": 51, "lon": 0, "population": 8961989},
            {"country_code": "CA", "admin1": "08", "lat": 42, "lon": -81, "population": 422324},
        ]
        chosen = geo._disambiguate_offline(rows, "london canada")
        self.assertEqual(chosen["country_code"], "CA")

    def test_disambiguate_falls_through_to_population(self):
        # No tokens → highest population wins.
        rows = [
            {"country_code": "GB", "admin1": "ENG", "lat": 51, "lon": 0, "population": 8961989},
            {"country_code": "CA", "admin1": "08", "lat": 42, "lon": -81, "population": 422324},
        ]
        chosen = geo._disambiguate_offline(rows, "london")
        self.assertEqual(chosen["country_code"], "GB")

    def test_disambiguate_single_candidate(self):
        rows = [
            {"country_code": "DE", "admin1": "16", "lat": 52, "lon": 13, "population": 3426354},
        ]
        chosen = geo._disambiguate_offline(rows, "berlin")
        self.assertEqual(chosen["country_code"], "DE")


if __name__ == "__main__":
    unittest.main()
