"""gated_bench_swap_probe.py - measure the G3-01 (E7a / E7 TODO-1) bench swap.

G3-01 in ``docs/LIVE_GAME_GATED_SYNC.md`` asked for an eyeball: "click a bench
champ in a real ARAM champ-select and confirm the swap registers visibly
faster". "Visibly faster" is not a predicate. This tool turns it into one, from
two clocks that live in the SAME process (``tools/lcu_agent.py``):

  T_cmd   the asctime of the agent's ``[cmd] bench_swap -> {...}`` log line in
          ``logs/lcu_agent.log`` (written right after the LCU POST returns,
          ``drain_once``), and
  ts      the ``ts`` of each LCU capture the agent pushes to the :8889 relay
          (``GET /latest-lcu`` -> ``data.ts``, stamped at the END of
          ``shape_snapshot``), polled here every ``--poll`` seconds.

THE DISCRIMINATOR. ``_state_push_loop`` waits INTERVAL (1.0 s) between
captures, so with ONE agent every natural capture-to-capture gap is longer than
INTERVAL. E7 TODO-1 makes ``_signal_state_refresh`` set ``_swap_wake`` after a
bench-swap drain, which ends that wait early, so a gap shorter than INTERVAL is
the wake. A natural tick that merely lands soon after the click looks fast too
(a quarter to half the time), so a small latency alone proves nothing.

PREDICATE (stated before any live look; one verdict per ``[cmd] bench_swap``):
  WAKE    a capture after T_cmd whose gap to the capture before it is under
          INTERVAL - WAKE_MARGIN_S (absolute, so a missed poll, which only
          widens gaps, can never fake one).
  g_nat   median of the baseline gaps (captures in the BASELINE_WINDOW_S before
          T_cmd, gaps over MISSED_POLL_GAP_S dropped as missed polls; at least
          MIN_BASELINE_GAPS, else NO_RESULT). Any baseline gap that is itself
          a WAKE means a second writer or another wake (reroll / accept_ready,
          a second agent process): NO_RESULT.
  c_est   max(0, g_nat - INTERVAL), the capture duration.
  N       the first capture after T_cmd whose ``champ_select.my_champion``
          differs from the last pre-click value (and is not 0);
  L       N.ts - T_cmd.
  PASS       N is a WAKE AND L <= 2 * c_est + LAT_SLACK_S (2 * c_est covers a
             click that lands mid-capture).
  FAIL       the polls were dense (no poll-to-poll gap over MAX_POLL_GAP_S from
             T_cmd to the decision point) and NO WAKE appeared from T_cmd to N
             (or to the NEW_CAPTURE_DEADLINE_S deadline when the champion never
             changed after an ok POST). A WAKE that still shows the old champion
             means the LCU applied the swap late: NO_RESULT, not FAIL. So does
             any capture within 2 * c_est + LAT_SLACK_S of T_cmd that still shows
             the old champion: the click may have landed mid-capture, and the
             woken capture after it can live in the relay for less than one poll,
             which hides the wake (a missed capture can hide a wake, never fake one).
  NO_RESULT  everything else: the POST failed (ok False), no baseline, a
             second writer, sparse polls, the watch ended before the deadline,
             or a natural tick inside the latency bound (coincidence).
  Row G3-01 PASS = at least one PASS and zero FAIL across the watch.

A swap made in the League CLIENT writes no ``[cmd] bench_swap`` line and
exercises none of E7a: the click must be on the RC dashboard bench strip
(``web/js/panels/champ_select.js`` ``.csv-bench-cell`` -> ``lcuCmd``).
``RC_LCU_INPROCESS`` does not matter here: the dashboard only READS the relay;
the agent's ``/upload-lcu`` push is its only writer, and the second-writer
check above covers a duplicate agent. Both ``lcu_agent.log`` and its ``.1``
rollover are read. The asctime is local time: in the one ambiguous hour when
clocks go back, ``mktime`` may be off by 3600 s and every event is NO_RESULT.

READ-ONLY: it GETs the relay and reads the agent log. It never writes, never
restarts and never ticks a row.

USAGE (from the main checkout, where the vision token and the log live)
    python tools/gated_bench_swap_probe.py --watch 90       # then click the bench
    python tools/gated_bench_swap_probe.py --watch 90 --json
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from tools import gated_live_probe as _probe  # noqa: E402

INTERVAL = 1.0  # tools/lcu_agent.py INTERVAL (state-push cadence)
WAKE_MARGIN_S = 0.05
BASELINE_WINDOW_S = 10.0
MIN_BASELINE_GAPS = 3
MISSED_POLL_GAP_S = 1.9
MAX_POLL_GAP_S = 0.3
LAT_SLACK_S = 0.25
NEW_CAPTURE_DEADLINE_S = 3.0

_LOG = _REPO / "logs" / "lcu_agent.log"
_CMD_RE = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),(\d{3}) \w+\s+\[cmd(?:-exc)?\] bench_swap -> (.*)$")


def parse_bench_swap_events(log_text: str) -> list[dict]:
    """Every ``[cmd] bench_swap`` / ``[cmd-exc] bench_swap`` line as
    {"t": epoch seconds (local asctime), "ok": bool, "result": raw text}."""
    out = []
    for line in log_text.splitlines():
        m = _CMD_RE.match(line.strip("\r"))
        if not m:
            continue
        stamp, ms, result = m.groups()
        t = time.mktime(time.strptime(stamp, "%Y-%m-%d %H:%M:%S")) + int(ms) / 1000.0
        out.append({"t": t, "ok": "'ok': True" in result, "result": result})
    return out


def capture_row(data: dict) -> dict | None:
    """One relay ``data`` payload -> the fields the predicate reads."""
    if not isinstance(data, dict) or not isinstance(data.get("ts"), (int, float)):
        return None
    cs = data.get("champ_select") or {}
    return {
        "ts": float(data["ts"]),
        "phase": data.get("phase"),
        "my_champion": cs.get("my_champion") if isinstance(cs, dict) else None,
        "bench": list(cs.get("bench") or []) if isinstance(cs, dict) else [],
        "queue_id": cs.get("queue_id") if isinstance(cs, dict) else None,
    }


def dedupe_captures(rows: list[dict | None]) -> list[dict]:
    """Distinct captures by ts, oldest first (many polls see one capture)."""
    seen: dict[float, dict] = {}
    for r in rows:
        if r is not None:
            seen.setdefault(r["ts"], r)
    return [seen[k] for k in sorted(seen)]


def _is_wake(gap: float) -> bool:
    return gap < INTERVAL - WAKE_MARGIN_S


def _polls_dense(polls: list[float] | None, lo: float, hi: float) -> bool:
    """True iff the probe polled with no gap over MAX_POLL_GAP_S across [lo, hi]."""
    if not polls:
        return False
    inside = [t for t in polls if lo <= t <= hi]
    edges = [max([t for t in polls if t < lo], default=None),
             min([t for t in polls if t > hi], default=None)]
    if None in edges:
        return False
    pts = [edges[0], *inside, edges[1]]
    return max(b - a for a, b in zip(pts, pts[1:])) <= MAX_POLL_GAP_S


def evaluate_swap(caps: list[dict], event: dict, polls: list[float] | None = None) -> dict:
    """Apply the module-docstring predicate to one bench-swap event.

    ``polls`` are the probe's own poll times; without them no FAIL is possible."""
    t_cmd = event["t"]
    res = {"t_cmd": round(t_cmd, 3), "ok": event["ok"]}

    def _done(verdict: str, reason: str, **kw) -> dict:
        res.update(kw)
        res["verdict"] = verdict
        res["reason"] = reason
        return res

    if not event["ok"]:
        return _done("NO_RESULT", "swap POST did not return ok (no latency to measure)")
    before = [c for c in caps if c["ts"] <= t_cmd]
    if not before:
        return _done("NO_RESULT", "no capture before the click")
    window = [c["ts"] for c in before if c["ts"] >= t_cmd - BASELINE_WINDOW_S]
    raw = [b - a for a, b in zip(window, window[1:])]
    if any(_is_wake(g) for g in raw):
        return _done("NO_RESULT", "off-cadence captures before the click (second writer or other wake)")
    gaps = [g for g in raw if g <= MISSED_POLL_GAP_S]
    if len(gaps) < MIN_BASELINE_GAPS:
        return _done("NO_RESULT", f"baseline has {len(gaps)} gaps, need {MIN_BASELINE_GAPS}")
    g_nat = statistics.median(gaps)
    c_est = max(0.0, g_nat - INTERVAL)
    lat_max = 2 * c_est + LAT_SLACK_S
    prev = before[-1]["my_champion"]
    res.update(g_nat=round(g_nat, 3), c_est=round(c_est, 3), lat_max=round(lat_max, 3),
               champion_before=prev)
    after = [i for i, c in enumerate(caps) if c["ts"] > t_cmd]
    wakes = [caps[i]["ts"] for i in after if _is_wake(caps[i]["ts"] - caps[i - 1]["ts"])]
    early_old = any(caps[i]["ts"] - t_cmd <= lat_max and caps[i]["my_champion"] == prev
                    for i in after)
    new_i = next((i for i in after if caps[i]["my_champion"] not in (prev, 0, None)), None)
    if new_i is None or caps[new_i]["ts"] - t_cmd > NEW_CAPTURE_DEADLINE_S:
        deadline = t_cmd + NEW_CAPTURE_DEADLINE_S
        if not caps or caps[-1]["ts"] < deadline:
            return _done("NO_RESULT", "watch ended before the deadline")
        if any(t <= deadline for t in wakes):
            return _done("NO_RESULT", "a wake fired but the champion never changed (LCU side)")
        if early_old:
            return _done("NO_RESULT", "an early capture still showed the old pick (a wake may be hidden)")
        if not _polls_dense(polls, t_cmd, deadline):
            return _done("NO_RESULT", "polls too sparse to rule out a missed wake")
        return _done("FAIL", f"champion unchanged {NEW_CAPTURE_DEADLINE_S} s after the click")
    n = caps[new_i]
    lat = n["ts"] - t_cmd
    gap = n["ts"] - caps[new_i - 1]["ts"]
    wake = _is_wake(gap)
    # bench_after rides along for G3-02 (rendered bench vs the LCU bench).
    res.update(champion_after=n["my_champion"], latency_s=round(lat, 3),
               gap_s=round(gap, 3), wake=wake, queue_id=n.get("queue_id"),
               bench_after=n.get("bench"))
    if wake and lat <= lat_max:
        return _done("PASS", "a wake capture showed the new pick within the bound")
    if wake:
        return _done("NO_RESULT", "a wake capture, but slower than the bound (re-run the swap)")
    if any(t < n["ts"] for t in wakes):
        return _done("NO_RESULT", "a wake fired before the LCU showed the swap")
    if lat <= lat_max:
        return _done("NO_RESULT", "a natural tick landed inside the bound (coincidence)")
    if early_old:
        return _done("NO_RESULT", "an early capture still showed the old pick (a wake may be hidden)")
    if not _polls_dense(polls, t_cmd, n["ts"]):
        return _done("NO_RESULT", "polls too sparse to rule out a missed wake")
    return _done("FAIL", "no wake: the new pick waited for a natural tick")


def row_verdict(results: list[dict]) -> str:
    """G3-01 PASS iff at least one PASS and no FAIL."""
    verdicts = [r["verdict"] for r in results]
    if "FAIL" in verdicts:
        return "FAIL"
    return "PASS" if "PASS" in verdicts else "NO_RESULT"


def watch(seconds: float, poll: float) -> tuple[list[dict], list[float]]:
    """Poll the relay for ``seconds``; return (distinct captures, poll times)."""
    url = f"{_probe._RELAY_BASE}/latest-lcu"
    token = _probe._relay_token()
    rows, polls = [], []
    start = time.time()
    while time.time() - start < seconds:
        wrap, _err = _probe._get_json(url, token)
        if isinstance(wrap, dict):
            rows.append(capture_row(wrap.get("data") or {}))
            polls.append(time.time())
        time.sleep(poll)
    return dedupe_captures(rows), polls


def _read_logs(path: Path) -> str:
    parts = []
    for p in (path.with_name(path.name + ".1"), path):
        try:
            parts.append(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--watch", type=float, default=90.0, help="seconds to watch")
    ap.add_argument("--poll", type=float, default=0.05, help="relay poll period")
    ap.add_argument("--log", type=Path, default=_LOG, help="lcu_agent.log path")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    caps, polls = watch(a.watch, a.poll)
    start, end = (polls[0], polls[-1]) if polls else (0.0, 0.0)
    events = [e for e in parse_bench_swap_events(_read_logs(a.log)) if start <= e["t"] <= end]
    results = [evaluate_swap(caps, e, polls) for e in events]
    gaps = [b["ts"] - a_["ts"] for a_, b in zip(caps, caps[1:])]
    out = {
        "window": [round(start, 3), round(end, 3)],
        "captures": len(caps),
        "median_gap_s": round(statistics.median(gaps), 3) if gaps else None,
        "max_poll_gap_s": round(max(b - a_ for a_, b in zip(polls, polls[1:])), 3)
        if len(polls) > 1 else None,
        "phases": sorted({str(c["phase"]) for c in caps}),
        "events": results,
        "row_verdict": row_verdict(results),
    }
    if a.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"captures {out['captures']}  median gap {out['median_gap_s']} s  "
              f"max poll gap {out['max_poll_gap_s']} s  phases {out['phases']}")
        for r in results:
            print(f"  {r['verdict']:9} L={r.get('latency_s')} gap={r.get('gap_s')} "
                  f"g_nat={r.get('g_nat')} - {r['reason']}")
        print(f"G3-01 row verdict: {out['row_verdict']}"
              + ("" if results else " (no dashboard bench_swap in the window)"))
    return 0 if caps else 1


if __name__ == "__main__":
    sys.exit(main())
