"""gated_g245_spawn_stream.py - read-only grader for G2-45 (R221 wave SPAWN clock).

G2-45 asks two live questions about the R221 spawn clock
(``dashboard/_wave_timing.py`` ``wave_timing``, fed by
``liveclient.minion_spawn_events``):

(1) the PAYLOAD - does the Live Client ``events.Events`` stream carry
    ``MinionsSpawning`` ONCE per game (at first-wave spawn) or once PER WAVE?
(2) the CADENCE TABLE - do the ``_CANNON_CADENCE`` breakpoints match the
    cannon waves that really spawn?

Facts measured at source (s144 lane gated c47) that shape the grading:

- The repo states BOTH answers to (1), in one function.
  ``dashboard/_liveclient.py`` ``liveclient_summary`` builds two extracts from
  the same stream: ``minion_events`` (RM-124; its comment says the Live Client
  "emits a single MinionsSpawning event at first-wave spawn") and
  ``minion_spawn_events`` (R221; its comment says it "emits it once per wave").
  ``tools/gated_g239_wave_clock.py`` adopted the ONCE reading and grades a
  second event as ``ANCHOR_MULTI``. Neither comment cites a capture.
- The two clocks disagree on the interval after 14:00 even with the same
  anchor: ``core.event_callouts`` walks a piecewise 30 / 25 / 20 s interval,
  ``_wave_timing`` uses the median observed gap, else a constant 30 s. Under
  ONCE the R221 clock therefore projects 30 s waves for the whole game. Which
  interval is right is a live observation; the ``clocks`` sub-command only
  shows where the two MODELS part, it is not evidence for either.
- ``wave_timing`` has no production caller (``tests/test_wave_timing.py``
  only); the consuming panel is deferred until this row closes.

Sub-commands (all READ-ONLY: no network, no write, no tick):

  stream FILE [FILE ...]
      Grade saved ``/api/state`` JSON snapshots (take two or more, the last
      one at game clock 3:00 or later) for question (1). Verdicts, stated
      before any game: REPEATS (two or more distinct spawn times), ONCE
      (exactly one, and the newest snapshot is at least ONCE_MIN_WAIT_S past
      it, so at least two later waves have spawned under any interval of
      30 s or less), TOO_EARLY, NO_EVENT, EXTRACTS_DISAGREE (the two extracts
      read the same stream, so differing times void the read), FIELDS_MISSING
      (neither key present: an RC build without the extracts), NOT_IN_GAME.
  clocks --anchor S [--spawns S,...] [--until S] [--observed M:SS,...]
      The cannon SPAWN times each clock predicts: ``event_callouts`` from the
      anchor (via the G2-39 tool, which walks ``wave_callout`` itself) and
      ``_wave_timing`` from the spawn list (default: the anchor alone, the
      ONCE case; pass ``--spawns`` with the captured times for REPEATS). With
      ``--observed`` (the game clock each cannon wave LEFT the nexus) it grades
      both: BOTH_MATCH, CALLOUTS_ONLY, TIMING_ONLY, NEITHER; else SCHEDULE.

Exit 0 = ONCE / REPEATS / BOTH_MATCH / a schedule printed; 3 = any other
verdict; 2 = an input file is missing or unreadable, or a bad argument.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dashboard._wave_timing import wave_timing  # noqa: E402
from tools.gated_g239_wave_clock import (  # noqa: E402
    DEFAULT_TOLERANCE_S,
    DEFAULT_UNTIL_S,
    bracket,
    clock,
    parse_clock,
    predicted_cannons,
)

# Stated before any game. Under any wave interval of 30 s or less, at least
# two later waves have spawned 75 s after the first one, so a stream that still
# holds one event by then is ONCE, not "not yet".
ONCE_MIN_WAIT_S = 75.0
# The first wave spawns near 1:05; a clock below this has nothing to show yet.
FIRST_WAVE_BY_S = 95.0

_SCAN_MAX = 400
_STEP_EPS_S = 0.01


def _finite(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _times(rows: Any, key: str) -> Optional[list[float]]:
    """Sorted valid times under ``key``; None when ``rows`` is not a list."""
    if not isinstance(rows, list):
        return None
    out = [t for t in (_finite(r.get(key)) for r in rows if isinstance(r, dict))
           if t is not None]
    return sorted(out)


def read_snapshot(state: Any) -> Optional[dict]:
    """The facts of one saved /api/state envelope, or None if not in game."""
    if not isinstance(state, dict):
        return None
    lc = state.get("liveclient")
    if not isinstance(lc, dict) or not lc:
        return None
    spawn = _times(lc.get("minion_spawn_events"), "spawn_at_s")
    anchor = _times(lc.get("minion_events"), "at_s")
    return {
        "game_time_s": _finite(lc.get("game_time_s")),
        "spawn_times": spawn,
        "anchor_times": anchor,
        "extracts_agree": spawn == anchor,
    }


def grade_stream(snapshots: list[Optional[dict]]) -> dict:
    """Question (1) over snapshots of one game, in any order."""
    live = [s for s in snapshots if s is not None]
    out: dict = {"verdict": "NOT_IN_GAME", "snapshots": len(snapshots),
                 "in_game": len(live), "game_time_s": None, "spawn_times": [],
                 "median_gap_s": None, "cumulative": None}
    if not live:
        return out
    if not all(s["extracts_agree"] for s in live):
        out["verdict"] = "EXTRACTS_DISAGREE"
        return out
    timed = [s for s in live if s["game_time_s"] is not None]
    newest = max(timed, key=lambda s: s["game_time_s"]) if timed else live[-1]
    gt = newest["game_time_s"]
    out["game_time_s"] = gt
    if newest["spawn_times"] is None:
        # Neither extract key is a list: an RC build without them, not a
        # stream that carried no event.
        out["verdict"] = "FIELDS_MISSING"
        return out
    distinct = sorted(set(newest["spawn_times"] or []))
    out["spawn_times"] = distinct
    # A per-wave stream is cumulative-past: every time an earlier snapshot
    # held must still be in a later one. Reported, not graded.
    ordered = sorted(timed, key=lambda s: s["game_time_s"])
    out["cumulative"] = all(
        set(a["spawn_times"] or []) <= set(b["spawn_times"] or [])
        for a, b in zip(ordered, ordered[1:]))
    if len(distinct) >= 2:
        gaps = [b - a for a, b in zip(distinct, distinct[1:])]
        gaps.sort()
        mid = len(gaps) // 2
        median = gaps[mid] if len(gaps) % 2 else (gaps[mid - 1] + gaps[mid]) / 2
        out["median_gap_s"] = round(median, 3)
        out["verdict"] = "REPEATS"
    elif len(distinct) == 1:
        waited = gt is not None and gt >= distinct[0] + ONCE_MIN_WAIT_S
        out["verdict"] = "ONCE" if waited else "TOO_EARLY"
    else:
        late = gt is not None and gt >= FIRST_WAVE_BY_S
        out["verdict"] = "NO_EVENT" if late else "TOO_EARLY"
    return out


def timing_cannons(spawns: list[float], until_s: float = DEFAULT_UNTIL_S) -> list[float]:
    """Cannon spawn times ``_wave_timing.wave_timing`` projects from ``spawns``."""
    clean = sorted(s for s in spawns if math.isfinite(s))
    if not clean or not math.isfinite(until_s):
        raise ValueError("spawns and until must be finite and non-empty")
    events = [{"spawn_at_s": s, "event_id": None} for s in clean]
    out: list[float] = []
    t = clean[0] + _STEP_EPS_S
    for _ in range(_SCAN_MAX):
        r = wave_timing(events, t)
        nxt = r["next_spawn_s"]
        if nxt is None or nxt > until_s or nxt <= t - 1.0:
            break
        if r["next_is_cannon"]:
            out.append(round(nxt, 3))
        t = nxt + _STEP_EPS_S
    return out


def first_divergence(a: list[float], b: list[float]) -> Optional[int]:
    for i, (x, y) in enumerate(zip(a, b)):
        if abs(x - y) > 1e-6:
            return i
    if len(a) != len(b):
        return min(len(a), len(b))
    return None


def _hits(predicted: list[float], observed: list[float], tol: float) -> list[dict]:
    pairs = []
    for obs in observed:
        if not predicted:
            pairs.append({"observed": clock(obs), "nearest": None,
                          "delta_s": None, "bracket": bracket(obs), "hit": False})
            continue
        near = min(predicted, key=lambda s: abs(s - obs))
        delta = round(obs - near, 1)
        pairs.append({"observed": clock(obs), "nearest": clock(near),
                      "delta_s": delta, "bracket": bracket(obs),
                      "hit": abs(delta) <= tol})
    return pairs


def grade_clocks(anchor_s: float, spawns: Optional[list[float]] = None,
                 until_s: float = DEFAULT_UNTIL_S,
                 observed: Optional[list[float]] = None,
                 tolerance_s: float = DEFAULT_TOLERANCE_S) -> dict:
    callouts = predicted_cannons(anchor_s, until_s)
    timing = timing_cannons(spawns or [anchor_s], until_s)
    div = first_divergence(callouts, timing)
    out: dict = {
        "verdict": "SCHEDULE",
        "anchor_s": anchor_s,
        "timing_input": "anchor only (ONCE)" if not spawns else f"{len(spawns)} spawns",
        "callouts_cannons": [clock(s) for s in callouts],
        "timing_cannons": [clock(s) for s in timing],
        "first_divergence": None,
    }
    if div is not None:
        out["first_divergence"] = {
            "index": div,
            "callouts": clock(callouts[div]) if div < len(callouts) else None,
            "timing": clock(timing[div]) if div < len(timing) else None,
        }
    if not observed:
        return out
    c_pairs = _hits(callouts, observed, tolerance_s)
    t_pairs = _hits(timing, observed, tolerance_s)
    out["callouts_pairs"] = c_pairs
    out["timing_pairs"] = t_pairs
    c_ok = all(p["hit"] for p in c_pairs)
    t_ok = all(p["hit"] for p in t_pairs)
    out["verdict"] = {(True, True): "BOTH_MATCH", (True, False): "CALLOUTS_ONLY",
                      (False, True): "TIMING_ONLY", (False, False): "NEITHER"}[(c_ok, t_ok)]
    return out


def _clock_list(text: str) -> list[float]:
    return [parse_clock(p) for p in text.split(",") if p.strip()]


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _emit(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    for k in sorted(result):
        print(f"{k}: {result[k]}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stream")
    s.add_argument("files", nargs="+", type=Path)
    s.add_argument("--json", action="store_true")
    c = sub.add_parser("clocks")
    c.add_argument("--anchor", required=True)
    c.add_argument("--spawns", default="")
    c.add_argument("--until", default=str(DEFAULT_UNTIL_S))
    c.add_argument("--observed", default="")
    c.add_argument("--tolerance-s", type=float, default=DEFAULT_TOLERANCE_S)
    c.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    if args.cmd == "stream":
        snaps = []
        for f in args.files:
            try:
                snaps.append(read_snapshot(_load(f)))
            except (OSError, ValueError) as exc:
                print(f"unreadable: {f.name}: {type(exc).__name__}", file=sys.stderr)
                return 2
        result = grade_stream(snaps)
        _emit(result, args.json)
        return 0 if result["verdict"] in ("ONCE", "REPEATS") else 3

    try:
        anchor = parse_clock(args.anchor)
        spawns = _clock_list(args.spawns) or None
        until = parse_clock(args.until)
        observed = _clock_list(args.observed)
        result = grade_clocks(anchor, spawns, until, observed, args.tolerance_s)
    except ValueError as exc:
        print(f"bad argument: {exc}", file=sys.stderr)
        return 2
    _emit(result, args.json)
    return 0 if result["verdict"] in ("SCHEDULE", "BOTH_MATCH") else 3


if __name__ == "__main__":
    raise SystemExit(main())
