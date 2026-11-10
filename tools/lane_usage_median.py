"""Read-only: median cache_creation per headless run, from headless_usage.jsonl.

The reader for the FLEET-3b acceptance (median cache_creation per run 25 percent
lower two weeks after the trimmed lane prompts). Prints overall, lane-only and
per-lane medians, plus total cache_creation and turns, because folding short runs
into longer ones moves the per-run median and the total in opposite directions.

Usage:
  python tools/lane_usage_median.py --since 2026-10-25 [--until 2026-11-01]
Dates are YYYY-MM-DD, compared with the local day in the row's ts field (its
first ten characters, an ISO date); --until is inclusive. A bound that is not
a real YYYY-MM-DD day, or --until before --since, exits 2 instead of silently
moving the window.

The default --usage file is the MAIN checkout's: the kit writes
headless_usage.jsonl there even when the run started in a linked worktree
(fleet_headless USAGE_REL / main_checkout), so a reader run from a lane
worktree must look there too.

Rows are counted only when they carry a usable figure: a ts whose first ten
characters are not an ISO date is skipped (a string compare would let
"garbage" > "2026-..." into an open-ended window), and so is a cache_creation
that is not a finite, non-negative number (a bool, NaN, inf or a string would
poison the median, and NaN / inf would make the printed report non-JSON).
median_turns is taken over the rows whose num_turns is itself a finite,
non-negative number; a missing one is not a zero-turn run.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from core.claude_project import main_checkout  # noqa: E402

USAGE_REL = Path("ops") / "loop" / "control" / "headless_usage.jsonl"
LANE_PREFIX = "lane-"
# Largest figure counted: 2**53, the top of float's exact-integer range. A real
# per-run token count is about six orders of magnitude below it.
MAX_FIGURE = 2 ** 53
_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def usage_path(root: Path = ROOT) -> Path:
    """headless_usage.jsonl in the MAIN checkout of ``root`` (worktree-safe)."""
    return main_checkout(root) / USAGE_REL


USAGE = usage_path()


def parse_day(text: object) -> _dt.date:
    """A real calendar day written exactly YYYY-MM-DD, else ValueError."""
    if not isinstance(text, str) or not _ISO_DAY.fullmatch(text):
        raise ValueError(f"not a YYYY-MM-DD day: {text!r}")
    return _dt.date.fromisoformat(text)


def _arg_day(text: str) -> _dt.date:
    try:
        return parse_day(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _row_day(row: dict) -> _dt.date | None:
    ts = row.get("ts")
    if not isinstance(ts, str):
        return None
    try:
        return parse_day(ts[:10])
    except ValueError:
        return None


def _figure(value: object) -> int | float | None:
    """A finite int / float in [0, MAX_FIGURE] (never a bool), else None.

    The ceiling keeps the sum and the even-n median finite: two rows of a
    finite 1.7e308 sum to inf, and a 10**400 int overflows the median's
    float division, either of which would end the report in a traceback."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value if 0 <= value <= MAX_FIGURE else None


def _as_day(value: object) -> _dt.date:
    return value if isinstance(value, _dt.date) else parse_day(value)


def load_rows(path: Path, since, until=None) -> list[dict]:
    """Rows of ``path`` whose ts day is in [since, until] with a usable
    cache_creation. ``since`` / ``until`` are dates or YYYY-MM-DD strings
    (ValueError otherwise); ``until`` None leaves the window open. OSError
    from reading ``path`` propagates to the caller."""
    lo = _as_day(since)
    hi = None if until is None else _as_day(until)
    rows = []
    # utf-8-sig: a BOM written by an editor would otherwise make the first
    # line non-JSON and silently drop that row.
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except (ValueError, RecursionError):
                # RecursionError: one deeply nested line ("[" * 200000) is a
                # skipped line, not the end of the report.
                continue
            if not isinstance(row, dict):
                continue
            day = _row_day(row)
            if day is None or day < lo or (hi is not None and day > hi):
                continue
            if _figure(row.get("cache_creation")) is not None:
                rows.append(row)
    return rows


def summarize(rows: list[dict]) -> dict:
    values = [v for v in (_figure(r.get("cache_creation")) for r in rows) if v is not None]
    turns = [t for t in (_figure(r.get("num_turns")) for r in rows) if t is not None]
    return {
        "n": len(values),
        "median_cache_creation": statistics.median(values) if values else None,
        "total_cache_creation": sum(values),
        "median_turns": statistics.median(turns) if turns else None,
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
    ap.add_argument("--since", required=True, type=_arg_day)
    ap.add_argument("--until", type=_arg_day)
    ap.add_argument("--usage", type=Path, default=USAGE)
    args = ap.parse_args(argv)
    if args.until is not None and args.until < args.since:
        print(f"lane_usage_median: --until {args.until} is before --since {args.since}",
              file=sys.stderr)
        return 2
    try:
        rows = load_rows(args.usage, args.since, args.until)
    except OSError as exc:
        print(f"lane_usage_median: cannot read {args.usage}: {exc.strerror or exc}",
              file=sys.stderr)
        return 2
    print(json.dumps(report(rows), indent=1, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
