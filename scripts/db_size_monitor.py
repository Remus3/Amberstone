"""
scripts/db_size_monitor.py - track RC's local-data growth.

Walks the key SQLite + JSONL files under data/ and writes the
results to data/coach_reference/db_sizes.json. Exit code is 0 when
all thresholds are clean, 1 when one or more breach (caller can pipe
into a /schedule routine that opens a PR with the report).

Thresholds (override via --max-rewind / --max-logs / --max-spend):
  rewind_history.db   2.0 GB     (audit anomaly 2026-04-28)
  logs/ aggregate     500   MB
  data/spend/         50    MB    (~ 5 years at current rate)

Run:
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts/db_size_monitor.py            # human-readable
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts/db_size_monitor.py --json     # machine-readable
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "coach_reference" / "db_sizes.json"

DEFAULT_THRESHOLDS = {
    "rewind_history.db": 2.0 * 1024 * 1024 * 1024,   # 2 GB
    "logs":              500 * 1024 * 1024,          # 500 MB
    "data/spend":         50 * 1024 * 1024,          #  50 MB
}


def _size(p: Path) -> int:
    if not p.exists():
        return 0
    if p.is_file():
        try: return p.stat().st_size
        except OSError: return 0
    total = 0
    try:
        for f in p.rglob("*"):
            if f.is_file():
                try: total += f.stat().st_size
                except OSError: pass
    except OSError:
        pass
    return total


def collect() -> dict:
    targets = [
        ("data/rewind_history.db", ROOT / "data" / "rewind_history.db"),
        ("data/match_history.db",  ROOT / "data" / "match_history.db"),
        ("data/match_metrics.db",  ROOT / "data" / "match_metrics.db"),
        ("data/decisions.db",      ROOT / "data" / "decisions.db"),
        ("data/db (per-mode)",     ROOT / "data" / "db"),
        ("data/coach_trace.jsonl", ROOT / "data" / "coach_trace.jsonl"),
        ("data/spend",             ROOT / "data" / "spend"),
        ("logs",                   ROOT / "logs"),
    ]
    rows = []
    for label, p in targets:
        rows.append({
            "label":  label,
            "path":   str(p.relative_to(ROOT)) if p.exists() else None,
            "exists": p.exists(),
            "bytes":  _size(p),
        })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows":         rows,
    }


def evaluate(report: dict, thresholds: dict) -> list[dict]:
    breaches = []
    by_label = {r["label"]: r for r in report["rows"]}
    rules = {
        "data/rewind_history.db": "rewind_history.db",
        "logs":                   "logs",
        "data/spend":             "data/spend",
    }
    for label, key in rules.items():
        cap = thresholds.get(key)
        if cap is None:
            continue
        row = by_label.get(label)
        if row and row["bytes"] > cap:
            breaches.append({
                "label":     label,
                "bytes":     row["bytes"],
                "threshold": cap,
                "over_by":   row["bytes"] - cap,
            })
    return breaches


def _fmt(b: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    f = float(b); i = 0
    while f >= 1024 and i < len(units) - 1:
        f /= 1024; i += 1
    return f"{f:6.2f} {units[i]}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--max-rewind-gb", type=float, default=2.0)
    ap.add_argument("--max-logs-mb",   type=float, default=500.0)
    ap.add_argument("--max-spend-mb",  type=float, default=50.0)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    thresholds = {
        "rewind_history.db": int(args.max_rewind_gb * 1024**3),
        "logs":              int(args.max_logs_mb   * 1024**2),
        "data/spend":        int(args.max_spend_mb  * 1024**2),
    }
    report = collect()
    breaches = evaluate(report, thresholds)
    report["breaches"] = breaches
    report["thresholds"] = thresholds

    if not args.no_write:
        try:
            OUT.parent.mkdir(parents=True, exist_ok=True)
            from core.polled_json import atomic_write_json
            atomic_write_json(OUT, report)
        except Exception as exc:  # noqa: BLE001
            print(f"warning: write {OUT}: {exc}", file=sys.stderr)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"DB / log sizes ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
        print("-" * 60)
        for r in report["rows"]:
            # ASCII only - this output is captured verbatim into the weekly
            # agent6 health report, which is committed and is asserted
            # byte-ASCII by tests/test_smart_quote_hygiene.py. A U+00D7 here
            # (the original marker) reached the repo on 2026-07-28 and turned
            # a scheduled task into a red suite.
            mark = "  " if r["exists"] else "x "
            print(f"  {mark}{r['label']:<28} {_fmt(r['bytes'])}")
        if breaches:
            print()
            print(f"⚠ {len(breaches)} threshold breach(es):")
            for b in breaches:
                print(f"  {b['label']:<28} {_fmt(b['bytes'])} > {_fmt(b['threshold'])} (over by {_fmt(b['over_by'])})")
        else:
            print()
            print("ok all sizes under threshold.")

    return 1 if breaches else 0


if __name__ == "__main__":
    sys.exit(main())
