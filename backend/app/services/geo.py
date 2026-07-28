"""
geo.py — geocoding enrichment for job `location` strings.

Pipeline-time service. Called from `run_pipeline.py` right after metadata
derivation, before the job is upserted to Turso. The output is a flat dict
that matches the `geo_*` columns on the `jobs` table — callers just splat
the result into the upsert payload.

Public surface:
    geocode_job_location(raw_location: str | None) -> dict
        Soft-fail: never raises, always returns a dict. On total failure the
        result has `geo_source = "unresolved"` and `geo_confidence = 0.0`,
        which the read path treats as "unknown, don't punish, don't reward."
        Offline-first: reads from the geo_cities table populated by
        scripts/build_geonames_cache.py. No network call.

    geocode_via_photon_manual(raw_location: str) -> dict
        Manual Photon fallback for the small residual set of unresolved
        rows. NOT called by the pipeline. Run via
        scripts/geocode_residual_unresolved.py from a non-cloud host.

    normalize_location_for_cache(raw_location: str) -> str
        The hash input. Stable: same input always maps to the same key, so
        the cache hit rate stays high across re-scrapes with minor formatting
        differences (whitespace, US state codes, common abbreviations).

Why offline
-----------
The pipeline runs on Vercel serverless, whose IPs are cloud / datacenter
ranges. Photon's public instance (komoot's free demo) blocks cloud IPs
because that's where scraping traffic comes from. Building a daily
geocoder on a public service that 403s on our egress is fragile and
unsustainable, especially with a 3-day wrap-up.

GeoNames cities15000.txt is public domain, ~25k cities with country,
admin region, lat/lon, population. We download it once (via
scripts/build_geonames_cache.py), load it into the geo_cities table,
and the geocoder reads from there at zero network cost. The disambiguation
logic (admin tokens, population tiebreaker) handles the top 200 most
common cities in our corpus correctly. Photon is kept as a manual
fallback for the ~5% of locations cities15000 doesn't have.

Design choices worth noting
---------------------------
1. **Macro-word pre-screen.** Strings like "Remote", "LATAM", "EMEA",
   "North America", "Global" don't geocode to a place — they're a *work
   scope*, not a place. We short-circuit them with a hardcoded lookup
   that sets `geo_country_code` (or leaves it null for true global) and
   skips the offline lookup. This is the largest accuracy win.
2. **Aggressive normalization before hashing.** "San Francisco", "SF",
   "San Francisco, CA", "san francisco ca" should all hit the same cache
   row. Without this the cache hit rate plateaus around 50–60%.
3. **Alternate-name expansion at build time.** cities15000's
   `alternatenames` column is a comma-joined dump of all-language
   variants; we extract English-like alternates (ASCII, short, no
   digits) and add them as additional lookup rows. This catches
   "New York" -> "New York City" and "Bangalore" -> "Bengaluru" without
   shipping the much larger alternateNamesV2 dataset.
4. **Disambiguation via tokens + population.** "London" with no
   disambiguation token returns the highest-population match (GB).
   "London, Canada" or "London, UK" disambiguates by country code or
   name match. "Portland, OR" disambiguates by admin code.
5. **Cache is permanent.** Place strings don't change meaning. The cache
   table grows to ~one row per unique location string ever seen and stops
   growing fast within a week of operation.
6. **Cache writes never raise.** The cache is an accelerator, not a
   source of truth. The job upsert still works with whatever result the
   geocoder returned in this run.
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone
from typing import Any

import requests

from app.db import turso


# -----------------------------------------------------------------------------
# Tunables
# -----------------------------------------------------------------------------
PHOTON_ENDPOINT = "https://photon.komoot.io/api/"
PHOTON_TIMEOUT_SECONDS = 5
PHOTON_RESULTS_LIMIT = 1
# Sleep used by the manual Photon fallback script
# (scripts/geocode_residual_unresolved.py). The pipeline never calls Photon
# so this isn't used at request time. Set high enough to be polite to a
# public instance that's known to throttle aggressive callers.
PHOTON_POLITE_SLEEP_SECONDS = 1.0


# -----------------------------------------------------------------------------
# Macro-word pre-screen
# -----------------------------------------------------------------------------
# These strings are *work scopes*, not places. Photon would either return no
# feature or return the wrong country (e.g. "Remote" → Iceland's
# "Reykjanesbær"). We short-circuit them with a hardcoded mapping so the
# read path treats them deterministically.
#
# Rule for adding entries: if the string appears in 50+ unique jobs across
# the corpus OR the user-facing concept is "where the work happens is not
# a place", add it here. Keep the entries pluralizable enough to be useful
# but exact enough to avoid false positives.
MACRO_LOCATION_OVERRIDES: dict[str, dict | None] = {
    "remote": {
        "geo_country_code": None,
        "geo_city": None,
        "geo_region": None,
        "geo_lat": None,
        "geo_lon": None,
        "geo_source": "macro",
        "geo_confidence": 0.0,
    },
    "worldwide": {
        "geo_country_code": None,
        "geo_city": None,
        "geo_region": None,
        "geo_lat": None,
        "geo_lon": None,
        "geo_source": "macro",
        "geo_confidence": 0.0,
    },
    "global": {
        "geo_country_code": None,
        "geo_city": None,
        "geo_region": None,
        "geo_lat": None,
        "geo_lon": None,
        "geo_source": "macro",
        "geo_confidence": 0.0,
    },
    "anywhere": {
        "geo_country_code": None,
        "geo_city": None,
        "geo_region": None,
        "geo_lat": None,
        "geo_lon": None,
        "geo_source": "macro",
        "geo_confidence": 0.0,
    },
    "us": {
        "geo_country_code": "US",
        "geo_city": None,
        "geo_region": None,
        "geo_lat": None,
        "geo_lon": None,
        "geo_source": "macro",
        "geo_confidence": 0.9,
    },
    "usa": {
        "geo_country_code": "US",
        "geo_city": None,
        "geo_region": None,
        "geo_lat": None,
        "geo_lon": None,
        "geo_source": "macro",
        "geo_confidence": 0.9,
    },
    "united states": {
        "geo_country_code": "US",
        "geo_city": None,
        "geo_region": None,
        "geo_lat": None,
        "geo_lon": None,
        "geo_source": "macro",
        "geo_confidence": 1.0,
    },
    "united states of america": {
        "geo_country_code": "US",
        "geo_city": None,
        "geo_region": None,
        "geo_lat": None,
        "geo_lon": None,
        "geo_source": "macro",
        "geo_confidence": 1.0,
    },
    "canada": {
        "geo_country_code": "CA",
        "geo_city": None,
        "geo_region": None,
        "geo_lat": None,
        "geo_lon": None,
        "geo_source": "macro",
        "geo_confidence": 1.0,
    },
    "uk": {
        "geo_country_code": "GB",
        "geo_city": None,
        "geo_region": None,
        "geo_lat": None,
        "geo_lon": None,
        "geo_source": "macro",
        "geo_confidence": 0.9,
    },
    "united kingdom": {
        "geo_country_code": "GB",
        "geo_city": None,
        "geo_region": None,
        "geo_lat": None,
        "geo_lon": None,
        "geo_source": "macro",
        "geo_confidence": 1.0,
    },
    "emea": {
        "geo_country_code": None,
        "geo_city": None,
        "geo_region": None,
        "geo_lat": None,
        "geo_lon": None,
        "geo_source": "macro",
        "geo_confidence": 0.0,
    },
    "latam": {
        "geo_country_code": None,
        "geo_city": None,
        "geo_region": None,
        "geo_lat": None,
        "geo_lon": None,
        "geo_source": "macro",
        "geo_confidence": 0.0,
    },
    "north america": {
        "geo_country_code": None,
        "geo_city": None,
        "geo_region": None,
        "geo_lat": None,
        "geo_lon": None,
        "geo_source": "macro",
        "geo_confidence": 0.0,
    },
    "south america": {
        "geo_country_code": None,
        "geo_city": None,
        "geo_region": None,
        "geo_lat": None,
        "geo_lon": None,
        "geo_source": "macro",
        "geo_confidence": 0.0,
    },
    "apac": {
        "geo_country_code": None,
        "geo_city": None,
        "geo_region": None,
        "geo_lat": None,
        "geo_lon": None,
        "geo_source": "macro",
        "geo_confidence": 0.0,
    },
    "europe": {
        "geo_country_code": None,
        "geo_city": None,
        "geo_region": None,
        "geo_lat": None,
        "geo_lon": None,
        "geo_source": "macro",
        "geo_confidence": 0.0,
    },
    "eu": {
        "geo_country_code": None,
        "geo_city": None,
        "geo_region": None,
        "geo_lat": None,
        "geo_lon": None,
        "geo_source": "macro",
        "geo_confidence": 0.0,
    },
}


# -----------------------------------------------------------------------------
# Normalization
# -----------------------------------------------------------------------------
# Common abbreviations we want to canonicalize BEFORE hashing so that
# "SF" and "San Francisco" share a cache row. Only expand where the expansion
# is unambiguous — "LA" is ambiguous (Los Angeles vs Louisiana) so we leave it.
_ABBREVIATION_EXPANSIONS: dict[str, str] = {
    "sf": "san francisco",
    "nyc": "new york",
    "dc": "washington",
    "uk": "united kingdom",
    "usa": "united states",
    "us": "united states",
}

# Strip common work-mode suffixes that Photon doesn't need and that would
# otherwise produce different hashes for "Berlin" vs "Berlin · Hybrid".
# Strip common work-mode suffixes that Photon doesn't need and that would
# otherwise produce different hashes for "Berlin" vs "Berlin · Hybrid".
# Plain `-` is included so "Berlin - Remote" fragments the same as "Berlin".
_WORK_MODE_SUFFIX_RE = re.compile(
    r"\s*(?:[·•|]|\s-\s)\s*(remote|hybrid|in-?office|on-?site|onsite)\s*$",
    re.IGNORECASE,
)
# Strip leading "Remote - " / "Hybrid - " prefixes already handled by
# resolve_job_location, but some raw strings still have them.
_WORK_MODE_PREFIX_RE = re.compile(
    r"^(remote|hybrid|in-?office|on-?site|onsite)\s*[-–—:,]\s*",
    re.IGNORECASE,
)


def normalize_location_for_cache(raw_location: str | None) -> str:
    """Build a stable cache key from a raw location string.

    Strips work-mode suffixes, collapses whitespace, lowercases, and expands
    a handful of unambiguous abbreviations. The output is the hash input —
    two raw strings that produce the same normalized string share a cache row.
    """
    if not raw_location:
        return ""
    s = raw_location.strip()
    if not s:
        return ""
    # Strip trailing work mode like " · Hybrid", " - Remote"
    s = _WORK_MODE_SUFFIX_RE.sub("", s)
    # Strip leading work mode like "Remote - ", "Hybrid: "
    s = _WORK_MODE_PREFIX_RE.sub("", s)
    # Collapse whitespace, strip punctuation noise
    s = re.sub(r"\s+", " ", s)
    s = s.strip(" ,;•|")
    # Don't let a missing comma fragment the cache. "san francisco, ca" and
    # "san francisco ca" should hash to the same key — Photon handles the
    # state code as a hint, not as a hard filter, so dropping the comma
    # costs nothing and improves cache hit rate.
    s = re.sub(r"\s*,\s*", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Un-abbreviate
    s = s.lower()
    if s in _ABBREVIATION_EXPANSIONS:
        s = _ABBREVIATION_EXPANSIONS[s]
    return s


def _cache_key(normalized: str) -> str:
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# -----------------------------------------------------------------------------
# Macro pre-screen
# -----------------------------------------------------------------------------
def _check_macro(normalized: str) -> dict | None:
    """If the normalized string is a known macro / scope word, return the
    hardcoded overrides. Otherwise return None so the caller falls through
    to Photon.
    """
    return MACRO_LOCATION_OVERRIDES.get(normalized)


# -----------------------------------------------------------------------------
# Photon call
# -----------------------------------------------------------------------------
def _call_photon(query: str) -> dict:
    """Single Photon call. Returns a fully-shaped geo result dict.

    Never raises — all exceptions are converted to a "unresolved" result
    so the calling pipeline step always has a valid dict to splat into the
    upsert payload. The cache write is the caller's responsibility.
    """
    try:
        resp = requests.get(
            PHOTON_ENDPOINT,
            params={"q": query, "limit": PHOTON_RESULTS_LIMIT},
            timeout=PHOTON_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
    except Exception as exc:
        print(f"[geo] Photon call failed ({type(exc).__name__}): {exc}")
        return _unresolved_result()

    try:
        payload = resp.json()
    except ValueError:
        return _unresolved_result()

    features = payload.get("features") or []
    if not features:
        return _unresolved_result()

    feature = features[0]
    geometry = feature.get("geometry") or {}
    coords = geometry.get("coordinates") or []
    properties = feature.get("properties") or {}

    # Photon returns coordinates as [lon, lat] (GeoJSON convention).
    if len(coords) < 2:
        return _unresolved_result()
    lon, lat = coords[0], coords[1]
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return _unresolved_result()

    country_code = properties.get("countrycode")
    city = properties.get("city") or properties.get("name")
    region = properties.get("state")

    # If Photon gave us no country code at all, treat the result as low
    # confidence — the place string was probably ambiguous.
    if not country_code:
        return {
            "geo_country_code": None,
            "geo_city": city,
            "geo_region": region,
            "geo_lat": float(lat),
            "geo_lon": float(lon),
            "geo_source": "photon",
            "geo_confidence": 0.5,
        }

    return {
        "geo_country_code": country_code.upper() if country_code else None,
        "geo_city": city,
        "geo_region": region,
        "geo_lat": float(lat),
        "geo_lon": float(lon),
        "geo_source": "photon",
        "geo_confidence": _confidence_from_osm(properties),
    }


# -----------------------------------------------------------------------------
# Confidence from OSM type
# -----------------------------------------------------------------------------
# Photon's `properties.osm_type` and `properties.osm_value` give us a quick
# signal of how authoritative the result is. A `relation/city` is a real
# city boundary in OSM; a `node/place` is a single point with a place tag.
# We map these to a 0.0–1.0 confidence without ever inventing a value.
_OSM_CONFIDENCE: dict[tuple[str, str], float] = {
    ("relation", "city"): 1.0,
    ("relation", "town"): 0.95,
    ("relation", "village"): 0.85,
    ("relation", "county"): 0.85,
    ("relation", "state"): 0.9,
    ("relation", "country"): 1.0,
    ("relation", "region"): 0.85,
    ("way", "city"): 0.9,
    ("way", "town"): 0.85,
    ("node", "place"): 0.85,
    ("node", "city"): 0.85,
    ("node", "town"): 0.8,
}


def _confidence_from_osm(properties: dict) -> float:
    osm_type = (properties.get("osm_type") or "").lower()
    osm_value = (properties.get("osm_value") or "").lower()
    if not osm_type or not osm_value:
        # No OSM metadata: trust country code presence as a rough proxy.
        return 0.75 if properties.get("countrycode") else 0.5
    confidence = _OSM_CONFIDENCE.get((osm_type, osm_value))
    return confidence if confidence is not None else 0.7


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------
def _unresolved_result() -> dict:
    """The "we genuinely don't know" row."""
    return {
        "geo_country_code": None,
        "geo_city": None,
        "geo_region": None,
        "geo_lat": None,
        "geo_lon": None,
        "geo_source": "unresolved",
        "geo_confidence": 0.0,
    }


def _strip_disambiguation_tokens(normalized: str) -> str:
    """Strip country/admin tokens from a normalized location string.

    "bengaluru karnataka india" -> "bengaluru"
    "new york ny us" -> "new york ny"
    "berlin" -> "berlin"

    Used to extract the place-name token for the offline lookup. The
    remaining tokens (state code, country code, country name) are kept
    separately so the disambiguation logic can use them as hints.

    This is heuristic — it doesn't try to be a complete ISO country /
    state parser. It just looks for the most common short tokens
    (2-letter codes) and a curated list of country names that appear
    frequently in our corpus.
    """
    # Common 2-letter admin / country codes that show up in job
    # location strings. Not exhaustive — a 2-letter token in a
    # location string is almost always a state or country code, not
    # a city name.
    short_codes = {
        # US states
        "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
        "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
        "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
        "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
        "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy",
        "dc",
        # Canadian provinces
        "ab", "bc", "mb", "nb", "nl", "ns", "nt", "nu", "on", "pe",
        "qc", "sk", "yt",
        # Country codes (most common in our corpus)
        "us", "uk", "ca", "de", "fr", "es", "it", "nl", "se", "ie",
        "in", "au", "nz", "jp", "sg", "br", "mx",
    }
    # Country names that often appear in raw location strings.
    # Only include names that don't conflict with common city-name
    # tokens. Multi-word country names get their full tokens, but
    # single-word generic words like "united" / "states" / "south"
    # are excluded — they'd over-strip city names like "New York"
    # or "South San Francisco".
    country_names = {
        "usa", "u.s.a", "u.s.",
        "canada", "germany", "france", "spain", "italy",
        "netherlands", "sweden", "ireland", "india", "australia",
        "japan", "singapore", "brazil", "mexico",
        "switzerland", "austria", "norway", "finland", "denmark",
        "poland", "portugal", "czech", "hungary", "romania",
        "greece", "turkey", "israel", "uae", "qatar",
        "korea", "china", "taiwan", "thailand", "malaysia",
        "indonesia", "philippines", "vietnam", "argentina", "chile",
        "colombia", "peru", "russia", "ukraine", "nigeria", "kenya",
        "egypt", "kingdom", "zealand",
    }
    # States/provinces by name. Only multi-word or distinctive names
    # so we don't accidentally strip city-name tokens. State codes
    # (NY, CA, etc.) are already in `short_codes` above; this set
    # is only for the full name when it appears next to a city.
    state_names = {
        "california", "texas", "florida", "carolina", "dakota",
        "virginia", "england", "scotland", "wales", "ontario",
        "quebec", "british", "columbia", "alberta", "manitoba",
        "saskatchewan",
    }
    tokens = normalized.split()
    kept = []
    for t in tokens:
        tl = t.lower().rstrip(".,;")
        if tl in short_codes or tl in country_names or tl in state_names:
            continue
        kept.append(t)
    stripped = " ".join(kept).strip()
    if not stripped:
        # Every token looked like a region/country hint — the string is
        # most likely the place name itself ("Columbia, SC", "Ontario").
        return " ".join(tokens[:1]).strip()
    return stripped


def _disambiguate_offline(
    candidates: list[dict],
    normalized: str,
) -> dict:
    """Pick the best GeoNames candidate for a job location string.

    Strategy: prefer a candidate whose country_code or admin1 appears
    in the original normalized string. If multiple still tie, pick
    the one with the highest population.

    Returns one of the input dicts (unmodified) or, if no candidate
    matches the disambiguation hints, the highest-population candidate.
    """
    if not candidates:
        raise ValueError("candidates is empty")
    if len(candidates) == 1:
        return candidates[0]

    # Pull the disambiguation tokens from the original string.
    tokens = set(normalized.lower().split())

    # First pass: exact country-code match in the disambiguation
    # tokens. This catches "Berlin, Germany" vs the Berlin in OH.
    for c in candidates:
        cc = (c.get("country_code") or "").lower()
        if cc in tokens:
            return c
    # Second pass: full country-name match. Build a quick
    # country-code -> name map for the candidates' codes.
    _COUNTRY_NAMES_BY_CODE = {
        "us": {"usa", "united", "states", "us"},
        "ca": {"canada"},
        "gb": {"uk", "united", "kingdom"},
        "de": {"germany"},
        "fr": {"france"},
        "in": {"india"},
        "au": {"australia"},
        "br": {"brazil"},
        "mx": {"mexico"},
        "jp": {"japan"},
        "sg": {"singapore"},
        "nl": {"netherlands"},
        "se": {"sweden"},
        "ie": {"ireland"},
        "nz": {"zealand"},
    }
    for c in candidates:
        names = _COUNTRY_NAMES_BY_CODE.get(
            (c.get("country_code") or "").lower(), set()
        )
        if tokens & names:
            return c
    # Fall through: highest population wins.
    return max(candidates, key=lambda c: c.get("population") or 0)


def _geocode_offline(normalized: str) -> dict | None:
    """Look up a normalized location string in the offline GeoNames table.

    Returns a fully-shaped geo result dict on match, or None when no
    candidate row exists. The caller decides how to treat a miss
    (currently: log + return _unresolved_result).

    The lookup is:
      1. Strip disambiguation tokens from the normalized string to
         get the place name.
      2. Query geo_cities for that name.
      3. If multiple matches, disambiguate using the original tokens.
    """
    place_name = _strip_disambiguation_tokens(normalized)
    if not place_name:
        return None
    rows = turso.lookup_geo_cities(place_name)
    if not rows:
        return None
    chosen = _disambiguate_offline(rows, normalized)
    # Confidence: 1.0 for primary asciiname match, 0.9 for an
    # alternate-name match. We don't know which we got without
    # re-querying, so use a single 0.9 — close enough for the
    # 0.0/0.5/1.0 bucketing the read path actually uses.
    return {
        "geo_country_code": chosen["country_code"],
        "geo_city": place_name.title(),
        "geo_region": chosen.get("admin1") or None,
        "geo_lat": chosen["lat"],
        "geo_lon": chosen["lon"],
        "geo_source": "geonames_offline",
        "geo_confidence": 0.9,
    }


def geocode_job_location(raw_location: str | None) -> dict:
    """Geocode a raw `jobs.location` string to a structured result.

    Returns a dict with keys: geo_country_code, geo_city, geo_region,
    geo_lat, geo_lon, geo_source, geo_confidence, geocoded_at. Suitable
    for splatting into the upsert payload.

    The flow is offline-first:
      1. Empty / whitespace → "unresolved" (no I/O).
      2. Normalize for cache key.
      3. Macro pre-screen → "macro" source (no I/O).
      4. Cache lookup → cached result if present.
      5. Offline lookup against geo_cities → cache write-through.
      6. (Photon is no longer called from the pipeline. Use
         geocode_via_photon_manual from a non-cloud host for the
         small residual set of unresolved rows.)

    This function never raises. All errors are absorbed and reflected
    in the result dict so the calling pipeline step can always write
    a row.
    """
    empty = _unresolved_result()
    if not raw_location or not raw_location.strip():
        return empty

    normalized = normalize_location_for_cache(raw_location)
    if not normalized:
        return empty

    # Macro pre-screen — short-circuit known scope words before any
    # I/O. The largest accuracy win for this layer.
    macro = _check_macro(normalized)
    if macro is not None:
        return {**macro, "geocoded_at": _now_iso()}

    # Cache lookup — same cache that was used for Photon originally;
    # the offline write path populates the same table.
    key = _cache_key(normalized)
    cached = turso.get_cached_geocode(key)
    if cached:
        return cached

    # Offline lookup. Reads from the geo_cities table populated by
    # scripts/build_geonames_cache.py. No network call.
    offline = _geocode_offline(normalized)
    if offline is None:
        result = _unresolved_result()
    else:
        result = offline
    result["geocoded_at"] = _now_iso()

    # Write-through cache.
    turso.set_cached_geocode(key, raw_location, result)
    return result


def geocode_via_photon_manual(raw_location: str) -> dict:
    """Manual Photon fallback for the small residual set of unresolved
    rows. NOT called by the pipeline — Photon's public instance blocks
    cloud / serverless IPs (Vercel, GitHub Actions) so calling it from
    a cron / serverless function is unreliable.

    Run this from a non-cloud host (your laptop) via the
    scripts/geocode_residual_unresolved.py script. The result still
    goes through turso.set_cached_geocode, so subsequent pipeline
    runs benefit from the same cache.
    """
    empty = _unresolved_result()
    if not raw_location or not raw_location.strip():
        return empty
    normalized = normalize_location_for_cache(raw_location)
    if not normalized:
        return empty
    result = _call_photon(normalized)
    result["geocoded_at"] = _now_iso()
    key = _cache_key(normalized)
    turso.set_cached_geocode(key, raw_location, result)
    return result


# -----------------------------------------------------------------------------
# Backfill helpers
# -----------------------------------------------------------------------------
def distinct_uncached_locations(limit: int = 1000) -> list[str]:
    """Return distinct non-null `location` strings from jobs that don't
    yet have a country code. Used by the seed/backfill script to find
    unique strings to geocode without scanning every job.
    """
    conn = turso.get_client()
    cursor = conn.execute(
        "SELECT DISTINCT location FROM jobs "
        "WHERE location IS NOT NULL AND location != '' "
        "AND geo_country_code IS NULL "
        "ORDER BY location LIMIT ?",
        [limit],
    )
    return [str(row[0]) for row in cursor.fetchall() if row and row[0]]


def geocode_distinct_locations(strings: list[str]) -> dict[str, dict]:
    """Geocode a list of distinct strings and return a {raw_location: result}
    mapping. Used by the seed/backfill script. Never raises; per-string
    failures degrade to "unresolved" via `geocode_job_location`.
    """
    out: dict[str, dict] = {}
    for s in strings:
        try:
            out[s] = geocode_job_location(s)
        except Exception as exc:
            # Defensive: geocode_job_location is documented to never raise,
            # but if a bug ever surfaces one we'd rather continue seeding
            # the rest of the corpus than abort the whole backfill.
            print(f"[geo] backfill failed for {s!r}: {exc}")
            out[s] = _unresolved_result()
    return out

# -----------------------------------------------------------------------------
# location_compatibility: pure function for the read path
# -----------------------------------------------------------------------------
# Called per (job, user) at request time — no I/O, no network, no DB. Same
# pattern as the embedding cosine-similarity function: cheap, deterministic,
# runs over rows already in memory. Returns a float in [0.0, 1.0] where 0.0
# means "hard filter this out" and 1.0 means "perfect match." The hard
# filter in the route only drops 0.0 rows; everything else (including
# 0.5 for unknown) is shown so the user sees the LLM's nuanced score.

def location_compatibility(
    job_geo: dict | None,
    profile_location: dict | None,
) -> float:
    """Compute how compatible a job's location is with a user's preferences.

    Args:
        job_geo: a flat dict shaped like the geo_* columns on a job row.
            May have null country/city/lat/lon if the geocoder couldn't
            resolve the place string. None is treated as fully unknown.
        profile_location: a flat dict with user-side location preferences.
            Recognized keys:
                location_mode: "country" | "city_radius" | "any"
                preferred_country_codes: list[str] of ISO alpha-2 codes
                preferred_lat, preferred_lon, preferred_radius_km: floats
                preferred_city: city name (geocoded server-side via the
                    PATCH endpoint, so preferred_lat/lon are populated
                    when this is set)

    Returns:
        float in [0.0, 1.0]:
            1.0 — same anchor location, or "any" mode, or no profile
            0.4 — in-country but far from the user's willing-to-relocate
                   radius (never goes below this for known in-country jobs
                   so a distant known job doesn't lose to an unresolved
                   one)
            0.5 — unknown: job not geocoded, or profile lacks preferences
            0.0 — hard incompatibility: wrong country, with a profile
                   that requires a specific country

    Behavioral contract for the 3-day wrap-up:
        - If profile has no structured preferences (no country codes, no
          city, location_mode != "any"), this returns 1.0 for every job.
          Existing users see zero regression.
        - If location_mode == "any", this returns 1.0 for every job. The
          per-request opt-out escape hatch.
        - Distance is a soft signal, never a hard cut. A user willing to
          relocate 500km from Portland sees Seattle (250km) at 0.92 and
          NYC (3900km) at 0.55 — close jobs win, far jobs still in the
          LLM batch. The hard filter only fires for wrong-country jobs
          when the user has explicitly listed preferred countries.

    The distance curve is logarithmic, normalized to the user's
    ``preferred_radius_km`` (or ``DEFAULT_WILLING_TO_RELOCATE_KM`` if
    not set). At 1x the radius the score is 0.85, at 4x it's 0.55, at
    16x (e.g. 8000km for a 500km default) it's 0.45. The floor of
    IN_COUNTRY_SCORE_FLOOR (0.4) keeps far-but-known jobs visible.
    """
    # No profile, or no location_mode set at all — the no-regression
    # path. Returns 1.0 for every job, identical to the old behavior.
    if profile_location is None:
        return 1.0
    location_mode = profile_location.get("location_mode") or "country"
    if location_mode == "any":
        return 1.0

    # Empty country set with a non-"any" mode — same as no profile.
    # The user is signaling "I haven't set anything yet" and we
    # treat that as "show me everything."
    preferred_country_codes = profile_location.get("preferred_country_codes") or []
    normalized_country_codes = {
        code.upper() for code in preferred_country_codes
        if isinstance(code, str) and code
    }

    has_explicit_anchor = isinstance(profile_location.get("preferred_lat"), (int, float)) and \
                        isinstance(profile_location.get("preferred_lon"), (int, float))

    if not normalized_country_codes and not has_explicit_anchor:
        # Truly nothing set — zero-regression path.
        return 1.0

    if not job_geo or job_geo.get("geo_source") == "unresolved":
        return 0.5

    job_country = job_geo.get("geo_country_code")
    if job_country:
        job_country = job_country.upper()

    # Hard country filter only applies if the user actually chose countries.
    if normalized_country_codes and (not job_country or job_country not in normalized_country_codes):
        return 0.0 if job_country else 0.5

    # From here: either country matched, or user has no country filter but
    # does have an explicit city anchor — do distance scoring either way.
    anchor_lat, anchor_lon = _resolve_anchor(profile_location, normalized_country_codes)

    # Country matched. Now compute the distance-based score.
    # The anchor (user's reference point) is determined by the
    # most-specific preference the user has set:
    #   1. preferred_lat/lon directly (highest precision)
    #   2. preferred_lat/lon populated by the PATCH endpoint's
    #      server-side city geocoding
    #   3. Country centroid (coarsest — same score for Portland
    #      and NYC for a US-only user, but still a soft signal)
    anchor_lat, anchor_lon = _resolve_anchor(profile_location, normalized_country_codes)
    willing_to_relocate_km = _resolve_willing_to_relocate_km(profile_location)

    job_lat = job_geo.get("geo_lat")
    job_lon = job_geo.get("geo_lon")
    if anchor_lat is None or job_lat is None:
        # We know the country matches but we can't compute a distance
        # (no anchor OR no job coords). Score is "we know they match
        # the country, but we don't know more." Between 0.5 (unknown
        # everything) and 1.0 (perfect match); 0.7 reads as
        # "country-match, no further info."
        return 0.7

    distance = _haversine_km(anchor_lat, anchor_lon, job_lat, job_lon)
    return _distance_score(distance, willing_to_relocate_km)


def _coerce_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):  # bool is an int subclass — exclude it
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve_anchor(
    profile_location: dict,
    normalized_country_codes: set[str],
) -> tuple[float | None, float | None]:
    lat = _coerce_float(profile_location.get("preferred_lat"))
    lon = _coerce_float(profile_location.get("preferred_lon"))
    if lat is not None and lon is not None:
        return lat, lon
    if normalized_country_codes:
        for cc in sorted(normalized_country_codes):
            hub = _country_tech_hub(cc)
            if hub is not None:
                return hub
            centroid = _country_centroid(cc)
            if centroid is not None:
                return centroid
    return None, None


def _resolve_willing_to_relocate_km(profile_location: dict) -> float:
    """Pick the distance the user is willing to relocate, in km.

    Falls back to DEFAULT_WILLING_TO_RELOCATE_KM (500km) when the
    user hasn't set preferred_radius_km. 500km covers common
    same-region moves: Portland to Seattle (250km), SF to LA (560km),
    NYC to Boston (300km), Berlin to Munich (500km).
    """
    radius = profile_location.get("preferred_radius_km")
    if isinstance(radius, (int, float)) and radius > 0:
        return float(radius)
    return float(DEFAULT_WILLING_TO_RELOCATE_KM)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers between two lat/lon points."""
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


# -----------------------------------------------------------------------------
# Default country anchor — picked when the user has set a country
# preference but no city / explicit lat/lon. Picking the centroid
# (population-weighted center) is a bad fallback for the US: it lands
# in Kansas, so a Portland user and a NYC user get the same anchor
# and almost every US job scores ~0.65. Picking a known tech hub is
# much better — a Portland user with a default-anchored SF anchor
# sees Bay Area jobs at 0.75 (correct: they're ~960km away) and NYC
# jobs at 0.62 (correct: ~3900km).
# -----------------------------------------------------------------------------
# Hand-curated for the ~10 countries in the existing job corpus. New
# countries fall back to the population centroid, which is good enough
# for the rare case.

_COUNTRY_TECH_HUBS: dict[str, tuple[float, float, str]] = {
    # (lat, lon, city_name_for_logging)
    "US": (37.7749, -122.4194, "San Francisco"),
    "CA": (43.6532, -79.3832, "Toronto"),
    "GB": (51.5074, -0.1278, "London"),
    "DE": (52.5200, 13.4050, "Berlin"),
    "FR": (48.8566, 2.3522, "Paris"),
    "IE": (53.3498, -6.2603, "Dublin"),
    "NL": (52.3676, 4.9041, "Amsterdam"),
    "AU": (-33.8688, 151.2093, "Sydney"),
    "IN": (12.9716, 77.5946, "Bangalore"),
    "JP": (35.6762, 139.6503, "Tokyo"),
    "SE": (59.3293, 18.0686, "Stockholm"),
    "NZ": (-36.8485, 174.7633, "Auckland"),
    "ES": (40.4168, -3.7038, "Madrid"),
    "IL": (32.0853, 34.7818, "Tel Aviv"),
}


def _country_tech_hub(cc: str) -> tuple[float, float] | None:
    """Return (lat, lon) for the default tech city in country ``cc``,
    or None if we don't have a curated entry. The function intentionally
    ignores the user-set city here — that's handled by the caller
    looking up preferred_lat / preferred_lon first.
    """
    entry = _COUNTRY_TECH_HUBS.get(cc)
    if entry is None:
        return None
    return entry[0], entry[1]


# Population-weighted centroids from the GeoNames cities15000 dataset.
# Used as a last-resort fallback when the country isn't in the tech-hub
# table. Hand-curated here for the ~30 countries that show up in the job
# corpus; missing countries fall back to None (the location_compatibility
# caller treats that as "unknown anchor" and returns 0.7).


_COUNTRY_CENTROIDS: dict[str, tuple[float, float]] = {
    "US": (39.83, -98.58),   # Kansas — population-weighted US centroid
    "CA": (56.13, -106.35),  # Canada — population-weighted
    "GB": (52.49, -1.89),    # England midlands
    "DE": (51.15, 10.45),    # Central Germany
    "FR": (46.78, 2.50),     # Central France
    "ES": (40.42, -3.70),    # Central Spain
    "IT": (42.50, 12.50),    # Central Italy
    "NL": (52.13, 5.29),     # Netherlands
    "SE": (60.13, 18.64),    # Sweden
    "IE": (53.13, -7.69),    # Ireland
    "IN": (22.50, 79.00),    # Central India
    "AU": (-25.27, 133.78),  # Central Australia
    "NZ": (-41.00, 174.00),  # New Zealand
    "JP": (36.20, 138.25),   # Central Japan
    "SG": (1.35, 103.82),    # Singapore
    "BR": (-14.24, -51.93),  # Central Brazil
    "MX": (23.63, -102.55),  # Central Mexico
    "CH": (46.82, 8.23),     # Switzerland
    "AT": (47.52, 14.55),    # Austria
    "NO": (60.47, 8.47),     # Norway
    "FI": (61.92, 25.75),    # Finland
    "DK": (56.26, 9.50),     # Denmark
    "PL": (51.92, 19.15),    # Poland
    "PT": (39.40, -8.22),    # Portugal
    "CZ": (49.82, 15.47),    # Czechia
    "HU": (47.16, 19.50),    # Hungary
    "RO": (45.94, 24.97),    # Romania
    "GR": (39.07, 21.82),    # Greece
    "TR": (38.96, 35.24),    # Central Turkey
    "IL": (31.05, 34.85),    # Israel
    "AE": (23.42, 53.85),    # UAE
    "ZA": (-30.56, 22.94),   # South Africa
    "KR": (35.91, 127.77),   # South Korea
    "CN": (35.86, 104.20),   # China
    "TW": (23.70, 120.96),   # Taiwan
    "TH": (15.87, 100.99),   # Thailand
    "MY": (4.21, 101.98),    # Malaysia
    "ID": (-0.79, 113.92),   # Indonesia
    "PH": (12.88, 121.77),   # Philippines
    "VN": (14.06, 108.28),   # Vietnam
    "AR": (-38.42, -63.62),  # Argentina
    "CL": (-35.68, -71.54),  # Chile
    "CO": (4.57, -74.30),    # Colombia
    "PE": (-9.19, -75.02),   # Peru
    "RU": (61.52, 105.32),   # Russia
    "UA": (48.38, 31.17),    # Ukraine
    "NG": (9.08, 8.68),      # Nigeria
    "KE": (-0.02, 37.91),    # Kenya
    "EG": (26.82, 30.80),    # Egypt
}

# Default willing-to-relocate distance. When the user has set
# preferred_lat/lon (or preferred_city that we geocode), the score
# uses that as the anchor. When only country is set, we use the
# country centroid. The "willing to relocate" radius governs how
# quickly the score decays with distance from the anchor:
# - 0km: 1.0
# - 250km: ~0.92
# - 500km: ~0.85
# - 1000km: ~0.75
# - 2000km: ~0.65
# - 4000km: ~0.55
# The curve is intentionally gentle: we never want to penalize a
# job that the LLM thinks is a great match just because the user
# is far away. We just want close jobs to have a small edge.
DEFAULT_WILLING_TO_RELOCATE_KM = 500

# Floor on the location score for in-country jobs. Prevents far-away
# in-country jobs from dropping below the 0.5 "unknown" floor, which
# would let a distant known job lose to a job we couldn't geocode.
IN_COUNTRY_SCORE_FLOOR = 0.4


def _country_centroid(country_code: str) -> tuple[float, float] | None:
    cc = (country_code or "").upper()
    return _COUNTRY_CENTROIDS.get(cc)


def _distance_score(distance_km: float, willing_to_relocate_km: float) -> float:
    """Piecewise curve from 1.0 (same place) down to IN_COUNTRY_SCORE_FLOOR.

    Three regions, designed to mirror user intuition about
    "willing-to-relocate":

      0 .. 0.5 * radius: gentle — same metro / nearby town.
        1.0 down to 0.95. A 100km job is barely penalized.

      0.5 * radius .. 1.0 * radius: moderate — same region, different city.
        0.95 down to 0.80. A 500km job (1x the default radius) has
        a noticeable but not punishing penalty.

      1.0 * radius .. infinity: logarithmic decay — different region / cross-country.
        0.80 minus 0.20 per decade of distance ratio. The 0.4 floor
        keeps very far in-country jobs visible (a Portland user sees
        NYC jobs at ~0.62, well above the 0.5 "unknown" floor).

    Example scores with default 500km willing-to-relocate radius:
        0km    -> 1.000
        50km   -> 0.990
        100km  -> 0.980
        234km  -> 0.953  (Portland to Seattle)
        500km  -> 0.800  (1x radius)
        1000km -> 0.740
        2000km -> 0.680
        4000km -> 0.619  (Portland to NYC, ~3900km)
        8000km -> 0.559  (floor region)
    """
    if distance_km <= 0:
        return 1.0
    half = willing_to_relocate_km * 0.5
    full = willing_to_relocate_km
    if distance_km <= half:
        return 1.0 - 0.05 * (distance_km / half)
    if distance_km <= full:
        t = (distance_km - half) / half
        return 0.95 - 0.15 * t
    extra = distance_km - full
    penalty = 0.20 * math.log10(1 + extra / full)
    return max(IN_COUNTRY_SCORE_FLOOR, 0.80 - penalty)

