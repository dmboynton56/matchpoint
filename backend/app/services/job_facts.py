import re

from app.schemas.ranking import JobFacts, SalaryFacts
from app.services.cleaning import normalizeText, resolve_job_location, stripHTML


WORK_MODE_PATTERN = re.compile(
    r"\b(remote|hybrid|in-office|on-site|onsite)\b", re.IGNORECASE
)
MONEY_PATTERN = re.compile(r"\$\s*\d[\d,]*(?:\.\d+)?\s*[kK]?")
# "$120,000 - $150,000", "$120k–$150k", "$120-150k", "$120,000 to 150,000"
MONEY_RANGE_PATTERN = re.compile(
    r"\$\s*\d[\d,]*(?:\.\d+)?\s*[kK]?\s*(?:-|–|—|\bto\b|\bthrough\b)\s*"
    r"\$?\s*\d[\d,]*(?:\.\d+)?\s*[kK]?",
    re.IGNORECASE,
)
RANGE_SEPARATOR_PATTERN = re.compile(
    r"\s*(?:-|–|—|\bto\b|\bthrough\b)\s*", re.IGNORECASE
)
SALARY_KEYWORDS = (
    "salary",
    "base pay",
    "compensation",
    "pay range",
    "pay rate",
    "per hour",
    "an hour",
    "/hr",
    "hourly",
    "per year",
    "annually",
)
CITY_STATE_PATTERN = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*,\s*[A-Z]{2})\b"
)
ROLE_FAMILIES = {
    "product": ("product manager", "product lead", "product owner", "product"),
    "software engineering": (
        "software engineer",
        "frontend",
        "front-end",
        "backend",
        "back-end",
        "full stack",
        "full-stack",
        "developer",
        "engineering",
    ),
    "data": ("data scientist", "data engineer", "analytics", "machine learning", "ml "),
    "design": ("designer", "design"),
    "sales": ("account executive", "sales", "business development"),
    "marketing": ("marketing", "growth"),
    "security": ("security", "cybersecurity"),
    "finance": ("finance", "accounting", "controller"),
}


def _clean_description(description: str | None) -> str:
    if not description:
        return ""
    if "<" in description and ">" in description:
        return normalizeText(stripHTML(description))
    return normalizeText(description)


def _canonical_work_mode(value: str) -> str:
    lowered = value.lower()
    if lowered == "remote":
        return "Remote"
    if lowered == "hybrid":
        return "Hybrid"
    if lowered in {"on-site", "onsite", "in-office"}:
        return "On-site"
    return value.title()


def _extract_work_modes(text: str) -> list[str]:
    modes: list[str] = []
    seen: set[str] = set()
    for match in WORK_MODE_PATTERN.findall(text):
        mode = _canonical_work_mode(match)
        key = mode.lower()
        if key not in seen:
            seen.add(key)
            modes.append(mode)
    return modes


def _extract_locations(location: str | None, description_text: str) -> list[str]:
    values: list[str] = []
    resolved = resolve_job_location(location or "", description_text)
    if resolved:
        place = resolved.split(" · ", 1)[0].strip()
        if place and place.lower() not in {
            "remote",
            "hybrid",
            "on-site",
            "in-office",
        }:
            values.append(place)

    for city in CITY_STATE_PATTERN.findall(description_text):
        if city not in values:
            values.append(city)
        if len(values) >= 8:
            break

    return values


def _parse_money(value: str) -> int | None:
    normalized = value.replace("$", "").replace(",", "").strip()
    multiplier = 1000 if normalized.lower().endswith("k") else 1
    normalized = normalized.rstrip("kK").strip()
    try:
        return int(float(normalized) * multiplier)
    except ValueError:
        return None


def _salary_period(sentence: str) -> str:
    lowered = sentence.lower()
    if "hour" in lowered or "/hr" in lowered:
        return "hourly"
    return "annual"


def _plausible_amounts(amounts: list[int], period: str) -> list[int]:
    if period == "hourly":
        return [amount for amount in amounts if 7 <= amount <= 500]
    return [amount for amount in amounts if 10_000 <= amount <= 1_500_000]


def _parse_range_amounts(range_text: str) -> list[int]:
    """Parse both sides of a money range, expanding "$120-150k" shorthand."""
    parts = RANGE_SEPARATOR_PATTERN.split(range_text, maxsplit=1)
    if len(parts) != 2:
        return []
    low_raw, high_raw = (part.strip() for part in parts)
    low = _parse_money(low_raw)
    high = _parse_money(high_raw)
    if low is None or high is None:
        return []
    if high_raw.lower().endswith("k") and not low_raw.lower().endswith("k"):
        if low < 1000:
            low *= 1000
    return [low, high]


def _build_salary(amounts: list[int], sentence: str) -> SalaryFacts | None:
    period = _salary_period(sentence)
    plausible = _plausible_amounts(amounts, period)
    if not plausible:
        return None
    return SalaryFacts(
        minimum=min(plausible),
        maximum=max(plausible),
        currency="USD",
        period=period,
        evidence=normalizeText(sentence)[:240],
    )


def extract_salary_facts(description_text: str) -> SalaryFacts | None:
    if not description_text:
        return None

    sentences = re.split(r"(?<=[.!?])\s+", description_text)

    # Pass 1: sentences that talk about pay explicitly — any $ amounts count.
    for sentence in sentences:
        lowered = sentence.lower()
        if not any(marker in lowered for marker in SALARY_KEYWORDS):
            continue

        amounts = [
            _parse_money(match.group(0))
            for match in MONEY_PATTERN.finditer(sentence)
        ]
        parsed_amounts = [amount for amount in amounts if amount is not None]
        if not parsed_amounts:
            continue

        salary = _build_salary(parsed_amounts, sentence)
        if salary:
            return salary

    # Pass 2: explicit money ranges anywhere ("$120,000 - $150,000"),
    # even without a salary keyword nearby.
    for sentence in sentences:
        match = MONEY_RANGE_PATTERN.search(sentence)
        if not match:
            continue
        amounts = _parse_range_amounts(match.group(0))
        if not amounts:
            continue
        salary = _build_salary(amounts, sentence)
        if salary:
            return salary

    return None


def _role_family_check_order() -> list[str]:
    return [family for family in ROLE_FAMILIES if family != "product"] + ["product"]


def infer_role_family(title: str) -> str | None:
    lowered = f" {title.lower()} "
    for family in _role_family_check_order():
        if any(marker in lowered for marker in ROLE_FAMILIES[family]):
            return family
    return None


def extract_job_facts(
    *, title: str, location: str | None, description: str | None
) -> JobFacts:
    description_text = _clean_description(description)
    mode_source = " ".join(
        part for part in (location or "", description_text[:1000]) if part
    )
    return JobFacts(
        work_modes=_extract_work_modes(mode_source),
        locations=_extract_locations(location, description_text),
        salary=extract_salary_facts(description_text),
        role_family=infer_role_family(title),
    )
