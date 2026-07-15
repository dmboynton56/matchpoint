#!/usr/bin/env python3
"""Generate test resume PDFs from Markdown sources in this directory."""

from __future__ import annotations

from pathlib import Path

try:
    from fpdf import FPDF
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "fpdf2 is required: pip install fpdf2\n"
        "Or regenerate with pandoc if you have a PDF engine installed."
    ) from exc

RESUMES = [
    "mid-level-developer",
    "senior-software-engineer",
    "engineering-manager-transition",
]


class ResumePDF(FPDF):
    def header(self) -> None:
        pass

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, f"Test resume - synthetic data - page {self.page_no()}", align="C")


def _ascii_safe(text: str) -> str:
    return (
        text.replace("\u2014", " - ")
        .replace("\u2013", "-")
        .replace("\u2022", "-")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )


def _write_line(pdf: ResumePDF, line: str, *, size: int = 10, style: str = "", lh: float = 5) -> None:
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", style, size)
    pdf.multi_cell(pdf.epw, lh, line)


def md_to_pdf(md_path: Path, pdf_path: Path) -> None:
    text = md_path.read_text(encoding="utf-8")
    pdf = ResumePDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_margins(18, 18, 18)

    for raw_line in text.splitlines():
        line = _ascii_safe(raw_line.rstrip())
        if not line.strip():
            pdf.ln(4)
            continue

        if line.startswith("# "):
            pdf.set_text_color(20, 20, 20)
            _write_line(pdf, line[2:].strip(), size=18, style="B", lh=9)
            pdf.ln(2)
        elif line.startswith("## "):
            pdf.ln(3)
            pdf.set_text_color(30, 30, 30)
            _write_line(pdf, line[3:].strip(), size=12, style="B", lh=7)
            pdf.ln(1)
        elif line.startswith("### "):
            pdf.ln(2)
            pdf.set_text_color(40, 40, 40)
            _write_line(pdf, line[4:].strip(), size=10, style="B", lh=6)
        elif line.startswith("---"):
            pdf.ln(2)
            pdf.set_draw_color(200, 200, 200)
            y = pdf.get_y()
            pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
            pdf.ln(4)
        elif line.startswith("- "):
            pdf.set_text_color(30, 30, 30)
            _write_line(pdf, "- " + line[2:].strip())
        elif line.startswith("**") and line.endswith("**"):
            pdf.set_text_color(30, 30, 30)
            _write_line(pdf, line.strip("*"), style="B")
        else:
            pdf.set_text_color(30, 30, 30)
            _write_line(pdf, line)

    pdf.output(str(pdf_path))


def main() -> None:
    here = Path(__file__).resolve().parent
    for stem in RESUMES:
        md = here / f"{stem}.md"
        pdf = here / f"{stem}.pdf"
        if not md.exists():
            raise FileNotFoundError(md)
        md_to_pdf(md, pdf)
        print(f"Wrote {pdf.name} ({pdf.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
