"""Set a collection's status in data/plan/collections.yaml, editing only that one line.

    python scripts/plan_status.py orchestral-suites queued
"""
import re
import sys
from pathlib import Path

STATUSES = {"todo", "queued", "collected", "imported", "done"}
PATH = Path(__file__).resolve().parent.parent / "data/plan/collections.yaml"


def main(cid: str, status: str) -> int:
    if status not in STATUSES:
        raise SystemExit(f"status must be one of {sorted(STATUSES)}")
    text = PATH.read_text(encoding="utf-8")
    pat = re.compile(r"^(- \{id: " + re.escape(cid) + r",.*?status: )(\w+)", re.M | re.S)
    m = pat.search(text)
    if not m or "\n- {" in m.group(0):
        raise SystemExit(f"collection {cid} not found")
    PATH.write_text(text[:m.start(2)] + status + text[m.end(2):], encoding="utf-8")
    print(f"{cid}: {m.group(2)} -> {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
