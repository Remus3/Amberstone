"""Strip test-run synthetic calls out of the `data/spend/` cost ledger.

WHY THIS EXISTS
---------------
`tests/test_aram_state_debounce.py` and `tests/test_arena_state_debounce.py`
drove the real ARAM / Arena coaches through `Coach._run_coach` with a mocked
Anthropic client whose response carried `input_tokens=10, output_tokens=20`.
That reached `coaches/_base_coach.py:713 _record_coach_call` ->
`core.cost_tracker.get_tracker().record_call(...)`, i.e. the operator's REAL
daily spend ledger. Every suite run booked fake calls. The leak is now closed
at the root by the autouse `redirect_cost_tracker_spend_dir_to_tmp` fixture in
`tests/conftest.py`; this tool recovers the rows that were already written.

WHAT COUNTS AS SYNTHETIC
------------------------
The ledger stores per-day AGGREGATES, not per-call rows, so a synthetic call
is only recoverable where its bucket is provably 100 percent synthetic. A
`by_purpose` bucket qualifies when ALL THREE hold:

  * the purpose is one the leak could produce (`aram_coach` / `arena_coach`),
  * `tokens == calls * 30` EXACTLY (10 in + 20 out per call), and
  * `usd == calls * 0.000088` EXACTLY - the Haiku 4.5 price of one 10/20 call,
    computed from `core.cost_tracker.MODEL_PRICING` rather than hardcoded so a
    price-table edit cannot silently change what this tool deletes.

A real coach call is ~1500-2500 input tokens, so any bucket carrying real
spend fails the token test by three orders of magnitude. A bucket that mixes
real and synthetic calls is NOT decomposable from aggregates and is left
untouched and REPORTED - dropping it would destroy real history, and guessing
a split would fabricate it. None were found on the 2026-08-06 pass.

The filter is PER BUCKET, never per file: 22 of the 40 affected day-files also
carry genuine spend under other purposes, and deleting those files would lose
real financial history.

IDEMPOTENCE
-----------
Repair removes the qualifying buckets and subtracts their exact contribution
from `by_model[haiku]` and the day totals. A second run finds no qualifying
bucket and writes nothing. `--dry-run` reports the same counts without
touching disk.

USAGE
-----
  python tools/repair_spend_ledger.py --dry-run
  python tools/repair_spend_ledger.py
  python tools/repair_spend_ledger.py --spend-dir <path> --json

Writes are atomic (temp file + `os.replace`) because the dashboard and the
cost-health watchdog poll these files.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

_SPEND_DIR = _APP / "data" / "spend"

# The leak's fingerprint. Both debounce fixtures used the same numbers.
SYNTH_MODEL = "claude-haiku-4-5-20251001"
SYNTH_TOKENS_IN = 10
SYNTH_TOKENS_OUT = 20
SYNTH_PURPOSES = ("aram_coach", "arena_coach")

# Non-ledger sidecars in the same directory; they carry no per-call rows, so
# the by_purpose pass skips them. They have their OWN leak and their own repair
# pass - see repair_match_sidecars() below.
_SKIP_FILES = ("_match_open.json", "recent_matches.json")

# Gates the leak could reach, as `_purpose_to_gate` maps SYNTH_PURPOSES.
_SYNTH_GATES = frozenset({"aram", "arena"})

# Money is compared in whole micro-dollars. record_call() rounds every running
# total to 6 decimal places, so a micro-dollar is the ledger's own resolution
# and an exact integer comparison is available - no epsilon needed, and none
# invented (an epsilon is how a mixed bucket would get mistaken for a pure one).
_MICRO = 1_000_000


def synth_usd_per_call() -> float:
    """USD of one synthetic call, derived from the live pricing table."""
    from core.cost_tracker import DEFAULT_PRICING, MODEL_PRICING
    price = MODEL_PRICING.get(SYNTH_MODEL, DEFAULT_PRICING)
    return ((SYNTH_TOKENS_IN / 1_000_000) * price["input"]
            + (SYNTH_TOKENS_OUT / 1_000_000) * price["output"])


def _micros(usd) -> int:
    return int(round(float(usd or 0.0) * _MICRO))


def _atomic_write_json(target: Path, doc: dict) -> None:
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    os.replace(tmp, target)


def classify_bucket(purpose: str, bucket, usd_per_call: float) -> str:
    """`pure` (all synthetic), `mixed` (undecomposable), or `clean`."""
    if purpose not in SYNTH_PURPOSES or not isinstance(bucket, dict):
        return "clean"
    calls = int(bucket.get("calls", 0) or 0)
    if calls <= 0:
        return "clean"
    # A bucket with NO `tokens` key predates that field. `record_call` has
    # always written it, so the leak cannot have produced such a bucket - it is
    # real spend by construction. Measured 2026-08-06: 15 such buckets across
    # 12 files (2026-04-28 .. 2026-05-27), at 28.7x to 47.0x the synthetic price
    # - low 2026-05-09 arena_coach, high 2026-04-28 aram_coach. Without this
    # branch they read as "suspect".
    if "tokens" not in bucket:
        return "clean"
    tokens = int(bucket.get("tokens", 0) or 0)
    per_call = SYNTH_TOKENS_IN + SYNTH_TOKENS_OUT
    if (tokens == calls * per_call
            and _micros(bucket.get("usd", 0.0)) == _micros(calls * usd_per_call)):
        return "pure"
    # Right purpose, wrong shape. A real coach call runs ~1500-2500 input
    # tokens, so a bucket of N synthetic plus even ONE real call lands above
    # `per_call` and below 2x it only while synthetic calls still dominate
    # (30N + 1500 over N+1 tokens/call clears 60 once N drops under ~50).
    # Report that band for human review - the aggregates cannot be decomposed,
    # so the tool must never guess a split. Above 2x, the bucket is dominated
    # by real spend and is not a recovery candidate at all.
    if calls * per_call < tokens < calls * per_call * 2:
        return "mixed"
    return "clean"


def repair_doc(doc: dict, usd_per_call: float) -> dict:
    """Return {'changed', 'dropped_calls', 'dropped_usd', 'purposes', 'mixed',
    'doc', 'error'} for one day-ledger document. Does not touch disk."""
    out = {"changed": False, "dropped_calls": 0, "dropped_usd": 0.0,
           "purposes": {}, "mixed": [], "doc": doc, "error": None}
    by_purpose = doc.get("by_purpose")
    if not isinstance(by_purpose, dict):
        return out

    drop_calls = 0
    for purpose, bucket in list(by_purpose.items()):
        verdict = classify_bucket(purpose, bucket, usd_per_call)
        if verdict == "mixed":
            out["mixed"].append(purpose)
        elif verdict == "pure":
            n = int(bucket.get("calls", 0) or 0)
            out["purposes"][purpose] = n
            drop_calls += n
    if not drop_calls:
        return out

    drop_usd_micro = _micros(drop_calls * usd_per_call)
    drop_tin = drop_calls * SYNTH_TOKENS_IN
    drop_tout = drop_calls * SYNTH_TOKENS_OUT

    # Reconcile the model bucket BEFORE mutating anything, so a ledger that
    # cannot absorb the subtraction is refused whole rather than half-edited.
    by_model = doc.get("by_model")
    mb = by_model.get(SYNTH_MODEL) if isinstance(by_model, dict) else None
    if not isinstance(mb, dict):
        out["error"] = ("no by_model[" + SYNTH_MODEL + "] bucket to subtract "
                        "the synthetic calls from")
        return out
    for field, delta in (("calls", drop_calls), ("tokens_in", drop_tin),
                         ("tokens_out", drop_tout)):
        if int(mb.get(field, 0) or 0) < delta:
            out["error"] = ("by_model." + field + " is smaller than the "
                            "synthetic contribution - refusing to write a "
                            "negative ledger")
            return out
    if _micros(mb.get("usd", 0.0)) < drop_usd_micro:
        out["error"] = ("by_model.usd is smaller than the synthetic "
                        "contribution - refusing to write a negative ledger")
        return out

    for purpose in out["purposes"]:
        del by_purpose[purpose]

    mb["calls"] = int(mb.get("calls", 0) or 0) - drop_calls
    mb["tokens_in"] = int(mb.get("tokens_in", 0) or 0) - drop_tin
    mb["tokens_out"] = int(mb.get("tokens_out", 0) or 0) - drop_tout
    mb["usd"] = round((_micros(mb.get("usd", 0.0)) - drop_usd_micro) / _MICRO, 6)
    if mb["calls"] == 0:
        del by_model[SYNTH_MODEL]

    doc["calls"] = int(doc.get("calls", 0) or 0) - drop_calls
    doc["tokens_in"] = int(doc.get("tokens_in", 0) or 0) - drop_tin
    doc["tokens_out"] = int(doc.get("tokens_out", 0) or 0) - drop_tout
    doc["total_usd"] = round(
        (_micros(doc.get("total_usd", 0.0)) - drop_usd_micro) / _MICRO, 6)
    # Clamp only exact-zero float noise, never a real negative (refused above).
    for field in ("calls", "tokens_in", "tokens_out"):
        doc[field] = max(0, int(doc[field]))
    doc["total_usd"] = max(0.0, doc["total_usd"])

    out["changed"] = True
    out["dropped_calls"] = drop_calls
    out["dropped_usd"] = round(drop_usd_micro / _MICRO, 6)
    return out


def _is_synthetic_match_record(rec) -> bool:
    """True for a per-match cost record the leak produced.

    `core/match_db.py:177` calls `get_tracker().note_match_boundary()` on every
    saved match and is the only route to this file. The PRODUCER of the two
    records found in the production ledger is UNIDENTIFIED - see the
    ruled-out list in the `redirect_cost_tracker_spend_dir_to_tmp` docstring in
    `tests/conftest.py`. What is measured is the SHAPE: `by_gate` all-zero (the
    synthetic ledger delta had already been snapshotted by a prior boundary
    call) and limited to the aram/arena gates, two records 41ms apart.

    The classification risk here is bounded in a way the day-file pass is not:
    an all-zero record contributes nothing to `recent_match_avg` except
    inflating the divisor `n`, so dropping a genuine zero-cost match would
    change no reported cost - it would only stop a $0 match from dragging the
    per-match average down. Over-deleting cannot lose real spend data.
    """
    if not isinstance(rec, dict):
        return False
    by_gate = rec.get("by_gate")
    if not isinstance(by_gate, dict) or not by_gate:
        return False
    if not set(by_gate) <= _SYNTH_GATES:
        return False
    for entry in by_gate.values():
        if not isinstance(entry, dict):
            return False
        if _micros(entry.get("usd", 0.0)) != 0 or int(entry.get("tokens", 0) or 0) != 0:
            return False
    return True


def repair_match_sidecars(spend_dir: Path, dry_run: bool = True) -> dict:
    """Second pass: the two per-match cost sidecars.

    `_match_open.json` is a TRANSIENT snapshot of the daily ledger's
    `by_purpose` at the last match boundary, not history - `note_match_boundary`
    treats a missing or empty file as "no prior snapshot" and falls back to the
    full current values. When its snapshot contains ONLY synthetic purposes it
    is a snapshot of a ledger this tool has just zeroed, so it is stale by
    construction and resetting it is the correct repair (leaving it makes the
    next real boundary diff against numbers that no longer exist).
    """
    out = {"match_open_reset": False, "match_records_dropped": 0,
           "match_records_kept": 0, "errors": []}

    open_path = spend_dir / "_match_open.json"
    if open_path.is_file():
        try:
            doc = json.loads(open_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            out["errors"].append("_match_open.json: unreadable: " + str(exc))
            doc = None
        if isinstance(doc, dict):
            bp = doc.get("by_purpose")
            if isinstance(bp, dict) and bp and set(bp) <= set(SYNTH_PURPOSES):
                out["match_open_reset"] = True
                if not dry_run:
                    _atomic_write_json(open_path, {})

    recent_path = spend_dir / "recent_matches.json"
    if recent_path.is_file():
        try:
            doc = json.loads(recent_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            out["errors"].append("recent_matches.json: unreadable: " + str(exc))
            return out
        matches = doc.get("matches") if isinstance(doc, dict) else None
        if isinstance(matches, list):
            kept = [m for m in matches if not _is_synthetic_match_record(m)]
            out["match_records_dropped"] = len(matches) - len(kept)
            out["match_records_kept"] = len(kept)
            if out["match_records_dropped"] and not dry_run:
                doc["matches"] = kept
                _atomic_write_json(recent_path, doc)
    return out


def repair_dir(spend_dir: Path, dry_run: bool = True) -> dict:
    usd_per_call = synth_usd_per_call()
    report = {
        "spend_dir": str(spend_dir),
        "dry_run": bool(dry_run),
        "usd_per_synthetic_call": usd_per_call,
        "files_scanned": 0,
        "files_changed": 0,
        "dropped_calls": 0,
        "dropped_usd": 0.0,
        "per_file": [],
        "mixed_buckets": [],
        "errors": [],
        "real_calls_after": 0,
        "real_usd_after": 0.0,
    }
    if not spend_dir.is_dir():
        report["errors"].append("spend dir does not exist: " + str(spend_dir))
        return report

    dropped_usd_micro = 0
    after_usd_micro = 0
    for path in sorted(spend_dir.glob("*.json")):
        if path.name in _SKIP_FILES:
            continue
        report["files_scanned"] += 1
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            report["errors"].append(path.name + ": unreadable: " + str(exc))
            continue
        if not isinstance(doc, dict):
            report["errors"].append(path.name + ": not a JSON object")
            continue

        before_calls = int(doc.get("calls", 0) or 0)
        before_usd = _micros(doc.get("total_usd", 0.0))
        res = repair_doc(doc, usd_per_call)
        if res["mixed"]:
            report["mixed_buckets"].append(
                {"file": path.name, "purposes": res["mixed"]})
        if res["error"]:
            report["errors"].append(path.name + ": " + res["error"])
            after_usd_micro += before_usd
            report["real_calls_after"] += before_calls
            continue
        if res["changed"]:
            report["files_changed"] += 1
            report["dropped_calls"] += res["dropped_calls"]
            dropped_usd_micro += _micros(res["dropped_usd"])
            report["per_file"].append({
                "file": path.name,
                "calls_before": before_calls,
                "calls_after": int(doc.get("calls", 0) or 0),
                "usd_before": round(before_usd / _MICRO, 6),
                "usd_after": round(_micros(doc.get("total_usd", 0.0)) / _MICRO, 6),
                "dropped_calls": res["dropped_calls"],
                "dropped_usd": res["dropped_usd"],
                "purposes": res["purposes"],
            })
            if not dry_run:
                _atomic_write_json(path, doc)
        after_usd_micro += _micros(doc.get("total_usd", 0.0))
        report["real_calls_after"] += int(doc.get("calls", 0) or 0)

    report["dropped_usd"] = round(dropped_usd_micro / _MICRO, 6)
    report["real_usd_after"] = round(after_usd_micro / _MICRO, 6)

    sidecars = repair_match_sidecars(spend_dir, dry_run=dry_run)
    report["sidecars"] = sidecars
    report["errors"].extend(sidecars["errors"])
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Remove test-run synthetic calls from the cost ledger.")
    ap.add_argument("--spend-dir", default=str(_SPEND_DIR))
    ap.add_argument("--dry-run", action="store_true",
                    help="report counts without writing anything")
    ap.add_argument("--json", action="store_true",
                    help="emit the full report as JSON")
    args = ap.parse_args(argv)

    report = repair_dir(Path(args.spend_dir), dry_run=args.dry_run)
    if args.json:
        print(json.dumps(report, indent=2))
        return 1 if report["errors"] else 0

    mode = "DRY RUN" if report["dry_run"] else "APPLIED"
    print("repair_spend_ledger [" + mode + "] " + report["spend_dir"])
    print("  synthetic call price: $" + format(
        report["usd_per_synthetic_call"], ".8f"))
    print("  files scanned: " + str(report["files_scanned"])
          + "  files changed: " + str(report["files_changed"]))
    for row in report["per_file"]:
        print("    " + row["file"]
              + "  calls " + str(row["calls_before"]) + " -> "
              + str(row["calls_after"])
              + "  usd " + format(row["usd_before"], ".6f") + " -> "
              + format(row["usd_after"], ".6f")
              + "  dropped " + str(row["dropped_calls"])
              + " " + json.dumps(row["purposes"]))
    print("  dropped calls: " + str(report["dropped_calls"])
          + "  dropped usd: $" + format(report["dropped_usd"], ".6f"))
    print("  real calls remaining: " + str(report["real_calls_after"])
          + "  real usd remaining: $" + format(report["real_usd_after"], ".6f"))
    sc = report.get("sidecars") or {}
    print("  per-match sidecars: _match_open reset="
          + str(bool(sc.get("match_open_reset")))
          + "  recent_matches dropped=" + str(sc.get("match_records_dropped", 0))
          + " kept=" + str(sc.get("match_records_kept", 0)))
    for m in report["mixed_buckets"]:
        print("  MIXED (left untouched, not decomposable): "
              + m["file"] + " " + json.dumps(m["purposes"]))
    for e in report["errors"]:
        print("  ERROR: " + e)
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
