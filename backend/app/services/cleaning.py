from bs4 import BeautifulSoup
import re

WORK_MODE_PATTERN = re.compile(
    r"\b(In-Office|Hybrid|Remote|On-site|Onsite)\b", re.IGNORECASE
)
VAGUE_LOCATION_VALUES = {
    "in-office",
    "hybrid",
    "remote",
    "on-site",
    "onsite",
    "hybrid; in-office",
    "hybrid, in-office",
}
REMOTE_REGION_ALIASES = {
    "usa": "United States",
    "us": "United States",
    "u.s.": "United States",
    "u.s.a.": "United States",
}
CITY_STATE_PATTERN = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*,\s*[A-Z]{2})\b"
)


def stripHTML(html: str) -> str:
    noHTML = BeautifulSoup(html, "html.parser")
    return noHTML.get_text(separator=" ")


def normalizeText(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _is_vague_only(location: str) -> bool:
    normalized = re.sub(r"\s+", " ", location.strip().lower())
    normalized = normalized.replace(";", ",")
    return normalized in VAGUE_LOCATION_VALUES


def _canonical_mode(mode: str) -> str:
    lowered = mode.lower()
    if lowered == "in-office":
        return "In-Office"
    if lowered == "hybrid":
        return "Hybrid"
    if lowered == "remote":
        return "Remote"
    if lowered in {"on-site", "onsite"}:
        return "On-site"
    return mode.title()


def _extract_modes(location: str) -> list[str]:
    modes = WORK_MODE_PATTERN.findall(location)
    deduped: list[str] = []
    seen: set[str] = set()
    for mode in modes:
        canonical = _canonical_mode(mode)
        key = canonical.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(canonical)
    return deduped


def _primary_mode(modes: list[str]) -> str | None:
    if not modes:
        return None
    priority = {"Hybrid": 0, "Remote": 1, "In-Office": 2, "On-site": 3}
    return sorted(modes, key=lambda mode: priority.get(mode, 99))[0]


def _normalize_place(place: str) -> str:
    cleaned = re.sub(r"\s+", " ", place.strip(" ,;•"))
    if not cleaned:
        return cleaned
    alias = REMOTE_REGION_ALIASES.get(cleaned.lower())
    return alias or cleaned


def _extract_place_from_raw(location: str) -> str | None:
    cleaned = location.strip()
    if not cleaned or _is_vague_only(cleaned):
        return None

    for pattern in (
        r"^(?:Hybrid|Remote)\s*[-–—]\s*(.+)$",
        r"^Remote,\s*(.+)$",
    ):
        match = re.match(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            place = _normalize_place(match.group(1))
            return place or None

    without_modes = WORK_MODE_PATTERN.sub("", cleaned)
    without_modes = re.sub(r"^[\s,;•\-–—]+|[\s,;•\-–—]+$", "", without_modes)
    without_modes = re.sub(r"\s+", " ", without_modes).strip()
    if without_modes and not _is_vague_only(without_modes):
        return _normalize_place(without_modes)
    return None


def _clean_description_text(description: str) -> str:
    if not description:
        return ""
    if "<" in description and ">" in description:
        return normalizeText(stripHTML(description))
    return normalizeText(description)


def _extract_place_from_description(description: str) -> str | None:
    text = _clean_description_text(description)
    if not text:
        return None

    locations_match = re.search(r"Locations\s*-\s*(.{0,160})", text, re.IGNORECASE)
    if locations_match:
        place = locations_match.group(1).strip()
        place = re.split(
            r"\s{2,}|\s+(?:Cloudflare|We|The|About|Responsibilities)\b",
            place,
            maxsplit=1,
        )[0].strip(" ,;")
        place = _normalize_place(place)
        if place and not _is_vague_only(place):
            return place

    mail_match = re.search(
        r"via mail at [^.]+\.\s*([A-Za-z .]+,\s*[A-Z]{2})\s*\d{5}",
        text,
        re.IGNORECASE,
    )
    if mail_match:
        return mail_match.group(1).strip()

    city_matches = CITY_STATE_PATTERN.findall(text)
    if city_matches:
        return city_matches[-1].strip()

    return None


def _format_location(place: str | None, mode: str | None, fallback: str) -> str:
    if place and mode:
        return f"{place} · {mode}"
    if place:
        return place
    if mode:
        return mode
    return fallback.strip()


def resolve_job_location(raw_location: str | None, description: str | None = None) -> str | None:
    if raw_location is None:
        return None

    location = raw_location.strip()
    if not location:
        return None

    if " · " in location:
        place_part = location.split(" · ", 1)[0].strip()
        if place_part and not _is_vague_only(place_part):
            return location

    place = _extract_place_from_raw(location)
    modes = _extract_modes(location)
    mode = _primary_mode(modes)

    if place and not mode and not _is_vague_only(location):
        return location

    if not place and (mode or _is_vague_only(location)):
        place = _extract_place_from_description(description or "")

    if place and mode:
        return _format_location(place, mode, location)

    if place:
        return place

    if mode:
        return mode

    return location


def buildCleanedText(job: dict) -> str:
    raw_location = str(job.get("location", "") or "")
    raw_description = str(job.get("description", "") or "")
    resolved_location = resolve_job_location(raw_location, raw_description) or raw_location
    stripped = stripHTML(raw_description)
    cleanedText = normalizeText(stripped)
    posting = f"""
    Title: {job['title']}
    Company:{job['company']}
    Location: {resolved_location}
    Description: {cleanedText}"""
    return posting
