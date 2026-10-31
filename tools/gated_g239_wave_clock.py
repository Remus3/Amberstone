"""gated_g239_wave_clock.py - read-only grader for G2-39 (RM-124 wave / cannon clock).

G2-39 asks two live questions before ``RC_WAVE_CALLOUT`` may default on:
(a) does ``liveclient.minion_events`` carry the MinionsSpawning anchor
``{at_s}`` at first-wave spawn, and (b) does the cannon cadence the clock walks
forward from that anchor (``core.event_callouts.wave_callout``) match the
cannon waves that really spawn.

Two facts shape what can be graded (measured at source, s144 lane gated c40):

- The Live Client API emits ONE MinionsSpawning event per game. No later wave
  and no cannon minion is ever reported, so the truth for (b) is an
  OBSERVATION (the game clock when a cannon wave leaves the nexus), never a
  feed field. The clock predicts the SPAWN, not the lane arrival.
- The wave row can never reach the screen in a live game: B4 (RM-189) blanks
  the served ``callouts`` (``dashboard/_state_builder.py``
  ``suppress_live_envelope``) and the client gate
  (``web/js/lib/live_directive_gate.js``) hides the mount. The only live
  record of the row is the pre-suppression shadow log
  ``data/det_coach_shadow.jsonl`` (``core/det_coach_shadow.py``, field
  ``callouts``), and only while RC runs with ``RC_WAVE_CALLOUT=1``.

Sub-commands (all READ-ONLY: no network, no write, no tick):

  schedule --anchor S [--until S]
      The cannon SPAWN times the clock predicts from anchor S, with the cadence
      bracket each falls in. Computed by calling ``wave_callout`` itself.
  state FILE
      Grade a saved ``/api/state`` JSON for check (a). Verdicts: ANCHOR_OK,
      ANCHOR_MULTI, ANCHOR_MISSING, ANCHOR_BAD, PRE_SPAWN, NOT_IN_GAME.
  shadow FILE --since ISO [--observed M:SS,...] [--tolerance-s N]
      Read the shadow log records at or after --since (an ISO time WITH a UTC
      offset, e.g. ``2026-01-02T18:00:00-05:00``; compared as a time, not as
      text) whose mode is SR-equivalent (``sr`` / ``client`` / ``game``: the
      log stores the raw dashboard mode_key), turn each
      wave row into its implied cannon spawn (``game_time_s + eta_s``) and
      grade the observed spawns against them. Verdicts: NO_RESULT (no wave row
      since --since: flag off, no SR game, or the log did not grow), SCHEDULE
      (rows present, nothing observed), MATCH, MISS.

Exit 0 = ANCHOR_OK / MATCH / a schedule printed; 3 = any other verdict;
2 = the input file is missing or unreadable.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.event_callouts import wave_callout  # noqa: E402

# Cadence brackets of the cannon rule, by the spawning wave's own time. The
# bounds restate core/event_callouts.py _CANNON_BRK_EVERY2_S / _EVERY1_S and are
# pinned against them by tests/test_gated_g239_wave_clock.py.
BRACKET_EVERY2_S = 840.0
BRACKET_EVERY1_S = 1500.0

# A first wave outside this window is not the 1:05 first-wave spawn the row
# names (stated before any game; wide enough for a clock read a tick late).
ANCHOR_MIN_S = 55.0
ANCHOR_MAX_S = 95.0

# Dashboard mode_keys the callout generator treats as SR (restates
# dashboard/_deterministic_coaching.py _MODE_KEY_TO_LOWER, pinned by the tests).
SR_MODE_KEYS = frozenset({"sr", "client", "game"})

DEFAULT_TOLERANCE_S = 3.0
DEFAULT_UNTIL_S = 1800.0
_SCAN_MAX = 400


def bracket(spawn_s: float) -> str:
    if spawn_s >= BRACKET_EVERY1_S:
        return "every1"
    if spawn_s >= BRACKET_EVERY2_S:
        return "every2"
    return "every3"


def clock(s: float) -> str:
    whole = int(round(s))
    return f"{whole // 60}:{whole % 60:02d}"


def parse_clock(text: str) -> float:
    """``M:SS`` (or plain seconds) -> seconds; ValueError on anything else."""
    text = text.strip()
    if ":" in text:
        mm, ss = text.split(":", 1)
        if not (mm.isdigit() and ss.isdigit() and len(ss) == 2 and int(ss) < 60):
            raise ValueError(f"bad clock {text!r}")
        return int(mm) * 60.0 + int(ss)
    val = float(text)
    if not math.isfinite(val) or val < 0:
        raise ValueError(f"bad clock {text!r}")
    return val


def predicted_cannons(anchor_s: float, until_s: float = DEFAULT_UNTIL_S) -> list[float]:
    """Cannon spawn times wave_callout predicts from ``anchor_s`` up to ``until_s``."""
    if not (math.isfinite(anchor_s) and math.isfinite(until_s)):
        raise ValueError("anchor and until must be finite")
    events = [{"at_s": anchor_s}]
    out: list[float] = []
    t = anchor_s
    for _ in range(_SCAN_MAX):
        c = wave_callout(t, events)
        if c is None:
            break
        spawn = round(t + float(c["eta_s"]), 3)
        if spawn > until_s:
            break
        out.append(spawn)
        t = spawn + 0.5
    return out


def _finite(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def grade_state(state: Any) -> dict:
    """Check (a) over one saved /api/state envelope."""
    out: dict = {"verdict": "NOT_IN_GAME", "events": 0, "anchor_s": None,
                 "game_time_s": None, "served_wave_rows": 0}
    if not isinstance(state, dict):
        return out
    callouts = state.get("callouts")
    if isinstance(callouts, list):
        out["served_wave_rows"] = sum(
            1 for c in callouts if isinstance(c, dict) and c.get("kind") == "wave")
    lc = state.get("liveclient")
    if not isinstance(lc, dict) or not lc:
        return out
    gt = _finite(lc.get("game_time_s"))
    out["game_time_s"] = gt
    ev = lc.get("minion_events")
    events = ev if isinstance(ev, list) else []
    out["events"] = len(events)
    times = [t for t in (_finite(e.get("at_s")) for e in events if isinstance(e, dict))
             if t is not None]
    if not events:
        out["verdict"] = "PRE_SPAWN" if gt is not None and gt < ANCHOR_MIN_S else "ANCHOR_MISSING"
        return out
    if len(times) != len(events):
        out["verdict"] = "ANCHOR_BAD"
        return out
    out["anchor_s"] = min(times)
    if len(events) > 1:
        out["verdict"] = "ANCHOR_MULTI"
    elif ANCHOR_MIN_S <= times[0] <= ANCHOR_MAX_S:
        out["verdict"] = "ANCHOR_OK"
    else:
        out["verdict"] = "ANCHOR_BAD"
    return out


def parse_since(text: str) -> datetime:
    """An ISO time WITH a UTC offset; a naive or unparsable value is a ValueError
    (a local time read as UTC would let an earlier game's rows in)."""
    dt = datetime.fromisoformat(text.strip())
    if dt.tzinfo is None:
        raise ValueError("--since needs a UTC offset")
    return dt


def _record_time(ts: Any) -> Optional[datetime]:
    if not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else None


def implied_spawns(records: list[dict], since: datetime) -> list[float]:
    """Distinct cannon spawns implied by the shadow log's wave rows (SR, ts >= since)."""
    seen: dict[int, float] = {}
    for rec in records:
        if not isinstance(rec, dict) or rec.get("mode") not in SR_MODE_KEYS:
            continue
        rt = _record_time(rec.get("ts"))
        if rt is None or rt < since:
            continue
        gt = _finite(rec.get("game_time_s"))
        callouts = rec.get("callouts")
        if gt is None or not isinstance(callouts, list):
            continue
        for c in callouts:
            if not isinstance(c, dict) or c.get("kind") != "wave":
                continue
            eta = _finite(c.get("eta_s"))
            if eta is None:
                continue
            spawn = gt + eta
            if not math.isfinite(spawn):
                continue
            seen.setdefault(int(round(spawn)), spawn)
    return sorted(seen.values())


def grade_shadow(implied: list[float], observed: list[float],
                 tolerance_s: float = DEFAULT_TOLERANCE_S) -> dict:
    out: dict = {"verdict": "NO_RESULT", "implied": [round(s, 1) for s in implied],
                 "pairs": [], "brackets_observed": []}
    if not implied:
        return out
    if not observed:
        out["verdict"] = "SCHEDULE"
        return out
    ok = True
    brackets: list[str] = []
    for obs in observed:
        near = min(implied, key=lambda s: abs(s - obs))
        delta = round(obs - near, 1)
        hit = abs(delta) <= tolerance_s
        ok = ok and hit
        out["pairs"].append({"observed": clock(obs), "implied": clock(near),
                             "delta_s": delta, "bracket": bracket(obs),
                             "hit": hit})
        if bracket(obs) not in brackets:
            brackets.append(bracket(obs))
    out["brackets_observed"] = brackets
    out["verdict"] = "MATCH" if ok else "MISS"
    return out


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"wave"' not in line:
                continue  # cheap prefilter: the log is large and wave rows are rare
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_sch = sub.add_parser("schedule")
    p_sch.add_argument("--anchor", type=float, required=True)
    p_sch.add_argument("--until", type=float, default=DEFAULT_UNTIL_S)
    p_st = sub.add_parser("state")
    p_st.add_argument("file", type=Path)
    p_sh = sub.add_parser("shadow")
    p_sh.add_argument("file", type=Path)
    p_sh.add_argument("--since", required=True)
    p_sh.add_argument("--observed", default="")
    p_sh.add_argument("--tolerance-s", type=float, default=DEFAULT_TOLERANCE_S)
    for p in (p_sch, p_st, p_sh):
        p.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "schedule":
        try:
            cannons = predicted_cannons(args.anchor, args.until)
        except ValueError as exc:
            print(f"bad input: {exc}", file=sys.stderr)
            return 2
        rows = [{"spawn": clock(s), "spawn_s": s, "bracket": bracket(s)}
                for s in cannons]
        if args.json:
            print(json.dumps({"anchor_s": args.anchor, "cannons": rows}))
        else:
            print(f"anchor {clock(args.anchor)} ({args.anchor}s)")
            for r in rows:
                print(f"cannon spawn {r['spawn']} {r['bracket']}")
        return 0

    try:
        if args.cmd == "state":
            res = grade_state(json.loads(args.file.read_text(encoding="utf-8")))
            good = res["verdict"] == "ANCHOR_OK"
        else:
            if not (math.isfinite(args.tolerance_s) and 0 < args.tolerance_s <= 30):
                raise ValueError("--tolerance-s must be in (0, 30]")
            observed = [parse_clock(x) for x in args.observed.split(",") if x.strip()]
            since = parse_since(args.since)
            res = grade_shadow(implied_spawns(_read_jsonl(args.file), since),
                               observed, args.tolerance_s)
            good = res["verdict"] == "MATCH"
    except (OSError, ValueError) as exc:
        print(f"unreadable input: {type(exc).__name__}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(res))
    else:
        for key, val in res.items():
            print(f"{key}: {val}")
    return 0 if good else 3


if __name__ == "__main__":
    sys.exit(main())
