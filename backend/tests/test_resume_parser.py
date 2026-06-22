import unittest

from app.services.resume_parser import (
    ResumeDocument,
    parse_resume,
)


class ParseResumeTests(unittest.TestCase):
    def test_empty_text_falls_back_to_single_section(self):
        doc = parse_resume("")
        self.assertEqual(len(doc.sections), 1)
        self.assertEqual(doc.sections[0].title, "Resume")
        self.assertEqual(len(doc.sections[0].entries), 1)
        self.assertEqual(doc.sections[0].entries[0].text, "")

    def test_recognizes_known_section_titles(self):
        doc = parse_resume(
            "WORK EXPERIENCE\nAcme Corp\n- Did a thing.\n"
            "PROJECTS\nMatchPoint\n- Built a thing.\n"
            "EDUCATION\nUC Berkeley\n- Studied things.\n"
        )
        section_titles = [s.title for s in doc.sections]
        self.assertIn("WORK EXPERIENCE", section_titles)
        self.assertIn("PROJECTS", section_titles)
        self.assertIn("EDUCATION", section_titles)

    def test_two_line_entry_header_folds_into_next_entry(self):
        # "Data Annotator" is a role, "Handshake (Contract)" is
        # the company. They should merge into a single entry.
        doc = parse_resume(
            "PROFESSIONAL EXPERIENCE\n"
            "Data Annotator\n"
            "Handshake (Contract)\n"
            "- Annotated data.\n"
        )
        self.assertEqual(len(doc.sections), 1)
        entries = doc.sections[0].entries
        self.assertEqual(len(entries), 1)
        self.assertIn("Data Annotator", entries[0].title)
        self.assertIn("Handshake (Contract)", entries[0].title)
        self.assertIn("Annotated data", entries[0].text)

    def test_date_metadata_folds_into_entry_title(self):
        doc = parse_resume(
            "PROFESSIONAL EXPERIENCE\n"
            "Acme Corp\n"
            "- Did the thing.\n"
            "12/2025 - Present\n"
        )
        entries = doc.sections[0].entries
        self.assertEqual(len(entries), 1)
        self.assertIn("Acme Corp", entries[0].title)
        self.assertIn("12/2025 - Present", entries[0].title)
        self.assertIn("Did the thing", entries[0].text)

    def test_location_metadata_folds_into_entry_title(self):
        doc = parse_resume(
            "PROFESSIONAL EXPERIENCE\n"
            "Acme Corp\n"
            "- Did the thing.\n"
            "Remote, US\n"
        )
        entries = doc.sections[0].entries
        self.assertEqual(len(entries), 1)
        self.assertIn("Acme Corp", entries[0].title)
        self.assertIn("Remote, US", entries[0].title)

    def test_skills_section_does_not_promote_sublines_to_entries(self):
        # "Languages", "Python, C++, SQL", "Frontend" etc. should
        # NOT be entry titles -- they're sub-headers and content.
        doc = parse_resume(
            "SKILLS\n"
            "Languages\n"
            "Python, C++, SQL\n"
            "Frontend\n"
            "React, JavaScript, HTML, CSS\n"
        )
        # The parser will be conservative: SKILLS has no real
        # entries (no body text), so the section is dropped or
        # contains no entries. We just need to make sure that
        # "Python, C++, SQL" did not become its own entry title.
        for section in doc.sections:
            for entry in section.entries:
                self.assertNotIn("Python, C++", entry.title)

    def test_real_resume_example(self):
        # The actual resume we've been using as a test case.
        sample = (
            "PROJECTS\n"
            "Spot It Symbol Detection (YOLOv11)\n"
            "- Developed and fine-tuned a YOLOv11 model.\n"
            "Personal CRM\n"
            "- Built a full-stack CRM application.\n"
            "PROFESSIONAL EXPERIENCE\n"
            "Data Annotator\n"
            "Handshake (Contract)\n"
            "- Annotated and validated data.\n"
            "12/2025 - Present\n"
            "AI Engineering Apprentice\n"
            "Flatiron School\n"
            "- Developing AI-powered full-stack applications.\n"
            "Present\n"
            "Remote, US\n"
            "- Built scalable backend APIs.\n"
        )
        doc = parse_resume(sample)
        # Should produce two sections (PROJECTS, PROFESSIONAL
        # EXPERIENCE), each with the expected number of entries.
        section_titles = [s.title for s in doc.sections]
        self.assertIn("PROJECTS", section_titles)
        self.assertIn("PROFESSIONAL EXPERIENCE", section_titles)
        # PROJECTS: 2 entries (Spot It, Personal CRM)
        projects = next(
            s for s in doc.sections if s.title == "PROJECTS"
        )
        self.assertEqual(len(projects.entries), 2)
        # PROFESSIONAL EXPERIENCE: 2 entries (Data Annotator +
        # Handshake (Contract) merged, then AI Engineering
        # Apprentice + Flatiron School merged)
        experience = next(
            s for s in doc.sections
            if s.title == "PROFESSIONAL EXPERIENCE"
        )
        self.assertEqual(len(experience.entries), 2)
        # First entry's title includes role + company + date.
        first = experience.entries[0]
        self.assertIn("Data Annotator", first.title)
        self.assertIn("Handshake (Contract)", first.title)
        self.assertIn("12/2025 - Present", first.title)
        # Second entry's title includes role + company + dates +
        # location.
        second = experience.entries[1]
        self.assertIn("AI Engineering Apprentice", second.title)
        self.assertIn("Flatiron School", second.title)
        self.assertIn("Remote, US", second.title)
        # Body text is the bullet content.
        self.assertIn("Annotated and validated data", first.text)
        self.assertIn("Developing AI-powered full-stack", second.text)
        self.assertIn("Built scalable backend APIs", second.text)


if __name__ == "__main__":
    unittest.main()