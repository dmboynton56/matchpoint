import re

from app.schemas.ranking import JobScore, MatchNote

LOW_FIT_THRESHOLD = 0.5
REGULAR_NOTE_COUNT = 3
MAX_WARNING_NOTES = 3

_STRONG_DRAWBACK_PHRASES = (
    "relocation would be required",
    "relocation required",
    "would be required unless",
    "below your",
    "below stated",
    "no evidence of",
    "not directly evidenced",
    "not evidenced",
    "lowering location",
    "lowering pay",
    "seniority gap",
    "experience gap",
    "significant gap",
    "no relocation",
    "no onsite",
    "no on-site",
)

_FIT_TOPIC_KEYWORDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "location_fit": (
        "location",
        (
            "location",
            "relocat",
            "on-site",
            "onsite",
            "on site",
            "hybrid",
            "remote",
            "commute",
            "metro",
            "relocation",
            "timezone",
            "work mode",
            "work-mode",
        ),
    ),
    "pay_fit": (
        "pay",
        (
            "pay",
            "salary",
            "compensation",
            "band",
            "below",
            "shortfall",
            "minimum base",
        ),
    ),
    "seniority_fit": (
        "seniority",
        (
            "seniority",
            "manager",
            "staff",
            "director",
            "lead",
            "junior",
            "apprentice",
            "intern",
            "years of experience",
            "level",
            "ic scope",
        ),
    ),
    "experience_fit": (
        "experience",
        (
            "experience",
            "production",
            "no evidence",
            "limited",
            "portfolio",
            "capstone",
        ),
    ),
}

_REPLACEMENT_TEMPLATES: tuple[tuple[str, str], ...] = (
    ("skills_fit", "Skills alignment scores {pct}% against the role requirements."),
    ("role_fit", "Role fit scores {pct}% based on title and responsibilities."),
    ("experience_fit", "Experience fit scores {pct}% from resume evidence."),
    ("preference_fit", "Preference alignment scores {pct}% from stated goals."),
    (
        "interview_likelihood",
        "Interview likelihood estimated at {pct}% from combined evidence.",
    ),
)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _note_mentions_topic(text: str, keywords: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(keyword in lower for keyword in keywords)


_DRAWBACK_SIGNALS = (
    "lowering",
    "mismatch",
    "stretch vs",
    "conflict with",
    "incompatible",
    "dealbreaker",
    "not stated",
    "unless you",
    "would be required",
    "required unless",
    "below your",
    "below stated",
    "no evidence",
    "not evidenced",
    "shortfall",
    "gap",
)


def _has_drawback_signal(text: str) -> bool:
    lower = text.lower()
    if any(phrase in lower for phrase in _STRONG_DRAWBACK_PHRASES):
        return True
    return any(signal in lower for signal in _DRAWBACK_SIGNALS)


def _looks_like_drawback(text: str, score: JobScore) -> bool:
    if not _has_drawback_signal(text):
        return False

    for fit_field, (_, keywords) in _FIT_TOPIC_KEYWORDS.items():
        fit_value = getattr(score, fit_field)
        if fit_value >= LOW_FIT_THRESHOLD:
            continue
        if _note_mentions_topic(text, keywords):
            return True

    return any(getattr(score, fit_field) < LOW_FIT_THRESHOLD for fit_field in _FIT_TOPIC_KEYWORDS)


def _replacement_regular_note(
    score: JobScore, existing_regular: list[MatchNote]
) -> MatchNote:
    existing_blob = " ".join(note.text.lower() for note in existing_regular)
    ranked_templates = sorted(
        _REPLACEMENT_TEMPLATES,
        key=lambda item: getattr(score, item[0]),
        reverse=True,
    )

    for field, template in ranked_templates:
        pct = round(getattr(score, field) * 100)
        text = template.format(pct=pct)
        topic_label = _FIT_TOPIC_KEYWORDS.get(field, (field, ()))[0]
        if topic_label in existing_blob:
            continue
        if text.lower() in existing_blob:
            continue
        return MatchNote(text=_normalize_text(text)[:150], is_warning=False)

    fallback_pct = round(
        (
            score.skills_fit
            + score.role_fit
            + score.experience_fit
        )
        / 3
        * 100
    )
    return MatchNote(
        text=_normalize_text(
            f"Core fit signals average {fallback_pct}% across skills, role, and experience."
        )[:150],
        is_warning=False,
    )


def _dedupe_notes(notes: list[MatchNote]) -> list[MatchNote]:
    seen: set[str] = set()
    deduped: list[MatchNote] = []
    for note in notes:
        key = note.text.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(note)
    return deduped


def normalize_match_notes(score: JobScore) -> list[MatchNote]:
    """
    Reclassify drawback text the model placed in regular notes into warnings,
    then backfill regular comments so each job still has exactly three.
    """
    regular_notes = [note for note in score.match_notes if not note.is_warning]
    warning_notes = [note for note in score.match_notes if note.is_warning]

    kept_regular: list[MatchNote] = []
    promoted_warnings: list[MatchNote] = []

    for note in regular_notes:
        normalized = _normalize_text(note.text)
        candidate = MatchNote(text=normalized[:150], is_warning=False)
        if _looks_like_drawback(normalized, score):
            promoted_warnings.append(
                MatchNote(text=normalized[:150], is_warning=True)
            )
        else:
            kept_regular.append(candidate)

    warnings = _dedupe_notes(warning_notes + promoted_warnings)

    while len(kept_regular) < REGULAR_NOTE_COUNT:
        kept_regular.append(_replacement_regular_note(score, kept_regular))

    result = kept_regular[:REGULAR_NOTE_COUNT] + warnings[:MAX_WARNING_NOTES]
    return result[: REGULAR_NOTE_COUNT + MAX_WARNING_NOTES]
