#!/usr/bin/env python
# arch: RC2-P5.5 (WS3) objective-playbook flip-readiness report over the objective shadow log | section=tools | frozen=no
"""objective_playbook_shadow report - the flip-readiness agreement gate for the
RC2 P5.5 (WS3) deterministic objective playbook (a Haiku-to-ZERO substrate).

``core/objective_playbook.py`` emits a deterministic contestable-objective
directive (a ``playbook_tag`` + ``playbook_line`` prose, dragon / herald today),
and ``core/objective_playbook_shadow.py`` records it per coarse game state
alongside the native (Haiku) ``objective`` prose into
``data/objective_playbook_shadow.jsonl`` (gitignored). The playbook row ships
ADDITIVE today, but before any FUTURE flip of the served Haiku ``objective``
FIELD onto the deterministic ``playbook_line`` the operator needs to know: at the
ticks where the playbook fires, what objective was Haiku ACTUALLY naming, and
would the two agree. This is that READ-ONLY gate.

THE COMPARISON (and why it is NOT the det_coach pattern). Unlike
``tools/det_coach_shadow_report.py`` - whose two surfaces sit in DIFFERENT
decision DOMAINS (a laning-trade verdict vs a macro call) and so need a
domain-divergence de-bias - here BOTH surfaces are already in the SAME register:
"which neutral objective to play around". The deterministic ``playbook_line`` is
always a dragon / herald directive; the native ``objective`` is always an
objective directive too (dragon / baron / nexus ...). So there is no cross-domain
mismatch to filter out - the whole point of the gate is to measure how often
Haiku names a DIFFERENT objective than the deterministic playbook. The dominant
(det=dragon, native=baron) divergence IS the do-not-flip finding, NOT noise.
Excluding the divergent rows would defeat the tool, so the HEADLINE alignment is
computed over EVERY both-present row (no row dropping).

  * HEADLINE = OBJECTIVE-CATEGORY ALIGNMENT RATE - over both-present rows, the
    fraction where the deterministic ``playbook_line`` primary objective category
    equals the native ``objective`` primary category. A LOW rate is the
    do-not-flip-blind signal: flipping the served objective field onto the
    playbook would, at non-aligned ticks, replace Haiku's objective with a
    different one.
  * CONFUSION matrix det-category -> native-category, most-common first (the
    det=dragon / native=baron cell is the headline divergence).

OBJECTIVE-CATEGORY CLASSIFIER. Markup (``[T]`` timer / ``[E]`` enemy / ``[A]``
ally tags) is stripped first - the tags are NOT balanced in the live prose so
each is dropped blindly. Then the line is normalized and scanned as WHOLE TOKENS
(so ``base`` never matches ``baseline``). Earliest matching token wins, with two
deliberate de-leaks each tied to a measured row count on the live log:
  * Step 1 (skip-clause excision) - a leading ``skip <objective>`` clause is
    dropped so the SKIPPED objective does not win ("SKIP DRAKE / TAKE BARON" was
    mis-scoring as dragon on ~2.6k lines; the intent is baron).
  * Step 2 (respawn demotion) - ``respawn`` (the "nothing to do but wait" tier)
    only wins when NO named objective appears, so a leading ``[T]37s until X
    respawn`` timer does not outrank a baron noun later in the line (~360 lines).

READ-ONLY: no engine, no network, no write. Fail-soft - a missing / empty /
malformed log yields zeroed sections, never an exception.

USAGE
    python tools/objective_playbook_shadow_report.py            # human summary
    python tools/objective_playbook_shadow_report.py --json      # JSON
    python tools/objective_playbook_shadow_report.py --path X     # alt log path
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
DEFAULT_PATH = _DATA / "objective_playbook_shadow.jsonl"

# Flip-readiness thresholds (do-not-flip-blind defaults). A HOLD is returned
# unless alignment clears the floor over a meaningful sample - intentionally
# conservative; this is a gate, not an authorization. The floor is higher than
# det_coach's 0.50 because here a low alignment directly means "Haiku names a
# different objective".
_MIN_ALIGN = 0.70
_MIN_SAMPLE = 50

# Objective-category keyword table, matched as WHOLE TOKENS after markup strip +
# normalize. Earliest matching token wins (token positions never tie). The
# "wait" category (respawn) is a FALLBACK tier - see classify_objective Step 2.
_KEYWORD_CATEGORY: dict[str, str] = {
    "elder": "elder",
    "baron": "baron",
    "nashor": "baron",
    "herald": "herald",
    "drake": "dragon",
    "dragon": "dragon",
    "inhibitor": "inhibitor",
    "inhib": "inhibitor",
    "nexus": "nexus",
    "tower": "tower",
    "turret": "tower",
    "plate": "tower",
    "vision": "vision",
    "ward": "vision",
    "sweep": "vision",
    "recall": "reset",
    "base": "reset",
    "push": "push",
    "siege": "push",
    "split": "push",
    "respawn": "wait",
    "group": "fight",
    "regroup": "fight",
    "teamfight": "fight",
}

# The fallback-tier category - never preempts a named objective (Step 2).
_FALLBACK_CATEGORY = "wait"

# Single-word bracket markup tags ([T] [/T] [E] [/E] [A] [/A] and any future
# single-word bracket tag). Dropped blindly - the live prose does NOT balance
# open/close tags, so pairing is not attempted.
_MARKUP_RE = re.compile(r"\[/?[A-Za-z]+\]")


def load_jsonl(path: Path) -> list[dict]:
    """Read a jsonl file into a list of dicts (fail-soft to []).

    A missing file or any unreadable / malformed LINE is skipped, never raised -
    the same robustness the shadow writer itself promises."""
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


def _strip_markup(text) -> str:
    """Remove every [T]/[/T]/[E]/[A] style single-word bracket tag -> space.

    The live prose does NOT balance open/close tags (far more [T] than [/T]), so
    each tag token is dropped blindly. Timer payloads ("[T]4:11" -> " 4:11")
    leave only digits/colons behind, which normalize to harmless numeric tokens
    that match no keyword."""
    if not text or not isinstance(text, str):
        return ""
    return _MARKUP_RE.sub(" ", text)


def _normalize_text(text: str) -> str:
    """Lowercase + map every non-alphanumeric char to a space + collapse runs,
    so "All-in!" and "ALL IN" both normalize to "all in"."""
    chars = [ch if ch.isalnum() else " " for ch in text.lower()]
    return " ".join("".join(chars).split())


def _excise_leading_skip(tokens: list[str]) -> list[str]:
    """Step 1 de-leak - drop leading "skip <x>" pairs so the SKIPPED objective
    does not win earliest-position ("skip drake, take baron" -> baron).

    Loops to handle multiple leading skips; a trailing lone "skip" is dropped
    too. Operates on a copy - never mutates the caller's list."""
    out = list(tokens)
    while len(out) >= 2 and out[0] == "skip":
        out = out[2:]
    if out and out[0] == "skip":
        out = out[1:]
    return out


def classify_objective(text) -> Optional[str]:
    """Map an objective directive / prose line to one coarse objective category
    ("dragon" / "baron" / "herald" / "elder" / "inhibitor" / "nexus" / "tower" /
    "vision" / "reset" / "push" / "fight" / "wait") - or None when no keyword
    hits.

    Pipeline: strip markup -> normalize -> excise leading skip-clause (Step 1) ->
    earliest WHOLE-TOKEN keyword wins, with "respawn"/"wait" demoted to a
    fallback that only wins when no named objective appears anywhere (Step 2)."""
    if not text or not isinstance(text, str):
        return None
    norm = _normalize_text(_strip_markup(text))
    if not norm:
        return None
    tokens = _excise_leading_skip(norm.split())
    fallback: Optional[str] = None
    for tok in tokens:
        cat = _KEYWORD_CATEGORY.get(tok)
        if cat is None:
            continue
        if cat == _FALLBACK_CATEGORY:
            if fallback is None:
                fallback = cat
            continue
        return cat
    return fallback


def _both_present(rec: dict) -> bool:
    """True when the record carries BOTH a deterministic playbook_line AND a
    native_objective - the only rows where the two surfaces can be compared."""
    return bool(rec.get("playbook_line")) and bool(rec.get("native_objective"))


def _coverage_block(records: list[dict]) -> dict:
    """Total / both-present + by-mode + by-lead_state + by-phase (each
    both/total) + top-15 per-champion both-present + engine-version
    distribution."""
    total = len(records)
    both = sum(1 for r in records if _both_present(r))
    by_mode: dict[str, dict] = {}
    by_lead: dict[str, dict] = {}
    by_phase: dict[str, dict] = {}
    by_champ_both: Counter = Counter()
    engine: Counter = Counter()
    for r in records:
        bp = _both_present(r)
        mode = str(r.get("mode") or "?")
        lead = str(r.get("lead_state") or "?")
        phase = str(r.get("phase") or "?")
        ms = by_mode.setdefault(mode, {"total": 0, "both": 0})
        ls = by_lead.setdefault(lead, {"total": 0, "both": 0})
        ps = by_phase.setdefault(phase, {"total": 0, "both": 0})
        ms["total"] += 1
        ls["total"] += 1
        ps["total"] += 1
        engine[str(r.get("engine_version") or "?")] += 1
        if bp:
            ms["both"] += 1
            ls["both"] += 1
            ps["both"] += 1
            by_champ_both[str(r.get("my_champion") or "?")] += 1
    return {
        "total": total,
        "both_present": both,
        "by_mode": dict(sorted(by_mode.items())),
        "by_lead_state": dict(sorted(by_lead.items())),
        "by_phase": dict(sorted(by_phase.items())),
        "by_engine_version": dict(sorted(engine.items())),
        "by_champion_both_top15": dict(by_champ_both.most_common(15)),
    }


def summarize_alignment(records: list[dict]) -> dict:
    """HEADLINE - deterministic-playbook objective category vs native objective
    category over EVERY both-present row (no row dropping; see module docstring
    for why cross-register exclusion does NOT apply here). Also reports the det
    and native category distributions and the unclassified counts (a None on
    either side counts as NOT aligned but is NOT excluded)."""
    both = 0
    aligned = 0
    det_dist: Counter = Counter()
    native_dist: Counter = Counter()
    det_unclassified = 0
    native_unclassified = 0
    for rec in records:
        if not _both_present(rec):
            continue
        both += 1
        det_cat = classify_objective(rec.get("playbook_line"))
        nat_cat = classify_objective(rec.get("native_objective"))
        det_dist[det_cat or "none"] += 1
        native_dist[nat_cat or "none"] += 1
        if det_cat is None:
            det_unclassified += 1
        if nat_cat is None:
            native_unclassified += 1
        if det_cat is not None and nat_cat is not None and det_cat == nat_cat:
            aligned += 1
    return {
        "both_present": both,
        "aligned": aligned,
        "alignment_rate": round(aligned / both, 4) if both else 0.0,
        "det_category_dist": dict(det_dist.most_common()),
        "native_category_dist": dict(native_dist.most_common()),
        "det_unclassified": det_unclassified,
        "native_unclassified": native_unclassified,
    }


def summarize_confusion(records: list[dict]) -> dict:
    """CONFUSION matrix det-category -> native-category over both-present rows,
    most-common first. An "agree" pair needs both sides classified AND equal
    (an unclassified "none" on either side is never an agreement)."""
    counts: dict[tuple[str, str], int] = {}
    for rec in records:
        if not _both_present(rec):
            continue
        det_cat = classify_objective(rec.get("playbook_line"))
        nat_cat = classify_objective(rec.get("native_objective"))
        d = det_cat or "none"
        n = nat_cat or "none"
        counts[(d, n)] = counts.get((d, n), 0) + 1
    pairs = [
        {"det": d, "native": n, "n": c, "agree": d == n and d != "none"}
        for (d, n), c in sorted(
            counts.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1])
        )
    ]
    return {
        "pairs": pairs,
        "mismatch_top": [p for p in pairs if not p["agree"]],
    }


def _flip_hint(coverage: dict, alignment: dict) -> str:
    """A coarse human read of flip-readiness. NOT a flip authorization - the
    operator decides; this only flags the obvious not-ready states. Default is
    HOLD (do-not-flip-blind): a REVIEW needs objective alignment >= the floor
    over a meaningful both-present sample."""
    both = coverage.get("both_present", 0)
    if both == 0:
        return "HOLD - no both-present rows yet; play real games to accrue data"
    if both < _MIN_SAMPLE:
        return (
            f"HOLD - only {both} both-present rows (< {_MIN_SAMPLE}); "
            "sample too small to judge"
        )
    rate = alignment.get("alignment_rate", 0.0)
    if rate < _MIN_ALIGN:
        return (
            f"HOLD - objective alignment {rate:.0%} < {_MIN_ALIGN:.0%}; Haiku "
            "names a different objective at these ticks, so flipping the served "
            "objective field onto the playbook would replace it"
        )
    return (
        f"REVIEW - objective alignment {rate:.0%} over {both} rows clears the "
        "floor; operator gate before any flip"
    )


def build_report(path: Path) -> dict:
    """Assemble the full objective_playbook_shadow report dict from the log."""
    records = load_jsonl(path)
    coverage = _coverage_block(records)
    alignment = summarize_alignment(records)
    confusion = summarize_confusion(records)
    return {
        "schema": "objective_playbook_shadow_report/v1",
        "coverage": coverage,
        "alignment": alignment,
        "confusion": confusion,
        "flip_ready_hint": _flip_hint(coverage, alignment),
    }


def _print_human(report: dict) -> None:
    cov = report.get("coverage") or {}
    al = report.get("alignment") or {}
    cf = report.get("confusion") or {}
    print(
        f"[coverage] total={cov.get('total', 0)} "
        f"both_present={cov.get('both_present', 0)}"
    )
    if cov.get("by_mode"):
        modes = ", ".join(
            f"{m}: {s.get('both', 0)}/{s.get('total', 0)}"
            for m, s in cov["by_mode"].items()
        )
        print(f"    by-mode (both/total): {modes}")
    if cov.get("by_lead_state"):
        leads = ", ".join(
            f"{k}: {s.get('both', 0)}/{s.get('total', 0)}"
            for k, s in cov["by_lead_state"].items()
        )
        print(f"    by-lead (both/total): {leads}")
    if cov.get("by_phase"):
        phases = ", ".join(
            f"{k}: {s.get('both', 0)}/{s.get('total', 0)}"
            for k, s in cov["by_phase"].items()
        )
        print(f"    by-phase (both/total): {phases}")
    if cov.get("by_engine_version"):
        eng = ", ".join(
            f"{v} x{n}" for v, n in cov["by_engine_version"].items()
        )
        print(f"    engine: {eng}")
    if cov.get("by_champion_both_top15"):
        print("    top champions (both-present):")
        for champ, n in cov["by_champion_both_top15"].items():
            print(f"        {champ} x{n}")
    print(
        f"[alignment] {al.get('aligned', 0)}/{al.get('both_present', 0)} "
        f"aligned (rate {al.get('alignment_rate', 0.0)})"
    )
    if al.get("det_category_dist"):
        dd = ", ".join(
            f"{k} x{v}" for k, v in al["det_category_dist"].items()
        )
        print(f"    det objective: {dd}")
    if al.get("native_category_dist"):
        nd = ", ".join(
            f"{k} x{v}" for k, v in al["native_category_dist"].items()
        )
        print(f"    native objective: {nd}")
    print(
        f"    unclassified: det={al.get('det_unclassified', 0)} "
        f"native={al.get('native_unclassified', 0)}"
    )
    mism = (cf.get("mismatch_top") or [])[:6]
    for c in mism:
        print(
            f"    MISMATCH det={c['det']} -> native={c['native']} x{c['n']}"
        )
    print(f"hint: {report.get('flip_ready_hint')}")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--path", default=str(DEFAULT_PATH))
    ap.add_argument(
        "--json", action="store_true", help="emit JSON not a summary"
    )
    args = ap.parse_args(argv)
    report = build_report(Path(args.path))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
