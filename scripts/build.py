#!/usr/bin/env python3
"""Build the static site from the data files.

Usage:
  python scripts/build.py              # writes site/index.html, ready for GitHub Pages
  python scripts/build.py --fragment   # page body only (for embedding or previews)

The site is one HTML file with all data embedded, so it can be hosted anywhere
that serves static files. Set REPO_URL below once the GitHub repository exists.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import ROOT, bwv_sort_key, load, main as validate  # noqa: E402

REPO_URL = "https://github.com/glima93/all-bach"
TEMPLATE = ROOT / "site-template" / "index.html"
OUT = ROOT / "site" / "index.html"


def main() -> int:
    if validate() != 0:
        print("Build stopped: fix the errors above first.")
        return 1

    works = sorted((w for _, w in load("works")), key=lambda w: bwv_sort_key(w["bwv"]))
    recordings = [r for _, r in load("recordings")]
    payload = {
        "works": works,
        "recordings": recordings,
        "repo_url": REPO_URL,
        "built": dt.date.today().isoformat(),
    }
    data_js = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    body = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", data_js, 1)

    if "--fragment" in sys.argv:
        page = body
    else:
        # Title, meta and styles go in <head>; the rest is the page body.
        split = body.index('<div class="wrap">')
        page = (
            '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            + body[:split] + "</head>\n<body>\n" + body[split:] + "\n</body>\n</html>\n"
        )
    out = ROOT / "site" / ("fragment.html" if "--fragment" in sys.argv else "index.html")
    out.parent.mkdir(exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote {out.relative_to(ROOT)} ({len(works)} works, {len(recordings)} recordings)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
