#!/usr/bin/env python3
"""Turn a MusicBrainz snapshot into recording files, merging with existing ones.

Usage:  python scripts/import_musicbrainz.py data/sources/<snapshot>.json

A snapshot lists *performances*: MusicBrainz recordings grouped by performer
and recording year (see data/sources/README.md for how they were made). It is
either a bare list of rows (the first snapshot, the Cello Suites) or
{"works": [BWV, ...], "native": [instrument, ...], "rows": [...]}, where
"works" gives the order of the movement masks and "native" the instruments
the music was written for (anything else counts as an arrangement).

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

CELLO_SUITES = ["1007", "1008", "1009", "1010", "1011", "1012"]
ALIASES = {"pau casals": "pablo casals"}

# MusicBrainz "[unknown]" artist: no performer to file the recording under.
UNKNOWN_ARTIST = "125ec42a-7229-4250-afc5-e057484327fe"
NO_ARTIST = "eec63d3c-3b81-4ad4-b1e4-7c147d4d2b61"  # MusicBrainz "[no artist]"

# Recordings MusicBrainz links to a collection's works that are not performances of them, per snapshot
# (data/sources/musicbrainz-<id>.json), keyed by representative recording ID, with the reason. Scoped by
# snapshot because a recording mislinked to one collection is often a real performance of another.
# Fix upstream in MusicBrainz too, then remove the entry here.
EXCLUDE_BY_SNAPSHOT = {
  "cello-suites": {
    "04f657f2-dbb1-4b2a-8c4b-e96a1e4f4080": "release is the Orchestral Suites BWV 1066-1069",
    "91db1c6e-aa80-4cfc-8ef5-50639f20bc1e": "release is Rameau's harpsichord works",
    "a81b39e1-c432-4893-a829-295bfd14ae80": "release is orchestral suites by other composers",
    "9cb32a24-055a-4bb5-aa3d-d5e37830ef5a": "release is trio sonatas",
    "0e978aec-44f7-4839-9f8a-d50b3af73f50": "accompaniment-only track of the Burrowes recording",
    "b0554f83-50e2-4505-8a48-628c6dc792c8": "magazine lesson disc, not a performance",
  },
  "violin-solo": {
    "ce8bd6ab-9ac8-497b-9a92-000f6f5440fd": "Bach's own keyboard versions (BWV 964/968), which have their own BWV numbers",
    "631731fb-8ba3-439c-90de-8ba0d8b397c6": "release is a keyboard partita",
    "30537d65-f1fe-4f4b-93f1-f83c2e106151": "release is Schubert and Mozart",
    "60c1ace9-813b-40ff-a960-0b4029adc451": "release is the sonatas for violin and keyboard",
  },
  "orchestral-suites": {
    "8580bc9d-bfdc-4e33-a087-acd8e8497e2c": "release is the keyboard Partitas (a Partita movement linked to the suites)",
  },
}
EXCLUDE: dict[str, str] = {}  # the current snapshot's entries, set in main()

INSTRUMENTS = {
    "cello": "cello", "violoncello": "cello",
    "baroque cello": "baroque-cello", "baroque violoncello": "baroque-cello",
    "violoncello piccolo": "violoncello-piccolo", "five-string cello": "violoncello-piccolo",
    "violoncello da spalla": "violoncello-da-spalla", "viola da spalla": "violoncello-da-spalla",
    "viola": "viola", "viola da gamba": "viola-da-gamba", "violin": "violin",
    "baroque violin": "baroque-violin",
    "guitar": "guitar", "classical guitar": "guitar", "acoustic guitar": "guitar",
    "lute": "lute", "harpsichord": "harpsichord", "piano": "piano", "grand piano": "piano",
    "organ": "organ", "pipe organ": "organ", "clavichord": "clavichord", "fortepiano": "fortepiano",
    "harpsichord / cembalo": "harpsichord", "cembalo": "harpsichord",
    "lautenwerck": "harpsichord", "lute-harpsichord": "harpsichord",
    "flute": "flute", "transverse flute": "flute", "concert flute": "flute",
    "baroque flute": "traverso", "traverso": "traverso", "flauto traverso": "traverso",
    "transverse flute (baroque)": "traverso", "recorder": "recorder", "alto recorder": "recorder",
    "treble recorder": "recorder", "oboe": "oboe", "baroque oboe": "oboe",
}
IMPLIED = {"1048": {1: [0, 2]}}
CELLO_FAMILY = ["cello", "baroque-cello", "violoncello-piccolo", "violoncello-da-spalla"]
HISTORICAL = {"baroque-cello", "violoncello-piccolo", "violoncello-da-spalla", "viola-da-gamba", "baroque-violin",
              "harpsichord", "clavichord", "fortepiano"}
MODERN = {"piano"}
KEYBOARD = ["harpsichord", "piano", "clavichord", "organ", "fortepiano"]
# Chamber mode: instruments that usually play the continuo, so a credit for one of them alone does not say
# what the solo part was played on.
CONTINUO = {"harpsichord", "piano", "organ", "fortepiano", "lute", "cello", "baroque-cello", "viola-da-gamba"}
HISTORICAL_LEAD = {"baroque-violin", "baroque-cello", "viola-da-gamba", "traverso", "recorder"}

# Orchestral and other ensemble works (snapshot native ["ensemble"]): the group plays; what needs
# working out is whether the group plays period instruments, and whether it is an arrangement.
GROUP_TYPES = {"Orchestra", "Group", "Choir"}
# Credits that only a period-instrument performance has.
PERIOD_INSTRUMENT = re.compile(r"baroque|natural (horn|trumpet)|corno da caccia|traverso|transverse flute \(baroque\)")
# Ensembles that play on period instruments. Matched against performer names, so it also
# catches them when MusicBrainz gives no instrument credits.
PERIOD_ENSEMBLE = re.compile(
    r"baroque|barock|barroc|baroc|antiqua|alte musik|ancient music|concentus musicus|leonhardt|collegium aureum|"
    r"petite bande|english concert|taverner|brandenburg consort|giardino armonico|concerto italiano|bach collegium|"
    r"europa galante|age of enlightenment|tafelmusik|concert des nations|zimmermann|dunedin consort|concerto copenhagen|"
    r"musiciens du louvre|zefiro|gardellino|b.rock|arcangelo|accademia bizantina|apollo.s fire|capriccio stravagante|"
    r"freiburger|netherlands bach society|nederlandse bachvereniging|pratum integrum|la stravaganza|collegium musicum 90|"
    r"orchestra of the antipodes|australian brandenburg|concerto k.ln|kammerakademie|cantus c.lln|il pomo d.oro|"
    r"les arts florissants|le concert d.astr.e|ensemble 415|harmonie universelle|sonnerie|la serenissima|"
    r"academy of ancient|monteverdi|english baroque|holland baroque|il complesso barocco|modo antiquo|ensemble 1700|"
    r"incogniti|florilegium|freitagsakademie|hanover band|musica florea|simphonie du marais|ensemble caprice|"
    r"wiener akademie|eighteenth century|new london consort|linde consort|schola cantorum basiliensis|musica amphion|"
    r"combattimento|harmony of nations|nova stravaganza|muses galantes|new dutch academy|magnifica comunit|"
    r"dantone|beznosiuk|barok|ensemble masques|les surprises|il fondamento|concert fran.ais|insula orchestra|"
    r"early music|voices of music|tulipa consort|trillium consort|apollon ensemble|american bach soloists|"
    r"ama deus|madeuf|blumenstock", re.I)
# Modern-instrument groups whose names would otherwise match PERIOD_ENSEMBLE or whose credits mention period instruments.
MODERN_ENSEMBLE = re.compile(r"m.nchener bach|zurich baroque ensemble|^baroque chamber orchestra|"
                             r"hamburg symphony baroque|festival baroque orchestra", re.I)
# Credits or names that mean the music was arranged for other forces (jazz trio, brass band, synthesizer …).
ARRANGED = re.compile(r"drum|saxophone|synthesi[sz]er|moog|electric|accordion|marimba|vibraphone|tuba|"
                      r"clarinet|banjo|mandolin|ukulele|harmonica|beatbox|bass guitar|guitar", re.I)
ARRANGED_NAMES = re.compile(r"brass|blechbl|\bsax(ophone)?\b|swingle|jazz|loussier|guitar|switched.on|synth|\bbeat\b|"
                            r"loeki|seldom sene|baby einstein|babies|sweet little band|pink mice|\bthe nice\b|"
                            r"\ble orme\b|softcore|camarata|mantovani|rond. veneziano|stringfever|colliery|crusaders|"
                            r"percussion|duckmandu|galliano|trombone|alfee|moorhouse|anugama|dan gibson|syrinx|"
                            r"early learning centre", re.I)
# In orchestral works only: names of groups that are not orchestras, so play the music arranged.
ARRANGED_GROUP_NAMES = re.compile(r"quartet|quartett|quatuor|quartetto|\bcellos\b|(?<!hanover )\bband\b|"
                                  r"trumpet ensemble|brass", re.I)
# Release titles that mean an arrangement (film and game soundtracks, lessons, nursery and relaxation albums).
ARRANGED_RELEASES = re.compile(r"soundtrack|learn to play|nursery|lullab|\bbaby\b|babies|bossa|switched.on|"
                               r"\bspa\b|for sleep|relaxation|meditation", re.I)


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


def expand(c: dict, bwvs: list[str], moves: dict[str, list[str]]) -> dict:
    """Snapshot rows are compact; turn one into the shape the importer works with.

    Row keys: n performer names, a artist MBIDs, y recording years, m one bitmask
    per work in snapshot order (bit i = movement i present), f first release year,
    l live, t artist types (Person, Orchestra …) in the order of a,
    ins instruments credited, roles {performer: instrument}, pl places
    recorded at, r [release MBID, title], rep representative recording MBID.
    """
    # Masks were built with JavaScript bitwise operators, which are signed 32-bit:
    # a work with 32 movements all present comes out as -1. Undo that.
    masks = [int(x) % 2**32 if int(x) < 0 else int(x) for x in c["m"].split(",")]
    mv = []
    for bwv, mask in zip(bwvs, masks):
        if mask >> len(moves[bwv]):
            raise SystemExit(f"Row {c['rep']}: BWV {bwv} has more movements in MusicBrainz than in data/works/{bwv}.yaml")
        names = moves[bwv]
        have = {i for i in range(len(names)) if mask >> i & 1}
        # Paired dances (Menuet I / Menuet II) are often one track in MusicBrainz,
        # linked only to the first: count the second as recorded too.
        have |= {i for i in range(1, len(names)) if names[i].endswith(" II") and names[i - 1] == names[i][:-1] and i - 1 in have}
        # Movements that rarely get a track of their own: the two-chord Adagio of Brandenburg
        # No. 3 is usually joined to a neighbouring track. Count it when both outer movements are there.
        for i, needs in IMPLIED.get(bwv, {}).items():
            if all(n in have for n in needs):
                have.add(i)
        mv += [f"{bwv}:{i}" for i in sorted(have)]
    return {
        "names": c["n"], "ids": c["a"], "types": c.get("t") or [], "years": c["y"], "mv": mv,
        "firstRelease": c.get("f"), "live": bool(c.get("l")),
        "ins": c.get("ins") or [], "roles": c.get("roles") or {},
        "places": c.get("pl") or [],
        "releases": [{"id": c["r"][0], "title": c["r"][1]}] if c.get("r") else [],
        "repId": c["rep"], "recIds": [c["rep"]],
    }


def instrument_of(perf: dict, native: set[str]) -> tuple[str, list[str], dict]:
    """Main instrument, other instruments credited, and per-performer roles.

    The main instrument is the first credited one the music was written for;
    failing that, the first credited instrument of any kind.
    """
    roles = {k: v.lower() for k, v in perf["roles"].items()}
    if not perf["ins"]:
        return "unknown", [], roles
    mapped = [(i, INSTRUMENTS.get(i.lower(), "other")) for i in perf["ins"]]
    main = next((m for _, m in mapped if m in native), None)
    if main is None and len({m for _, m in mapped}) >= 3:
        return "ensemble", [], roles  # a string trio or similar group arrangement
    main = main or mapped[0][1]
    main_label = next(i for i, m in mapped if m == main)
    others = [i for i, m in mapped if i != main_label and m != main]
    return main, others, roles


def in_scoring(instrument: str, scoring: str) -> bool:
    """Whether a credited instrument is one the work is written for (scoring text of data/works/)."""
    i, sc = instrument.lower(), scoring.lower()
    # Continuo keyboards count; plain "strings" does not, so a violinist or cellist alone on a suite (the Air
    # with piano) is a transcription, while the violinist named in a violin concerto's scoring is a soloist.
    if re.search(r"harpsichord|organ|cembalo", i) and "continuo" in sc:
        return True
    word = re.sub(r"^(baroque|natural|piccolo|transverse|french) ", "", i).split(" ")[0].rstrip("s")
    return bool(word) and word in sc


def ensemble_of(perf: dict, scoring: str = "") -> tuple[str, str, bool, list[str]]:
    """For an ensemble work: instrument, performance practice, arrangement, instruments to mention."""
    roles = {v.lower() for v in perf["roles"].values()}
    ins = [i.lower() for i in perf["ins"]]
    names = " ".join(perf["names"])
    group = (any(t in GROUP_TYPES for t in perf["types"]) or roles & {"conductor", "orchestra"}
             or len(perf["names"]) >= 3 or len(set(ins)) >= 3)
    arranged = [i for i in perf["ins"] if ARRANGED.search(i)]
    release = " ".join(r["title"] for r in perf["releases"])
    if (arranged or ARRANGED_NAMES.search(names) or "Choir" in perf["types"] or ARRANGED_RELEASES.search(release)
            or (scoring and ARRANGED_GROUP_NAMES.search(perf["names"][0]))):
        main = "ensemble" if group else (INSTRUMENTS.get(ins[0], "other") if ins else "unknown")
        return main, "unknown", True, arranged
    if group:
        period = (any(PERIOD_INSTRUMENT.search(i) for i in ins) or bool(PERIOD_ENSEMBLE.search(names))) \
            and not MODERN_ENSEMBLE.search(perf["names"][0])
        return "ensemble", "historical" if period else "unknown", False, []
    if ins:
        main = INSTRUMENTS.get(ins[0], "other")
        if scoring:
            # One or two players with credits: soloists named on a compilation when every instrument credited
            # is in the work's scoring (a trumpeter in Brandenburg No. 2); otherwise a transcription.
            if all(in_scoring(i, scoring) for i in ins) and not all(INSTRUMENTS.get(i) in KEYBOARD for i in ins):
                return "ensemble", "unknown", False, []
            return main, "unknown", True, []
        bwvs = {m.split(":")[0] for m in perf["mv"]}
        if main in KEYBOARD and bwvs - {"1050"}:
            return main, "unknown", True, []
        return "ensemble", "unknown", False, []
    return "unknown", "unknown", False, []


def works_block(perf: dict, bwvs: list[str], moves: dict[str, list[str]]) -> list:
    out = []
    have = set(perf["mv"])
    for bwv in bwvs:
        idx = [i for i in range(len(moves[bwv])) if f"{bwv}:{i}" in have]
        if not idx:
            continue
        if len(idx) == len(moves[bwv]):
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


TYPE_ROLE = {"Orchestra": "orchestra", "Choir": "choir", "Group": "ensemble"}


def is_group(perf: dict) -> bool:
    roles = {v.lower() for v in perf["roles"].values()}
    ins = {i.lower() for i in perf["ins"]}
    return bool(any(t in GROUP_TYPES for t in perf["types"]) or roles & {"conductor", "orchestra"}
                or len(perf["names"]) >= 3 or len(ins) >= 3)


def period_group(perf: dict) -> bool:
    return (any(PERIOD_INSTRUMENT.search(i.lower()) for i in perf["ins"])
            or bool(PERIOD_ENSEMBLE.search(" ".join(perf["names"])))) and not MODERN_ENSEMBLE.search(perf["names"][0])


def arranged_credits(perf: dict) -> list[str]:
    return [i for i in perf["ins"] if ARRANGED.search(i)]


def vocal_of(perf: dict) -> tuple[str, str, bool, list[str]]:
    """Vocal works: choir, orchestra and soloists are all native; only jazz, pop and the like are arrangements."""
    arranged = arranged_credits(perf)
    if arranged or ARRANGED_NAMES.search(" ".join(perf["names"])):
        return "voices-and-instruments", "unknown", True, arranged
    return "voices-and-instruments", "historical" if period_group(perf) else "unknown", False, []


def chamber_of(perf: dict, lead: list[str]) -> tuple[str, str, bool, list[str]]:
    """Chamber works: `lead` is the solo part's instrument family, the written instrument first.

    Another orchestral instrument on the solo part (cello for gamba, recorder for flute) is filed as that
    instrument, not as an arrangement; keyboard and other continuo credits alone don't name the solo part.
    """
    arranged = arranged_credits(perf)
    if arranged or ARRANGED_NAMES.search(" ".join(perf["names"])):
        return ("ensemble" if is_group(perf) else INSTRUMENTS.get(arranged[0].lower(), "other") if arranged else "unknown",
                "unknown", True, arranged)
    mapped = [INSTRUMENTS.get(i.lower(), "other") for i in perf["ins"]]
    if lead == ["ensemble"]:
        main = "ensemble"
    else:
        main = next((m for m in mapped if m in lead), None) \
            or next((m for m in mapped if m not in CONTINUO and m != "other"), None) \
            or (lead[0] if perf["ins"] or len(perf["names"]) > 1 else "unknown")
    practice = ("historical" if main in HISTORICAL_LEAD or period_group(perf)
                else "modern" if "piano" in mapped else "unknown")
    return main, practice, False, []


def from_perf(perf: dict, bwvs: list[str], moves: dict[str, list[str]], native: set[str], same_performer: int,
              mode: str = "classic", lead: list[str] | None = None, scoring: str | None = None) -> dict:
    ensemble_work = mode in ("ensemble", "vocal", "chamber") or (mode == "open" and is_group(perf))
    if ensemble_work:
        instrument, practice, arranged, mention = (
            vocal_of(perf) if mode == "vocal" else chamber_of(perf, lead or []) if mode == "chamber"
            else ensemble_of(perf, scoring or ""))
        others, roles = [], {k: v.lower() for k, v in perf["roles"].items()}
    else:
        instrument, others, roles = instrument_of(perf, native)
        if mode == "organ" and instrument == "unknown" and len(perf["names"]) == 1:
            instrument = "organ"  # a lone performer of an organ work, with no instrument credit
        if mode == "open":
            others = [i for i in others if ARRANGED.search(i)]
    solo = len(perf["names"]) == 1
    performers = []
    types = perf.get("types") or []
    for i, name in enumerate(perf["names"]):
        role = roles.get(name.lower()) or roles.get(name)
        if not role and i < len(types) and types[i] in TYPE_ROLE:
            role = TYPE_ROLE[types[i]]
        if not role:
            role = instrument.replace("-", " ") if solo and instrument not in ("unknown", "other", "ensemble") else "performer"
        performers.append({"name": name, "role": role})
    rec = {
        "id": "",
        "performers": performers,
        "instrument": instrument,
        "performance_practice": "historical" if instrument in HISTORICAL else "modern" if instrument in MODERN else "unknown",
        "arrangement": instrument not in native | {"unknown"} or bool(others),
        "recorded": {"years": Flow(sorted(perf["years"])), "place": "; ".join(dict.fromkeys(perf["places"])) or None},
        "released": year(perf.get("firstRelease")),
        "original_label": None,
        "works": works_block(perf, bwvs, moves),
        "links": mb_links(perf),
        "status": "draft",
        "musicbrainz": {"artist": perf["ids"][0], "recordings": Flow(sorted(perf["recIds"]))},
        "help_wanted": [],
        "notes": "Live recording." if perf.get("live") else None,
    }
    if ensemble_work:
        rec["performance_practice"] = practice
        rec["arrangement"] = arranged
        others = mention
    elif mode == "open":
        rec["arrangement"] = instrument == "other" and bool(arranged_credits(perf)) \
            or bool(ARRANGED_NAMES.search(" ".join(perf["names"])))
    elif mode == "lute" and instrument == "guitar":
        rec["performance_practice"] = "modern"  # decided 28 Oct 2026: guitar is native for the lute works
    elif mode == "lute" and instrument == "lute":
        rec["performance_practice"] = "historical"
    if rec["arrangement"]:
        rec["arranger"] = None
        if instrument == "other" and perf["ins"]:
            rec["notes"] = ((rec["notes"] or "") + f" Played on {', '.join(perf['ins'][:3])}.").strip()
        elif others:
            rec["notes"] = ((rec["notes"] or "") + f" With {', '.join(others[:3])}.").strip()
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
    data = json.loads(Path(snapshot).read_text(encoding="utf-8"))
    EXCLUDE.clear()
    EXCLUDE.update(EXCLUDE_BY_SNAPSHOT.get(Path(snapshot).stem.removeprefix("musicbrainz-"), {}))
    if isinstance(data, list):
        data = {"works": CELLO_SUITES, "native": CELLO_FAMILY, "rows": data}
    bwvs, native, rows = data["works"], set(data["native"]), data["rows"]
    # Importer mode (docs/catalogue-plan.md): older snapshots have none; "ensemble" was then the native list.
    mode = data.get("mode") or ("ensemble" if "ensemble" in native else "classic")
    lead = data["native"] if mode == "chamber" else None
    # Scoring of the works, for telling soloists from transcriptions in orchestral works. Snapshots from the
    # browser collector (no "mode" key) keep their original rules, so re-importing them changes nothing.
    scorings = {w["bwv"]: w.get("scoring") or "" for _, w in load("works")}
    scoring = " ".join(scorings.get(b, "") for b in bwvs) if data.get("mode") == "ensemble" else None
    moves = movement_names()
    missing = [b for b in bwvs if b not in moves]
    if missing:
        raise SystemExit(f"Add work files for BWV {', '.join(missing)} before importing")
    perfs = [expand(c, bwvs, moves) for c in rows if c["a"] and c["rep"] not in EXCLUDE and UNKNOWN_ARTIST not in c["a"]
             and NO_ARTIST not in c["a"]]
    existing = {p: r for p, r in load("recordings")}
    by_mbid = {m: p for p, r in existing.items() for m in (r.get("musicbrainz") or {}).get("recordings", [])}

    per_performer: dict[str, int] = {}
    for perf in perfs:
        per_performer[norm(perf["names"][0])] = per_performer.get(norm(perf["names"][0]), 0) + 1

    used_paths: set[Path] = set()
    results = []
    for perf in perfs:
        main_name = norm(perf["names"][0])
        new = from_perf(perf, bwvs, moves, native, per_performer[main_name], mode, lead, scoring)
        target = next((by_mbid[m] for m in perf["recIds"] if m in by_mbid), None)
        if target is None:
            for path, r in existing.items():
                if path in used_paths or r.get("musicbrainz") or norm(r["performers"][0]["name"]) != main_name:
                    continue
                if not {w["bwv"] for w in r["works"]} & set(bwvs):
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

    # File names: <performer>-<year>, then -2, -3 … for clashes. Names already on disk are never
    # reused, including those from other snapshots, and a matched file keeps its name when it still fits.
    untouched = [p for p in existing if p not in used_paths]
    occupied = {p.stem for p in untouched}
    stems = []
    for target, rec in results:
        ys = rec["recorded"]["years"]
        stems.append(f"{slug_for(rec)}-{min(ys)}" if ys else f"{slug_for(rec)}-undated")
    ids: list[str | None] = [None] * len(results)
    for i, ((target, rec), stem) in enumerate(zip(results, stems)):
        if target is not None and target.stem not in occupied and re.fullmatch(re.escape(stem) + r"(-\d+)?", target.stem):
            ids[i] = target.stem
            occupied.add(target.stem)
    for i, stem in enumerate(stems):
        if ids[i] is None:
            n = 1
            while (stem if n == 1 else f"{stem}-{n}") in occupied:
                n += 1
            ids[i] = stem if n == 1 else f"{stem}-{n}"
            occupied.add(ids[i])
    out_dir = DATA / "recordings"
    for (target, rec), rid in zip(results, ids):
        rec["id"] = rid
        path = out_dir / f"{rec['id']}.yaml"
        if target is not None and target != path:
            target.unlink()
        with path.open("w", encoding="utf-8") as fh:
            yaml.dump(order(rec), fh, Dumper=_dumper(), allow_unicode=True, sort_keys=False, width=110)

    merged = sum(1 for t, _ in results if t is not None)
    unmatched = [p.name for p in untouched if {w["bwv"] for w in existing[p]["works"]} & set(bwvs)
                 and not existing[p].get("musicbrainz")]
    print(f"{len(rows) - len(perfs)} rows skipped (see EXCLUDE), {merged} existing files updated, "
          f"{len(results) - merged} new files; hand-made files for these works not matched: {unmatched}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
