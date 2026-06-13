#!/usr/bin/env python3
"""tools/cost_health_watchdog.py - self-healing cost + health watchdog.

Runs every 15 minutes (RC-CostHealthWatchdog scheduled task). Probes:

  - RC daemon health      (ops/runtime/health.json)
  - bridge connectivity   (ops/runtime/bridge_watcher_health.json)
  - tracked API spend     (data/spend/YYYY-MM-DD.json) vs a trailing baseline

Detects a cost breach (today > 1.5x trailing-median baseline, with an absolute
floor so an idle day cannot false-positive against a near-zero baseline), a
per-lane cost escalation (a purpose lane whose mean USD/call >= 2x its
trailing-baseline cost/call week-over-week - the disk proxy for the
rc_coach_cost_usd_per_call p95 doubling), or a daemon flap (>=3 pid changes
inside the rolling window, or alive=false, or last_reload_ok=false). On any of
these it CLASSIFIES the hot spend purpose to the Sonnet/Haiku caller file (from
docs/COST_TRACE.md) and emits a concrete remediation proposal (debounce /
interval / pythonw / prompt-size+cache review).

It NEVER silently restarts or edits code. Cron mode only detects + logs +
proposes. --remediate (opt-in, never used by the cron) may apply ONE bounded,
fully-logged config debounce (lower vision_calls_per_min toward a floor); it
still never touches code and never restarts a process.

Exit 0 = healthy, 1 = breach/flap detected (so a wrapper can alert).
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

_APP = Path(__file__).parent.parent
_HEALTH = _APP / "ops" / "runtime" / "health.json"
_BRIDGE = _APP / "ops" / "runtime" / "bridge_watcher_health.json"
_SPEND_DIR = _APP / "data" / "spend"
_STATE = _APP / "ops" / "runtime" / "cost_health_watchdog_state.json"
_LOG = _APP / "logs" / "cost_health_watchdog.log"
_COACH_CFG = _APP / "config" / "coach_settings.json"

BREACH_MULT = 1.5
FLOOR_ABS_USD = 0.50          # below this, never call it a breach (idle noise)
FLAP_WINDOW_S = 3600.0        # rolling window for pid-change counting
FLAP_PID_CHANGES = 3          # >=3 pid changes in window == flap. Two clean
                              # restarts in a dev/fix session (e.g. a
                              # restart_trigger.txt double-bounce) is benign;
                              # the supervisor relaunches a crashed daemon
                              # within ~5s so a genuine crash loop yields far
                              # more than two changes/hour. alive=false /
                              # last_reload_ok=false still flap immediately,
                              # independent of count.
VISION_RATE_FLOOR = 3.0       # --remediate will not push below this
P95_DOUBLE_MULT = 2.0         # per-lane p95-cost >= 2x trailing baseline == signal
P95_FLOOR_USD = 0.002         # ignore lanes whose p95 is below this (sub-cent noise)
P95_MIN_CALLS = 20            # need this many calls today for a stable p95

# purpose -> (tier, primary caller file) from docs/COST_TRACE.md.
PURPOSE_MAP = {
    "vision_relay":   ("SONNET", "vision_server/_inference.py:141"),
    "vision_direct":  ("SONNET", "modes/shared_vision.py:251"),
    "coach_relay":    ("HAIKU",  "vision_server/_inference.py:176"),
    "sr_coach":       ("HAIKU",  "coach_integration/_coach.py:354"),
    "aram_coach":     ("HAIKU",  "coaches/aram_coach.py:743"),
    "arena_coach":    ("HAIKU",  "coaches/arena_coach.py:587"),
    "brawl_coach":    ("HAIKU",  "coaches/brawl_coach.py:439"),
}


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _finite(val, default: float = 0.0) -> float:
    """Coerce a ledger value to a FINITE float.

    A corrupt spend ledger can carry a non-finite ``total_usd`` / per-lane
    ``usd`` / ``calls`` (NaN or +/-Infinity - e.g. a divide-by-zero that leaked
    into the ledger writer). Left unguarded those poison this watchdog two ways:
    (1) every threshold comparison against a NaN is False, so a corrupt ledger
    silently DISABLES breach detection; and (2) ``json.dumps`` serializes them as
    the bare ``NaN`` / ``Infinity`` tokens, which are invalid JSON per RFC 8259 -
    so the watchdog's own stdout report and persisted state file would break any
    strict downstream parser (JS ``JSON.parse``, a Go/Rust cron wrapper). Coerce
    every ledger numeric through here so the math stays sound and the emitted
    JSON stays strict."""
    try:
        f = float(val)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _atomic_write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


def _age_s(ts):
    if ts is None:
        return None
    try:
        if isinstance(ts, (int, float)):
            return max(0.0, time.time() - float(ts))
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
    except (ValueError, TypeError):
        return None


def probe_health(path: Path = _HEALTH) -> dict:
    h = _read_json(path, {})
    return {
        "ok": bool(h),
        "pid": h.get("pid"),
        "alive": bool(h.get("alive")),
        "last_reload_ok": bool(h.get("last_reload_ok", True)),
        "mode": h.get("mode"),
        "age_s": _age_s(h.get("updated_at")),
    }


def probe_bridge(path: Path = _BRIDGE) -> dict:
    b = _read_json(path, {})
    return {
        "ok": bool(b),
        "alive": bool(b.get("alive")),
        "last_poll_ok": bool(b.get("last_poll_ok", True)),
        "queue_depth": b.get("queue_depth"),
        "age_s": _age_s(b.get("updated_at")),
    }


def spend_baseline(spend_dir: Path, today: str) -> dict:
    """today_usd, trailing median baseline (prior days > 0, up to 7), breach."""
    today_doc = _read_json(spend_dir / (today + ".json"), {})
    today_usd = _finite(today_doc.get("total_usd", 0.0) or 0.0)
    prior = []
    for f in sorted(spend_dir.glob("*.json")):
        if f.stem == today:
            continue
        v = _finite(_read_json(f, {}).get("total_usd", 0.0) or 0.0)
        if v > 0:
            prior.append(v)
    prior = prior[-7:]
    baseline = statistics.median(prior) if prior else 0.0
    breach = (
        today_usd > FLOOR_ABS_USD
        and baseline > 0
        and today_usd > BREACH_MULT * baseline
    )
    return {
        "today_usd": round(today_usd, 6),
        "baseline_usd": round(baseline, 6),
        "samples": len(prior),
        "breach": breach,
        "by_purpose": today_doc.get("by_purpose", {}),
    }


def percentile(samples: list[float] | tuple[float, ...], pct: float) -> float:
    """Nearest-rank percentile of `samples` (0 < pct <= 100).

    Pure, dependency-free. rank = ceil(pct/100 * N), 1-indexed into the
    sorted sample list (clamped to [1, N]). Hand-checkable: for the 20-value
    list 1..20, p95 -> ceil(0.95*20)=19 -> sorted[18] == 19; p50 ->
    ceil(0.50*20)=10 -> sorted[9] == 10. Empty -> 0.0.
    """
    vals = sorted(float(s) for s in samples)
    n = len(vals)
    if n == 0:
        return 0.0
    if pct <= 0:
        return vals[0]
    if pct >= 100:
        return vals[-1]
    import math
    rank = math.ceil((pct / 100.0) * n)
    rank = max(1, min(rank, n))
    return vals[rank - 1]


def _lane_mean_cost(doc: dict) -> dict:
    """{purpose -> mean usd/call} for one day's ledger doc. Lanes with 0
    calls are skipped (no meaningful per-call cost)."""
    out = {}
    for name, pb in (doc.get("by_purpose") or {}).items():
        calls = _finite(pb.get("calls", 0) or 0)
        usd = _finite(pb.get("usd", 0.0) or 0.0)
        if calls > 0:
            out[name] = usd / calls
    return out


def lane_cost_signals(spend_dir: Path, today: str) -> dict:
    """Per-lane week-over-week cost-per-call escalation.

    The ledger keeps per-day per-lane (usd, calls) aggregates, not per-call
    samples, so the stable available proxy for "p95 cost on this lane" is the
    lane's mean cost per call for the day; we compare today's per-lane mean
    against the trailing-median of prior days' per-lane means and flag any
    lane that has at least P95_MIN_CALLS calls today, a today-cost above
    P95_FLOOR_USD, a positive baseline, and today >= P95_DOUBLE_MULT x
    baseline. `percentile()` is exposed for callers that DO have a per-call
    sample (e.g. scraping the rc_coach_cost_usd_per_call histogram buckets);
    this aggregate path is what the cron can compute from disk.
    """
    today_doc = _read_json(spend_dir / (today + ".json"), {})
    today_means = _lane_mean_cost(today_doc)
    today_calls = {
        name: _finite((today_doc.get("by_purpose") or {})
                      .get(name, {}).get("calls", 0) or 0)
        for name in today_means
    }
    prior_series: dict = {}
    for f in sorted(spend_dir.glob("*.json")):
        if f.stem == today:
            continue
        for name, mean in _lane_mean_cost(_read_json(f, {})).items():
            prior_series.setdefault(name, []).append(mean)
    flagged = []
    lanes = {}
    for name, today_mean in sorted(today_means.items()):
        prior = prior_series.get(name, [])[-7:]
        baseline = statistics.median(prior) if prior else 0.0
        doubled = (
            today_calls.get(name, 0) >= P95_MIN_CALLS
            and today_mean > P95_FLOOR_USD
            and baseline > 0
            and today_mean >= P95_DOUBLE_MULT * baseline
        )
        lanes[name] = {
            "today_cost_per_call": round(today_mean, 8),
            "baseline_cost_per_call": round(baseline, 8),
            "samples": len(prior),
            "calls_today": int(today_calls.get(name, 0)),
            "doubled": doubled,
        }
        if doubled:
            flagged.append(name)
    return {
        "p95_doubled": bool(flagged),
        "flagged_lanes": flagged,
        "lanes": lanes,
    }


def detect_flap(prev_state: dict, health: dict, now: float) -> dict:
    """Track pid changes in a rolling window. Flap = >=N changes, or
    alive=false, or last_reload_ok=false."""
    changes = [
        t for t in prev_state.get("pid_change_ts", [])
        if now - t <= FLAP_WINDOW_S
    ]
    last_pid = prev_state.get("last_pid")
    cur_pid = health.get("pid")
    if last_pid is not None and cur_pid is not None and cur_pid != last_pid:
        changes.append(now)
    flap = (
        len(changes) >= FLAP_PID_CHANGES
        or not health.get("alive", True)
        or not health.get("last_reload_ok", True)
    )
    return {
        "flap": flap,
        "pid_changes_in_window": len(changes),
        "pid_change_ts": changes,
        "last_pid": cur_pid if cur_pid is not None else last_pid,
    }


def classify(by_purpose: dict) -> dict:
    """Hottest purpose by usd -> tier, caller file, remediation proposal."""
    if not by_purpose:
        return {"hot_purpose": None, "tier": None, "file": None,
                "proposal": "no per-purpose data; inspect data/spend"}
    hot = max(by_purpose.items(),
              key=lambda kv: float(kv[1].get("usd", 0.0) or 0.0))
    name = hot[0]
    tier, fil = PURPOSE_MAP.get(name, ("UNKNOWN", "unmapped"))
    if tier == "SONNET":
        prop = ("hot SONNET purpose '" + name + "' (" + fil + "); debounce "
                "vision: lower vision_calls_per_min in "
                "config/coach_settings.json toward "
                + str(VISION_RATE_FLOOR) + "/min, verify the 2s frame dedupe "
                "is hitting (core/cost_tracker.vision_dedupe_*)")
    elif tier == "HAIKU":
        prop = ("hot HAIKU purpose '" + name + "' (" + fil + "); widen the "
                "coach poll interval / add a same-state debounce so identical "
                "game snapshots do not re-pay a Haiku call")
    else:
        prop = ("unmapped purpose '" + name + "'; trace its messages.create "
                "and wire it through cost_tracker.record_call, then debounce")
    return {"hot_purpose": name, "tier": tier, "file": fil, "proposal": prop}


def _log_line(text: str) -> None:
    try:
        _LOG.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).isoformat()
        with _LOG.open("a", encoding="utf-8") as fh:
            fh.write(stamp + " " + text + "\n")
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--remediate", action="store_true",
                    help="apply ONE bounded, logged config debounce "
                         "(never used by the cron; never edits code)")
    ap.add_argument("--spend-dir", default=str(_SPEND_DIR))
    ap.add_argument("--state", default=str(_STATE))
    args = ap.parse_args(argv)

    now = time.time()
    state_path = Path(args.state)
    prev = _read_json(state_path, {})
    health = probe_health()
    bridge = probe_bridge()
    spend = spend_baseline(Path(args.spend_dir), date.today().isoformat())
    lanes = lane_cost_signals(Path(args.spend_dir), date.today().isoformat())
    flap = detect_flap(prev, health, now)
    if spend["breach"] or flap["flap"] or lanes["p95_doubled"]:
        cls = classify(spend["by_purpose"])
        if lanes["p95_doubled"]:
            ln = ", ".join(lanes["flagged_lanes"])
            tier, fil = next(
                (PURPOSE_MAP.get(p, ("UNKNOWN", "unmapped"))
                 for p in lanes["flagged_lanes"]
                 if p in PURPOSE_MAP),
                ("UNKNOWN", "unmapped"))
            cls["p95_proposal"] = (
                "per-call cost on lane(s) [" + ln + "] >= "
                + str(P95_DOUBLE_MULT) + "x the trailing baseline cost/call "
                "(week-over-week escalation; primary " + tier + " "
                + fil + "). Inspect prompt/token growth on that lane: a "
                "fatter system prompt, lost cache_control ephemeral marker, "
                "or larger context per call. Detect+log only; propose a "
                "prompt-size / cache-hit review, do not auto-restart")
    else:
        cls = {"hot_purpose": None, "tier": None, "file": None,
               "proposal": None}

    breached = bool(spend["breach"] or flap["flap"] or lanes["p95_doubled"])
    incidents = list(prev.get("incidents", []))[-49:]
    if breached:
        incident = {
            "at": datetime.now(timezone.utc).isoformat(),
            "cost_breach": spend["breach"],
            "flap": flap["flap"],
            "p95_doubled": lanes["p95_doubled"],
            "p95_flagged_lanes": lanes["flagged_lanes"],
            "today_usd": spend["today_usd"],
            "baseline_usd": spend["baseline_usd"],
            "pid_changes_in_window": flap["pid_changes_in_window"],
            "health_alive": health["alive"],
            "last_reload_ok": health["last_reload_ok"],
            "classification": cls,
            "remediated": False,
        }
        if args.remediate and spend["breach"] and cls["tier"] == "SONNET":
            cfg = _read_json(_COACH_CFG, {})
            cur = float(cfg.get("vision_calls_per_min", 6.0) or 6.0)
            new = max(VISION_RATE_FLOOR, round(cur * 0.66, 2))
            if new < cur:
                cfg["vision_calls_per_min"] = new
                _atomic_write_json(_COACH_CFG, cfg)
                incident["remediated"] = True
                incident["remediation"] = (
                    "vision_calls_per_min " + str(cur) + " -> " + str(new)
                    + " (logged, bounded; no restart, no code edit)")
                _log_line("REMEDIATE " + incident["remediation"])
        incidents.append(incident)
        _log_line("BREACH " + json.dumps({
            "cost": spend["breach"], "flap": flap["flap"],
            "p95_doubled": lanes["p95_doubled"],
            "p95_flagged_lanes": lanes["flagged_lanes"],
            "today_usd": spend["today_usd"],
            "baseline_usd": spend["baseline_usd"],
            "proposal": cls["proposal"],
            "p95_proposal": cls.get("p95_proposal")}))

    state = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "last_pid": flap["last_pid"],
        "pid_change_ts": flap["pid_change_ts"],
        "health": health,
        "bridge": bridge,
        "spend": {k: v for k, v in spend.items() if k != "by_purpose"},
        "lane_cost": lanes,
        "breached": breached,
        "incidents": incidents,
    }
    _atomic_write_json(state_path, state)

    print(json.dumps({
        "breached": breached,
        "cost_breach": spend["breach"],
        "flap": flap["flap"],
        "p95_doubled": lanes["p95_doubled"],
        "p95_flagged_lanes": lanes["flagged_lanes"],
        "today_usd": spend["today_usd"],
        "baseline_usd": spend["baseline_usd"],
        "health_alive": health["alive"],
        "bridge_alive": bridge["alive"],
        "proposal": cls["proposal"],
        "p95_proposal": cls.get("p95_proposal"),
    }))
    return 1 if breached else 0


if __name__ == "__main__":
    sys.exit(main())
