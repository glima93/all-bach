#!/usr/bin/env python3
"""Build the static site from the data files.

Usage:
  python scripts/build.py              # writes site/index.html, ready for GitHub Pages
  python scripts/build.py --fragment   # page body only (for embedding or previews)

The site is static: one HTML page with the works and the counts embedded, plus
site/data/<collection>.json (the recordings of one volume, loaded when a work page
opens) and site/data/search.json (every recording, trimmed, loaded on the first
search). That keeps the page small however many recordings the catalogue holds.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import ROOT, bwv_sort_key, load, main as validate  # noqa: E402

REPO_URL = "https://github.com/glima93/all-bach"
TEMPLATE = ROOT / "site-template" / "index.html"
OUT = ROOT / "site" / "index.html"


# Shelf order of the BWV chapters; a collection's chapter comes from data/plan/collections.yaml.
CHAPTERS = ["Cantatas", "Motets", "Masses and Magnificat", "Passions and Oratorios", "Chorales", "Songs and Arias",
            "Organ", "Keyboard", "Lute", "Chamber", "Orchestral", "Late contrapuntal works", "Additions"]


def col_slug(name: str) -> str:
    s = unicodedata.normalize("NFD", name)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"^the ", "", s)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def chapter_of() -> dict[int, str]:
    plan = yaml.safe_load((ROOT / "data/plan/collections.yaml").read_text(encoding="utf-8"))["collections"]
    out = {}
    for c in plan:
        for spec in c["bwv"]:
            lo, _, hi = spec.partition("-")
            for n in range(int(lo), int(hi or lo) + 1):
                out[n] = c["chapter"]
    return out


def to_come() -> list[dict]:
    """Planned collections not on the shelf yet, for the dust outlines and the cabinet."""
    plan = yaml.safe_load((ROOT / "data/plan/collections.yaml").read_text(encoding="utf-8"))["collections"]
    return [{"title": c["title"], "chapter": c["chapter"], "bwv": c["bwv"],
             "run": c["run"][0] if isinstance(c["run"], list) else c["run"]}
            for c in plan if c["status"] not in ("done", "imported")]


def first_year(r: dict):
    ys = (r.get("recorded") or {}).get("years") or []
    return min(ys) if ys else r.get("released")


def trimmed(r: dict) -> dict:
    """What search needs to find and show a recording."""
    link = next((l for l in r["links"] if l["platform"] != "musicbrainz"), r["links"][0] if r["links"] else None)
    keep = ("id", "performers", "instrument", "performance_practice", "arrangement", "recorded", "released",
            "original_label", "works", "notes")
    return {**{k: r[k] for k in keep if k in r}, "links": [link] if link else []}


def dump(x) -> str:
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"))


def main() -> int:
    if validate() != 0:
        print("Build stopped: fix the errors above first.")
        return 1

    works = sorted((w for _, w in load("works")), key=lambda w: bwv_sort_key(w["bwv"]))
    recordings = sorted((r for _, r in load("recordings")), key=lambda r: r["id"])
    chapters = chapter_of()
    work_col = {w["bwv"]: w["collection"] for w in works}
    cols: list[dict] = []
    for w in works:
        if not cols or cols[-1]["name"] != w["collection"]:
            n = int(re.match(r"\d+", w["bwv"]).group())
            cols.append({"name": w["collection"], "slug": col_slug(w["collection"]),
                         "chapter": chapters.get(n, "Additions"), "recs": []})
    by_name = {c["name"]: c for c in cols}
    stats: dict[str, list] = {}
    for r in recordings:
        for name in dict.fromkeys(work_col[w["bwv"]] for w in r["works"]):
            by_name[name]["recs"].append(r)
        for w in r["works"]:
            st = stats.setdefault(w["bwv"], [0, None])
            st[0] += 1
            y = first_year(r)
            if y and (st[1] is None or y < st[1]):
                st[1] = y
    data_dir = ROOT / "site" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for old in data_dir.glob("*.json"):
        old.unlink()
    for c in cols:
        (data_dir / f"{c['slug']}.json").write_text(dump(c["recs"]), encoding="utf-8")
        ys = [y for y in map(first_year, c["recs"]) if y]
        c["n"], c["since"] = len(c.pop("recs")), (min(ys) if ys else None)
    (data_dir / "search.json").write_text(dump([trimmed(r) for r in recordings]), encoding="utf-8")
    payload = {
        "works": works,
        "cols": cols,
        "chapters": [ch for ch in CHAPTERS if any(c["chapter"] == ch for c in cols)],
        "all_chapters": CHAPTERS,
        "to_come": to_come(),
        "stats": stats,
        "total": len(recordings),
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
