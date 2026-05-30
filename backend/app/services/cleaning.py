from bs4 import BeautifulSoup
import re


NOISE_HEADERS = [
    "who we are",
    "benefits",
    "pay transparency",
    "privacy",
    "equal opportunity",
    "interview process",
    "hiring process",
    "our culture",
    "life at",
]

IMPORTANT_ABOUT_HEADERS = [
    "about the role",
    "about this role",
    "about the position",
    "about the opportunity",
]

IMPORTANT_HEADERS = [
    # Responsibilities
    "responsibilities",
    "key responsibilities",
    "job responsibilities",
    "primary responsibilities",
    "role responsibilities",
    "what you'll do",
    "what you will do",
    "what you'll be doing",
    "what you will be doing",
    "your responsibilities",
    "day-to-day",
    "day to day",
    "your impact",
    "what you'll accomplish",
    "what you'll own",
    "areas of responsibility",

    # Requirements
    "requirements",
    "minimum requirements",
    "required qualifications",
    "minimum qualifications",
    "basic qualifications",
    "must have",
    "must-haves",
    "what you bring",
    "what we're looking for",
    "who you are",
    "candidate profile",

    # Preferred
    "preferred qualifications",
    "preferred experience",
    "preferred skills",
    "desired qualifications",
    "nice to have",
    "nice-to-have",
    "bonus points",
    "bonus qualifications",

    # Skills
    "skills",
    "technical skills",
    "required skills",
    "core competencies",
    "competencies",
    "technical requirements",
    "technologies",
    "tools and technologies",

    # Experience
    "experience",
    "professional experience",
    "relevant experience",
    "background",
    "expertise",

    # Role / Position
    "job description",
    "about the role",
    "about this role",
    "about the position",
    "about the opportunity",
    "role overview",
    "position overview",
    "overview",
    "the opportunity",
    "the role",
    "role summary",
    "position summary",

    # Duties
    "duties",
    "key duties",
    "essential duties",
    "essential functions",

    # Qualifications
    "qualifications",
    "candidate qualifications",

    # Success metrics
    "what success looks like",
    "success in this role",
    "how you'll succeed",

    # Growth
    "career growth",
    "growth opportunities",
]

HEADER_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6"]


def normalizeHeader(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def stripHTML(html: str) -> str:
    noHTML = BeautifulSoup(html, "html.parser")
    return noHTML.get_text(separator=" ")


def normalizeText(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def removeNoiseSections(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    original_text = normalizeText(stripHTML(html))

    headers = soup.find_all(HEADER_TAGS)

    found_important = False

    for header in headers:
        header_text = normalizeHeader(
            header.get_text(" ", strip=True)
        )

        if any(
            important in header_text
            for important in IMPORTANT_HEADERS
        ):
            found_important = True

        remove_section = False

        if (
        "about" in header_text
            and not any(
                important in header_text
                for important in IMPORTANT_ABOUT_HEADERS
            )
        ):
            remove_section = True

        elif any(
            noise in header_text
            for noise in NOISE_HEADERS
        ):
            remove_section = True

        if not remove_section:
            continue

        current = header

        while current:
            next_node = current.find_next_sibling()

            current.decompose()

            if (
                next_node
                and next_node.name in HEADER_TAGS
            ):
                break

            current = next_node

    cleaned_html = str(soup)

    

    # Failsafes
    if not found_important and len(cleaned_html) < 500:
        return html



    return cleaned_html


def buildCleanedText(job):
    html = removeNoiseSections(job["description"])

    stripped = stripHTML(html)

    cleanedText = normalizeText(stripped)

    return f"""
    Title: {job['title']}
    Company: {job['company']}
    Location: {job['location']}
    Description: {cleanedText}
    """