from app.schemas.ranking import MATCH_NOTE_MAX_CHARS, JobScore, MatchNote
from app.services.match_notes import normalize_match_notes


def _base_score(**overrides) -> JobScore:
    payload = {
        "job_id": "job-1",
        "interview_likelihood": 0.5,
        "skills_fit": 0.82,
        "experience_fit": 0.7,
        "seniority_fit": 0.6,
        "location_fit": 0.35,
        "pay_fit": 0.75,
        "role_fit": 0.8,
        "preference_fit": 0.7,
        "match_notes": [],
    }
    payload.update(overrides)
    return JobScore(**payload)


def test_promotes_location_drawback_from_regular_to_warning():
    score = _base_score(
        match_notes=[
            MatchNote(text="Strong React overlap with the stack.", is_warning=False),
            MatchNote(text="API work maps to backend responsibilities.", is_warning=False),
            MatchNote(
                text="SF on-site; candidate is in Denver with no relocation, lowering location fit.",
                is_warning=False,
            ),
        ]
    )

    notes = normalize_match_notes(score)
    regular = [note for note in notes if not note.is_warning]
    warnings = [note for note in notes if note.is_warning]

    assert len(regular) == 3
    assert len(warnings) == 1
    assert "Denver" in warnings[0].text
    assert all("Denver" not in note.text for note in regular)
    assert all(len(note.text) <= MATCH_NOTE_MAX_CHARS for note in notes)


def test_keeps_existing_warnings_and_regular_notes():
    score = _base_score(
        match_notes=[
            MatchNote(text="Python and ML projects align with the stack.", is_warning=False),
            MatchNote(text="Data pipeline work mirrors responsibilities.", is_warning=False),
            MatchNote(text="Remote scope fits the posting window.", is_warning=False),
            MatchNote(
                text="Listed salary band appears below your stated minimum target.",
                is_warning=True,
            ),
        ]
    )

    notes = normalize_match_notes(score)
    regular = [note for note in notes if not note.is_warning]
    warnings = [note for note in notes if note.is_warning]

    assert len(regular) == 3
    assert len(warnings) == 1
    assert "salary band" in warnings[0].text.lower()
    assert all(len(note.text) <= MATCH_NOTE_MAX_CHARS for note in notes)


def test_backfills_regular_note_after_reclassification():
    score = _base_score(
        location_fit=0.3,
        match_notes=[
            MatchNote(text="Kubernetes keywords overlap with your resume.", is_warning=False),
            MatchNote(text="Platform ownership maps to the charter.", is_warning=False),
            MatchNote(
                text="On-site in Austin — relocation would be required unless you already live nearby.",
                is_warning=False,
            ),
        ],
    )

    notes = normalize_match_notes(score)
    regular = [note for note in notes if not note.is_warning]
    warnings = [note for note in notes if note.is_warning]

    assert len(regular) == 3
    assert len(warnings) == 1
    assert any("scores" in note.text.lower() for note in regular)
    assert all(len(note.text) <= MATCH_NOTE_MAX_CHARS for note in notes)
