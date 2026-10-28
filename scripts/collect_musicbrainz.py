#!/usr/bin/env python3
"""Collect a MusicBrainz snapshot for one or more collections of data/plan/collections.yaml.

Runs on GitHub Actions (Claude's workspace cannot reach MusicBrainz), at about one request per second.

    python scripts/collect_musicbrainz.py --queued                 # every collection with status: queued
    python scripts/collect_musicbrainz.py --collection brandenburg  # one collection, whatever its status

For each finished collection it writes, under --out (default .mbcache/out/<id>/):
    musicbrainz-<id>.json   the snapshot, rows as described in data/sources/README.md
    tree-<id>.json          the MusicBrainz works found for each BWV number, with their movements,
                            for scripts/work_stub.py and for review
Progress is saved in .mbcache/state-<id>.json after every few requests, so a run that stops at its time
budget continues where it left off the next time.

This is a port of scripts/musicbrainz-collect.js (the browser collector used for the first five
collections). The grouping and the row format are the same; what is new:
- works are found by BWV number when the collection has no MusicBrainz parent work (`mb_parent`);
- movements that have movements of their own (a mass's Gloria) are followed down to the last level;
- recordings linked to the whole work rather than to its movements count as complete performances,
  unless --no-whole is given;
- "vocal" relations keep the voice type (soprano, tenor …).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
BACH = "24f1766e-9635-4d58-a4d4-9413f9f98a4c"
API = "https://musicbrainz.org/ws/2/"
UA = "AllBach/0.2 ( https://github.com/glima93/all-bach )"
GROUPS = ["Orchestra", "Group", "Choir"]
# Modes whose performances are grouped by the orchestra, ensemble or choir when one is credited.
GROUPED_MODES = {"ensemble", "vocal", "chamber", "open"}
NATIVE = {
    "ensemble": ["ensemble"],
    "vocal": ["voices-and-instruments"],
    "keyboard": ["harpsichord", "piano", "clavichord", "organ", "fortepiano"],
    "organ": ["organ"],
    "lute": ["lute", "guitar", "harpsichord"],
    "chamber": [],   # set per collection: `native` in collections.yaml, lead instrument first
    "open": ["ensemble", "harpsichord", "piano", "clavichord", "organ", "fortepiano", "viola-da-gamba",
             "violin", "viola", "cello"],
    "solo": [],
}

session = requests.Session()
session.headers["User-Agent"] = UA
_last = [0.0]


class OutOfTime(Exception):
    pass


class Collector:
    def __init__(self, cid: str, state_dir: Path, deadline: float, whole: bool):
        self.cid, self.deadline, self.whole = cid, deadline, whole
        self.path = state_dir / f"state-{cid}.json"
        self.s = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.unsaved = 0

    def save(self, force: bool = False) -> None:
        self.unsaved += 1
        if force or self.unsaved >= 20:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.s, ensure_ascii=False))
            self.unsaved = 0

    def mb(self, path: str) -> dict:
        """One API call; waits so calls are at least 1.1 s apart, backs off on 503 for several minutes."""
        if time.time() > self.deadline:
            self.save(force=True)
            raise OutOfTime
        url = API + path + ("&" if "?" in path else "?") + "fmt=json"
        for i in range(20):
            gap = time.time() - _last[0]
            if gap < 1.1:
                time.sleep(1.1 - gap)
            try:
                r = session.get(url, timeout=60)
            except requests.RequestException:
                r = None
            _last[0] = time.time()
            if r is not None and r.ok:
                return r.json()
            if r is not None and r.status_code == 404:
                raise LookupError("404 " + path)
            time.sleep(min(60, 3 * (i + 1)))
        raise RuntimeError("MusicBrainz request failed: " + path)

    def cached(self, key: str, fn):
        if key not in self.s:
            self.s[key] = fn()
            self.save()
        return self.s[key]

    # ── finding the works ───────────────────────────────────────────────────────────────
    def work(self, wid: str) -> dict:
        def get():
            w = self.mb(f"work/{wid}?inc=work-rels")
            rels = w.get("relations") or []
            parts = sorted((r for r in rels if r["type"] == "parts" and r["direction"] == "forward"),
                           key=lambda r: (r.get("ordering-key") is None, r.get("ordering-key") or 0))
            key = next((a["value"] for a in w.get("attributes") or [] if a.get("type") == "Key"), None)
            return {
                "id": wid, "title": w["title"], "disambiguation": w.get("disambiguation") or "", "key": key,
                "parts": [{"id": r["work"]["id"], "title": r["work"]["title"]} for r in parts],
                "arrangement_of": [r["work"]["id"] for r in rels if r["type"] == "arrangement" and r["direction"] == "backward"],
                "part_of": [r["work"]["id"] for r in rels if r["type"] == "parts" and r["direction"] == "backward"
                            and "part of collection" not in (r.get("attributes") or [])],
            }
        return self.cached("work:" + wid, get)

    def leaves(self, wid: str, depth: int = 0) -> list[dict]:
        """The movements to collect: parts of parts, down to works with no parts of their own."""
        w = self.work(wid)
        if not w["parts"] or depth >= 3:
            return [{"id": w["id"], "title": w["title"]}]
        out = []
        for p in w["parts"]:
            out += self.leaves(p["id"], depth + 1)
        return out

    def find(self, bwv: str) -> dict:
        """The MusicBrainz work for one BWV number: searched by title, arrangements and movements dropped,
        the candidate with the most movements kept. Every candidate is recorded for review."""
        def get():
            q = f'"BWV {bwv}" AND arid:{BACH}'
            res = self.mb("work?query=" + requests.utils.quote(q) + "&limit=25")
            pat = re.compile(rf"BWV\s*{bwv}(?![0-9a-z./])", re.I)
            cands = []
            for w in res.get("works") or []:
                m = pat.search(w["title"])
                if not m or ":" in w["title"][m.end():]:
                    continue
                cands.append({"id": w["id"], "title": w["title"], "score": w.get("score", 0)})
            return cands[:6]
        cands = self.cached("search:" + bwv, get)
        kept = []
        for c in cands:
            w = self.work(c["id"])
            if w["arrangement_of"] or w["part_of"] or re.search(r"\barr\b|arrang|transcri|bearb", w["disambiguation"], re.I):
                continue
            kept.append((len(w["parts"]), c["score"], c["id"]))
        kept.sort(key=lambda k: (-k[0], -k[1]))
        return {"bwv": bwv, "id": kept[0][2] if kept else None,
                "candidates": [{"id": c["id"], "title": c["title"]} for c in cands],
                "ambiguous": len(kept) > 1 and kept[0][:2] == kept[1][:2]}

    def tree(self, col: dict) -> list[dict]:
        """[{bwv, id, title, key, movements: [{id, title}], …}] in BWV order; works not in MusicBrainz are left out."""
        out = []
        if col.get("mb_parent"):
            parent = self.work(col["mb_parent"])
            for p in parent["parts"]:
                m = re.search(r"BWV\s*(\d+[a-z]?)", p["title"])
                out.append({"bwv": m.group(1) if m else p["title"], "id": p["id"], "candidates": [], "ambiguous": False})
        else:
            for spec in col["bwv"]:
                lo, _, hi = spec.partition("-")
                for n in range(int(lo), int(hi or lo) + 1):
                    out.append(self.find(str(n)))
        works = []
        for f in out:
            if not f["id"]:
                continue
            w = self.work(f["id"])
            works.append({**f, "title": w["title"], "key": w["key"], "has_parts": bool(w["parts"]),
                          "movements": self.leaves(f["id"])})
        return works

    # ── collecting the recordings ───────────────────────────────────────────────────────
    def recordings(self, wid: str) -> list[list]:
        """Every recording linked to one work: [id, artist ids, names, types, year, last year, live, first release]."""
        def get():
            w = self.mb(f"work/{wid}?inc=recording-rels")
            rel = {}
            for r in w.get("relations") or []:
                if r["type"] != "performance" or not r.get("recording"):
                    continue
                ys = [y for y in (year_of(r.get("begin")), year_of(r.get("end"))) if y]
                rel[r["recording"]["id"]] = (min(ys) if ys else None, max(ys) if ys else None,
                                             1 if "live" in (r.get("attributes") or []) else 0)
            out, off = [], 0
            while True:
                b = self.mb(f"recording?work={wid}&inc=artist-credits&limit=100&offset={off}")
                for r in b.get("recordings") or []:
                    ac = [c for c in r.get("artist-credit") or [] if c["artist"]["id"] != BACH]
                    y, y2, live = rel.get(r["id"], (None, None, 0))
                    out.append([r["id"], [c["artist"]["id"] for c in ac], [c["name"] for c in ac],
                                [c["artist"].get("type") or "" for c in ac], y, y2, live,
                                year_of(r.get("first-release-date"))])
                off += 100
                if off >= b.get("recording-count", 0):
                    return out
        return self.cached("rec:" + wid, get)

    def detail(self, rid: str) -> dict:
        def get():
            r = self.mb(f"recording/{rid}?inc=artist-rels+place-rels+releases")
            ins, roles, pl = [], {}, []
            for x in r.get("relations") or []:
                if x.get("target-type") == "artist" and x.get("artist"):
                    name = x["artist"]["name"]
                    if x["type"] == "instrument":
                        for i in x.get("attributes") or []:
                            if i not in ins:
                                ins.append(i)
                            roles.setdefault(name, i)
                    elif x["type"] == "conductor":
                        roles[name] = "conductor"
                    elif x["type"] == "performing orchestra":
                        roles[name] = "orchestra"
                    elif x["type"] == "vocal":
                        voice = next((a for a in x.get("attributes") or [] if a not in ("additional", "guest", "solo")), "voice")
                        roles.setdefault(name, re.sub(r" vocals?$", "", voice))
                if x.get("target-type") == "place" and x.get("place") and x["type"] == "recorded at":
                    pl.append(x["place"]["name"])
            rels = r.get("releases") or []
            official = sorted((x for x in rels if x.get("status") in ("Official", None)),
                              key=lambda x: x.get("date") or "9999")
            rel = official[0] if official else (rels[0] if rels else None)
            return {"ins": ins, "roles": roles, "pl": pl, "r": [rel["id"], rel["title"]] if rel else None}
        return self.cached("det:" + rid, get)


def year_of(d) -> int | None:
    return int(d[:4]) if d and re.match(r"^\d{4}", d) else None


def group(works: list[dict], recs_by_leaf, whole_recs, grouped: bool) -> list[dict]:
    """Performances, exactly as musicbrainz-collect.js groups them (see data/sources/README.md)."""
    recs: dict[str, dict] = {}

    def add(row, wi, pis):
        rid, a, n, t, y, y2, live, f = row
        e = recs.setdefault(rid, {"id": rid, "a": a, "n": n, "t": t, "ys": [], "l": 0, "f": None, "mv": []})
        for yy in (y, y2):
            if yy and yy not in e["ys"]:
                e["ys"].append(yy)
        e["l"] = e["l"] or live
        if f and (not e["f"] or f < e["f"]):
            e["f"] = f
        for pi in pis:
            if f"{wi}:{pi}" not in e["mv"]:
                e["mv"].append(f"{wi}:{pi}")

    for wi, w in enumerate(works):
        for pi, mvt in enumerate(w["movements"]):
            for row in recs_by_leaf(mvt["id"]):
                add(row, wi, [pi])
        for row in whole_recs(w):
            add(row, wi, range(len(w["movements"])))

    def key(r):
        g = [x for x, t in zip(r["a"], r["t"]) if t in GROUPS] if grouped else []
        return "+".join(sorted(g or r["a"])) or "?" + "+".join(r["n"])

    by_artist: dict[str, list] = {}
    for r in recs.values():
        by_artist.setdefault(key(r), []).append(r)
    perfs = []
    for lst in by_artist.values():
        dated: dict[int, list] = {}
        undated = []
        for r in lst:
            if r["ys"]:
                dated.setdefault(min(r["ys"]), []).append(r)
            else:
                undated.append(r)
        groups = []
        for y in sorted(dated):
            rs = dated[y]
            groups.append({"rs": list(rs), "ys": ordered({yy for r in rs for yy in r["ys"]}, rs, "ys"),
                           "mv": ordered(None, rs, "mv")})
        i = 1
        while i < len(groups):
            a, b = groups[i - 1], groups[i]
            if min(b["ys"]) - max(a["ys"]) <= 3 and not set(b["mv"]) & set(a["mv"]):
                a["rs"] += b["rs"]
                a["ys"] += [y for y in b["ys"] if y not in a["ys"]]
                a["mv"] += [m for m in b["mv"] if m not in a["mv"]]
                groups.pop(i)
            else:
                i += 1
        und_mv = ordered(None, undated, "mv")
        home = [g for g in groups if all(m in g["mv"] for m in und_mv)]
        if undated and len(home) == 1:
            home[0]["rs"] += undated
            home[0]["mv"] += [m for m in und_mv if m not in home[0]["mv"]]
        elif undated:
            groups.append({"rs": undated, "ys": [], "mv": und_mv})
        perfs += groups

    out = []
    for g in perfs:
        seen: dict[str, dict] = {}
        for r in g["rs"]:
            for i, aid in enumerate(r["a"]):
                seen.setdefault(aid, {"id": aid, "n": r["n"][i], "t": r["t"][i], "c": 0})["c"] += 1
        people = sorted(seen.values(), key=lambda p: (-(p["t"] in GROUPS), -p["c"]))
        mvs = set(g["mv"])
        m = [sum(2 ** pi for pi in range(len(w["movements"])) if f"{wi}:{pi}" in mvs) for wi, w in enumerate(works)]
        fs = [r["f"] for r in g["rs"] if r["f"]]
        out.append({"n": [p["n"] for p in people], "a": [p["id"] for p in people], "t": [p["t"] for p in people],
                    "y": sorted(g["ys"]), "m": ",".join(map(str, m)), "f": min(fs) if fs else None,
                    "l": 1 if any(r["l"] for r in g["rs"]) else 0, "rep": g["rs"][0]["id"]})
    return out


def ordered(_unused, rs, field):
    """Values of `field` over records, first-seen order (JavaScript Set semantics)."""
    out = []
    for r in rs:
        for v in r[field]:
            if v not in out:
                out.append(v)
    return out


def rows(perfs: list[dict], det) -> list[dict]:
    out = []
    for p in perfs:
        d = det(p["rep"])
        row = {"n": p["n"], "a": p["a"], "y": p["y"], "m": p["m"]}
        if any(p["t"]):
            row["t"] = p["t"]
        if p["f"]:
            row["f"] = p["f"]
        if p["l"]:
            row["l"] = 1
        if d.get("ins"):
            row["ins"] = d["ins"]
        if d.get("roles"):
            row["roles"] = d["roles"]
        if d.get("pl"):
            row["pl"] = d["pl"]
        if d.get("r"):
            row["r"] = d["r"]
        row["rep"] = p["rep"]
        out.append(row)
    out.sort(key=lambda r: ((r["a"][0] if r["a"] else ""), (r["y"][0] if r["y"] else 9999)))
    return out


def dumps(x) -> str:
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"))


def collect(col: dict, args) -> bool:
    c = Collector(col["id"], Path(args.state), args.deadline, not args.no_whole)
    try:
        works = c.cached("tree", lambda: c.tree(col))
        mode = col.get("mode", "ensemble")
        grouped = mode in GROUPED_MODES
        whole = (lambda w: c.recordings(w["id"]) if w["has_parts"] else []) if c.whole else (lambda w: [])
        perfs = group(works, c.recordings, whole, grouped)
        print(f"{col['id']}: {len(works)} works, {len(perfs)} performances; fetching details", flush=True)
        for i, p in enumerate(perfs, 1):
            c.detail(p["rep"])
            if i % 100 == 0:
                print(f"  details {i}/{len(perfs)}", flush=True)
        c.save(force=True)
    except OutOfTime:
        print(f"{col['id']}: out of time, progress saved", flush=True)
        return False
    out = Path(args.out) / col["id"]
    out.mkdir(parents=True, exist_ok=True)
    native = col.get("native") or NATIVE.get(mode, [])
    snap = ('{\n"works": ' + json.dumps([w["bwv"] for w in works]) + ',\n"native": ' + json.dumps(native) +
            ',\n"mode": ' + json.dumps(mode) + ',\n"rows": [\n' +
            ",\n".join(dumps(r) for r in rows(perfs, c.detail)) + "\n]\n}\n")
    (out / f"musicbrainz-{col['id']}.json").write_text(snap, encoding="utf-8")
    n_rec = len({r[0] for w in works for m in w["movements"] for r in c.recordings(m["id"])})
    tree = {"collection": col["id"], "taken": time.strftime("%Y-%m-%d"), "recordings": n_rec,
            "performances": len(perfs), "works": works}
    (out / f"tree-{col['id']}.json").write_text(json.dumps(tree, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{col['id']}: done, {n_rec} recordings in {len(perfs)} performances", flush=True)
    return True


def remote_collect_branches() -> set[str]:
    try:
        out = subprocess.run(["git", "ls-remote", "--heads", "origin", "collect/*"], capture_output=True,
                             text=True, check=True, cwd=ROOT).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return set()
    return {line.split("refs/heads/collect/")[1] for line in out.splitlines() if "refs/heads/collect/" in line}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queued", action="store_true", help="collect every collection with status: queued")
    ap.add_argument("--collection", action="append", default=[], help="collect this collection id")
    ap.add_argument("--budget-minutes", type=float, default=330)
    ap.add_argument("--state", default=str(ROOT / ".mbcache"))
    ap.add_argument("--out", default=str(ROOT / ".mbcache" / "out"))
    ap.add_argument("--no-whole", action="store_true", help="ignore recordings linked to a whole work")
    args = ap.parse_args()
    args.deadline = time.time() + args.budget_minutes * 60
    cols = yaml.safe_load((ROOT / "data/plan/collections.yaml").read_text(encoding="utf-8"))["collections"]
    by_id = {c["id"]: c for c in cols}
    todo = [by_id[i] for i in args.collection]
    if args.queued:
        have = remote_collect_branches()
        todo += [c for c in cols if c["status"] == "queued" and c["id"] not in have]
    if not todo:
        print("nothing to collect")
    done = []
    for col in todo:
        if collect(col, args):
            done.append(col["id"])
        else:
            break
    Path(args.state).mkdir(parents=True, exist_ok=True)
    (Path(args.state) / "done.txt").write_text("".join(i + "\n" for i in done))
    return 0


if __name__ == "__main__":
    sys.exit(main())
