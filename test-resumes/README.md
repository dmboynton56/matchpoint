# Test resumes

Synthetic PDF resumes for local testing (upload flow, parsing, job matching, suggestions). **Not real people** — use `@email.example` addresses only.

| File | Profile | Typical `target_role` for testing |
|------|---------|-----------------------------------|
| `mid-level-developer.pdf` | ~4 yrs full-stack IC, React/Python | Software Engineer, Full Stack Developer |
| `senior-software-engineer.pdf` | ~11 yrs backend/platform IC | Senior Software Engineer, Staff Engineer |
| `engineering-manager-transition.pdf` | ~8 yrs, recent Tech Lead, EM path | Engineering Manager, Team Lead |

## Regenerate PDFs

Source Markdown lives alongside the PDFs. Requires [pandoc](https://pandoc.org/) and a PDF engine (macOS: built-in via `--pdf-engine=pdflatex` or wkhtmltopdf).

```bash
cd test-resumes
for f in mid-level-developer senior-software-engineer engineering-manager-transition; do
  pandoc "${f}.md" -o "${f}.pdf" --pdf-engine=pdflatex -V geometry:margin=0.75in
done
```

Or run the generator script:

```bash
python test-resumes/generate_pdfs.py
```

## Usage

Upload any PDF through the app Resume page while signed in. Each profile exercises different experience levels for match ranking and bullet-coach suggestions.
