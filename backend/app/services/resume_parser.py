"""Simple resume parser for the bullet-coach flow.

The parser does one job: split a resume into sections -> entries
-> prose blobs. It does NOT try to identify individual bullets
inside an entry. The LLM is responsible for picking which
sentence inside an entry to coach on (and the validator confirms
the LLM's choice is a real substring of the entry's text).

Why entry-level only
--------------------
Bullet-level parsing is fragile: resumes line-wrap at fixed
widths, use inconsistent markers, mix prose with bullets, and
have no standard format. We tried bullet-level parsing with
wrap detection and acronym handling and it still mangled real
resumes. Entry-level is enough to give the UI "where does this
bullet live in your resume?" context, which is the actual
value the user wants.

Output shape
------------

  ResumeDocument
    - sections: list[ResumeSection]
        - title: "Work Experience"
        - entries: list[ResumeEntry]
            - title: "Flatiron School -- Software Engineering Coach"
            - text: "Built a job matching platform for graduating
              students. Led 12 cohorts through full-stack curriculum.
              Reduced average code review turnaround from 48 hours
              to 6 hours."

The LLM receives each entry as one block and picks the sentence
to coach on. The UI uses the entry title to render "Your
bullet in Work Experience -> Flatiron School -- Software
Engineering Coach".

Public surface
--------------
- `parse_resume(text: str) -> ResumeDocument`
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel


class ResumeEntry(BaseModel):
    """One thing the candidate did (a job, a project, a degree).

    `title` is the human-readable header (company, role, project
    name, school). `text` is the full prose of everything under
    that header -- bullets and sentences collapsed into one
    newline-separated blob. The LLM picks a sentence from
    `text` to coach on; the UI shows the title as context.
    """

    title: str
    text: str


class ResumeSection(BaseModel):
    """A logical grouping of entries.

    In a real resume, this is the section header: "Work
    Experience", "Projects", "Education", etc. The parser
    always returns at least one section, even if it had to
    synthesize one.
    """

    title: str
    entries: list[ResumeEntry]


class ResumeDocument(BaseModel):
    sections: list[ResumeSection]


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------

# Section headers: lines that are ALL CAPS, or end with a colon,
# or match a known section title. Case-insensitive match against
# the known list.
_KNOWN_SECTION_TITLES: frozenset[str] = frozenset({
    "work experience",
    "experience",
    "professional experience",
    "employment",
    "employment history",
    "projects",
    "project experience",
    "selected projects",
    "education",
    "academic background",
    "skills",
    "technical skills",
    "core competencies",
    "summary",
    "professional summary",
    "objective",
    "certifications",
    "publications",
    "awards",
    "volunteer",
    "volunteer experience",
    "interests",
})

# Date hint used to detect entry headers (lines like "Jan 2022 -
# Present", "2020-2023", "12/2025 - Present").
_DATE_HINT_RE = re.compile(
    r"("
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
    r"\s+\d{2,4}"
    r"|\d{4}\s*[-\u2013\u2014]\s*(?:\d{4}|Present|Current|Now)"
    r"|\d{4}\s*[-\u2013\u2014]\s*\d{2,4}"
    r"|\d{4}\b"
    r"|\d{1,2}/\d{2,4}\s*[-\u2013\u2014]\s*"
    r"(?:\d{1,2}/\d{2,4}|Present|Current|Now)"
    r")",
    re.IGNORECASE,
)


def _looks_like_section_header(line: str) -> bool:
    """True for lines that are section headers (ALL CAPS, ends in
    colon, or matches a known section title).
    """
    stripped = line.strip().rstrip(":").strip()
    if not stripped:
        return False
    if stripped.lower() in _KNOWN_SECTION_TITLES:
        return True
    # All-uppercase alphabetic characters, AND no lowercase
    # letters (excludes mixed-case words like "MatchPoint" or "iOS").
    letters = [c for c in stripped if c.isalpha()]
    if (
        len(letters) >= 2
        and all(c.isupper() for c in letters)
        and not any(c.islower() for c in letters)
    ):
        return True
    # Ends with colon, short
    if line.rstrip().endswith(":") and len(stripped) < 60:
        return True
    return False


def _looks_like_entry_title(line: str) -> bool:
    """True for lines that look like an entry header (job title,
    project name, school, etc.).

    Conservative heuristic. We only call something an entry if
    there's STRONG evidence:
      1. Contains a date hint AND is not a pure-date line
         (catches "Job Title | Jan 2022 - Present" but NOT
         "Jan 2022 - Present" alone -- that one is metadata).
      2. Has a " -- " or " @ " separator between two fragments
         (catches "Flatiron School -- Software Engineering Coach",
         "Acme Corp -- Senior Engineer"). " | " is NOT enough
         alone because "Python, C++ | Java, Go" matches it.
      3. Mixed-case short line (1-5 words, no period at end,
         contains both upper and lower letters). Catches
         "Personal CRM", "MatchPoint", "iOS" but not "B.S.
         Computer Science" (4 words ends with period) or
         "12/2025 - Present" (no letters).

    We deliberately err on the side of NOT calling something an
    entry. False negatives (a real entry header treated as body)
    just merge it with the previous entry's text. False
    positives (a body line treated as an entry) fragment the
    output and break the LLM's downstream parsing.
    """
    stripped = line.strip()
    if not stripped:
        return False
    if _looks_like_section_header(line):
        return False
    # Pure metadata (date-only, location, status) is NEVER an
    # entry. Folding it into the previous entry's title is
    # always the right call.
    if _is_metadata_line(line):
        return False
    if " -- " in stripped or " @ " in stripped:
        return True
    # Date hint mixed with non-metadata content -- e.g.
    # "Data Annotator | 12/2025 - Present" -- is an entry.
    if _DATE_HINT_RE.search(stripped):
        return True
    # Mixed-case short line that looks like a name.
    if 2 <= len(stripped) <= 60 and not stripped.endswith("."):
        words = stripped.split()
        if 1 <= len(words) <= 5:
            letters = [c for c in stripped if c.isalpha()]
            if letters and any(c.isupper() for c in letters) and any(
                c.islower() for c in letters
            ):
                return True
    return False


def _is_metadata_line(line: str) -> bool:
    """True for lines that are metadata (date, location) rather
    than a new entry or a new bullet. Used to fold lines like
    "Jan 2022 - Present" or "Remote, US" into the previous
    entry's title instead of creating a new entry.
    """
    stripped = line.strip()
    if not stripped:
        return False
    if _DATE_HINT_RE.search(stripped):
        return True
    if (
        2 <= len(stripped) <= 60
        and not stripped.endswith((".", "!", "?"))
        and "," in stripped
        and len(stripped.split(",")) <= 3
    ):
        return True
    # Single-word status: "Present", "Remote", "Hybrid".
    # Require the word to be all-uppercase OR all-lowercase with
    # first letter uppercase ("Title Case"). Mixed-case words
    # like "MatchPoint" or "iOS" are project / brand names, not
    # status, so we exclude them.
    if (
        len(stripped.split()) == 1
        and len(stripped) <= 20
        and stripped[:1].isupper()
    ):
        letters = [c for c in stripped if c.isalpha()]
        if letters and not any(
            c.isupper() and c.islower()
            for c in stripped
            if c.isalpha()
        ) and all(
            c == stripped[0] or not c.isupper()
            for c in stripped[1:]
            if c.isalpha()
        ):
            # Either "PRESENT" (all caps) or "Present" / "Remote"
            # (one capital then lowercase). Not "MatchPoint" /
            # "iOS" / "GitHub".
            return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_resume(text: str) -> ResumeDocument:
    """Parse a resume string into sections -> entries.

    Always returns a ResumeDocument. If parsing finds no structure
    at all, falls back to a single "Resume" section with one
    empty-title entry containing the whole text. This gives the
    LLM *something* to work with even on unusual resume formats.
    """
    if not text or not text.strip():
        return _fallback_document(text)

    lines = text.splitlines()

    # Walk the lines, classifying each as "section", "entry", or
    # "body". Body lines accumulate into the current entry's text.
    sections: list[ResumeSection] = []
    current_section: Optional[ResumeSection] = None
    current_entry: Optional[ResumeEntry] = None
    # Pre-entry noise (name, email, phone at the top of the
    # resume) gets dropped on the floor.
    saw_first_entry = False
    # Lines that aren't part of an entry yet (after a section
    # header, before the first entry) get stashed here.
    pending_body: list[str] = []
    # Pending metadata to fold into the next entry's title.
    pending_metadata: list[str] = []

    def _flush_entry() -> None:
        nonlocal current_entry
        if current_section is not None and current_entry is not None:
            if pending_metadata:
                # Fold any trailing metadata (e.g. "Remote, US")
                # into the entry's title.
                title_pieces = [current_entry.title] + pending_metadata
                current_entry.title = " | ".join(
                    piece for piece in title_pieces if piece
                )
                pending_metadata.clear()
            if current_entry.title or current_entry.text:
                # Drop entries with neither title nor text.
                current_section.entries.append(current_entry)
        current_entry = None

    def _flush_section() -> None:
        nonlocal current_section
        _flush_entry()
        if current_section is not None and (
            current_section.entries or current_section.title != "Resume"
        ):
            sections.append(current_section)
        current_section = None

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            # Blank line: end the current body if any.
            if current_entry is not None and current_entry.text.strip():
                current_entry.text = current_entry.text.rstrip() + "\n"
            continue

        if _looks_like_section_header(raw_line):
            _flush_section()
            title = stripped.rstrip(":").strip()
            current_section = ResumeSection(title=title, entries=[])
            # Any pending body lines belong to a synthetic entry
            # under this section.
            if pending_body and current_section is not None:
                synthetic = ResumeEntry(
                    title="", text="\n".join(pending_body).strip()
                )
                current_section.entries.append(synthetic)
                pending_body = []
            continue

        if _looks_like_entry_title(raw_line):
            _flush_entry()
            saw_first_entry = True
            current_entry = ResumeEntry(title=stripped, text="")
            continue

        if _is_metadata_line(raw_line):
            # Fold into the current or next entry's title.
            if current_entry is not None:
                if current_entry.title:
                    current_entry.title = (
                        current_entry.title + " | " + stripped
                    )
                else:
                    current_entry.title = stripped
            else:
                pending_metadata.append(stripped)
            continue

        # Body line. Append to the current entry, or to
        # pending_body if we don't have an entry yet.
        if current_entry is None:
            pending_body.append(stripped)
        else:
            if current_entry.text:
                # Single space between body lines (collapses
                # line-wrap to one paragraph per entry).
                current_entry.text = (
                    current_entry.text.rstrip() + " " + stripped
                )
            else:
                current_entry.text = stripped

    # Capture any trailing metadata that wasn't yet folded.
    if pending_metadata and current_entry is not None:
        pieces = [current_entry.title] + pending_metadata
        current_entry.title = " | ".join(p for p in pieces if p)
    elif pending_metadata and pending_body and current_section is None:
        # We're in the fallback shape -- promote the metadata
        # into the pending body.
        pending_body.extend(pending_metadata)

    _flush_section()

    # Promote any leftover pending_body into a synthetic entry on
    # a fallback "Resume" section.
    if pending_body and not sections:
        sections = [
            ResumeSection(
                title="Resume",
                entries=[
                    ResumeEntry(
                        title="", text="\n".join(pending_body).strip()
                    )
                ],
            )
        ]

    if not sections:
        return _fallback_document(text)

    # Post-pass: merge empty-text entries into the next entry's
    # title. This catches the common "role on one line, company
    # on the next" pattern (e.g. "Data Annotator" / "Handshake
    # (Contract)"). Without this, "Data Annotator" becomes its
    # own entry with no body, and the actual entry starts on the
    # next line.
    for section in sections:
        merged_entries: list[ResumeEntry] = []
        pending_title_parts: list[str] = []
        for entry in section.entries:
            if entry.text.strip():
                # Real entry -- flush any pending title parts
                # into it, then add it.
                if pending_title_parts:
                    prefix = " | ".join(pending_title_parts)
                    if entry.title:
                        entry.title = prefix + " | " + entry.title
                    else:
                        entry.title = prefix
                    pending_title_parts = []
                merged_entries.append(entry)
            else:
                # Empty-text entry -- save its title for the
                # next real entry.
                if entry.title:
                    pending_title_parts.append(entry.title)
        # If the section ends with pending parts and no real
        # entry follows, drop them (better than an empty entry
        # at the end).
        section.entries = merged_entries

    # Drop sections that ended up with no entries after merging.
    sections = [s for s in sections if s.entries]

    if not sections:
        return _fallback_document(text)

    return ResumeDocument(sections=sections)


def _fallback_document(text: str) -> ResumeDocument:
    """Single "Resume" section with the whole text in one entry.

    The LLM can still pick a sentence from this. Better than
    shipping an empty document.
    """
    return ResumeDocument(
        sections=[
            ResumeSection(
                title="Resume",
                entries=[
                    ResumeEntry(
                        title="", text=(text or "").strip()
                    )
                ],
            )
        ]
    )