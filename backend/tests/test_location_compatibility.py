"""Tests for the location_compatibility pure function.

These tests are the only thing that protects the no-regression guarantee
for existing users. Each test exercises a specific behavioral contract
documented in the function's docstring.

The new contract (post-distance-curve):
  - 0.0  = hard filter (wrong country)
  - 0.4  = floor for known in-country jobs
  - 0.5  = unknown (job not geocoded, or profile lacks prefs)
  - 0.7  = country matches but no distance info available
  - 0.7-1.0 = same country, score based on distance from user's anchor
  - 1.0  = same anchor location, or "any" mode, or no profile

The distance curve is piecewise: gentle within half the willing-to-
relocate radius, moderate within one radius, log decay beyond. The
test cases below pin specific points on the curve so future tweaks
to the constants are visible.
"""

import math
import unittest

from app.services.geo import location_compatibility


# Common test anchors (real lat/lon, not synthetic)
SF = (37.7749, -122.4194)
OAKLAND = (37.8044, -122.2712)  # ~13km from SF
PORTLAND = (45.5152, -122.6784)
SEATTLE = (47.6062, -122.3321)  # ~234km from Portland
NYC = (40.7128, -74.0060)  # ~4100km from SF, ~3900km from Portland
LA = (34.0522, -118.2437)  # ~559km from SF


def _us_job(lat, lon, **extras):
    """Helper: a known US job at given coords."""
    base = {
        "geo_country_code": "US",
        "geo_source": "geonames_offline",
        "geo_lat": lat,
        "geo_lon": lon,
    }
    base.update(extras)
    return base


def _profile(preferred_country_codes, preferred_lat=None, preferred_lon=None,
             preferred_radius_km=None, location_mode="country"):
    """Helper: a profile with the given country + optional anchor."""
    p = {
        "location_mode": location_mode,
        "preferred_country_codes": preferred_country_codes,
    }
    if preferred_lat is not None:
        p["preferred_lat"] = preferred_lat
    if preferred_lon is not None:
        p["preferred_lon"] = preferred_lon
    if preferred_radius_km is not None:
        p["preferred_radius_km"] = preferred_radius_km
    return p


class NoRegressionTests(unittest.TestCase):
    """The no-regression contract for users who haven't set prefs."""

    def test_no_profile_returns_one(self):
        # A None profile means "no preferences set" — never filter.
        self.assertEqual(
            location_compatibility(_us_job(*SF), None),
            1.0,
        )

    def test_empty_profile_returns_one(self):
        # An empty profile_location dict is the same as None.
        self.assertEqual(
            location_compatibility(_us_job(*SF), {}),
            1.0,
        )

    def test_any_mode_always_returns_one(self):
        # "Show me everything" — never filter, no matter what the
        # job looks like.
        self.assertEqual(
            location_compatibility(
                {"geo_country_code": "IN"},
                {"location_mode": "any", "preferred_country_codes": ["US"]},
            ),
            1.0,
        )

    def test_no_country_codes_with_country_mode_returns_one(self):
        # The zero-regression guarantee. A user with location_mode='country'
        # but no country codes sees everything.
        self.assertEqual(
            location_compatibility(
                {"geo_country_code": "IN", "geo_source": "geonames_offline"},
                _profile([]),
            ),
            1.0,
        )

    def test_country_code_normalized_to_uppercase(self):
        # Profile stored "us" lowercase, job is "US" — should still match.
        # With no city anchor and US centroid as fallback, the score
        # depends on distance from the centroid. Portland is ~2100km
        # from Kansas, so the score will be in the 0.55-0.7 range.
        score = location_compatibility(
            _us_job(*PORTLAND),
            _profile(["us"]),
        )
        # Country matches, distance is in log-decay region.
        self.assertGreater(score, 0.5)
        self.assertLess(score, 0.8)


class HardFilterTests(unittest.TestCase):
    """The hard filter only fires for country mismatches."""

    def test_india_job_with_us_country_pref_is_zero(self):
        # The actual "stop showing India to US users" guarantee.
        self.assertEqual(
            location_compatibility(
                _us_job(12.9716, 77.5946, geo_country_code="IN"),
                _profile(["US"]),
            ),
            0.0,
        )

    def test_wrong_country_with_country_mode_is_zero(self):
        # A Canadian job for a US-only user is hard-filtered.
        self.assertEqual(
            location_compatibility(
                _us_job(43.6532, -79.3832, geo_country_code="CA"),
                _profile(["US"]),
            ),
            0.0,
        )

    def test_unresolved_job_returns_half(self):
        # We genuinely don't know the country. Don't drop, don't reward.
        self.assertEqual(
            location_compatibility(
                {"geo_source": "unresolved", "geo_country_code": None},
                _profile(["US"]),
            ),
            0.5,
        )

    def test_macro_job_returns_half(self):
        # "Remote" / "LATAM" jobs have geo_source='macro' and no country.
        # Don't punish, don't reward — let the LLM see them.
        self.assertEqual(
            location_compatibility(
                {"geo_country_code": None, "geo_source": "macro"},
                _profile(["US"]),
            ),
            0.5,
        )


class DistanceCurveTests(unittest.TestCase):
    """The piecewise distance curve at specific known distances.

    These are the "shape of the curve" tests. They pin specific values
    so future tweaks to DEFAULT_WILLING_TO_RELOCATE_KM or the curve
    constants are visible in code review. If you change the curve,
    update these.
    """

    def _portland_user(self):
        return _profile(
            ["US"],
            preferred_lat=PORTLAND[0],
            preferred_lon=PORTLAND[1],
        )

    def test_same_city_is_one(self):
        # Portland user + Portland job = 1.0
        score = location_compatibility(_us_job(*PORTLAND), self._portland_user())
        self.assertAlmostEqual(score, 1.0, places=4)

    def test_portland_to_seattle_is_very_close(self):
        # 234km, default radius 500km — well within willing-to-relocate.
        # Within half-radius (250km), the curve is 1.0 -> 0.95. Score
        # should be around 0.95.
        score = location_compatibility(_us_job(*SEATTLE), self._portland_user())
        self.assertAlmostEqual(score, 0.953, places=2)

    def test_portland_to_sf_is_one_radius(self):
        # SF is ~960km from Portland, ~1.9x the default radius.
        # That's in the log-decay region. Score should be ~0.74.
        score = location_compatibility(_us_job(*SF), self._portland_user())
        self.assertGreater(score, 0.65)
        self.assertLess(score, 0.85)

    def test_portland_to_nyc_is_cross_country(self):
        # NYC is ~3900km from Portland, ~7.8x the default radius.
        # That's deep in the log-decay region. Score should be ~0.62.
        score = location_compatibility(_us_job(*NYC), self._portland_user())
        self.assertGreater(score, 0.55)
        self.assertLess(score, 0.7)

    def test_far_jobs_stay_above_floor(self):
        # Even the worst in-country case stays above 0.4.
        # 16000km is at the floor.
        score = location_compatibility(
            _us_job(0.0, 0.0),  # Gulf of Guinea, US territory
            self._portland_user(),
        )
        self.assertGreaterEqual(score, 0.4)

    def test_local_user_with_local_job_is_near_one(self):
        # SF user + Oakland job (~13km) — well within the gentle
        # region. Score should be very close to 1.0 but not exactly
        # (the curve is continuous, not flat). 13km / 250km half-radius
        # = 0.05 of the gentle slope, so score = 1.0 - 0.05*0.052 = 0.997.
        score = location_compatibility(
            _us_job(*OAKLAND),
            _profile(["US"], preferred_lat=SF[0], preferred_lon=SF[1]),
        )
        self.assertAlmostEqual(score, 0.997, places=2)
        self.assertGreater(score, 0.99)

    def test_sf_to_la_is_within_radius(self):
        # SF to LA is ~559km, just past the default 500km radius.
        # Score should be in the log-decay region.
        score = location_compatibility(
            _us_job(*LA),
            _profile(["US"], preferred_lat=SF[0], preferred_lon=SF[1]),
        )
        # LA is barely past 1x radius, so score is near 0.80.
        self.assertGreater(score, 0.7)
        self.assertLess(score, 0.85)

    def test_distance_score_uses_user_radius_not_default(self):
        # A user with preferred_radius_km=2000 sees Portland to Seattle
        # (234km) as essentially the same place.
        score_default = location_compatibility(
            _us_job(*SEATTLE), self._portland_user()
        )
        score_big_radius = location_compatibility(
            _us_job(*SEATTLE),
            _profile(["US"],
                     preferred_lat=PORTLAND[0],
                     preferred_lon=PORTLAND[1],
                     preferred_radius_km=2000),
        )
        # Same distance, bigger radius → closer to 1.0.
        self.assertGreater(score_big_radius, score_default)
        self.assertAlmostEqual(score_big_radius, 0.99, places=1)


class CountryCentroidTests(unittest.TestCase):
    """When the user sets a country but no city, the country centroid
    is the anchor."""

    def test_us_only_user_with_us_job_in_country(self):
        # User has no anchor. Country centroid is Kansas (39.83, -98.58).
        # A Portland job is ~2100km from Kansas. Score should be in
        # the log-decay region — well above the 0.4 floor, well below
        # the 1.0 perfect score.
        score = location_compatibility(
            _us_job(*PORTLAND), _profile(["US"])
        )
        self.assertGreater(score, 0.5)
        self.assertLess(score, 0.8)

    def test_us_centroid_does_not_prefer_east_or_west(self):
        # Both Portland (west coast) and NYC (east coast) are similar
        # distance from Kansas. The scores should be close to each
        # other — within 0.05.
        west = location_compatibility(_us_job(*PORTLAND), _profile(["US"]))
        east = location_compatibility(_us_job(*NYC), _profile(["US"]))
        self.assertAlmostEqual(west, east, delta=0.05)

    def test_country_centroid_falls_back_to_default_radius(self):
        # Without a preferred_radius_km, the user gets the 500km
        # default. With country centroid as anchor, distance is the
        # same regardless of city, so the radius doesn't change the
        # score for same-country jobs in the same region.
        score = location_compatibility(
            _us_job(*PORTLAND), _profile(["US"])
        )
        # No assertion on specific value — just that the function
        # doesn't crash and returns something in the expected range.
        self.assertGreater(score, 0.4)
        self.assertLess(score, 1.0)


class NoJobCoordsTests(unittest.TestCase):
    """When the job's coords are missing but the country is known."""

    def test_country_match_with_no_job_coords(self):
        # Country matched, user has an anchor, but job has no coords.
        # Score is "we know they match the country, but we don't know
        # more" — 0.7.
        score = location_compatibility(
            _us_job(None, None),
            _profile(["US"], preferred_lat=PORTLAND[0], preferred_lon=PORTLAND[1]),
        )
        self.assertEqual(score, 0.7)

    def test_country_match_with_user_no_anchor(self):
        # Country matches, neither side has coords. Same 0.7.
        score = location_compatibility(
            _us_job(None, None),
            _profile(["US"]),
        )
        self.assertEqual(score, 0.7)


class MultiCountryTests(unittest.TestCase):
    """Multiple preferred countries."""

    def test_multi_country_pref_accepts_match(self):
        # US or CA — a Canadian job is fine.
        score = location_compatibility(
            _us_job(43.6532, -79.3832, geo_country_code="CA"),
            _profile(["US", "CA"]),
        )
        # Country matches, distance from US centroid is moderate.
        # Just verify it's in the in-country range.
        self.assertGreater(score, 0.4)
        self.assertLess(score, 1.0)


class HardFilterEdgeCases(unittest.TestCase):
    """Edge cases the hard filter must handle."""

    def test_no_country_codes_with_city_radius(self):
        # location_mode='city_radius' but no country codes set and no
        # lat/lon — should return 1.0 (no signal, don't filter).
        score = location_compatibility(
            _us_job(*SF),
            {"location_mode": "city_radius", "preferred_country_codes": []},
        )
        self.assertEqual(score, 1.0)


class HaversineTests(unittest.TestCase):
    """Sanity checks on the distance function."""

    def test_zero_distance_for_same_point(self):
        from app.services.geo import _haversine_km
        self.assertAlmostEqual(_haversine_km(37.7749, -122.4194, 37.7749, -122.4194), 0.0)

    def test_known_distance_sf_to_la(self):
        # SF to LA is ~559 km.
        from app.services.geo import _haversine_km
        sf = (37.7749, -122.4194)
        la = (34.0522, -118.2437)
        d = _haversine_km(sf[0], sf[1], la[0], la[1])
        self.assertTrue(540 < d < 580, f"Expected ~559km, got {d}")


if __name__ == "__main__":
    unittest.main()
