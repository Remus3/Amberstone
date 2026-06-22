#!/usr/bin/env python
# arch: HZ mismatch root-cause diagnosis over the laning-combat shadow log | section=tools | frozen=no
"""HZ mismatch diagnosis - WHY the precomputed laning COMBAT verdict reads more
cautious/passive than the live Haiku coach, per genuine-mismatch class.

This is a STANDALONE analysis tool, NOT a flip and NOT a threshold tune. Tuning
the precompute thresholds until the agreement metric goes up is circular - the
metric is the very thing under suspicion. Instead this tool reads the LOG-TIME
net_swing scalar that every covered choice already embeds in
``choices[0].expected_outcome`` (e.g. "net swing -0.12; you remove 30% of
Caitlyn, they remove 42% of you") and, per genuine-mismatch class (the same
population tools.hz_shadow_report counts), reports:

  * the net_swing DISTRIBUTION across 6 fixed buckets (deep-negative model-error
    zone ... favored-trade zone), plus median / mean / extrema and the median
    pct-removed pair;
  * a mechanical, deterministic CALIBRATION-vs-MODEL-ERROR verdict that READS
    the distribution. A deep-negative cluster (the precompute thinks the enemy
    full-combo near-kills you) points at the structural sequence_b=_FULL_COMBO
    assumption (core/laning_scenario_precompute.py) which no threshold tune can
    fix. A cluster near the hold threshold points at CALIBRATION (a defensible
    nudge to the _BACK_OFF / _HOLD_LOW / _TRADE cutoffs in
    core/precomputed_laning_coach.py) - but only ever WITH ground-truth
    corroboration, never to chase this metric.

The genuine-mismatch population is defined by tools.hz_shadow_report:
``pair = record_agreement(rec)`` not None and not pair["agree"]; each class is
(pair["precompute"], pair["native"]). Reusing record_agreement guarantees this
tool's class counts sum to exactly the shadow report's mismatch count.

READ-ONLY analysis with ONE side effect: writing the markdown report
(ops/audit/HZ_MISMATCH_DIAGNOSE.md by default; --no-write to skip). Fail-soft: a
missing / empty / malformed log yields a zeroed report, never an exception.

USAGE
    python tools/hz_mismatch_diagnose.py                 # human summary + md
    python tools/hz_mismatch_diagnose.py --json          # machine-readable JSON
    python tools/hz_mismatch_diagnose.py --all-classes    # every disagreeing pair
    python tools/hz_mismatch_diagnose.py --no-write       # skip the md write

# follow-up: optional rewind-db ground-truth cross-ref (out of scope this slice)
"""
from __future__ import annotations

import argparse
import bisect
import json
import re
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Optional

# tools/ is NOT a package: under pytest the repo root is on sys.path (so
# "from tools import X" resolves), but "python tools/hz_mismatch_diagnose.py"
# puts only tools/ on sys.path. Try the package form first, fall back to the
# bare module. NO top-level "from core ..." / "from agents ..." - that import
# would break the bare-CLI path. (Mirror of hz_shadow_report's standalone rule.)
try:
    from tools import hz_shadow_report as rep
except ImportError:  # pragma: no cover - exercised only via the bare CLI path
    import hz_shadow_report as rep

_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MD_PATH = _ROOT / "ops" / "audit" / "HZ_MISMATCH_DIAGNOSE.md"
DEFAULT_CURRENT_ENGINE = "1.149.0"

SCHEMA = "hz_mismatch_diagnose/v1"

# net_swing is embedded as text in the recommended (A) choice's expected_outcome,
# e.g. "net swing -0.12; you remove 30% of Caitlyn, they remove 42% of you".
# The enemy name can contain spaces/commas (e.g. "Aurelion Sol") so match it
# non-greedily up to the literal ", they remove".
_EO_RE = re.compile(
    r"net swing\s*([+-]?\d+(?:\.\d+)?)\s*;\s*you remove\s*(\d+)%\s*of\s*"
    r".+?,\s*they remove\s*(\d+)%\s*of you"
)

# 6 half-open (lo, hi] buckets over net_swing. bucket_index uses bisect_left over
# these edges minus one, clamped to [0,5]. The labels name the diagnostic zone.
_BUCKET_EDGES = (-1.01, -0.5, -0.18, -0.05, 0.0, 0.10, 1.01)
_BUCKET_LABELS = (
    "(-inf,-0.5]   deep-neg (model-error zone)",
    "(-0.5,-0.18]  firm back_off",
    "(-0.18,-0.05] hold zone (calibration zone)",
    "(-0.05,0]     even dead-zone (neg half)",
    "(0,+0.10)     even dead-zone (pos half)",
    "[+0.10,+inf)  favored trade",
)

# A "passive precompute" class = the precompute side recommends a more cautious
# verdict than the native (Haiku) side - the systematic over-caution we are
# diagnosing. The native verdict is strictly more aggressive.
_PASSIVE_PRE = frozenset({"back_off", "hold", "even"})
_AGGRESSIVE_NATIVE = frozenset({"hold", "trade", "all_in"})

# Fixed default class order (the systematic over-caution classes first).
_DEFAULT_CLASSES: tuple[tuple[str, str], ...] = (
    ("back_off", "hold"),
    ("hold", "all_in"),
    ("back_off", "trade"),
    ("even", "trade"),
    ("hold", "trade"),
    ("even", "hold"),
)


def parse_expected_outcome(text) -> Optional[dict]:
    """Parse a choice expected_outcome string into its signed net_swing + the
    two pct-removed fractions, or None when the text carries no scalar.

    Returns {"net_swing": float, "pct_enemy_removed": float (0..1),
    "pct_my_removed": float (0..1)}. "you remove X%" -> pct_enemy_removed,
    "they remove Y% of you" -> pct_my_removed."""
    if not text or not isinstance(text, str):
        return None
    m = _EO_RE.search(text)
    if not m:
        return None
    return {
        "net_swing": float(m.group(1)),
        "pct_enemy_removed": int(m.group(2)) / 100.0,
        "pct_my_removed": int(m.group(3)) / 100.0,
    }


def record_scalars(rec: dict) -> Optional[dict]:
    """The log-time net_swing scalars from a record's recommended (A) choice,
    or None when there is no choices[0].expected_outcome to parse.

    This LOG-TIME scalar is authoritative (no engine drift) - it is NOT
    re-derived from the live table; that is the whole point of the diagnosis."""
    choices = rec.get("choices")
    if not (isinstance(choices, list) and choices and isinstance(choices[0], dict)):
        return None
    return parse_expected_outcome(choices[0].get("expected_outcome"))


def bucket_index(swing: float) -> int:
    """Index into _BUCKET_LABELS for a net_swing value, clamped to [0, 5].

    Base = ``bisect_left(_BUCKET_EDGES, swing) - 1`` (the pinned formula), which
    makes buckets 0..3 closed on the upper edge ((lo, hi]): an exact -0.5 / -0.18
    / -0.05 / 0.0 lands in the LOWER bucket. The top bucket is closed on the
    LOWER edge instead ([+0.10, +inf), per _BUCKET_LABELS), so an exact +0.10
    belongs to bucket 5, not bucket 4 - the one asymmetric edge the bare formula
    rounds the wrong way."""
    idx = bisect.bisect_left(_BUCKET_EDGES, swing) - 1
    if swing >= 0.10:
        idx = 5
    if idx < 0:
        return 0
    if idx > 5:
        return 5
    return idx


def classify_class_verdict(class_pair, buckets, median_swing) -> str:
    """Mechanical, deterministic read of one class's net_swing distribution.

    NOT an authorization to change thresholds - a description of where the swing
    mass sits. For a PASSIVE-precompute class (the over-caution we are chasing):
    a deep-negative dominant cluster reads MODEL-ERROR (the structural enemy
    full-combo assumption), a near-threshold cluster reads CALIBRATION. For a
    class where the NATIVE side is the more passive one, a firmly positive swing
    reads as Haiku noise / a CV veto rather than precompute over-caution."""
    pre, native = class_pair
    total = sum(buckets)
    if total == 0:
        return "no-data"
    deep = buckets[0]
    passive_pre = pre in _PASSIVE_PRE and native in _AGGRESSIVE_NATIVE \
        and _aggressiveness(native) > _aggressiveness(pre)
    if passive_pre:
        if deep / total >= 0.5 or median_swing <= -0.30:
            return ("MODEL-ERROR (enemy-full-combo over-kill; "
                    "Haiku likely right)")
        if (buckets[2] + buckets[3] + buckets[4]) / total >= 0.5 \
                and median_swing > -0.18:
            return ("CALIBRATION (clustered near threshold; "
                    "_BACK_OFF/_HOLD nudge defensible)")
        if median_swing >= 0.0:
            return "CALIBRATION (under-called a non-negative trade)"
        return "MIXED (no dominant bucket; inspect per-pair)"
    # native is the more passive side (e.g. trade->back_off, even->back_off)
    if median_swing >= 0.18:
        return ("HAIKU-NOISE/CV-VETO (precompute firmly positive, "
                "native passive)")
    return "AMBIGUOUS (small edge; either side defensible)"


_AGGRESSION_ORDER = {"back_off": 0, "even": 1, "hold": 2, "trade": 3, "all_in": 4}


def _aggressiveness(verdict: str) -> int:
    """Coarse ordinal so a class can be tagged passive-precompute (native more
    aggressive) vs native-more-passive. back_off < even < hold < trade < all_in."""
    return _AGGRESSION_ORDER.get(verdict, 2)


def _genuine_mismatch_pairs(records: list[dict]) -> list[tuple[tuple[str, str], dict]]:
    """The genuine-mismatch population: (class_pair, record) for every record
    where rep.record_agreement is not None and not agree, with rep's non-laning
    native-state guard applied. Single source of truth - this is exactly the
    population tools.hz_shadow_report counts as a mismatch, so class counts sum
    to summarize_agreement's (comparable_covered - agree)."""
    out: list[tuple[tuple[str, str], dict]] = []
    for rec in records:
        if rep._is_non_laning_native_state(rec):
            continue
        pair = rep.record_agreement(rec)
        if pair is None or pair["agree"]:
            continue
        out.append(((pair["precompute"], pair["native"]), rec))
    return out


def _class_block(class_pair, recs: list[dict]) -> dict:
    """Build one class's distribution block from its member records."""
    pre, native = class_pair
    swings: list[float] = []
    pct_my: list[float] = []
    pct_enemy: list[float] = []
    buckets = [0, 0, 0, 0, 0, 0]
    unparseable = 0
    for rec in recs:
        sc = record_scalars(rec)
        if sc is None:
            unparseable += 1
            continue
        s = sc["net_swing"]
        swings.append(s)
        pct_my.append(sc["pct_my_removed"])
        pct_enemy.append(sc["pct_enemy_removed"])
        buckets[bucket_index(s)] += 1
    median_swing = round(statistics.median(swings), 4) if swings else 0.0
    verdict = classify_class_verdict(class_pair, buckets, median_swing)
    return {
        "precompute": pre,
        "native": native,
        "count": len(recs),
        "unparseable": unparseable,
        "buckets": buckets,
        "median_swing": median_swing,
        "mean_swing": round(statistics.fmean(swings), 4) if swings else 0.0,
        "min_swing": round(min(swings), 4) if swings else 0.0,
        "max_swing": round(max(swings), 4) if swings else 0.0,
        "median_pct_my_removed": round(statistics.median(pct_my), 4)
        if pct_my else 0.0,
        "median_pct_enemy_removed": round(statistics.median(pct_enemy), 4)
        if pct_enemy else 0.0,
        "verdict": verdict,
    }


def _drift_block(records: list[dict], current_engine: str) -> dict:
    """Engine-version provenance of the WHOLE log (every record, not just
    mismatches). logged_under_other > 0 means some buckets reflect a precompute
    that spoke under a now-superseded engine; their re-derived cell at the live
    engine may differ - but the log-time bucket is the correct denominator for
    "was the precompute too cautious WHEN it spoke"."""
    by_engine: Counter = Counter(
        str(r.get("engine_version") or "?") for r in records
    )
    logged_current = by_engine.get(current_engine, 0)
    return {
        "by_engine_version": dict(sorted(by_engine.items())),
        "current_engine": current_engine,
        "logged_under_current": logged_current,
        "logged_under_other": sum(by_engine.values()) - logged_current,
    }


def diagnose(records: list[dict], *, all_classes: bool = False,
             current_engine: str = DEFAULT_CURRENT_ENGINE,
             now: Optional[str] = None) -> dict:
    """Assemble the full diagnosis dict from a list of laning shadow records.

    ``now`` is an injectable generated-at string (default the real UTC clock via
    time.gmtime/strftime) so the numeric body stays clock-independent for
    deterministic tests. ``all_classes`` additionally emits every other
    disagreeing class beyond the fixed default set, sorted by (-count, pre,
    native)."""
    if now is None:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    pairs = _genuine_mismatch_pairs(records)
    by_class: dict[tuple[str, str], list[dict]] = {}
    for class_pair, rec in pairs:
        by_class.setdefault(class_pair, []).append(rec)

    ordered: list[tuple[str, str]] = list(_DEFAULT_CLASSES)
    if all_classes:
        extra = [cp for cp in by_class if cp not in set(_DEFAULT_CLASSES)]
        extra.sort(key=lambda cp: (-len(by_class[cp]), cp[0], cp[1]))
        ordered.extend(extra)

    classes = []
    for class_pair in ordered:
        recs = by_class.get(class_pair, [])
        # default classes always render (even at count 0, as "no-data"); extra
        # classes only exist because by_class has them, so they are non-empty.
        classes.append(_class_block(class_pair, recs))

    return {
        "schema": SCHEMA,
        "generated_at": now,
        "total_records": len(records),
        "genuine_mismatches": len(pairs),
        "bucket_labels": list(_BUCKET_LABELS),
        "classes": classes,
        "drift": _drift_block(records, current_engine),
    }


def _hist(buckets) -> str:
    """a|b|c|d|e|f bucket histogram cell."""
    return "|".join(str(b) for b in buckets)


def render_markdown(report: dict) -> str:
    """PURE, ASCII-only markdown render of a diagnosis report. Deterministic for
    a fixed report (generated_at is carried in the report, not re-clocked here)."""
    drift = report.get("drift", {})
    lines: list[str] = []
    lines.append("# HZ laning-combat mismatch diagnosis")
    lines.append("")
    lines.append(f"generated-at: {report.get('generated_at', '?')}")
    lines.append(f"schema: {report.get('schema', SCHEMA)}")
    lines.append(f"current-engine: {drift.get('current_engine', '?')}")
    lines.append(
        f"total-records: {report.get('total_records', 0)}  "
        f"genuine-mismatches: {report.get('genuine_mismatches', 0)}"
    )
    lines.append("")
    if drift.get("logged_under_other", 0) > 0:
        lines.append(
            f"WARNING: {drift['logged_under_other']} of "
            f"{drift.get('logged_under_current', 0) + drift['logged_under_other']} "
            "records were logged under a NON-current engine version; their "
            "re-derived cell at the live engine may differ. The buckets below "
            "reflect the LOG-TIME precompute output, which is the correct "
            "denominator for 'was the precompute too cautious WHEN it spoke'."
        )
        lines.append("")
    lines.append("## Bucket legend")
    for i, label in enumerate(report.get("bucket_labels", [])):
        lines.append(f"- bucket {i}: {label}")
    lines.append("")
    lines.append("## Per-class net_swing distribution")
    lines.append("")
    lines.append("| class (pre -> native) | count | median swing | "
                 "buckets a|b|c|d|e|f | verdict |")
    lines.append("|---|---|---|---|---|")
    for c in report.get("classes", []):
        lines.append(
            f"| {c['precompute']} -> {c['native']} | {c['count']} | "
            f"{c['median_swing']:+.2f} | {_hist(c['buckets'])} | {c['verdict']} |"
        )
    lines.append("")
    lines.append("## Anti-circularity footer")
    lines.append("")
    lines.append(
        "This is a reading of the LOG-TIME net_swing distribution, NOT a flip "
        "and NOT a threshold tune. Tuning the precompute cutoffs to chase the "
        "agreement metric is circular - the metric is the thing under "
        "suspicion."
    )
    lines.append("")
    lines.append(
        "- CALIBRATION classes justify INVESTIGATING a _BACK_OFF / _HOLD_LOW / "
        "_TRADE nudge in core/precomputed_laning_coach.py:79-81 ONLY WITH "
        "ground-truth corroboration (rewind-db trade outcomes or a live "
        "side-by-side), never to chase this number."
    )
    lines.append(
        "- MODEL-ERROR classes point at the structural sequence_b=_FULL_COMBO "
        "assumption (core/laning_scenario_precompute.py:355): the precompute "
        "scores the enemy landing their FULL combo, so it over-states "
        "incoming damage. A threshold tune cannot fix a structural-input "
        "error - the enemy-sequence model itself is the lever."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def write_markdown(report: dict, path: Path) -> None:
    """The ONLY side effect: write the markdown report (mkdir parents)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(report), encoding="utf-8")


def _print_human(report: dict, md_path: Optional[Path]) -> None:
    print(f"HZ laning-combat mismatch diagnosis (schema {report['schema']})")
    print(f"  total records: {report['total_records']}  "
          f"genuine mismatches: {report['genuine_mismatches']}")
    for c in report["classes"]:
        print(
            f"  pre={c['precompute']} -> native={c['native']} "
            f"n={c['count']} median={c['median_swing']:+.2f} "
            f"buckets={_hist(c['buckets'])} => {c['verdict']}"
        )
    drift = report["drift"]
    if drift.get("logged_under_other", 0) > 0:
        print(f"  WARNING: {drift['logged_under_other']} records logged under a "
              f"non-current engine (current {drift['current_engine']}); buckets "
              "are log-time precompute output (the correct denominator).")
    if md_path is not None:
        print(f"  markdown written: {md_path}")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--choice-path", default=str(rep.DEFAULT_CHOICE_PATH))
    ap.add_argument("--json", action="store_true", help="emit JSON not a summary")
    ap.add_argument("--all-classes", action="store_true",
                    help="also emit disagreeing classes beyond the default set")
    ap.add_argument("--current-engine", default=DEFAULT_CURRENT_ENGINE)
    ap.add_argument("--md-path", default=str(DEFAULT_MD_PATH))
    ap.add_argument("--no-write", action="store_true",
                    help="skip the markdown write (no side effect)")
    args = ap.parse_args(argv)

    records = rep.load_jsonl(Path(args.choice_path))
    report = diagnose(records, all_classes=args.all_classes,
                      current_engine=args.current_engine)

    md_path: Optional[Path] = None
    if not args.no_write:
        md_path = Path(args.md_path)
        write_markdown(report, md_path)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report, md_path)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
