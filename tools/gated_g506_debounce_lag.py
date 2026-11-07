"""gated_g506_debounce_lag.py - G5-06 read-back: Arena state-debounce coach-file lag.

Row G5-06 in docs/LIVE_GAME_GATED_SYNC.md validates the ``RC_ARENA_STATE_DEBOUNCE``
default-ON flip (``coaches/arena_coach.py``, read ONCE at import, default OFF).
With the flag ON, ``_run_coach`` skips the Haiku call while the coarse board
signature is unchanged and the cached coaching is younger than the 45 s ceiling
(``_STATE_DEBOUNCE_MAX_STALE_S``). The live question is whether the served coach
file still keeps up with the game: does ``data/arena_coaching_data.json``
``game_time_s`` ever trail the Live Client game time by more than 150 s?

Two halves, so the in-game pass is copy-paste:

  sample   LIVE, during an Arena game: every ``--interval`` seconds (fixed rate)
           read the coach file's ``game_time_s``, THEN GET ``/api/state``
           (``mode_key``, ``liveclient.game_time_s`` / ``hp`` / ``hp_max``), so a
           slow GET can only make the measured lag LARGER, never hide one. Each
           line records ``get_s``, the span from the coach-file read to the end
           of the GET (RM-1345), so grade can discount it. One
           JSON line per poll goes to STDOUT (redirect it to a scratch file; a
           PowerShell 5.1 UTF-16 redirect is read back fine). It writes nothing
           itself. Start it before the game clock starts; Ctrl-C after the game
           ends.
  grade    AFTER the game: grade those samples against the day log and
           ``data/coach_tick_trace.jsonl``.

WHY NOT THE COMPUTE HALF (the SUBSTITUTION trap). ``tests/test_arena_state_debounce.py``
proves the skip FIRES on an unchanged signature; only the file the dashboard
serves, read against the game's own clock, says whether the coach the player sees
went stale.

PREDICATES (stated in the G5-06 row before any game):
  window   ``--since`` / ``--until`` (the game clock's start and the game's end,
           local clock) are REQUIRED: a proof line or sample from another game
           must not count.
  proof    at least one ``Arena state-debounce: signature unchanged`` line in the
           window. Zero = the flag was not proven ON: INCONCLUSIVE, never a pass.
  usable   a sample with ``mode_key == "arena"``, the player alive
           (``liveclient.hp > 0``) and both game times numeric. None usable =
           NO_RESULT.
  lag      ``liveclient.game_time_s - coach game_time_s``. PASS iff proof holds
           and no usable sample lags over 150 s.
  coverage (tool-side preconditions; each can only turn a PASS into
           INCONCLUSIVE). A coach file AHEAD of the live clock by more than 30 s
           is another game's file, not a fresh one. The KNOWN samples (usable,
           or dead: arena, ``hp == 0`` with ``hp_max > 0``, a numeric game time)
           must tile the whole window, both edges included, with no gap over
           35 s (the row's 20-30 s cadence plus 5 s of poll jitter); a failed
           poll is unknown, never dead, so it cannot excuse a gap. A dead run
           (consecutive dead samples) may not span over 120 s, since a missing
           ``currentHealth`` also reads as 0. The window must hold the WHOLE
           game: the first known sample's game time is at most 60 s, and the
           first poll after the last known sample comes within 35 s and shows
           the game over (``mode_key`` not arena, or no live game time).
  excuse   a lag over 150 s is INCONCLUSIVE if its window (the ``lag_s`` seconds
           before the sample) holds an ``Arena coach error`` line, an
           ``Arena: no fields parsed`` line, or overlaps a ``coach_tick_trace``
           call with ``mode == "arena"``, ``phase == "coach"`` and
           ``dur_ms > 20000`` (the record's ``ts`` is the call's END, so the call
           spans ``ts - dur_ms`` to ``ts``). The budget and kill-switch gates
           return SILENTLY (no log line), so an unexcused lag is FAIL only when
           the operator asserts both clear with ``--budget-ok``; without it the
           lag stays INCONCLUSIVE. A missing ``--trace`` file cannot rule a slow
           call out (trace writes are best-effort), so it also keeps an
           unexcused lag INCONCLUSIVE. The measured lag over-states the lag at
           the coach-file read by up to the sample's ``get_s``, so an unexcused
           lag is also INCONCLUSIVE when ``lag_s - get_s`` is within the bound,
           or when the sample carries no ``get_s`` (RM-1345). A vision-read
           failure is off the coach write path and excuses nothing.

The coherence half (does reused text still fit the board?) stays an operator
eyeball and is not graded here.

READ-ONLY: GETs the local dashboard and reads files. It prints game times, lags
and log excerpts only, never a Riot id, game id or match key, and never ticks a
row - its output is the INPUT to the four-part evidence contract.

USAGE (from the main checkout, RC started with RC_ARENA_STATE_DEBOUNCE=1)
    python tools/gated_g506_debounce_lag.py sample --interval 25 > <scratch>/g506.jsonl
    python tools/gated_g506_debounce_lag.py grade --samples <scratch>/g506.jsonl \
        --log logs/<date>.log --since <HH:MM:SS> --until <HH:MM:SS> [--budget-ok]
Exit 0 = PASS, 1 = INCONCLUSIVE / NO_RESULT, 2 = FAIL.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import ssl
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

_ROOT = Path(__file__).resolve().parent.parent
LAG_BOUND_S = 150.0
SLOW_CALL_MS = 20000.0
AHEAD_TOL_S = 30.0
MAX_GAP_S = 35.0
MAX_DEAD_RUN_S = 120.0
START_GT_MAX_S = 60.0
PROOF_MARK = "Arena state-debounce: signature unchanged"
EXCUSE_MARKS = ("Arena coach error", "Arena: no fields parsed")
_LOG_LINE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?\s")
_LOG_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def make_sample(state: Any, coach: Any, wall: datetime, get_s: float | None = None) -> dict[str, Any]:
    """One sample row from an /api/state document and the coach file document.

    ``get_s`` is the sampler's own span from the coach-file read to the end of
    the ``/api/state`` GET (RM-1345): the measured lag can exceed the true lag
    at the read by at most that much.
    """
    state = state if isinstance(state, dict) else {}
    lc = state.get("liveclient") if isinstance(state.get("liveclient"), dict) else {}
    coach = coach if isinstance(coach, dict) else {}
    lc_gt, co_gt = _num(lc.get("game_time_s")), _num(coach.get("game_time_s"))
    span = _num(get_s)
    return {
        "wall": wall.isoformat(timespec="seconds"),
        "error": state.get("error"),
        "mode_key": state.get("mode_key"),
        "lc_game_time_s": lc_gt,
        "coach_game_time_s": co_gt,
        "hp": _num(lc.get("hp")),
        "hp_max": _num(lc.get("hp_max")),
        "lag_s": round(lc_gt - co_gt, 1) if lc_gt is not None and co_gt is not None else None,
        "get_s": round(span, 3) if span is not None and span >= 0 else None,
    }


def get_slack(s: dict, lag: float, bound: float) -> str | None:
    """Why an otherwise unexcused over-bound lag is not a FAIL on the sampler's own timing, or None.

    The sampler reads the coach file FIRST and the live clock at the end of the
    GET, so the measured lag over-states the lag at the read by up to ``get_s``.
    A sample without a recorded span (an older sampler) cannot rule that out.
    """
    span = _num(s.get("get_s"))
    if span is None or span < 0:
        return "no get_s on the sample: the sampler's GET time cannot be ruled out"
    if lag - span <= bound:
        return f"lag minus the {span:.1f} s read-to-GET span is within the {bound:.0f} s bound"
    return None


def _wall(s: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(s["wall"])
    except (KeyError, TypeError, ValueError):
        return None


def usable(s: Any) -> bool:
    return (isinstance(s, dict) and s.get("mode_key") == "arena" and (_num(s.get("hp")) or 0) > 0
            and _num(s.get("lc_game_time_s")) is not None and _num(s.get("lag_s")) is not None
            and _wall(s) is not None)


def _dead(s: Any) -> bool:
    return (isinstance(s, dict) and s.get("mode_key") == "arena" and _num(s.get("hp")) == 0
            and (_num(s.get("hp_max")) or 0) > 0
            and _num(s.get("lc_game_time_s")) is not None and _wall(s) is not None)


def _ended(s: Any) -> bool:
    """A clean poll (no GET error) that shows no Arena game running."""
    return (isinstance(s, dict) and not s.get("error") and _wall(s) is not None
            and (s.get("mode_key") != "arena" or _num(s.get("lc_game_time_s")) is None))


def log_date(path: Path, override: str | None = None) -> date:
    m = _LOG_DATE.search(override or path.name)
    if not m:
        raise ValueError(f"no YYYY-MM-DD in {override or path.name!r}; pass --date")
    return date(int(m[1]), int(m[2]), int(m[3]))


def parse_log(lines: Iterable[str], day: date) -> list[tuple[datetime, str]]:
    """(local time, line) for every timestamped log line; continuation lines are dropped."""
    out = []
    for line in lines:
        m = _LOG_LINE.match(line)
        if m:
            frac = (m[4] or "0").ljust(6, "0")
            out.append((datetime(day.year, day.month, day.day, int(m[1]), int(m[2]),
                                 int(m[3]), int(frac)), line.rstrip("\n")))
    return out


def slow_calls(trace_rows: Iterable[dict]) -> list[tuple[datetime, datetime]]:
    """(start, end) local times of slow Arena coach calls; the trace ``ts`` is the call's END."""
    out = []
    for r in trace_rows:
        if not (isinstance(r, dict) and r.get("mode") == "arena" and r.get("phase") == "coach"):
            continue
        ts, dur = _num(r.get("ts")), _num(r.get("dur_ms"))
        if ts is not None and dur is not None and dur > SLOW_CALL_MS:
            end = datetime.fromtimestamp(ts)
            out.append((end - timedelta(milliseconds=dur), end))
    return out


def coverage(samples: list[dict], rows: list[dict], window: list[dict],
             since: datetime, until: datetime) -> dict[str, Any]:
    """Tool-side preconditions: the known samples tile the whole game; no coach file from the future."""
    known = sorted((s for s in window if usable(s) or _dead(s)), key=_wall)
    walls = sorted({_wall(s) for s in known})
    points = [since, *walls, until]
    holes = [f"{a.isoformat(timespec='seconds')} -> {b.isoformat(timespec='seconds')}"
             for a, b in zip(points, points[1:]) if (b - a).total_seconds() > MAX_GAP_S]
    dead_runs, run = [], []
    for s in [*known, None]:
        if s is not None and _dead(s):
            run.append(_wall(s))
            continue
        if run and (run[-1] - run[0]).total_seconds() > MAX_DEAD_RUN_S:
            dead_runs.append(f"{run[0].isoformat(timespec='seconds')} -> {run[-1].isoformat(timespec='seconds')}")
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
        excuses += [f"coach_tick_trace slow arena coach call {a.isoformat(timespec='seconds')} -> "
                    f"{b.isoformat(timespec='seconds')}" for a, b in slow if a <= end and b >= start]
        if excuses:
            v, note = "INCONCLUSIVE", ""
        elif not budget_ok:
            v, note = "INCONCLUSIVE", "budget / kill-switch not asserted (--budget-ok)"
        elif not trace_ok:
            v, note = "INCONCLUSIVE", "no --trace file: a slow coach call cannot be ruled out"
        elif slack := get_slack(s, lag, LAG_BOUND_S):
            v, note = "INCONCLUSIVE", slack
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
    out = [f"G5-06 verdict: {rep['verdict']}",
           f"proof lines ({PROOF_MARK!r}): {rep['proof_lines']}"
           + ("  <- flag NOT proven ON" if rep["proof_lines"] == 0 else ""),
           f"samples: {rep['samples']} total, {rep['usable']} usable (arena, alive, both times)",
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


def _get_state(base: str, timeout: float = 8.0) -> Any:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # loopback mkcert dashboard, same as curl -k
    with urllib.request.urlopen(f"{base}/api/state", timeout=timeout, context=ctx) as r:
        return json.loads(r.read().decode("utf-8"))


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_jsonl(path: Path | None) -> list[dict]:
    """JSON lines from UTF-8 or a BOM-marked UTF-16 file (a PowerShell 5.1 ``>`` redirect)."""
    if path is None or not path.exists():
        return []
    raw = path.read_bytes()
    text = raw.decode("utf-16", errors="replace") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") \
        else raw.decode("utf-8-sig", errors="replace")
    rows = []
    for line in text.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _clock(day: date, hms: str) -> datetime:
    t = datetime.strptime(hms, "%H:%M:%S")
    return datetime(day.year, day.month, day.day, t.hour, t.minute, t.second)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("sample", help="live: print one JSON sample line per poll")
    sp.add_argument("--count", type=int, default=144, help="polls (default 60 min at 25 s); Ctrl-C stops")
    sp.add_argument("--interval", type=float, default=25.0)
    sp.add_argument("--base", default="https://127.0.0.1:8888")
    sp.add_argument("--coach-file", type=Path, default=_ROOT / "data" / "arena_coaching_data.json")
    gp = sub.add_parser("grade", help="post-game: grade a samples file")
    gp.add_argument("--samples", type=Path, required=True)
    gp.add_argument("--log", type=Path, required=True)
    gp.add_argument("--date", default=None, help="YYYY-MM-DD when the log name carries none")
    gp.add_argument("--trace", type=Path, default=_ROOT / "data" / "coach_tick_trace.jsonl")
    gp.add_argument("--since", required=True, help="HH:MM:SS local, game clock start")
    gp.add_argument("--until", required=True, help="HH:MM:SS local, game end")
    gp.add_argument("--budget-ok", action="store_true",
                    help="operator asserts the daily budget was not exhausted and arena not kill-switched")
    gp.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "sample":
        t0 = time.monotonic()  # fixed-rate schedule: a slow GET does not stretch the cadence
        try:
            for i in range(max(a.count, 0)):
                r0 = time.monotonic()
                coach = _read_json(a.coach_file)  # coach file FIRST: GET delay can only enlarge the lag
                try:
                    state = _get_state(a.base)
                except (OSError, ValueError) as e:
                    state = {"error": type(e).__name__}
                span = time.monotonic() - r0  # recorded so grade can discount it (RM-1345)
                print(json.dumps(make_sample(state, coach, datetime.now(), span)), flush=True)
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
        print(f"G5-06 verdict: NO_RESULT (log or window unreadable: {e})")
        return 1
    rep = grade(_read_jsonl(a.samples), log, slow_calls(_read_jsonl(a.trace)),
                since, until, a.budget_ok, trace_ok=a.trace.is_file())
    print(json.dumps(rep, indent=2) if a.json else render(rep))
    return {"PASS": 0, "FAIL": 2}.get(rep["verdict"], 1)


if __name__ == "__main__":
    sys.exit(main())
