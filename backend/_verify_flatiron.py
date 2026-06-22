"""Verify Flatiron School candidate URLs. Same shape as
_verify_learning_links.py — only OK results ship in the final table.
"""
from __future__ import annotations

import sys
import urllib.request
import urllib.error


CANDIDATES = [
    ("flatiron homepage",      "https://flatironschool.com/"),
    ("flatiron courses",       "https://flatironschool.com/courses/"),
    ("flatiron programs",      "https://flatironschool.com/programs/"),
    ("flatiron software eng",  "https://flatironschool.com/courses/software-engineering/"),
    ("flatiron data science",  "https://flatironschool.com/courses/data-science/"),
    ("flatiron data analytics","https://flatironschool.com/courses/data-analytics/"),
    ("flatiron cybersecurity", "https://flatironschool.com/courses/cybersecurity/"),
    ("flatiron product design","https://flatironschool.com/courses/product-design/"),
    ("flatiron ux/ui",         "https://flatironschool.com/courses/ux-ui-design/"),
    ("flatiron web dev",       "https://flatironschool.com/courses/web-development/"),
    ("flatiron full stack",    "https://flatironschool.com/courses/full-stack-engineering/"),
]


def check(label: str, url: str, timeout: int = 15) -> str:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final = resp.geturl()
            note = f"  -> {final}" if final.rstrip("/") != url.rstrip("/") else ""
            return f"OK    {label:26s}  {url}{note}"
    except urllib.error.HTTPError as e:
        return f"BAD   {label:26s}  {url}  (HTTP {e.code})"
    except Exception as e:
        return f"BAD   {label:26s}  {url}  ({type(e).__name__}: {e})"


def main() -> int:
    for label, url in CANDIDATES:
        print(check(label, url), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
