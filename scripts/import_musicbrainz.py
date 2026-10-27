#!/usr/bin/env python3
"""Turn a MusicBrainz snapshot into recording files, merging with existing ones.

Usage:  python scripts/import_musicbrainz.py data/sources/musicbrainz-cello-suites.json

The snapshot is a list of *performances*: MusicBrainz recordings grouped by
performer and recording year (see data/sources/README.md for how it was made).

Rules:
- A performance whose MusicBrainz recording ID already appears in a file
  (under `musicbrainz.recordings`) updates that file: empty fields are filled,
  nothing a contributor wrote is overwritten. Running the import twice is safe.
- A hand-made file with no MusicBrainz IDs is matched by performer name and
  recording year, or by release year within one year, or, when the file has
  no dates at all, when MusicBrainz knows exactly one performance by that
  performer. Ambiguous cases are left alone; link them by hand by adding
  `musicbrainz: {recordings: [<id>]}` to the file and re-running.
- Everything else becomes a new draft file.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import DATA, load  # noqa: E402

BWVS = ["1007", "1008", "1009", "1010", "1011", "1012"]
ALIASES = {"pau casals": "pablo casals"}

# MusicBrainz "[unknown]" artist: no performer to file the recording under.
UNKNOWN_ARTIST = "125ec42a-7229-4250-afc5-e057484327fe"

# Recordings MusicBrainz links to the suites that are not performances of them.
# Keyed by representative recording ID, with the reason. Fix upstream in
# MusicBrainz too, then remove the entry here.
EXCLUDE = {
    "04f657f2-dbb1-4b2a-8c4b-e96a1e4f4080": "release is the Orchestral Suites BWV 1066-1069",
    "91db1c6e-aa80-4cfc-8ef5-50639f20bc1e": "release is Rameau's harpsichord works",
    "a81b39e1-c432-4893-a829-295bfd14ae80": "release is orchestral suites by other composers",
    "9cb32a24-055a-4bb5-aa3d-d5e37830ef5a": "release is trio sonatas",
    "0e978aec-44f7-4839-9f8a-d50b3af73f50": "accompaniment-only track of the Burrowes recording",
    "b0554f83-50e2-4505-8a48-628c6dc792c8": "magazine lesson disc, not a performance",
}

INSTRUMENTS = {
    "cello": "cello", "violoncello": "cello",
    "baroque cello": "baroque-cello", "baroque violoncello": "baroque-cello",
    "violoncello piccolo": "violoncello-piccolo", "five-string cello": "violoncello-piccolo",
    "violoncello da spalla": "violoncello-da-spalla", "viola da spalla": "violoncello-da-spalla",
    "viola": "viola", "viola da gamba": "viola-da-gamba", "violin": "violin",
    "guitar": "guitar", "classical guitar": "guitar", "acoustic guitar": "guitar",
    "lute": "lute", "harpsichord": "harpsichord", "piano": "piano", "grand piano": "piano",
    "organ": "organ", "clavichord": "clavichord",
}
CELLO_FAMILY = {"cello", "baroque-cello", "violoncello-piccolo", "violoncello-da-spalla", "unknown"}
HISTORICAL = {"baroque-cello", "violoncello-piccolo", "violoncello-da-spalla", "viola-da-gamba"}


class Flow(list):
    """A list written in YAML flow style: [a, b]."""


class FlowDict(dict):
    """A mapping written in YAML flow style: { a: 1 }."""


def _dumper():
    class D(yaml.SafeDumper):
        pass
    D.add_representer(Flow, lambda d, v: d.represent_sequence("tag:yaml.org,2002:seq", v, flow_style=True))
    D.add_representer(FlowDict, lambda d, v: d.represent_mapping("tag:yaml.org,2002:map", v.items(), flow_style=True))
    D.add_representer(type(None), lambda d, _: d.represent_scalar("tag:yaml.org,2002:null", "null"))
    return D


def norm(name: str) -> str:
    s = re.sub(r"[‐-―'’]", " ", name.split(",")[0])
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]+", " ", s)
    s = " ".join(s.split())
    return ALIASES.get(s, s)


def slug_for(rec: dict) -> str:
    """Full performer name as a slug; falls back to the MusicBrainz artist ID for non-Latin names."""
    s = norm(rec["performers"][0]["name"]).replace(" ", "-")
    if not s:
        artist = (rec.get("musicbrainz") or {}).get("artist", "")
        s = f"artist-{artist[:8]}" if artist else "unknown"
    return s


def year(s) -> int | None:
    return int(str(s)[:4]) if s else None


def movement_names() -> dict[str, list[str]]:
    return {w["bwv"]: w["movements"] for _, w in load("works")}


def expand(c: dict) -> dict:
    """Snapshot rows are compact; turn one into the shape the importer works with.

    Row keys: n performer names, a artist MBIDs, y recording years, m six bitmasks
    (one per suite, bit i = movement i present), f first release year, l live,
    ins instruments credited, roles {performer: instrument}, pl places recorded at,
    r [release MBID, title], rep representative recording MBID.
    """
    masks = [int(x) for x in c["m"].split(",")]
    mv = [f"{BWVS[k]}:{i}" for k, mask in enumerate(masks) for i in range(6) if mask >> i & 1]
    return {
        "names": c["n"], "ids": c["a"], "years": c["y"], "mv": mv,
        "firstRelease": c.get("f"), "live": bool(c.get("l")),
        "ins": c.get("ins") or [], "roles": c.get("roles") or {},
        "places": c.get("pl") or [],
        "releases": [{"id": c["r"][0], "title": c["r"][1]}] if c.get("r") else [],
        "repId": c["rep"], "recIds": [c["rep"]],
    }


def instrument_of(perf: dict) -> tuple[str, dict]:
    """Main instrument (first credited) and per-performer roles."""
    if not perf["ins"]:
        return "unknown", {}
    first = perf["ins"][0].lower()
    return INSTRUMENTS.get(first, "other"), {k: v.lower() for k, v in perf["roles"].items()}


def works_block(perf: dict, moves: dict[str, list[str]]) -> list:
    out = []
    have = set(perf["mv"])
    for bwv in BWVS:
        idx = [i for i in range(6) if f"{bwv}:{i}" in have]
        if not idx:
            continue
        if len(idx) == 6:
            out.append(FlowDict(bwv=bwv, complete=True))
        else:
            out.append(FlowDict(bwv=bwv, complete=False, movements=Flow(moves[bwv][i] for i in idx)))
    return out


def mb_links(perf: dict) -> list[dict]:
    links = [{"platform": "musicbrainz", "kind": "release",
              "url": f"https://musicbrainz.org/release/{r['id']}", "title": r["title"]} for r in perf["releases"]]
    if not links:
        links.append({"platform": "musicbrainz", "kind": "page",
                      "url": f"https://musicbrainz.org/recording/{perf['repId']}", "title": None})
    return links


def help_items(rec: dict, same_performer: int) -> list[str]:
    items = []
    if not rec["recorded"]["years"]:
        items.append("Recording year")
        if same_performer > 1:
            items.append("Check whether this is the same performance as another entry by this performer")
    if not rec["recorded"]["place"]:
        items.append("Recording place")
    if rec["instrument"] == "unknown":
        items.append("Instrument (MusicBrainz has no instrument credit)")
    if not any(l["platform"] != "musicbrainz" for l in rec["links"]):
        items.append("Streaming links (Spotify, Apple Music, YouTube …)")
    return items


def from_perf(perf: dict, moves: dict[str, list[str]], same_performer: int) -> dict:
    instrument, roles = instrument_of(perf)
    solo = len(perf["names"]) == 1
    performers = []
    for name in perf["names"]:
        role = roles.get(name.lower()) or roles.get(name)
        if not role:
            role = instrument.replace("-", " ") if solo and instrument not in ("unknown", "other") else "performer"
        performers.append({"name": name, "role": role})
    rec = {
        "id": "",
        "performers": performers,
        "instrument": instrument,
        "performance_practice": "historical" if instrument in HISTORICAL else "unknown",
        "arrangement": instrument not in CELLO_FAMILY,
        "recorded": {"years": Flow(sorted(perf["years"])), "place": "; ".join(dict.fromkeys(perf["places"])) or None},
        "released": year(perf.get("firstRelease")),
        "original_label": None,
        "works": works_block(perf, moves),
        "links": mb_links(perf),
        "status": "draft",
        "musicbrainz": {"artist": perf["ids"][0], "recordings": Flow(sorted(perf["recIds"]))},
        "help_wanted": [],
        "notes": "Live recording." if perf.get("live") else None,
    }
    if rec["arrangement"]:
        rec["arranger"] = None
        if instrument == "other" and perf["ins"]:
            rec["notes"] = ((rec["notes"] or "") + f" Played on {', '.join(perf['ins'][:3])}.").strip()
    rec["help_wanted"] = help_items(rec, same_performer)
    return rec


def merge(old: dict, new: dict) -> dict:
    """Fill gaps in an existing file from MusicBrainz without overwriting anything."""
    out = dict(old)
    out["recorded"] = dict(old.get("recorded") or {})
    years = out["recorded"].get("years") or new["recorded"]["years"]
    out["recorded"]["years"] = Flow(years)
    if not out["recorded"].get("place"):
        out["recorded"]["place"] = new["recorded"]["place"]
    if out.get("released") is None:
        out["released"] = new["released"]
    if out.get("instrument") in (None, "unknown") and new["instrument"] != "unknown":
        out["instrument"] = new["instrument"]
    out["works"] = [FlowDict(w, **({"movements": Flow(w["movements"])} if "movements" in w else {})) for w in old["works"]]
    urls = {l["url"] for l in old["links"]}
    out["links"] = list(old["links"]) + [l for l in new["links"] if l["url"] not in urls]
    mb = dict(old.get("musicbrainz") or {})
    mb.setdefault("artist", new["musicbrainz"]["artist"])
    mb["recordings"] = Flow(sorted(set(mb.get("recordings", [])) | set(new["musicbrainz"]["recordings"])))
    out["musicbrainz"] = mb
    answered = []
    if out["recorded"]["years"]:
        answered += ["recording year", "recording dates", "recording and release year", "same performance"]
    if out["recorded"].get("place"):
        answered += ["place"]
    if out.get("instrument") not in (None, "unknown"):
        answered += ["instrument (musicbrainz"]
    out["help_wanted"] = [h for h in old.get("help_wanted") or [] if not any(a in h.lower() for a in answered)]
    return out


def order(rec: dict) -> dict:
    keys = ["id", "performers", "instrument", "performance_practice", "arrangement", "arranger", "recorded",
            "released", "original_label", "works", "links", "status", "help_wanted", "notes", "musicbrainz"]
    return {k: rec[k] for k in keys if k in rec}


def main(snapshot: str) -> int:
    rows = json.loads(Path(snapshot).read_text(encoding="utf-8"))
    perfs = [expand(c) for c in rows if c["rep"] not in EXCLUDE and UNKNOWN_ARTIST not in c["a"]]
    moves = movement_names()
    existing = {p: r for p, r in load("recordings")}
    by_mbid = {m: p for p, r in existing.items() for m in (r.get("musicbrainz") or {}).get("recordings", [])}

    per_performer: dict[str, int] = {}
    for perf in perfs:
        per_performer[norm(perf["names"][0])] = per_performer.get(norm(perf["names"][0]), 0) + 1

    used_paths: set[Path] = set()
    results = []
    for perf in perfs:
        main_name = norm(perf["names"][0])
        new = from_perf(perf, moves, per_performer[main_name])
        target = next((by_mbid[m] for m in perf["recIds"] if m in by_mbid), None)
        if target is None:
            for path, r in existing.items():
                if path in used_paths or r.get("musicbrainz") or norm(r["performers"][0]["name"]) != main_name:
                    continue
                ys = (r.get("recorded") or {}).get("years") or []
                rel = r.get("released")
                if ys and perf["years"] and set(ys) & set(perf["years"]):
                    target = path
                elif not ys and rel and perf["years"] and abs(min(perf["years"]) - rel) <= 1:
                    target = path
                elif not ys and not rel and per_performer[main_name] == 1:
                    target = path
                if target:
                    break
        if target is not None:
            results.append((target, merge(existing[target], new)))
            used_paths.add(target)
        else:
            results.append((None, new))

    untouched = [p for p in existing if p not in used_paths]
    taken = {p.stem: 1 for p in untouched}
    out_dir = DATA / "recordings"
    for target, rec in results:
        ys = rec["recorded"]["years"]
        stem = f"{slug_for(rec)}-{min(ys)}" if ys else f"{slug_for(rec)}-undated"
        n = taken.get(stem, 0) + 1
        taken[stem] = n
        rec["id"] = stem if n == 1 else f"{stem}-{n}"
        path = out_dir / f"{rec['id']}.yaml"
        if target is not None and target != path:
            target.unlink()
        with path.open("w", encoding="utf-8") as fh:
            yaml.dump(order(rec), fh, Dumper=_dumper(), allow_unicode=True, sort_keys=False, width=110)

    merged = sum(1 for t, _ in results if t is not None)
    print(f"{len(rows) - len(perfs)} rows skipped (see EXCLUDE), {merged} existing files updated, "
          f"{len(results) - merged} new files, untouched: {[p.name for p in untouched]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
