#!/usr/bin/env python3
"""Check every data file before it is merged.

Usage:  python scripts/validate.py

Exits with status 1 if any error is found, so it can run in CI.
Warnings are printed but do not fail the check.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SCHEMA = ROOT / "schema"

PLATFORM_HOSTS = {
    "spotify": {"open.spotify.com"},
    "apple-music": {"music.apple.com", "classical.music.apple.com"},
    "youtube": {"www.youtube.com", "youtube.com", "youtu.be"},
    "youtube-music": {"music.youtube.com"},
    "idagio": {"app.idagio.com", "www.idagio.com"},
    "qobuz": {"www.qobuz.com", "open.qobuz.com", "play.qobuz.com"},
    "tidal": {"tidal.com", "listen.tidal.com"},
    "deezer": {"www.deezer.com", "deezer.com"},
    "presto": {"www.prestomusic.com"},
    "archive-org": {"archive.org"},
    "musicbrainz": {"musicbrainz.org"},
}
TRACKING_PARAMS = ("utm_", "si", "nap_web", "go", "request_id", "fbclid", "gclid")


def bwv_to_filename(bwv: str) -> str:
    """'1007' -> '1007', '1046a' -> '1046a', 'Anh. 3' -> 'anh-3'."""
    return bwv.lower().replace("anh. ", "anh-").replace("anh.", "anh-").replace(" ", "-")


def load(kind: str) -> list[tuple[Path, dict]]:
    items = []
    for path in sorted((DATA / kind).glob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            items.append((path, yaml.safe_load(fh)))
    return items


def bwv_sort_key(bwv: str):
    """Sort numerically, appendix numbers last: 1007 < 1046 < 1046a < Anh. 3."""
    s = bwv.lower()
    appendix = s.startswith("anh")
    digits = "".join(c for c in s if c.isdigit() or c == ".").strip(".")
    num = float(digits.split(".")[0]) if digits else 0
    suffix = "".join(c for c in s.split()[-1] if c.isalpha()) if not appendix else ""
    return (appendix, num, suffix)


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    work_schema = Draft202012Validator(json.loads((SCHEMA / "work.schema.json").read_text()))
    rec_schema = Draft202012Validator(json.loads((SCHEMA / "recording.schema.json").read_text()))

    works = load("works")
    recordings = load("recordings")

    # --- works -------------------------------------------------------------
    by_bwv: dict[str, dict] = {}
    for path, w in works:
        name = path.relative_to(ROOT)
        if not isinstance(w, dict):
            errors.append(f"{name}: file is empty or not a mapping")
            continue
        for e in work_schema.iter_errors(w):
            errors.append(f"{name}: {'/'.join(map(str, e.path)) or '(top)'}: {e.message}")
        bwv = w.get("bwv")
        if not isinstance(bwv, str):
            continue
        if path.stem != bwv_to_filename(bwv):
            errors.append(f"{name}: file should be named {bwv_to_filename(bwv)}.yaml for BWV {bwv}")
        if bwv in by_bwv:
            errors.append(f"{name}: BWV {bwv} is defined twice")
        if "TODO" in str(w.get("scoring")) or "TODO" in str(w.get("title")):
            errors.append(f"{name}: work stub not filled in yet (title and scoring are still TODO)")
        by_bwv[bwv] = w

    for path, w in works:
        if isinstance(w, dict) and w.get("variant_of") and w["variant_of"] not in by_bwv:
            errors.append(f"{path.relative_to(ROOT)}: variant_of BWV {w['variant_of']} has no work file")

    # --- recordings --------------------------------------------------------
    ids: set[str] = set()
    seen_urls: dict[str, str] = {}
    for path, r in recordings:
        name = path.relative_to(ROOT)
        if not isinstance(r, dict):
            errors.append(f"{name}: file is empty or not a mapping")
            continue
        for e in rec_schema.iter_errors(r):
            errors.append(f"{name}: {'/'.join(map(str, e.path)) or '(top)'}: {e.message}")
        rid = r.get("id")
        if rid != path.stem:
            errors.append(f"{name}: id '{rid}' must match the file name '{path.stem}'")
        if rid in ids:
            errors.append(f"{name}: id '{rid}' is used twice")
        ids.add(rid)

        for item in r.get("works", []) or []:
            bwv = item.get("bwv")
            work = by_bwv.get(bwv)
            if work is None:
                errors.append(f"{name}: BWV {bwv} has no work file in data/works/ (add it first)")
                continue
            if item.get("complete") is False:
                moves = item.get("movements") or []
                if not moves:
                    errors.append(f"{name}: BWV {bwv} is marked incomplete; list the movements included")
                unknown = [m for m in moves if m not in work.get("movements", [])]
                if unknown:
                    errors.append(f"{name}: BWV {bwv}: unknown movement(s) {unknown}; use the names in data/works/{bwv_to_filename(bwv)}.yaml")
            elif item.get("movements"):
                warnings.append(f"{name}: BWV {bwv} is complete, so 'movements' is ignored")

        for link in r.get("links", []) or []:
            url = link.get("url", "")
            parsed = urlparse(url)
            hosts = PLATFORM_HOSTS.get(link.get("platform"))
            if hosts and parsed.hostname not in hosts:
                errors.append(f"{name}: {url} does not look like a {link.get('platform')} link")
            params = parse_qs(parsed.query)
            tracking = [p for p in params if p.startswith(TRACKING_PARAMS[0]) or p in TRACKING_PARAMS[1:]]
            if tracking:
                errors.append(f"{name}: remove tracking parameters {tracking} from {url}")
            clean = f"{parsed.hostname}{parsed.path}".rstrip("/")
            if clean in seen_urls and seen_urls[clean] != rid and link.get("platform") != "musicbrainz":
                warnings.append(f"{name}: link {url} is also used by '{seen_urls[clean]}'; check these are different performances")
            seen_urls[clean] = rid

        if r.get("status") == "reviewed" and r.get("help_wanted"):
            warnings.append(f"{name}: marked reviewed but still lists help_wanted items")
        if r.get("status") == "reviewed" and r.get("arrangement") and not r.get("arranger"):
            warnings.append(f"{name}: arrangement without an arranger")

    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error:   {e}")
    print(f"\n{len(by_bwv)} works, {len(ids)} recordings: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
