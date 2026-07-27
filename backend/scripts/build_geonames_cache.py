"""Build the geo_cities dataset and push it to the data-cache branch.

Why a data-cache branch instead of a Turso table:
  - 193k rows × multi-row INSERT over the HTTP transport to Turso
    takes 30+ minutes. The data-cache branch (the same pattern the
    embedding matrix uses) gets the dataset to Vercel in seconds:
    one file, one push, one fetch per process.
  - The data is fully public domain reference data — no per-user
    state, no incremental updates, just "all the cities, once." A
    branch-tracked binary file is the right tool.

Output:
  - data/geo_cities/cities.json.gz on the data-cache branch
  - gzipped JSON; one entry per (name_lower, country_code, admin1)
  - The Python read path downloads, decompresses, parses once per
    process, then serves lookups from a dict.

Usage:
  cd backend
  python -m scripts.build_geonames_cache

Idempotent: re-runs re-download the dataset, rebuild the JSON, and
force-push the new file. Safe to run multiple times.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import os
import sys
import tempfile
import time
import zipfile

import certifi
import requests


GEONAMES_CITIES15000_URL = (
    "https://download.geonames.org/export/dump/cities15000.zip"
)
GEONAMES_TEXT_FILENAME = "cities15000.txt"

# GeoNames tab-separated columns. We use only the ones we need.
GEONAMES_COLUMNS = (
    "geonameid", "name", "asciiname", "alternatenames",
    "lat", "lon", "feature_class", "feature_code",
    "country_code", "cc2", "admin1", "admin2", "admin3", "admin4",
    "population", "elevation", "dem", "timezone", "modified",
)

# Feature codes we care about. "PPL" entries are populated places with
# no admin level; "PPLA" / "PPLA2" are admin-1 / admin-2 capitals;
# "PPLC" is a country capital. We skip everything else (mountains,
# rivers, etc.) since jobs aren't located there.
INCLUDED_FEATURE_CODES = {
    "PPLC", "PPLA", "PPLA2", "PPLA3", "PPLA4",
    "PPL", "PPLX", "PPLF", "PPLS",
}


def _download_cities15000() -> str:
    """Download and extract cities15000.txt. Returns the path to the .tsv."""
    print(f"Downloading {GEONAMES_CITIES15000_URL}…")
    resp = requests.get(
        GEONAMES_CITIES15000_URL,
        headers={"User-Agent": "matchpoint-geocoder/1.0"},
        timeout=30,
        verify=certifi.where(),
    )
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        tmp_dir = tempfile.mkdtemp(prefix="geonames_")
        zf.extract(GEONAMES_TEXT_FILENAME, path=tmp_dir)
    return os.path.join(tmp_dir, GEONAMES_TEXT_FILENAME)


def _is_english_like_alternate(s: str) -> bool:
    """True if the alternate name is a plain ASCII English word/phrase.

    See the comment in services/geo.py for the full rules. We keep only
    English-looking alternates so the JSON payload doesn't bloat with
    Cyrillic / Devanagari / Arabic transliterations.
    """
    if not s or len(s) > 30:
        return False
    try:
        s.encode("ascii")
    except UnicodeEncodeError:
        return False
    if s.isdigit():
        return False
    for ch in s:
        if not (ch.isascii() and (ch.isalpha() or ch in " -'.&")):
            return False
    return True


def _build_dataset(tsv_path: str) -> list[dict]:
    """Parse cities15000.txt and produce the deduped dataset.

    Each output record is a dict with:
        name_lower: lookup key (lowercased city name)
        country_code: ISO alpha-2
        admin1: GeoNames admin-1 code (region/state, may be empty)
        lat, lon: floats
        population: int

    We also expand English-looking alternates as additional lookup
    rows pointing at the same lat/lon. This catches "New York" ->
    "New York City" and "Bangalore" -> "Bengaluru" without shipping
    the (much larger) alternateNamesV2 dataset.

    Dedup: when multiple cities share (name_lower, country_code,
    admin1) after expansion, keep the highest-population record.
    """
    by_key: dict[tuple[str, str, str], dict] = {}
    with open(tsv_path, "r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, fieldnames=GEONAMES_COLUMNS, delimiter="\t")
        for row in reader:
            feature_code = (row.get("feature_code") or "").strip()
            if feature_code not in INCLUDED_FEATURE_CODES:
                continue
            name = (row.get("asciiname") or "").strip()
            if not name:
                continue
            country_code = (row.get("country_code") or "").strip().upper()
            if len(country_code) != 2:
                continue
            try:
                lat = float(row.get("lat") or 0)
                lon = float(row.get("lon") or 0)
            except ValueError:
                continue
            if lat == 0 and lon == 0:
                continue
            try:
                population = int(row.get("population") or 0)
            except ValueError:
                population = 0
            admin1 = (row.get("admin1") or "").strip()
            base = {
                "country_code": country_code,
                "admin1": admin1,
                "lat": lat,
                "lon": lon,
                "population": population,
            }
            candidates = [(name.lower(), base)]
            alternates_raw = (row.get("alternatenames") or "").strip()
            if alternates_raw:
                for alt in alternates_raw.split(","):
                    alt = alt.strip()
                    if not alt or alt.lower() == name.lower():
                        continue
                    if not _is_english_like_alternate(alt):
                        continue
                    candidates.append((alt.lower(), base))
            for key_name, payload in candidates:
                key = (key_name, payload["country_code"], payload["admin1"] or "")
                existing = by_key.get(key)
                if existing is None or payload["population"] > existing["population"]:
                    by_key[key] = {
                        "name_lower": key_name,
                        **payload,
                    }
    return list(by_key.values())


def _serialize_gzjson(records: list[dict]) -> bytes:
    """Serialize the dataset to gzipped JSON.

    Schema is a list of objects, one per (name_lower, country_code,
    admin1) tuple. The Python read path does the inverse. We use
    compact separators and a single top-level array for the
    fastest parse on the read side.
    """
    print(f"  Serializing {len(records)} records to JSON…")
    raw = json.dumps(
        records,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    print(f"  Uncompressed: {len(raw) / 1e6:.1f} MB")
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as gz:
        gz.write(raw)
    compressed = buf.getvalue()
    print(f"  Compressed (gzip): {len(compressed) / 1e6:.1f} MB")
    return compressed


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    if not os.getenv("TURSO_DATABASE_URL"):
        raise RuntimeError("TURSO_DATABASE_URL must be set")
    # We don't need Turso for the data-cache path, but the import
    # below uses the client to keep a single connection module loaded.

    tsv_path = _download_cities15000()
    print(f"Parsing {tsv_path}…")
    t0 = time.time()
    records = _build_dataset(tsv_path)
    print(f"  {len(records)} unique (name, country, admin1) tuples after dedupe "
          f"({time.time() - t0:.1f}s)")

    gz_bytes = _serialize_gzjson(records)

    # Push to the data-cache branch. This is the same pattern the
    # embedding matrix uses, generalized: a file path, a bytes
    # payload, a commit message.
    from app.services.git_data_cache import push_geo_cities_to_branch

    print("\nPushing to data-cache branch…")
    push_geo_cities_to_branch(gz_bytes)
    print("Done. Vercel will pick up the new file on next cold start.")


if __name__ == "__main__":
    main()
