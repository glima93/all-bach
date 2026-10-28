"""Write data/works/<bwv>.yaml stubs from a collector work tree (data/sources/tree-<id>.json).

    python scripts/work_stub.py data/sources/tree-orchestral-suites.json

The movement list comes from MusicBrainz, in MusicBrainz order, which is what the importer needs. Names
can be put in English afterwards, but not reordered, merged or split, and only before importing. Title,
scoring, composed, notes and links are left for the work-file writer (docs/batch-runbook.md), marked TODO.
Existing work files are never overwritten; the script reports any whose movement count disagrees.
"""
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
GENRE = {"Orchestral": "orchestral", "Keyboard": "keyboard", "Organ": "organ", "Chamber": "chamber",
         "Lute": "lute", "Cantatas": "cantata", "Masses and Magnificat": "mass",
         "Passions and Oratorios": "oratorio", "Motets": "motet", "Chorales": "chorale",
         "Songs and Arias": "song", "Late contrapuntal works": "other", "Additions": "other"}


def short_title(title: str) -> str:
    return re.sub(r",?\s*BWV\s*\d+[a-z]?\b.*$", "", title).strip() or title


def movement_name(title: str, bwv: str, work_title: str) -> str:
    m = re.search(rf"BWV\s*{bwv}[a-z]?\s*:\s*(.+)$", title)
    if m:
        return m.group(1).strip()
    if title.startswith(work_title):
        return title[len(work_title):].lstrip(" :,") or short_title(title)
    return title


def q(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def main(tree_path: str) -> int:
    tree = json.loads(Path(tree_path).read_text(encoding="utf-8"))
    cols = yaml.safe_load((ROOT / "data/plan/collections.yaml").read_text(encoding="utf-8"))["collections"]
    col = next(c for c in cols if c["id"] == tree["collection"])
    written, clashes = [], []
    for w in tree["works"]:
        path = ROOT / "data/works" / f"{w['bwv']}.yaml"
        moves = [movement_name(m["title"], w["bwv"], w["title"]) for m in w["movements"]]
        if len(moves) == 1 and not w.get("has_parts"):
            moves = [short_title(w["title"])]
        if path.exists():
            old = yaml.safe_load(path.read_text(encoding="utf-8"))
            if len(old["movements"]) != len(moves):
                clashes.append(f"BWV {w['bwv']}: {len(old['movements'])} movements on file, {len(moves)} in MusicBrainz")
            continue
        lines = [
            "# TODO (work-file writer): English title, scoring, composed, notes and links. Movement names may",
            "# be put in English but must keep this order and number (they follow MusicBrainz).",
            f"bwv: {q(w['bwv'])}",
            f"title: {q(short_title(w['title']))}",
            f"key: {q(w['key']) if w.get('key') else 'null'}",
            f"collection: {q(col['title'])}",
            f"genre: {GENRE.get(col['chapter'], 'other')}",
            'scoring: "TODO"',
            "composed: null",
            "movements:",
            *[f"  - {q(m)}" for m in moves],
            "notes: null",
            "links:",
            "  wikipedia: null",
            f"  bach_digital: null",
            f"# MusicBrainz work: https://musicbrainz.org/work/{w['id']}",
        ]
        if w.get("ambiguous"):
            lines.append("# Several MusicBrainz works matched this BWV number equally well; check the one above.")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written.append(w["bwv"])
    print(f"{len(written)} work stubs written: {', '.join(written) or '-'}")
    for c in clashes:
        print("movement count differs:", c)
    return 1 if clashes else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
