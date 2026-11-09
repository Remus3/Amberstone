"""gated_g316_shadow_game_id.py - grade the G3-16 game_id predicate.

G3-16 in ``docs/LIVE_GAME_GATED_SYNC.md`` asks whether the HZ-C1 shadow rows
in ``data/hz_choice_shadow.jsonl`` carry the REAL Riot ``game_id`` during a
live game. ``core.hz_choice_shadow.log_precomputed_choices`` writes
``game_id`` (the LCU gameflow id threaded from the LCU snapshot by
``dashboard._deterministic_coaching.shadow_log_precomputed_choices``, or None)
and ``game_run_id`` (``game_id`` when present, else the ``_run_id_for``
stand-in ``local-<mode>-<ts>``).

A real id arriving a tick or two AFTER the first row is by design
(``tests/test_b4_shadow_match_id.py`` "appearing mid game takes over"), so a
game may legitimately open with ``local-`` rows. What the post-game review
(B4-e) cannot survive is a ``local-`` row AFTER a real-id row, a real row whose
``game_run_id`` is not its ``game_id``, or a non-numeric id.

Verdicts over the rows whose ``ts`` is at or after ``--since`` (the game's
start, UTC ISO):

- PASS: at least one real-id row; every real row carries the SAME numeric
  ``game_id`` with ``game_run_id == game_id``; no ``local-`` row after the
  first real row.
- FAIL: a real row with ``game_run_id != game_id``, a non-numeric non-null
  ``game_id``, a ``local-`` row after a real row, or (only with ``--phase``
  naming an in-game LCU phase) rows that are ALL ``local-``.
- NO_RESULT: no row in the window, rows written by a pre-B4-d writer (no
  ``game_run_id`` key), more than one real ``game_id`` in the window (it spans
  two games: narrow ``--since``), or all rows ``local-`` without an in-game
  ``--phase``.

Read-only: it streams the jsonl with a plain line reader, writes nothing,
calls no network. It prints counts and the verdict, never an id value (RM-906).
This is PREP for the live check, never a tick on its own: the evidence
contract still needs the /api/state LCU phase read at the same time.

    python tools/gated_g316_shadow_game_id.py --since 2026-11-08T20:00:00Z
    python tools/gated_g316_shadow_game_id.py --since <iso> --phase InProgress
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "data" / "hz_choice_shadow.jsonl"

# Mirrors dashboard._state_builder._IN_GAME_PHASES (Reconnect is a live game,
# S134 P0; lcu.snapshot_shape.shape_snapshot reads gameId there too).
IN_GAME_PHASES = ("GameStart", "InProgress", "Reconnect")
LOCAL_PREFIX = "local-"
_NUMERIC = re.compile(r"^[0-9]+$")


def parse_ts(value: object) -> Optional[datetime]:
    """ISO string -> aware UTC datetime; None when unparseable."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def rows_since(lines: Iterable[str], since: datetime) -> list[dict]:
    """Decode jsonl lines, keep dict rows whose ts parses and is >= since."""
    out: list[dict] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        ts = parse_ts(row.get("ts"))
        if ts is not None and ts >= since:
            out.append(row)
    return out


def grade(rows: list[dict], phase: Optional[str] = None) -> dict:
    """Return {verdict, reason, counts} for the rows of one game window."""
    counts = {"rows": len(rows), "real": 0, "local": 0, "lead_local": 0,
              "local_after_real": 0, "mismatch": 0, "bad_id": 0,
              "distinct_real_ids": 0, "distinct_local_runs": 0,
              "pre_b4d": 0}
    if not rows:
        return {"verdict": "NO_RESULT", "reason": "no row in the window",
                "counts": counts}
    real_ids: set[str] = set()
    local_runs: set[str] = set()
    seen_real = False
    for row in rows:
        if "game_run_id" not in row:
            counts["pre_b4d"] += 1
            continue
        gid = row.get("game_id")
        run = row.get("game_run_id")
        if gid is None or gid == "":
            if isinstance(run, str) and run.startswith(LOCAL_PREFIX):
                counts["local"] += 1
                local_runs.add(run)
                if seen_real:
                    counts["local_after_real"] += 1
                else:
                    counts["lead_local"] += 1
            else:
                counts["bad_id"] += 1
            continue
        gid_s = str(gid)
        if not _NUMERIC.match(gid_s):
            counts["bad_id"] += 1
            continue
        seen_real = True
        counts["real"] += 1
        real_ids.add(gid_s)
        if run != gid_s:
            counts["mismatch"] += 1
    counts["distinct_real_ids"] = len(real_ids)
    counts["distinct_local_runs"] = len(local_runs)

    if counts["pre_b4d"] == len(rows):
        return {"verdict": "NO_RESULT",
                "reason": "every row predates B4-d (no game_run_id key)",
                "counts": counts}
    if counts["mismatch"]:
        return {"verdict": "FAIL", "reason": "real row with game_run_id "
                "!= game_id", "counts": counts}
    if counts["bad_id"]:
        return {"verdict": "FAIL", "reason": "game_id not numeric, or no id "
                "and no local- run", "counts": counts}
    if len(real_ids) > 1:
        return {"verdict": "NO_RESULT", "reason": "more than one real game_id "
                "in the window - narrow --since to one game",
                "counts": counts}
    if counts["local_after_real"]:
        return {"verdict": "FAIL", "reason": "local- row after a real-id row "
                "(the LCU id dropped mid-game)", "counts": counts}
    if counts["real"]:
        return {"verdict": "PASS", "reason": "one numeric game_id, "
                "game_run_id == game_id on every real row", "counts": counts}
    if phase in IN_GAME_PHASES:
        return {"verdict": "FAIL", "reason": f"all rows local- while the LCU "
                f"phase is {phase}", "counts": counts}
    return {"verdict": "NO_RESULT", "reason": "all rows local- and no in-game "
            "--phase given", "counts": counts}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", required=True,
                    help="game start, UTC ISO (rows with ts >= since)")
    ap.add_argument("--phase", default=None,
                    help="LCU phase read from /api/state at probe time")
    ap.add_argument("--path", default=str(DEFAULT_PATH),
                    help="shadow jsonl (default data/hz_choice_shadow.jsonl)")
    args = ap.parse_args(argv)
    since = parse_ts(args.since)
    if since is None:
        print(f"bad --since: {args.since!r}", file=sys.stderr)
        return 2
    path = Path(args.path)
    if not path.is_file():
        print(f"NO_RESULT: no file at {path.name}")
        return 0
    with path.open(encoding="utf-8", errors="replace") as fh:
        rows = rows_since(fh, since)
    res = grade(rows, args.phase)
    c = res["counts"]
    print(f"{res['verdict']}: {res['reason']}")
    print(" ".join(f"{k}={c[k]}" for k in sorted(c)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
