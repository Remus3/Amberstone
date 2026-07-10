#!/usr/bin/env python
# arch: OCR-vs-Sonnet shadow agreement report (Lane E OCR-only flip gate) | section=tools | frozen=no
"""OCR shadow-validation report - the flip-readiness gate for the Lane E OCR
migration (retiring the Sonnet escalation for a numeric field in favor of
OCR-only).

This is the OCR sibling of ``tools/aram_shadow_report.py``. It reads
``data/ocr_shadow.jsonl`` - the per-field OCR-vs-Sonnet comparison log written
by ``core.vision_routing._log_ocr_shadow`` - where each row is one field
observation ``{ts, field, ocr_val, sonnet_val, match}`` and ``match`` is
``ocr_val is not None and ocr_val == sonnet_val`` (an OCR miss and an OCR
mismatch both read as ``match=False``). The report aggregates per field so the
operator can judge, field by field, whether OCR alone agrees with Sonnet often
enough to drop the Sonnet escalation for that field.

The two-part flip gate mirrors ``aram_shadow_report``'s action gate: a field is
FLIP-ELIGIBLE only when it has accrued at least ``MIN_SAMPLES`` rows AND its
match rate clears ``MATCH_GATE``. The default gate (0.90) is deliberately
stricter than aram's 0.70 verdict gate: OCR-only would replace Sonnet as the
ground-truth numeric, so near-exact agreement is required. Both thresholds are
CLI-overridable (``--gate`` / ``--min-samples``).

The shadow log only fills during a LIVE ARAM/Arena game (the vision tick is
gated on ``_fetch_game_data`` being non-None), so a missing/empty log is the
expected pre-accrual state, not an error.

This is a READ-ONLY report (no engine, no network, no write). Fail-soft: a
missing / empty / malformed log yields a zeroed section, never an exception. It
does NOT flip anything - the operator decides and the flip stays live-gated;
this only flags readiness.

USAGE
    python tools/ocr_shadow_report.py                    # human summary
    python tools/ocr_shadow_report.py --json             # machine-readable JSON
    python tools/ocr_shadow_report.py --gate 0.95        # stricter match gate
    python tools/ocr_shadow_report.py --min-samples 100  # more rows required
    python tools/ocr_shadow_report.py --path X           # a different log
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = _ROOT / "data" / "ocr_shadow.jsonl"

# The eight numeric shadow fields registered by both coaches:
# coaches/aram_coach.py:513 (_ARAM_SHADOW_FIELDS) and
# coaches/arena_coach.py:1122 (SHADOW_FIELDS). Seeded into every report so a
# field with zero accrued rows still shows (at zero) rather than vanishing.
KNOWN_FIELDS = (
    "ally_1_hp", "ally_2_hp", "ally_3_hp", "ally_4_hp",
    "gold", "level", "cs", "kda",
)

# Flip-gate defaults (CLI-overridable). MATCH_GATE is intentionally stricter
# than aram_shadow_report.FLIP_GATE (0.70): OCR-only replaces Sonnet as the
# numeric source of truth, so it must agree near-exactly. MIN_SAMPLES guards
# against a small-sample fluke clearing the rate gate on a handful of ticks.
MATCH_GATE = 0.90
MIN_SAMPLES = 50


def load_jsonl(path) -> list[dict]:
    """Read a jsonl file into a list of dicts (fail-soft to []).

    A missing file or any unreadable / malformed LINE is skipped, never raised -
    the same robustness core.vision_routing._log_ocr_shadow promises on write."""
    out: list[dict] = []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _row_present(rec: dict) -> bool:
    """True when OCR produced a value for this row (ocr_val is not None). A None
    ocr_val is an OCR miss - the field was not read this tick."""
    return rec.get("ocr_val") is not None


def _row_matched(rec: dict) -> bool:
    """True when OCR agreed with Sonnet for this row. Trusts the logged ``match``
    flag when it is a real bool (the capture-time verdict is authoritative);
    otherwise recomputes ``ocr_val is not None and ocr_val == sonnet_val`` to
    mirror core.vision_routing._log_ocr_shadow exactly."""
    flag = rec.get("match")
    if isinstance(flag, bool):
        return flag
    ov = rec.get("ocr_val")
    return ov is not None and ov == rec.get("sonnet_val")


def _eligibility(samples: int, match_rate: float, gate: float,
                 min_samples: int) -> tuple[bool, str]:
    """The two-part flip gate + a human reason. Samples first (the harder
    blocker to read), then the rate gate. NOT a flip authorization."""
    if samples < min_samples:
        return False, f"insufficient samples ({samples} < {min_samples})"
    if match_rate < gate:
        return (False,
                f"below gate ({round(100 * match_rate)}% < {round(100 * gate)}%)")
    return (True,
            f"ELIGIBLE ({round(100 * match_rate)}% match over {samples} samples) "
            "- operator flip auth still required")


def summarize_fields(records: list[dict], *, gate: float = MATCH_GATE,
                     min_samples: int = MIN_SAMPLES) -> dict:
    """Per-field OCR-vs-Sonnet aggregation over the shadow rows.

    Every KNOWN_FIELDS field is seeded (present even at zero); any additional
    field observed in the data is included too (schema-drift safe). For each
    field: sample count, how often OCR produced a value (present), how often it
    matched Sonnet, the folded match rate (matches/samples), the coverage rate
    (present/samples), the conditional accuracy (matches/present), and the
    two-part flip eligibility with its reason."""
    fields = sorted(set(KNOWN_FIELDS) | {
        rec.get("field") for rec in records
        if isinstance(rec.get("field"), str)
    })
    out: dict[str, dict] = {}
    for field in fields:
        rows = [r for r in records if r.get("field") == field]
        samples = len(rows)
        present = sum(1 for r in rows if _row_present(r))
        matches = sum(1 for r in rows if _row_matched(r))
        match_rate = round(matches / samples, 4) if samples else 0.0
        present_rate = round(present / samples, 4) if samples else 0.0
        accuracy = round(matches / present, 4) if present else 0.0
        eligible, reason = _eligibility(samples, match_rate, gate, min_samples)
        out[field] = {
            "samples": samples,
            "ocr_present": present,
            "matches": matches,
            "match_rate": match_rate,
            "present_rate": present_rate,
            "accuracy_when_present": accuracy,
            "flip_eligible": eligible,
            "reason": reason,
        }
    return out


def _flip_hint(fields: dict, total: int, gate: float, min_samples: int) -> str:
    """A coarse human read of flip-readiness. NOT a flip authorization - the
    operator decides and the OCR-only flip stays live-gated."""
    if total == 0:
        return ("no OCR shadow data yet - data/ocr_shadow.jsonl fills only "
                "during a live ARAM/Arena game; play real games to accrue rows "
                "before any flip (operator gate)")
    eligible = sorted(f for f, v in fields.items() if v["flip_eligible"])
    gpct = round(100 * gate)
    if eligible:
        return (f"flip-eligible fields (>={gpct}% match over >={min_samples} "
                f"samples): {', '.join(eligible)}. NOT a flip authorization - "
                "operator decides; OCR-only flip stays live-gated")
    return (f"no field clears the gate yet (>={min_samples} samples AND "
            f">={gpct}% match) - keep accruing shadow rows. NOT a flip "
            "authorization (operator gate)")


def build_report(path, *, gate: float = MATCH_GATE,
                 min_samples: int = MIN_SAMPLES) -> dict:
    """Assemble the full OCR shadow report dict from one shadow log path."""
    records = load_jsonl(Path(path))
    fields = summarize_fields(records, gate=gate, min_samples=min_samples)
    eligible = sorted(f for f, v in fields.items() if v["flip_eligible"])
    return {
        "schema": "ocr_shadow_report/v1",
        "path": str(path),
        "total": len(records),
        "gate": gate,
        "min_samples": min_samples,
        "fields": fields,
        "eligible_fields": eligible,
        "flip_ready_hint": _flip_hint(fields, len(records), gate, min_samples),
    }


def _print_human(report: dict) -> None:
    print(f"total {report.get('total', 0)} "
          f"(gate {round(100 * report.get('gate', 0.0))}%, "
          f"min_samples {report.get('min_samples', 0)})")
    print("[fields]")
    fields = report.get("fields") or {}
    for field in sorted(fields):
        v = fields[field]
        flag = "ELIGIBLE" if v.get("flip_eligible") else "--"
        print(f"    {field}: samples={v.get('samples', 0)} "
              f"present={v.get('ocr_present', 0)} "
              f"match={v.get('matches', 0)} "
              f"rate={round(100 * v.get('match_rate', 0.0))}% "
              f"acc_present={round(100 * v.get('accuracy_when_present', 0.0))}% "
              f"-> {flag} ({v.get('reason', '')})")
    print(f"hint: {report.get('flip_ready_hint')}")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--path", default=str(DEFAULT_PATH))
    ap.add_argument("--json", action="store_true", help="emit JSON not a summary")
    ap.add_argument("--gate", type=float, default=MATCH_GATE,
                    help=f"match-rate flip gate (default {MATCH_GATE})")
    ap.add_argument("--min-samples", type=int, default=MIN_SAMPLES,
                    help=f"min rows per field to be flip-eligible (default {MIN_SAMPLES})")
    args = ap.parse_args(argv)
    report = build_report(args.path, gate=args.gate, min_samples=args.min_samples)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
