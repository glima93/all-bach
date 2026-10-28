"""Check data/plan/collections.yaml: every BWV number 1–1128 in exactly one collection, runs in order.

    python scripts/plan_coverage.py          # check, and print the run schedule
"""
import sys
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
LAST = 1128


def numbers(spec: str) -> range:
    lo, _, hi = spec.partition("-")
    return range(int(lo), int(hi or lo) + 1)


def main() -> int:
    cols = yaml.safe_load((ROOT / "data/plan/collections.yaml").read_text(encoding="utf-8"))["collections"]
    owner: dict[int, list[str]] = defaultdict(list)
    for c in cols:
        for spec in c["bwv"]:
            for n in numbers(spec):
                owner[n].append(c["id"])
    errors = [f"BWV {n} is in no collection" for n in range(1, LAST + 1) if n not in owner]
    errors += [f"BWV {n} is in {', '.join(ids)}" for n, ids in sorted(owner.items()) if len(ids) > 1]
    errors += [f"BWV {n} is beyond {LAST}" for n in owner if n > LAST]
    ids = [c["id"] for c in cols]
    errors += [f"duplicate id {i}" for i in {i for i in ids if ids.count(i) > 1}]

    runs: dict[int, list[str]] = defaultdict(list)
    for c in cols:
        for r in c["run"] if isinstance(c["run"], list) else [c["run"]]:
            runs[r].append(c["id"])
    if sorted(runs) != list(range(len(runs))):
        errors.append(f"runs are not numbered 0..{len(runs) - 1} without gaps")

    for e in errors:
        print("error:", e)
    todo = [c for c in cols if c["status"] != "done"]
    print(f"{len(cols)} collections ({len(cols) - len(todo)} done), BWV 1–{LAST} covered once each"
          if not errors else f"{len(errors)} error(s)")
    for r in sorted(runs):
        if r:
            print(f"  run {r:2}: {', '.join(runs[r])}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
