"""LAND DUE lines for the lane status file (MAIN ORDER 2026-11-14 0930 section 3, Fleet
Insights W46: 593 commits on seven lane branches; repo 158, uiux and true-audit 106).

For each lane: `git rev-list --count main..lane/<lane>` in the MAIN checkout, one line
"<lane> <n> ahead of main", and " LAND DUE" on any lane MORE than LAND_DUE_AT (100) ahead.
stamp() merges the block into ops/loop/control/progress/s144-lanes.json as "land_due".
The kit's write_progress rewrites that file whole and has no extra-key door, so the s144
rotator calls stamp() right after each write_progress (as it does RC-4's stamp_daily); the
counts are cached TTL_S seconds so a busy poll costs no git calls.

CLI (read-only unless --stamp): python -m ops.loop.lane_status_landdue [--stamp]

Stdlib plus core/polled_json (atomic write), ASCII only.
"""
from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
import time
from pathlib import Path

LAND_DUE_AT = 100
TTL_S = 120.0
STATUS_REL = Path("ops/loop/control/progress/s144-lanes.json")
LANES = ("gated", "queue", "uiux", "research", "ds", "repo", "true-audit")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_CACHE: dict = {}


def ahead_counts(root, lanes, *, main: str = "main", run=None) -> dict:
    """{lane: commits on lane/<lane> not on `main`}; None when git cannot count it."""
    run = run or subprocess.run
    out = {}
    for lane in lanes:
        try:
            r = run(["git", "rev-list", "--count", f"{main}..lane/{lane}"], cwd=str(root),
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=60, creationflags=NO_WINDOW)
            text = (r.stdout or "").strip()
            out[lane] = int(text) if r.returncode == 0 and text.isdigit() else None
        except (OSError, subprocess.SubprocessError, ValueError):
            out[lane] = None
    return out


def land_due_lines(counts: dict, threshold: int = LAND_DUE_AT) -> list:
    lines = []
    for lane, n in counts.items():
        if n is None:
            lines.append(f"{lane} ? ahead of main (count unavailable)")
        else:
            lines.append(f"{lane} {n} ahead of main" + (" LAND DUE" if n > threshold else ""))
    return lines


def land_due_block(counts: dict, threshold: int = LAND_DUE_AT) -> dict:
    return {
        "at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "threshold": threshold,
        "lanes": {lane: {"ahead": n, "land_due": n is not None and n > threshold}
                  for lane, n in counts.items()},
        "due": [lane for lane, n in counts.items() if n is not None and n > threshold],
        "lines": land_due_lines(counts, threshold),
    }


def cached_counts(root, lanes, *, run=None, cache=None, now=None) -> dict:
    cache = _CACHE if cache is None else cache
    now = time.time() if now is None else float(now)
    key = (str(root), tuple(lanes))
    hit = cache.get(key)
    if hit is not None and now - hit[0] < TTL_S:
        return dict(hit[1])
    counts = ahead_counts(root, lanes, run=run)
    cache[key] = (now, counts)
    return dict(counts)


def stamp(root, lanes=LANES, *, status_path=None, counts=None, run=None, cache=None,
          now=None) -> dict:
    """Merge the LAND DUE block into the lane status file as "land_due", atomically.
    Raises OSError / ValueError on an unreadable status file; the driver's caller
    swallows them. Returns the block."""
    from core.polled_json import atomic_write_bytes  # noqa: PLC0415
    path = Path(status_path) if status_path else Path(root) / STATUS_REL
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"status file is not an object: {path}")
    if counts is None:
        counts = cached_counts(root, lanes, run=run, cache=cache, now=now)
    block = land_due_block(counts)
    doc["land_due"] = block
    atomic_write_bytes(path, json.dumps(doc).encode("ascii", "replace"))
    return block


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--stamp", action="store_true", help="also merge into the status file")
    args = ap.parse_args(argv)
    counts = ahead_counts(args.root, LANES)
    if args.stamp:
        stamp(args.root, LANES, counts=counts)
    sys.stdout.write("\n".join(land_due_lines(counts)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
