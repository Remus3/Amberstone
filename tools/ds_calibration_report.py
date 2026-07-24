"""RM-32 / D-01 - run the DS pick-vs-outcome calibration pass, write a report.

Joins the accrued ``data/ds_calibration.jsonl`` recommendation log against
real match outcomes in ``data/rewind_history.db`` via
``core.ds_calibration_agreement`` and writes the aggregate to
``data/ds_calibration_agreement.json``.

Usage::

    python tools/ds_calibration_report.py
    python tools/ds_calibration_report.py --min-n 10
    python tools/ds_calibration_report.py --db data/rewind_history.db \
        --log data/ds_calibration.jsonl --out data/ds_calibration_agreement.json

DESCRIPTIVE ONLY. The payload is an audit artifact for a human reading how
often the operator followed a DS recommendation and how those games ended. It
is NOT a coach input and must never be wired into ``agents/daemon_slayer``
rank - see the firewall note in ``core/ds_calibration_agreement.py``.

Writes ATOMICALLY (tmp.write_text then tmp.replace - CLAUDE.md hard rule). The
payload carries NO wall-clock timestamp, so a re-run over unchanged inputs
yields a byte-identical file. ASCII only.

Exits non-zero with a plain one-line message when an input is missing or the
aggregation reports a failure.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.ds_calibration_agreement import (  # noqa: E402
    MIN_BUCKET_N,
    compute_ds_calibration_agreement_from_db,
)

SCHEMA = "ds_calibration_agreement/v1"

DEFAULT_DB = _PROJECT_ROOT / "data" / "rewind_history.db"
DEFAULT_LOG = _PROJECT_ROOT / "data" / "ds_calibration.jsonl"
DEFAULT_OUT = _PROJECT_ROOT / "data" / "ds_calibration_agreement.json"

_GENERATED_NOTE = (
    "offline calibration pass over core.ds_calibration recommendations joined "
    "to rewind_history.db outcomes; descriptive corpus evidence only, never an "
    "input to daemon_slayer rank"
)

_CARRY = (
    "ok", "min_n", "alpha", "shrink_k", "ticks", "observations", "followed",
    "follow_rate_overall", "follow_rate_overall_smoothed", "cells",
    "cells_dropped_below_min_n", "games", "coverage",
)


def build_payload(result: dict) -> dict:
    """Reshape an aggregator result into the schema-versioned report payload.

    Only fields the aggregator produced are carried forward - notably NOT
    ``elapsed_ms``, so the artifact stays reproducible across runs.
    """
    payload = {"schema": SCHEMA, "generated_note": _GENERATED_NOTE}
    for key in _CARRY:
        if key in result:
            payload[key] = result[key]
    return payload


def write_atomic(payload: dict, out_path: Path) -> None:
    """Serialise ``payload`` to ``out_path`` via a tmp file plus replace."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True),
        encoding="utf-8",
    )
    tmp.replace(out_path)


def summarise(payload: dict) -> str:
    """Plain-ASCII operator summary, honest about a thin sample."""
    cov = payload.get("coverage") or {}
    games = payload.get("games") or {}
    cells = payload.get("cells") or []
    lines = [
        "DS calibration pass (descriptive only)",
        f"  ticks={payload.get('ticks')} "
        f"no_game_id={cov.get('records_without_game_id')}",
        f"  games: in_log={cov.get('games_in_log')} "
        f"joined={cov.get('games_joined')} "
        f"unjoined={cov.get('games_unjoined')} "
        f"inventory_fallback={cov.get('games_inventory_fallback')}",
        f"  observations={payload.get('observations')} "
        f"followed={payload.get('followed')} "
        f"follow_rate={payload.get('follow_rate_overall')} "
        f"smoothed={payload.get('follow_rate_overall_smoothed')}",
        f"  game outcomes: W={games.get('wins')} L={games.get('losses')} "
        f"mean_follow_win={games.get('mean_follow_rate_win')} "
        f"mean_follow_loss={games.get('mean_follow_rate_loss')}",
        f"  cells emitted={len(cells)} "
        f"omitted_below_min_n={payload.get('cells_dropped_below_min_n')} "
        f"(min_n={payload.get('min_n')})",
    ]
    for cell in cells:
        lines.append(
            f"    {cell['mode']:<6} {cell['scorer']:<10} n={cell['n']:<5} "
            f"follow={cell['follow_rate']} (sm {cell['follow_rate_smoothed']}) "
            f"wr_followed={cell['winrate_followed']} "
            f"wr_unfollowed={cell['winrate_unfollowed']} "
            f"delta_shrunk={cell['winrate_delta_shrunk']}"
        )
    if not cells:
        lines.append(
            "    NO CELL CLEARS THE GATE - the joined sample is too thin to "
            "conclude anything. Report the counts above, not a verdict.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Run the DS pick-vs-outcome calibration pass and write a "
                    "descriptive report.",
    )
    ap.add_argument("--db", default=str(DEFAULT_DB),
                    help="path to rewind_history.db (default: data/rewind_history.db)")
    ap.add_argument("--log", default=str(DEFAULT_LOG),
                    help="path to ds_calibration.jsonl (default: data/ds_calibration.jsonl)")
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help="output JSON path (default: data/ds_calibration_agreement.json)")
    ap.add_argument("--min-n", type=int, default=MIN_BUCKET_N,
                    help=f"hard per-cell sample gate (default: {MIN_BUCKET_N})")
    args = ap.parse_args(argv)

    db_path = Path(args.db)
    log_path = Path(args.log)
    if not db_path.exists():
        print(f"ERROR: db not found: {db_path}", file=sys.stderr)
        return 2
    if not log_path.exists():
        print(f"ERROR: calibration log not found: {log_path}", file=sys.stderr)
        return 2

    try:
        result = compute_ds_calibration_agreement_from_db(
            db_path=db_path, log_path=log_path, min_n=args.min_n)
    except Exception as exc:  # noqa: BLE001 - a CLI reports, it does not traceback
        print(f"ERROR: aggregation failed: {exc}", file=sys.stderr)
        return 3

    if not result.get("ok"):
        print(f"ERROR: {result.get('error') or 'aggregation returned not-ok'}",
              file=sys.stderr)
        return 3

    payload = build_payload(result)
    out_path = Path(args.out)
    try:
        write_atomic(payload, out_path)
    except OSError as exc:
        print(f"ERROR: write failed: {exc}", file=sys.stderr)
        return 4

    print(summarise(payload))
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
