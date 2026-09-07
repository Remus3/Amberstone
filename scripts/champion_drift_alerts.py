"""
scripts/champion_drift_alerts.py - weekly drift report.

AUDIT 2026-04-28 (proposal 2.4): compare each champion's last 7 days of
real games against `data/coach_reference/champion_benchmarks.json`. If a
metric (CS@10, KDA, gold/min, kp_pct) has dropped > THRESHOLD vs the
champion's p50 - and we have at least MIN_GAMES recent samples - flag it.

Designed to run nightly as a scheduled remote agent (proposal 4.6 sister
job). Read-only; emits one line per drift to stdout and optionally writes
to data/coach_reference/drift_alerts.json.

Run:
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts/champion_drift_alerts.py
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts/champion_drift_alerts.py --json
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts/champion_drift_alerts.py --champ Vayne --days 14
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MATCH_DB     = ROOT / "data" / "match_history.db"
BENCHMARKS   = ROOT / "data" / "coach_reference" / "champion_benchmarks.json"
ALERTS_OUT   = ROOT / "data" / "coach_reference" / "drift_alerts.json"

DEFAULT_DAYS    = 7
DEFAULT_MIN_GAMES = 3
# Drift threshold: a metric has "drifted" if the recent p50 is this far
# below benchmark p50, expressed as (recent / benchmark) ratio.
DEFAULT_DROP_PCT = 10  # 10 % below benchmark = drift


def _bench() -> dict:
    if not BENCHMARKS.exists():
        return {"champions": {}}
    try:
        return json.loads(BENCHMARKS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"champions": {}}


def _recent_rows(days: int, champ: str = "") -> list[dict]:
    if not MATCH_DB.exists():
        return []
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(str(MATCH_DB))
    conn.row_factory = sqlite3.Row
    try:
        if champ:
            rows = conn.execute(
                "SELECT * FROM matches WHERE champion = ? AND timestamp >= ?",
                (champ, cutoff),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM matches WHERE timestamp >= ?",
                (cutoff,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _median(values: list[float]) -> float:
    # Drop None AND non-finite (inf/nan): SQLite stores IEEE-754 doubles, so a
    # corrupt/computed metric column can hold inf/nan. A nan in the sort poisons
    # the midpoint and inf propagates into pct_below -> a bare Infinity/NaN JSON
    # token in drift_alerts.json (json.dumps does not pass allow_nan=False).
    vs = sorted(v for v in values if v is not None and math.isfinite(v))
    if not vs:
        return 0.0
    n = len(vs)
    return vs[n // 2] if n % 2 else (vs[n // 2 - 1] + vs[n // 2]) / 2


def compute_drifts(*, days: int = DEFAULT_DAYS, min_games: int = DEFAULT_MIN_GAMES,
                   drop_pct: float = DEFAULT_DROP_PCT, champ: str = "") -> list[dict]:
    bench = _bench().get("champions", {})
    rows = _recent_rows(days, champ=champ)
    by_champ: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_champ[r.get("champion", "")].append(r)

    alerts: list[dict] = []
    metrics = [
        # (recent_field, benchmark_metric_key)
        ("cs_per_min",   "cs_per_min"),
        ("gold_per_min", "gold_per_min"),
        ("kp_pct",       "kp_pct"),
    ]
    for c, samples in by_champ.items():
        if not c or len(samples) < min_games:
            continue
        b = bench.get(c, {})
        for field, bm_key in metrics:
            recent_vals = [s.get(field) for s in samples if s.get(field) is not None]
            if not recent_vals:
                continue
            recent_p50 = _median(recent_vals)
            # Benchmarks are stored per-mode; we use sr_ranked as the
            # canonical reference here. Future: per-mode comparison.
            bm_record = ((b.get("sr_ranked") or {}).get(bm_key) or {})
            bm_p50 = bm_record.get("p50")
            # `bm_p50` is read straight from benchmarks JSON - guard non-finite
            # (a poisoned benchmark file) alongside the <=0 check before dividing.
            if not bm_p50 or not isinstance(bm_p50, (int, float)) \
                    or not math.isfinite(bm_p50) or bm_p50 <= 0:
                continue
            pct_below = (1.0 - recent_p50 / bm_p50) * 100.0
            if math.isfinite(pct_below) and pct_below >= drop_pct:
                alerts.append({
                    "champion":     c,
                    "metric":       bm_key,
                    "recent_p50":   round(recent_p50, 2),
                    "benchmark_p50": round(float(bm_p50), 2),
                    "pct_below":    round(pct_below, 1),
                    "samples":      len(recent_vals),
                    "window_days":  days,
                })
    alerts.sort(key=lambda a: a["pct_below"], reverse=True)
    return alerts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    ap.add_argument("--min-games", type=int, default=DEFAULT_MIN_GAMES)
    ap.add_argument("--drop-pct", type=float, default=DEFAULT_DROP_PCT)
    ap.add_argument("--champ", default="")
    ap.add_argument("--json", action="store_true",
                    help="Emit JSON only (machine-readable).")
    ap.add_argument("--out", type=Path, default=ALERTS_OUT,
                    help="Path to write JSON alerts (default: data/coach_reference/drift_alerts.json).")
    ap.add_argument("--no-write", action="store_true",
                    help="Don't persist alerts to --out.")
    args = ap.parse_args()

    alerts = compute_drifts(
        days=args.days, min_games=args.min_games,
        drop_pct=args.drop_pct, champ=args.champ,
    )
    if args.json:
        print(json.dumps({"alerts": alerts, "generated_at": datetime.now().isoformat()},
                         indent=2))
    else:
        if not alerts:
            print(f"No drift detected in last {args.days} day(s).")
        else:
            print(f"Found {len(alerts)} drift(s) (>{args.drop_pct}% below benchmark p50):")
            for a in alerts:
                print(f"  {a['champion']:<14} {a['metric']:<13} "
                      f"recent={a['recent_p50']:>7.2f}  bench={a['benchmark_p50']:>7.2f}  "
                      f"-{a['pct_below']}%  ({a['samples']} games)")

    if not args.no_write:
        try:
            from core.polled_json import atomic_write_json
            atomic_write_json(args.out, {
                "alerts": alerts,
                "generated_at": datetime.now().isoformat(),
            })
        except Exception as exc:  # noqa: BLE001
            print(f"warning: write {args.out}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
