"""Read-only: median cache_creation per headless run, from headless_usage.jsonl.

The reader for the FLEET-3b acceptance (median cache_creation per run 25 percent
lower two weeks after the trimmed lane prompts). Prints overall, lane-only and
per-lane medians, plus total cache_creation and turns, because folding short runs
into longer ones moves the per-run median and the total in opposite directions.

Usage:
  python tools/lane_usage_median.py --since 2026-10-25 [--until 2026-11-01]
Dates are the local day in the row's ts field; --until is inclusive.
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

USAGE = Path(__file__).resolve().parent.parent / "ops" / "loop" / "control" / "headless_usage.jsonl"
LANE_PREFIX = "lane-"


def load_rows(path: Path, since: str, until: str | None) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        day = str(row.get("ts", ""))[:10]
        if day < since or (until and day > until):
            continue
        if isinstance(row.get("cache_creation"), (int, float)):
            rows.append(row)
    return rows


def summarize(rows: list[dict]) -> dict:
    values = [r["cache_creation"] for r in rows]
    return {
        "n": len(values),
        "median_cache_creation": statistics.median(values) if values else None,
        "total_cache_creation": sum(values),
        "median_turns": statistics.median([r.get("num_turns") or 0 for r in rows]) if rows else None,
    }


def report(rows: list[dict]) -> dict:
    lanes = defaultdict(list)
    for row in rows:
        note = str(row.get("note", ""))
        if note.startswith(LANE_PREFIX):
            lanes[note].append(row)
    lane_rows = [r for group in lanes.values() for r in group]
    return {
        "all_runs": summarize(rows),
        "lane_runs": summarize(lane_rows),
        "per_lane": {note: summarize(lanes[note]) for note in sorted(lanes)},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", required=True)
    ap.add_argument("--until")
    ap.add_argument("--usage", type=Path, default=USAGE)
    args = ap.parse_args(argv)
    print(json.dumps(report(load_rows(args.usage, args.since, args.until)), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
