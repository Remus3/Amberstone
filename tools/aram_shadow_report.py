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

ENEMY-LESS EXCLUSION (RM-852): a row with no enemy team is not an ARAM game
tick - in production the champion and the enemy team come from the same
Live Client allPlayers list, so a real tick that names a champion always names
its enemies. 669 enemy-less Kai'Sa rows reached the live corpus from
build_state test harnesses before RM-406; RM-859 archive-split them byte-exact
(nothing deleted) to data/aram_coach_rm859_test_leak_2026-06_2026-09_shadow.jsonl.
This read-time exclusion stays as the backstop: counted as ``enemy_less_excluded``
and left out of every gate summary (dead state, action, choices, field presence,
flip hint). A row without the ``enemy_comp`` key fails closed the same way.

R78 TAIL FIELDS (RM-882): every row since R78 (``8f013ee4``) carries
``item_extra`` and ``objective`` on both sides, and gated row G3-14 is the flip
of exactly those two. Field presence covers them, and ``tail_agreement``
scores each over the rows where BOTH sides are populated. Three states keep a
field OUT of the tail gate math, each with ``agreement_rate`` None (never 0 %
and never a rate that reads as readiness):

* "no live baseline" - the live side is empty on every comparable (non-dead,
  gated) row. The live ARAM prompt has no Objective output field
  (``coaches/aram_coach.py`` ``_SYSTEM`` OUTPUT FORMAT; ``parse_fields`` never
  asks for "objective"), so live ``objective`` is always "".
* "no comparable rows" - the live side spoke, never beside a deterministic
  value.
* "degenerate" - one side shows a single distinct value across the comparable
  rows, so every match is that constant and the ratio measures how often the
  OTHER side happens to say it, not agreement. The deterministic
  ``item_extra`` is the literal "omit" by design
  (``core/aram_deterministic_coach.py`` ``_safe_item_extra``), so it lands here.

NORMALISATION: case and surrounding whitespace are folded (the live value is
free text parsed out of a Haiku reply, the deterministic one a code literal;
"Omit" and "omit" show the player the same chip). No synonym table: "omitted"
is NOT "omit". The prompt asks for the literal "omit" (``_SYSTEM`` Item extra
line) and the deterministic side emits exactly that literal; a synonym map is
open-ended and can only raise agreement, and a flip gate must err low. The
gate itself uses the EXACT rate (the lower bound); the folded rate is printed
beside it. The action gate is unchanged.

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
# The R78 tail fields (RM-882): scored as free text by summarize_tail.
_TAIL_FIELDS = ("item_extra", "objective")
_FIELDS = (
    "action", "fight_rule", "risk", "reset_item", "item_build",
    "item_build_reasons", "choices",
) + _TAIL_FIELDS
FLIP_GATE = 0.70
NO_LIVE_BASELINE = "no live baseline"
NO_COMPARABLE_ROWS = "no comparable rows"
DEGENERATE = "degenerate"
MEASURED = "measured"
_SIDE_LABEL = {"deterministic": "deterministic", "live_haiku": "Haiku"}


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


def has_enemy_comp(rec: dict) -> bool:
    """True when the row lists at least one named enemy champion.

    Only such a row is an ARAM game tick (RM-852). A missing key, a non-list,
    or a list of blanks reads as enemy-less: fail closed, because a row that
    cannot show it came from a game must not move the flip gate."""
    comp = rec.get("enemy_comp") if isinstance(rec, dict) else None
    if not isinstance(comp, list):
        return False
    return any(isinstance(e, str) and e.strip() for e in comp)


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
    det_instrumented = 0
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
        # A row is "instrumented" when its deterministic block carries the
        # choices KEY at all (present-or-empty). Rows logged before the choices
        # instrumentation landed lack the key entirely; counting them as
        # coverage misses drags the raw rate far below current-code coverage.
        if "choices" in _side(rec, "deterministic"):
            det_instrumented += 1
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
        "det_instrumented": det_instrumented,
        "det_coverage_rate_instrumented": (
            round(det_present / det_instrumented, 4) if det_instrumented else 0.0),
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

    For each field (the 7 original ones plus the R78 tail item_extra /
    objective, RM-882), tally how often it is present on both sides, only
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


def _norm_text(value) -> str:
    """A tail field value for comparison: trimmed + case-folded text, or a
    canonical JSON dump for a (malformed) non-string value.

    Deliberately NO synonym folding: "omitted" stays distinct from "omit"
    (the prompt's requested literal; see the module docstring)."""
    if isinstance(value, str):
        return value.strip().casefold()
    return json.dumps(value, sort_keys=True, default=str)


def _display(value) -> str:
    """A raw value as it is shown inside a degenerate note."""
    return value.strip() if isinstance(value, str) else _norm_text(value)


def summarize_tail(records: list[dict]) -> dict:
    """Agreement on the R78 tail fields (item_extra / objective), RM-882.

    Over non-dead rows only. A row is comparable when BOTH sides populate the
    field; ``agree`` compares trimmed, case-folded text and ``agree_exact`` the
    raw values; ``det_distinct`` / ``live_distinct`` count each side's
    distinct folded values over the comparable rows. ``baseline`` is, first
    match wins:

    * "no live baseline" - the live side is empty on every non-dead row, so
      there is nothing to agree WITH (live ``objective``: the ARAM prompt never
      asks for one);
    * "no comparable rows" - the live side spoke, but never beside a populated
      deterministic value;
    * "degenerate" - one side holds a single distinct value over the
      comparable rows (``degenerate`` names the side and the constant), so
      every match is that constant and no ratio is agreement;
    * "measured" - ``agreement_rate`` (folded) and ``agreement_rate_exact``.

    Both rates are None unless measured - never 0.0. ``gate`` applies
    FLIP_GATE to the EXACT rate of the measured fields only (the lower bound,
    so folding can never carry a field over the bar); every other field is
    listed as excluded and never counts as a miss or a pass. ``met`` is None
    when no tail field is measured."""
    out: dict = {}
    for field in _TAIL_FIELDS:
        non_dead_total = det_instrumented = det_present = live_present = 0
        both = det_only = live_only = neither = 0
        agree = agree_exact = 0
        det_vals: Counter = Counter()
        live_vals: Counter = Counter()
        det_raw: dict[str, Counter] = {}
        live_raw: dict[str, Counter] = {}
        for rec in records:
            if _is_dead_state(rec):
                continue
            non_dead_total += 1
            # Pre-R78 rows carry no tail key at all (the choices lesson).
            if field in _side(rec, "deterministic"):
                det_instrumented += 1
            dv = _field_value(rec, "deterministic", field)
            lv = _field_value(rec, "live_haiku", field)
            dp = _is_present(dv)
            lp = _is_present(lv)
            det_present += int(dp)
            live_present += int(lp)
            if dp and lp:
                both += 1
                dn = _norm_text(dv)
                ln = _norm_text(lv)
                det_vals[dn] += 1
                live_vals[ln] += 1
                det_raw.setdefault(dn, Counter())[_display(dv)] += 1
                live_raw.setdefault(ln, Counter())[_display(lv)] += 1
                if dv == lv:
                    agree_exact += 1
                if dn == ln:
                    agree += 1
            elif dp:
                det_only += 1
            elif lp:
                live_only += 1
            else:
                neither += 1
        degenerate = None
        if live_present == 0:
            baseline = NO_LIVE_BASELINE
        elif both == 0:
            baseline = NO_COMPARABLE_ROWS
        elif len(det_vals) == 1 or len(live_vals) == 1:
            baseline = DEGENERATE
            side, raw = (("deterministic", det_raw) if len(det_vals) == 1
                         else ("live_haiku", live_raw))
            (only,) = raw.values()
            constant = only.most_common(1)[0][0]
            degenerate = f'{_SIDE_LABEL[side]} side constant "{constant}"'
        else:
            baseline = MEASURED
        measured = baseline == MEASURED
        rate = round(agree / both, 4) if measured else None
        rate_exact = round(agree_exact / both, 4) if measured else None
        out[field] = {
            "baseline": baseline,
            "degenerate": degenerate,
            "non_dead_total": non_dead_total,
            "det_instrumented": det_instrumented,
            "det_present": det_present,
            "live_present": live_present,
            "both": both,
            "det_only": det_only,
            "live_only": live_only,
            "neither": neither,
            "comparable": both,
            "det_distinct": len(det_vals),
            "live_distinct": len(live_vals),
            "agree": agree,
            "agree_exact": agree_exact,
            "agreement_rate": rate,
            "agreement_rate_exact": rate_exact,
            "gate_met": (rate_exact >= FLIP_GATE) if measured else None,
        }

    def _with(baseline: str) -> list[str]:
        return [f for f in _TAIL_FIELDS if out[f]["baseline"] == baseline]

    measured_fields = _with(MEASURED)
    out["gate"] = {
        "bar": FLIP_GATE,
        "basis": "exact",
        "measured": measured_fields,
        "excluded_no_live_baseline": _with(NO_LIVE_BASELINE),
        "excluded_no_comparable_rows": _with(NO_COMPARABLE_ROWS),
        "excluded_degenerate": _with(DEGENERATE),
        "met": (all(out[f]["gate_met"] for f in measured_fields)
                if measured_fields else None),
    }
    return out


def _tail_hint(tail: dict) -> str:
    """The R78 tail clause appended to the flip hint (RM-882). Worded so it
    never contains the action gate's "gate MET" / "below 70% gate" text, and
    so an excluded field never carries a percentage."""
    parts = []
    for field in _TAIL_FIELDS:
        slot = tail.get(field) or {}
        baseline = slot.get("baseline")
        if baseline == MEASURED:
            exact = slot.get("agreement_rate_exact") or 0.0
            folded = slot.get("agreement_rate") or 0.0
            bar = "meets 70% bar" if exact >= FLIP_GATE else "below 70% bar"
            parts.append(f"{field} agreement {round(100 * exact)}% exact "
                         f"({round(100 * folded)}% case-folded) over "
                         f"{slot.get('comparable', 0)} comparable rows ({bar})")
        elif baseline == DEGENERATE:
            parts.append(f"{field} degenerate: {slot.get('degenerate')} - not "
                         "agreement, excluded from gate math")
        elif baseline == NO_COMPARABLE_ROWS:
            parts.append(f"{field} no comparable rows - excluded from gate math")
        else:
            parts.append(f"{field} no live baseline (live side empty on every "
                         "comparable row) - excluded from gate math")
    return "; R78 tail: " + "; ".join(parts)


def _flip_hint(action: dict, choices: dict, total: int,
               enemy_less: int = 0, tail: Optional[dict] = None) -> str:
    """A coarse human read of flip-readiness. NOT a flip authorization - the
    operator decides; this only flags the obvious not-ready states. ``total``
    is the GATED row count (enemy-less rows already removed)."""
    if total == 0:
        excluded = (f" ({enemy_less} enemy-less rows excluded - not game ticks)"
                    if enemy_less else "")
        return ("no shadow data yet - play real ARAM games to accrue coverage"
                + excluded)
    comparable = action["comparable"]
    if comparable == 0:
        return ("coverage accruing - no comparable action ticks yet (mostly "
                "dead-state or unclassified) - keep playing before any flip "
                "(operator gate)")
    pct = round(100 * action["agreement_rate"])
    cc = round(100 * choices.get("det_coverage_rate_instrumented", 0.0))
    gate = (">=70% gate MET" if action["agreement_rate"] >= FLIP_GATE
            else "below 70% gate")
    return (f"action agreement {pct}% over {comparable} comparable ticks "
            f"({gate}); deterministic choices coverage {cc}% over instrumented "
            "rows - NOT a flip authorization (operator gate; live "
            "Haiku-retirement stays live-gated)"
            + (_tail_hint(tail) if tail else ""))


def build_report(path) -> dict:
    """Assemble the full ARAM shadow report dict from one shadow log path.

    ``total`` is every row in the log; ``enemy_less_excluded`` the rows with no
    enemy team (RM-852); ``gated`` the rest, which is the ONLY population the
    dead-state split and every gate summary below are computed over."""
    all_records = load_jsonl(Path(path))
    records = [r for r in all_records if has_enemy_comp(r)]
    enemy_less = len(all_records) - len(records)
    action = summarize_action(records)
    choices = summarize_choices(records)
    tail = summarize_tail(records)
    return {
        "schema": "aram_shadow_report/v1",
        "total": len(all_records),
        "enemy_less_excluded": enemy_less,
        "gated": len(records),
        "dead_state": sum(1 for r in records if _is_dead_state(r)),
        "non_dead": sum(1 for r in records if not _is_dead_state(r)),
        "action": action,
        "choices": choices,
        "field_presence": summarize_field_presence(records),
        "tail_agreement": tail,
        "flip_ready_hint": _flip_hint(action, choices, len(records), enemy_less,
                                      tail),
    }


def _print_human(report: dict) -> None:
    print(f"total {report.get('total', 0)}, "
          f"enemy_less_excluded {report.get('enemy_less_excluded', 0)}, "
          f"gated {report.get('gated', 0)}, "
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
          f"{ch.get('non_dead_total', 0)} ({ch.get('det_coverage_rate', 0.0)}) raw, "
          f"{ch.get('det_present', 0)}/{ch.get('det_instrumented', 0)} "
          f"({ch.get('det_coverage_rate_instrumented', 0.0)}) instrumented, "
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
    _print_tail(report.get("tail_agreement") or {})
    print(f"hint: {report.get('flip_ready_hint')}")


def _print_tail(tail: dict) -> None:
    """The R78 tail block (RM-882): a field with no live baseline prints the
    words "no live baseline", never a 0/0 ratio."""
    print("[tail_agreement]")
    for field in _TAIL_FIELDS:
        slot = tail.get(field) or {}
        baseline = slot.get("baseline", NO_LIVE_BASELINE)
        dp = slot.get("det_present", 0)
        lp = slot.get("live_present", 0)
        comparable = slot.get("comparable", 0)
        if baseline == MEASURED:
            print(f"    {field}: agree {slot.get('agree_exact', 0)}/{comparable} "
                  f"({slot.get('agreement_rate_exact')}) exact, "
                  f"{slot.get('agree', 0)}/{comparable} "
                  f"({slot.get('agreement_rate')}) case-folded, "
                  f"live_present {lp}, det_present {dp} - measured")
        elif baseline == DEGENERATE:
            print(f"    {field}: degenerate: {slot.get('degenerate')} over "
                  f"{comparable} comparable rows (det {slot.get('det_distinct', 0)}"
                  f" / live {slot.get('live_distinct', 0)} distinct; every match "
                  f"- {slot.get('agree_exact', 0)} exact, {slot.get('agree', 0)} "
                  "case-folded - is that constant) - excluded from gate math")
        elif baseline == NO_COMPARABLE_ROWS:
            print(f"    {field}: no comparable rows (live_present {lp}, "
                  f"det_present {dp}) - excluded from gate math")
        else:
            print(f"    {field}: no live baseline (live side empty on all "
                  f"{slot.get('non_dead_total', 0)} non-dead rows; "
                  f"det_present {dp}) - excluded from gate math")
    gate = tail.get("gate") or {}
    measured = gate.get("measured") or []
    excluded = [f"{f} ({why})" for key, why in (
        ("excluded_no_live_baseline", NO_LIVE_BASELINE),
        ("excluded_no_comparable_rows", NO_COMPARABLE_ROWS),
        ("excluded_degenerate", DEGENERATE),
    ) for f in (gate.get(key) or [])]
    met = gate.get("met")
    print(f"    tail gate (70% bar, exact rate): measured "
          f"{', '.join(measured) or 'none'}; excluded "
          f"{', '.join(excluded) or 'none'}; met {'n/a' if met is None else met}")


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
