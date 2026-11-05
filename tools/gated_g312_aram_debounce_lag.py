"""gated_g312_aram_debounce_lag.py - G3-12 read-back: ARAM state-debounce coach-file lag.

Row G3-12 in docs/LIVE_GAME_GATED_SYNC.md validates the ``RC_ARAM_STATE_DEBOUNCE``
default-ON flip (``coaches/aram_coach.py``, read ONCE at import, default OFF).
With the flag ON, ``_run_coach`` skips the Haiku call while the coarse coaching
signature is unchanged and the cached coaching is younger than the 45 s ceiling
(``_STATE_DEBOUNCE_MAX_STALE_S``). The live question is whether the served coach
file still keeps up with the game: does ``data/aram_coaching_data.json``
``game_time_s`` ever trail the Live Client game time by more than 90 s?

This is the ARAM twin of ``tools/gated_g506_debounce_lag.py`` (G5-06, Arena).
It reuses that tool's mode-neutral pieces (sample row, log parser, file
readers, the coverage limits) and differs in four places only: the mode
(``mode_key`` / trace ``mode`` ``"aram"``), the coach file, the three log
strings, and the bound (90 s, not 150 s).

WHY 90 s HOLDS FOR ARAM AND NOT FOR ARENA (narrowly). The ARAM signature
carries a 30 s game-time band (``_coach_state_signature``, ``time_band``), the
Arena one does not. The file's ``game_time_s`` is the DISPATCH state's game
time g0. Once the game clock leaves g0's band (at most g0 + 30 s), the next
dispatch re-calls whatever the 45 s ceiling says; a stable board dispatches
every 25 s (``_STABLE_DEBOUNCE_S``; ``_last_coach`` is set at dispatch even for a
run that then skips), the poll ticks every 1.5 s, and a Haiku attempt times out
at 20 s. The coach also reads a Live Client snapshot up to 12 s old
(``_fetch_game_data``), so a dispatch can still read the old band. Worst case
with single-attempt calls and no slow tick: about 88 s, a margin of about 2 s.
So any delay outside that budget excuses: a ``coach_tick_trace`` ``coach``
record over 20000 ms (an SDK retry logs nothing), any other ARAM trace phase
over 2000 ms, or a failed coach-file write.

SAMPLING RESOLUTION. Only the sampled points are graded: with 25 s polls a true
peak up to about one interval above the bound can fall between two samples, so
PASS means "no SAMPLED lag over 90 s", not "the lag never crossed 90 s".

Two halves, so the in-game pass is copy-paste:

  sample   LIVE, during an ARAM / Mayhem game: every ``--interval`` seconds
           (fixed rate) read the coach file's ``game_time_s``, THEN GET
           ``/api/state`` (``mode_key``, ``liveclient.game_time_s`` / ``hp`` /
           ``hp_max``), so a slow GET can only make the measured lag LARGER.
           One JSON line per poll goes to STDOUT (redirect it to a scratch file;
           a PowerShell 5.1 UTF-16 redirect is read back fine). It writes
           nothing itself. Start it before the game clock starts; Ctrl-C after
           the game ends.
  grade    AFTER the game: grade those samples against the day log and
           ``data/coach_tick_trace.jsonl``.

WHY NOT THE COMPUTE HALF (the SUBSTITUTION trap). ``tests/test_aram_state_debounce.py``
proves the skip FIRES on an unchanged signature; only the file the dashboard
serves, read against the game's own clock, says whether the coach the player
sees went stale.

PREDICATES (stated in the G3-12 row before any game):
  window   ``--since`` / ``--until`` (game clock start and game end, local
           clock) are REQUIRED.
  proof    at least one ``ARAM state-debounce: signature unchanged`` line in
           the window. Zero = the flag was not proven ON: INCONCLUSIVE.
  usable   ``mode_key == "aram"``, the player alive (``liveclient.hp > 0``)
           and both game times numeric. None usable = NO_RESULT.
  lag      ``liveclient.game_time_s - coach game_time_s``. PASS iff proof
           holds and no usable sample lags over 90 s.
  coverage the same tool-side preconditions as G5-06 (each can only turn a PASS
           into INCONCLUSIVE): no coach file ahead of the live clock by over
           30 s; known samples (usable, or dead: aram, ``hp == 0`` with
           ``hp_max > 0``) tile the window with no gap over 35 s; no dead run
           over 120 s; the first known game time at most 60 s; a clean
           game-over poll within 35 s of the last known sample.
  excuse   a lag over 90 s is INCONCLUSIVE if its window (the ``lag_s``
           seconds before the sample) holds an ``ARAM coach error`` line
           (``core/safe_coach_output.py``), an ``ARAM: no fields parsed`` line
           (returns before the write), a ``safe_write aram_coaching_data.json``
           line (a failed write), or overlaps a ``coach_tick_trace`` record with
           ``mode == "aram"`` and ``phase == "coach"`` over 20000 ms or any other
           phase over 2000 ms (the record's ``ts`` is its END). A missing
           Anthropic client returns silently too, but then no proof line can
           exist, so it grades INCONCLUSIVE on its own. The kill-switch, budget and
           feature-policy gates return SILENTLY, so an unexcused lag is FAIL
           only with ``--budget-ok`` (the operator asserts all three clear) and
           a readable ``--trace`` file; otherwise INCONCLUSIVE.

The coherence half (does reused text still fit the board?) stays an operator
eyeball and is not graded here.

READ-ONLY: GETs the local dashboard and reads files. It prints game times, lags
and log excerpts only, never a Riot id, game id or match key, and never ticks a
row - its output is the INPUT to the four-part evidence contract.

USAGE (from the main checkout, RC started with RC_ARAM_STATE_DEBOUNCE=1)
    python tools/gated_g312_aram_debounce_lag.py sample --interval 25 > <scratch>/g312.jsonl
    python tools/gated_g312_aram_debounce_lag.py grade --samples <scratch>/g312.jsonl \
        --log logs/<date>.log --since <HH:MM:SS> --until <HH:MM:SS> [--budget-ok]
Exit 0 = PASS, 1 = INCONCLUSIVE / NO_RESULT, 2 = FAIL.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.gated_g506_debounce_lag import (  # noqa: E402
    AHEAD_TOL_S,
    MAX_DEAD_RUN_S,
    MAX_GAP_S,
    SLOW_CALL_MS,
    START_GT_MAX_S,
    _clock,
    _get_state,
    _num,
    _read_json,
    _read_jsonl,
    _wall,
    log_date,
    make_sample,
    parse_log,
)

MODE = "aram"
LAG_BOUND_S = 90.0
# A non-coach ARAM trace phase (parse / on_state / tick / shadow) over this delays
# the next dispatch; the worst-case margin under the 90 s bound is about 2 s.
SLOW_OTHER_MS = 2000.0
PROOF_MARK = "ARAM state-debounce: signature unchanged"
# safe_write logs "safe_write <name>: ..." on a failed write, and the debounce
# stamp is still taken after it, so the next same-band dispatch skips.
EXCUSE_MARKS = ("ARAM coach error", "ARAM: no fields parsed", "safe_write aram_coaching_data.json")

__all__ = ["make_sample", "parse_log", "log_date", "usable", "slow_calls", "coverage", "grade",
           "render", "main"]


def _timed(s: Any) -> bool:
    return (isinstance(s, dict) and s.get("mode_key") == MODE
            and _num(s.get("lc_game_time_s")) is not None and _wall(s) is not None)


def usable(s: Any) -> bool:
    return _timed(s) and (_num(s.get("hp")) or 0) > 0 and _num(s.get("lag_s")) is not None


def _dead(s: Any) -> bool:
    return _timed(s) and _num(s.get("hp")) == 0 and (_num(s.get("hp_max")) or 0) > 0


def _ended(s: Any) -> bool:
    """A clean poll (no GET error) that shows no ARAM game running."""
    return (isinstance(s, dict) and not s.get("error") and _wall(s) is not None
            and (s.get("mode_key") != MODE or _num(s.get("lc_game_time_s")) is None))


def slow_calls(trace_rows: Iterable[dict]) -> list[tuple[datetime, datetime]]:
    """(start, end) local times of slow ARAM trace records; the trace ``ts`` is the record's END.

    A ``coach`` record counts over SLOW_CALL_MS (a retried Haiku call); any other
    ARAM phase counts over SLOW_OTHER_MS (it delays the next dispatch).
    """
    out = []
    for r in trace_rows:
        if not (isinstance(r, dict) and r.get("mode") == MODE and isinstance(r.get("phase"), str)):
            continue
        limit = SLOW_CALL_MS if r["phase"] == "coach" else SLOW_OTHER_MS
        ts, dur = _num(r.get("ts")), _num(r.get("dur_ms"))
        if ts is not None and dur is not None and dur > limit:
            end = datetime.fromtimestamp(ts)
            out.append((end - timedelta(milliseconds=dur), end))
    return out


def _span(a: datetime, b: datetime) -> str:
    return f"{a.isoformat(timespec='seconds')} -> {b.isoformat(timespec='seconds')}"


def coverage(samples: list[dict], rows: list[dict], window: list[dict],
             since: datetime, until: datetime) -> dict[str, Any]:
    """Tool-side preconditions: the known samples tile the whole game; no coach file from the future."""
    known = sorted((s for s in window if usable(s) or _dead(s)), key=_wall)
    walls = sorted({_wall(s) for s in known})
    points = [since, *walls, until]
    holes = [_span(a, b) for a, b in zip(points, points[1:]) if (b - a).total_seconds() > MAX_GAP_S]
    dead_runs, run = [], []
    for s in known + [None]:
        if s is not None and _dead(s):
            run.append(_wall(s))
            continue
        if run and (run[-1] - run[0]).total_seconds() > MAX_DEAD_RUN_S:
            dead_runs.append(_span(run[0], run[-1]))
        run = []
    start_gt = _num(known[0]["lc_game_time_s"]) if known else None
    end_seen = False
    if walls:
        after = sorted((s for s in samples if isinstance(s, dict) and (_wall(s) or walls[-1]) > walls[-1]),
                       key=_wall)
        end_seen = bool(after) and _ended(after[0]) and \
            (_wall(after[0]) - walls[-1]).total_seconds() <= MAX_GAP_S
    ahead = [s["wall"] for s in rows if float(s["lag_s"]) < -AHEAD_TOL_S]
    return {"known": len(walls), "holes": holes, "dead_runs": dead_runs, "ahead": ahead,
            "start_game_time_s": start_gt,
            "start_ok": start_gt is not None and start_gt <= START_GT_MAX_S, "end_seen": end_seen}


def grade(samples: list[dict], log: list[tuple[datetime, str]], slow: list[tuple[datetime, datetime]],
          since: datetime, until: datetime, budget_ok: bool = False,
          trace_ok: bool = True) -> dict[str, Any]:
    def in_win(t: datetime | None) -> bool:
        return t is not None and since <= t <= until

    proof = sum(1 for t, line in log if PROOF_MARK in line and in_win(t))
    window = [s for s in samples if isinstance(s, dict) and in_win(_wall(s))]
    rows = sorted((s for s in window if usable(s)), key=_wall)
    cov = coverage(samples, rows, window, since, until)
    lags = [float(s["lag_s"]) for s in rows]
    over = []
    for s in rows:
        lag = float(s["lag_s"])
        if lag <= LAG_BOUND_S:
            continue
        end = _wall(s)
        start = end - timedelta(seconds=lag)
        excuses = [line for t, line in log if start <= t <= end and any(k in line for k in EXCUSE_MARKS)]
        excuses += [f"coach_tick_trace slow aram record {_span(a, b)}"
                    for a, b in slow if a <= end and b >= start]
        if excuses:
            v, note = "INCONCLUSIVE", ""
        elif not budget_ok:
            v, note = "INCONCLUSIVE", "budget / kill-switch / feature policy not asserted (--budget-ok)"
        elif not trace_ok:
            v, note = "INCONCLUSIVE", "no --trace file: a slow coach call cannot be ruled out"
        else:
            v, note = "FAIL", ""
        over.append({"wall": s["wall"], "lag_s": lag, "verdict": v, "excuses": excuses[:5], "note": note})
    incomplete = (cov["holes"] or cov["dead_runs"] or cov["ahead"]
                  or not cov["start_ok"] or not cov["end_seen"])
    if not rows:
        verdict = "NO_RESULT"
    elif proof == 0:
        verdict = "INCONCLUSIVE"
    elif any(o["verdict"] == "FAIL" for o in over):
        verdict = "FAIL"
    elif over or incomplete:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "PASS"
    return {"verdict": verdict, "proof_lines": proof, "samples": len(samples), "usable": len(rows),
            "max_lag_s": max(lags) if lags else None, "over_bound": over, "coverage": cov}


def render(rep: dict[str, Any]) -> str:
    out = [f"G3-12 verdict: {rep['verdict']}",
           f"proof lines ({PROOF_MARK!r}): {rep['proof_lines']}"
           + ("  <- flag NOT proven ON" if rep["proof_lines"] == 0 else ""),
           f"samples: {rep['samples']} total, {rep['usable']} usable (aram, alive, both times)",
           f"max lag: {rep['max_lag_s']} s (bound {LAG_BOUND_S:.0f} s)"]
    cov = rep["coverage"]
    out.append(f"known samples (alive or dead): {cov['known']}; gaps over {MAX_GAP_S:.0f} s: {len(cov['holes'])}")
    out.append(f"first known game time: {cov['start_game_time_s']} s (need <= {START_GT_MAX_S:.0f})"
               + ("" if cov["start_ok"] else "  <- window does not start at the game clock"))
    out.append("game over seen after the last known sample: " + ("yes" if cov["end_seen"] else "NO"))
    out += [f"- coverage hole: {h}" for h in cov["holes"]]
    out += [f"- dead run over {MAX_DEAD_RUN_S:.0f} s (missing hp?): {d}" for d in cov["dead_runs"]]
    out += [f"- coach file ahead of the live clock (another game's file?) at {w}" for w in cov["ahead"]]
    for o in rep["over_bound"]:
        out.append(f"- over bound at {o['wall']}: lag {o['lag_s']} s -> {o['verdict']} {o['note']}".rstrip())
        out += [f"    excuse: {e}" for e in o["excuses"]]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("sample", help="live: print one JSON sample line per poll")
    sp.add_argument("--count", type=int, default=144, help="polls (default 60 min at 25 s); Ctrl-C stops")
    sp.add_argument("--interval", type=float, default=25.0)
    sp.add_argument("--base", default="https://127.0.0.1:8888")
    sp.add_argument("--coach-file", type=Path, default=_ROOT / "data" / "aram_coaching_data.json")
    gp = sub.add_parser("grade", help="post-game: grade a samples file")
    gp.add_argument("--samples", type=Path, required=True)
    gp.add_argument("--log", type=Path, required=True)
    gp.add_argument("--date", default=None, help="YYYY-MM-DD when the log name carries none")
    gp.add_argument("--trace", type=Path, default=_ROOT / "data" / "coach_tick_trace.jsonl")
    gp.add_argument("--since", required=True, help="HH:MM:SS local, game clock start")
    gp.add_argument("--until", required=True, help="HH:MM:SS local, game end")
    gp.add_argument("--budget-ok", action="store_true",
                    help="operator asserts the daily budget was not exhausted, aram was not "
                         "kill-switched and aram.live_coaching was allowed")
    gp.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "sample":
        t0 = time.monotonic()  # fixed-rate schedule: a slow GET does not stretch the cadence
        try:
            for i in range(max(a.count, 0)):
                coach = _read_json(a.coach_file)  # coach file FIRST: GET delay can only enlarge the lag
                try:
                    state = _get_state(a.base)
                except (OSError, ValueError) as e:
                    state = {"error": type(e).__name__}
                print(json.dumps(make_sample(state, coach, datetime.now())), flush=True)
                if i + 1 < a.count:
                    time.sleep(max(0.0, t0 + (i + 1) * a.interval - time.monotonic()))
        except KeyboardInterrupt:
            pass  # Ctrl-C at game end is the normal stop
        return 0

    try:
        day = log_date(a.log, a.date)
        log = parse_log(a.log.read_text(encoding="utf-8", errors="replace").splitlines(), day)
        since, until = _clock(day, a.since), _clock(day, a.until)
    except (OSError, ValueError) as e:
        print(f"G3-12 verdict: NO_RESULT (log or window unreadable: {e})")
        return 1
    rep = grade(_read_jsonl(a.samples), log, slow_calls(_read_jsonl(a.trace)),
                since, until, a.budget_ok, trace_ok=a.trace.is_file())
    print(json.dumps(rep, indent=2) if a.json else render(rep))
    return {"PASS": 0, "FAIL": 2}.get(rep["verdict"], 1)


if __name__ == "__main__":
    sys.exit(main())
