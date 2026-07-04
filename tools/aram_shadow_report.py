#!/usr/bin/env python
# arch: ARAM deterministic-vs-Haiku shadow agreement report (flip-readiness gate) | section=tools | frozen=no
"""ARAM shadow-validation report - the flip-readiness gate for retiring the
live ARAM Haiku coach (the "do not flip blind" gate).

This is the ARAM sibling of ``tools/hz_shadow_report.py``. It reads
``data/aram_coach_shadow.jsonl`` - a per-tick shadow log where each row
carries what the DETERMINISTIC coach would offer alongside what the live
Haiku coach actually said - and measures per-field agreement between the two
sides so the operator can judge whether the deterministic ARAM coach is ready
to replace the live Haiku call.

Before the ARAM Haiku coach is flipped off, the operator needs to know, per
field (action / fight_rule / risk / reset_item / item_build / item_build_reasons
/ choices), how often the deterministic side agrees with what Haiku said. The
headline is ACTION agreement (the coarse trade verdict) over comparable ticks,
plus the deterministic choices coverage.

DEAD-STATE EXCLUSION: a dead player's Haiku output carries
action="WAIT RESPAWN" (a respawn-timer overlay state, NOT a laning verdict)
while the deterministic side is empty. Roughly a quarter of the real rows are
dead-state; scoring them against a laning recommendation is meaningless and
floods the gate with false ticks (the cycle-53 false-0% finding). Every
summary excludes dead-state rows first.

This is a READ-ONLY report (no engine, no network, no write). Fail-soft: a
missing / empty / malformed log yields a zeroed section, never an exception.
It does NOT flip anything - the operator decides; this only flags readiness.

USAGE
    python tools/aram_shadow_report.py            # human summary, default path
    python tools/aram_shadow_report.py --json     # machine-readable JSON
    python tools/aram_shadow_report.py --path X    # a different shadow log
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = _ROOT / "data" / "aram_coach_shadow.jsonl"
_FIELDS = (
    "action", "fight_rule", "risk", "reset_item", "item_build",
    "item_build_reasons", "choices",
)
FLIP_GATE = 0.70


def load_jsonl(path: Path) -> list[dict]:
    """Read a jsonl file into a list of dicts (fail-soft to []).

    A missing file or any unreadable / malformed LINE is skipped, never raised -
    the same robustness the shadow writers themselves promise."""
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


# Ordered verdict keyword table - multi-word phrases FIRST, then single
# tokens with the more-specific ones ahead of any token they contain as a
# substring ("back to base" before "base", "disengage" before "engage"),
# so "back off" never falls into recall and "disengage" never reads all_in.
# First phrase that hits wins - deterministic by construction.
_VERDICT_PHRASES: tuple[tuple[str, str], ...] = (
    ("back to base", "recall"),
    ("back away", "back_off"),
    ("fall back", "back_off"),
    ("play safe", "back_off"),
    ("back off", "back_off"),
    ("all in", "all_in"),
    ("allin", "all_in"),
    ("backoff", "back_off"),
    ("disengage", "back_off"),
    ("engage", "all_in"),
    ("commit", "all_in"),
    ("even trade", "even"),
    ("even", "even"),
    ("trade", "trade"),
    ("poke", "trade"),
    ("harass", "trade"),
    ("retreat", "back_off"),
    ("careful", "back_off"),
    ("recall", "recall"),
    ("shop", "recall"),
    ("reset", "recall"),
    ("base", "recall"),
    ("hold", "hold"),
    ("farm", "hold"),
    ("wait", "hold"),
    ("sustain", "hold"),
)


def _normalize_verdict_text(text: str) -> str:
    """Lowercase + map every non-alphanumeric char to a space + collapse runs,
    so "All-in!" and "ALL IN" both normalize to "all in"."""
    chars = [ch if ch.isalnum() else " " for ch in text.lower()]
    return " ".join("".join(chars).split())


# Coach status / overlay action strings that are NOT laning verdicts: a dead
# player's respawn timer ("WAIT RESPAWN" - coaches/aram_coach.py) or a
# policy-disabled placeholder ("COACHING DISABLED" - core/feature_policy.py).
# These are not a laning trade decision at all, so scoring them against a
# precompute laning recommendation is meaningless. Without this guard the
# "wait" keyword maps "WAIT RESPAWN" to "hold" and floods the flip-readiness
# gate with dead-state ticks (cycle-53 finding: 20/20 comparable-covered were
# "WAIT RESPAWN" -> a false 0% agreement). A genuine "wait for jungler" hold
# verdict is unaffected (no marker substring).
_NON_LANING_STATE_MARKERS: tuple[str, ...] = ("respawn", "coaching disabled")


def classify_verdict(text) -> Optional[str]:
    """Map free text (a precompute A-label or Haiku prose/chip label) to one
    coarse verdict: "trade" / "all_in" / "back_off" / "recall" / "hold" /
    "even" - or None when no keyword hits (unclassifiable) or the text is a
    non-laning coach status/overlay state (dead-state, policy-disabled)."""
    if not text or not isinstance(text, str):
        return None
    norm = _normalize_verdict_text(text)
    if not norm:
        return None
    if any(marker in norm for marker in _NON_LANING_STATE_MARKERS):
        return None
    for phrase, verdict in _VERDICT_PHRASES:
        if phrase in norm:
            return verdict
    return None


def _side(rec: dict, side: str) -> dict:
    """The deterministic / live_haiku sub-dict, or {} when malformed/absent."""
    value = rec.get(side)
    return value if isinstance(value, dict) else {}


def _field_value(rec: dict, side: str, field: str):
    """One field's raw value off one side, or None when the side/field absent."""
    return _side(rec, side).get(field)


def _is_present(value) -> bool:
    """True when a field value is meaningfully populated. A blank / whitespace
    string, an empty list/dict, or None all read as absent."""
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return len(value) > 0
    if value is None:
        return False
    return bool(value)


def _is_dead_state(rec: dict) -> bool:
    """True when this tick is a dead-player / policy-disabled overlay state
    rather than a live laning decision. Authority is the Haiku action string
    (mirroring hz_shadow_report._is_non_laning_native_state): a live dead player
    reports "WAIT RESPAWN" on the Haiku side while the deterministic side is
    empty. Excluded from every summary (the cycle-53 false-0% lesson)."""
    action = _field_value(rec, "live_haiku", "action")
    if not isinstance(action, str):
        return False
    norm = _normalize_verdict_text(action)
    return any(marker in norm for marker in _NON_LANING_STATE_MARKERS)


def _first_choice_label(choices) -> Optional[str]:
    """The recommended (first) A/B chip label from a choices list, or None."""
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        label = choices[0].get("label")
        if label:
            return str(label)
    return None


def summarize_action(records: list[dict]) -> dict:
    """Deterministic-vs-Haiku ACTION agreement over the comparable sample.

    Dead-state ticks are excluded FIRST (counted only into
    ``dead_state_excluded``). For each surviving tick both action strings are
    classified to a coarse verdict; a tick is comparable only when BOTH sides
    classify. ``live_only_classified`` is the flip-risk case - the deterministic
    side is silent (or unclassifiable) while Haiku spoke a real verdict."""
    comparable = 0
    agree = 0
    by_deterministic: dict[str, int] = {}
    by_native: dict[str, dict] = {}
    confusion: dict[tuple[str, str], int] = {}
    det_only_classified = 0
    live_only_classified = 0
    both_unclassified = 0
    dead_state_excluded = 0
    for rec in records:
        if _is_dead_state(rec):
            dead_state_excluded += 1
            continue
        dv = classify_verdict(_field_value(rec, "deterministic", "action"))
        nv = classify_verdict(_field_value(rec, "live_haiku", "action"))
        if dv is not None and nv is not None:
            comparable += 1
            agreed = dv == nv
            if agreed:
                agree += 1
            by_deterministic[dv] = by_deterministic.get(dv, 0) + 1
            nslot = by_native.setdefault(nv, {"n": 0, "agree": 0})
            nslot["n"] += 1
            if agreed:
                nslot["agree"] += 1
            confusion[(dv, nv)] = confusion.get((dv, nv), 0) + 1
        elif dv is not None and nv is None:
            det_only_classified += 1
        elif dv is None and nv is not None:
            live_only_classified += 1
        else:
            both_unclassified += 1
    return {
        "comparable": comparable,
        "agree": agree,
        "agreement_rate": round(agree / comparable, 4) if comparable else 0.0,
        "by_deterministic": dict(sorted(by_deterministic.items())),
        "by_native": dict(sorted(by_native.items())),
        "confusion": [
            {"deterministic": dv, "native": nv, "n": n, "agree": dv == nv}
            for (dv, nv), n in sorted(
                confusion.items(), key=lambda kv: (-kv[1], kv[0])
            )
        ],
        "det_only_classified": det_only_classified,
        "live_only_classified": live_only_classified,
        "both_unclassified": both_unclassified,
        "dead_state_excluded": dead_state_excluded,
    }


def summarize_choices(records: list[dict]) -> dict:
    """Deterministic choices coverage + A/B label agreement over non-dead rows.

    Dead-state rows are skipped (not counted here at all). ``det_coverage_rate``
    is how often the deterministic side even offers choices; label agreement is
    measured only over rows where BOTH sides present choices and both first
    labels classify."""
    non_dead_total = 0
    det_present = 0
    both_present = 0
    det_only = 0
    live_only = 0
    neither = 0
    label_comparable = 0
    label_agree = 0
    for rec in records:
        if _is_dead_state(rec):
            continue
        non_dead_total += 1
        dp = _is_present(_field_value(rec, "deterministic", "choices"))
        lp = _is_present(_field_value(rec, "live_haiku", "choices"))
        if dp:
            det_present += 1
        if dp and lp:
            both_present += 1
        elif dp and not lp:
            det_only += 1
        elif not dp and lp:
            live_only += 1
        else:
            neither += 1
        if dp and lp:
            dl = classify_verdict(
                _first_choice_label(_field_value(rec, "deterministic", "choices")))
            nl = classify_verdict(
                _first_choice_label(_field_value(rec, "live_haiku", "choices")))
            if dl is not None and nl is not None:
                label_comparable += 1
                if dl == nl:
                    label_agree += 1
    return {
        "non_dead_total": non_dead_total,
        "det_present": det_present,
        "det_coverage_rate": (
            round(det_present / non_dead_total, 4) if non_dead_total else 0.0),
        "both_present": both_present,
        "det_only": det_only,
        "live_only": live_only,
        "neither": neither,
        "label_comparable": label_comparable,
        "label_agree": label_agree,
        "label_agreement_rate": (
            round(label_agree / label_comparable, 4) if label_comparable else 0.0),
    }


def summarize_field_presence(records: list[dict]) -> dict:
    """Per-field both/det_only/live_only/neither counts over non-dead rows.

    For each of the 7 fields, tally how often it is present on both sides, only
    one side, or neither - a coverage read that shows which fields the
    deterministic coach still leaves empty relative to Haiku."""
    out: dict[str, dict] = {
        field: {"both": 0, "det_only": 0, "live_only": 0, "neither": 0}
        for field in _FIELDS
    }
    for rec in records:
        if _is_dead_state(rec):
            continue
        for field in _FIELDS:
            dp = _is_present(_field_value(rec, "deterministic", field))
            lp = _is_present(_field_value(rec, "live_haiku", field))
            slot = out[field]
            if dp and lp:
                slot["both"] += 1
            elif dp and not lp:
                slot["det_only"] += 1
            elif not dp and lp:
                slot["live_only"] += 1
            else:
                slot["neither"] += 1
    return out


def _flip_hint(action: dict, choices: dict, total: int) -> str:
    """A coarse human read of flip-readiness. NOT a flip authorization - the
    operator decides; this only flags the obvious not-ready states."""
    if total == 0:
        return "no shadow data yet - play real ARAM games to accrue coverage"
    comparable = action["comparable"]
    if comparable == 0:
        return ("coverage accruing - no comparable action ticks yet (mostly "
                "dead-state or unclassified) - keep playing before any flip "
                "(operator gate)")
    pct = round(100 * action["agreement_rate"])
    cc = round(100 * choices["det_coverage_rate"])
    gate = (">=70% gate MET" if action["agreement_rate"] >= FLIP_GATE
            else "below 70% gate")
    return (f"action agreement {pct}% over {comparable} comparable ticks "
            f"({gate}); deterministic choices coverage {cc}% - NOT a flip "
            "authorization (operator gate; live Haiku-retirement stays "
            "live-gated)")


def build_report(path) -> dict:
    """Assemble the full ARAM shadow report dict from one shadow log path."""
    records = load_jsonl(Path(path))
    action = summarize_action(records)
    choices = summarize_choices(records)
    return {
        "schema": "aram_shadow_report/v1",
        "total": len(records),
        "dead_state": sum(1 for r in records if _is_dead_state(r)),
        "non_dead": sum(1 for r in records if not _is_dead_state(r)),
        "action": action,
        "choices": choices,
        "field_presence": summarize_field_presence(records),
        "flip_ready_hint": _flip_hint(action, choices, len(records)),
    }


def _print_human(report: dict) -> None:
    print(f"total {report.get('total', 0)}, "
          f"dead_state {report.get('dead_state', 0)}, "
          f"non_dead {report.get('non_dead', 0)}")
    act = report.get("action") or {}
    print(f"[action] {act.get('agree', 0)}/{act.get('comparable', 0)} "
          f"({act.get('agreement_rate', 0.0)}) comparable, "
          f"det_only {act.get('det_only_classified', 0)}, "
          f"live_only {act.get('live_only_classified', 0)}, "
          f"both_unclassified {act.get('both_unclassified', 0)}, "
          f"dead_state_excluded {act.get('dead_state_excluded', 0)}")
    ch = report.get("choices") or {}
    print(f"[choices] det coverage {ch.get('det_present', 0)}/"
          f"{ch.get('non_dead_total', 0)} ({ch.get('det_coverage_rate', 0.0)}), "
          f"both {ch.get('both_present', 0)}, det_only {ch.get('det_only', 0)}, "
          f"live_only {ch.get('live_only', 0)}, neither {ch.get('neither', 0)}, "
          f"label agree {ch.get('label_agree', 0)}/{ch.get('label_comparable', 0)}")
    print("[field_presence]")
    fp = report.get("field_presence") or {}
    for field in _FIELDS:
        slot = fp.get(field) or {}
        print(f"    {field}: both={slot.get('both', 0)} "
              f"det_only={slot.get('det_only', 0)} "
              f"live_only={slot.get('live_only', 0)} "
              f"neither={slot.get('neither', 0)}")
    mism = [c for c in (act.get("confusion") or []) if not c["agree"]]
    for c in mism[:6]:
        print(f"    MISMATCH det={c['deterministic']} -> "
              f"native={c['native']} x{c['n']}")
    print(f"hint: {report.get('flip_ready_hint')}")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--path", default=str(DEFAULT_PATH))
    ap.add_argument("--json", action="store_true", help="emit JSON not a summary")
    args = ap.parse_args(argv)
    report = build_report(args.path)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
