#!/usr/bin/env python
# arch: RC2-P5.7 (WS4) macro-response register flip-readiness report over the macro shadow log | section=tools | frozen=no
"""macro_response_shadow report - the flip-readiness agreement gate for the RC2
P5.7 (WS4) deterministic macro response (a Haiku-to-ZERO substrate).

``core/macro_response.py`` emits a deterministic REACTIVE-macro directive (a
``macro_tag`` + ``macro_line`` prose: a lost-objective recovery line, or - in
every accrued row so far - the generic ``macro_stagnation`` "break the stall"
nudge), and ``core/macro_response_shadow.py`` records it per coarse game state
alongside the native (Haiku) ``objective`` prose into
``data/macro_response_shadow.jsonl`` (gitignored). The macro row ships ADDITIVE
today, but before any FUTURE flip of the served Haiku ``objective`` FIELD onto
the deterministic ``macro_line`` the operator needs to know: at the ticks where
the macro nudge fires, does Haiku's macro REGISTER agree. This is that READ-ONLY
gate.

WHY THE REGISTER METRIC (and NOT the objective-category one). Unlike
``tools/objective_playbook_shadow_report.py`` - whose deterministic side names a
concrete objective (dragon / herald) so an OBJECTIVE-CATEGORY match is
meaningful - the macro deterministic side is a single ``macro_stagnation`` tag
with exactly three lead-keyed GENERIC stall nudges ("force vision and a pick" /
"take a side lane for a pick" / "keep scaling, safe CS"). Those name no single
objective, so the objective-category metric would false-score near 0%. The
RE-DERIVED metric is the ACTION REGISTER: is the directive ACTIVE-PUSH
(proactive - rotate / group / setup / take / push / force / pick / engage ...)
or PASSIVE-SCALE (reactive - farm / scale / safe / hold / wait / back / defend
...). The deterministic register is a near-constant of ``lead_state``: ahead and
even are ACTIVE (force / take); behind is PASSIVE (the ``safe`` token carries it).

  * HEADLINE = REGISTER ALIGNMENT RATE - over both-present rows, the fraction
    where the deterministic ``macro_line`` register equals the native
    ``objective`` register. A LOW rate is the do-not-flip-blind signal.
  * BY-LEAD block - because the det register is constant per lead_state, the
    per-lead alignment is the REAL signal: e.g. on the live log the BEHIND lead
    aligns 0% (det = PASSIVE "keep scaling / safe" but Haiku is ACTIVE "rotate to
    baron / force end" in 100% of behind rows), even while the headline clears.
  * CONFUSION matrix det-register -> native-register, most-common first.

REGISTER CLASSIFIER. Markup (``[T]`` timer / ``[E]`` enemy / ``[A]`` ally tags)
is stripped first - the tags are NOT balanced in the live prose so each is
dropped blindly. Then the line is normalized and scanned as WHOLE TOKENS, so
``defend`` (536 live rows) never fires the ACTIVE ``end`` hidden inside it, and
``baseline`` never fires the PASSIVE ``base``. Earliest matching token wins. NO
de-leak and NO fallback tier: a leading ``skip <register-word>`` excision was
measured to change only 0.556% of rows (below the keep-it-simple floor) and
would mis-demote genuine "SKIP - end game on nexus" ACTIVE rows, so the
classifier is a single earliest-whole-token pass (drake / baron / nexus are not
register words, so the objective-tool's skip-clause leak does not transfer).

READ-ONLY: no engine, no network, no write. Fail-soft - a missing / empty /
malformed log yields zeroed sections, never an exception.

USAGE
    python tools/macro_response_shadow_report.py            # human summary
    python tools/macro_response_shadow_report.py --json      # JSON
    python tools/macro_response_shadow_report.py --path X     # alt log path
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
DEFAULT_PATH = _DATA / "macro_response_shadow.jsonl"

# Flip-readiness thresholds (do-not-flip-blind defaults). The register is BINARY
# (ACTIVE / PASSIVE), so random agreement is ~50%; the floor MUST sit well above
# 0.50 to mean "they agree". Reuse the objective tool's 0.70 / 50 pair: 0.70 is
# 20 points above chance, and 50 both-present rows is the minimum to trust a
# rate. A HOLD is returned unless alignment clears the floor over a meaningful
# sample - this is a gate, not an authorization.
_MIN_ALIGN = 0.70
_MIN_SAMPLE = 50

# Action-register keyword table, matched as WHOLE TOKENS after markup strip +
# normalize. Earliest matching token wins (token positions never tie). The
# low-frequency words (farm/scale/recall/disengage/pressure) rarely DECIDE a
# live row but are retained for register completeness + symmetry with the
# core.macro_response STAGNATION vocabulary ("keep scaling, safe CS"); they are
# never wrong - they only fire when they are the earliest register token.
_KEYWORD_REGISTER: dict[str, str] = {
    # ACTIVE-PUSH - proactive: go make something happen.
    "rotate": "ACTIVE",     # reposition-to-act
    "group": "ACTIVE",      # collect-to-act
    "setup": "ACTIVE",      # stage-objective
    "take": "ACTIVE",       # claim
    "push": "ACTIVE",       # advance
    "force": "ACTIVE",      # compel
    "pick": "ACTIVE",       # hunt
    "engage": "ACTIVE",     # initiate
    "contest": "ACTIVE",    # fight-for
    "siege": "ACTIVE",      # pressure-turret
    "collapse": "ACTIVE",   # converge
    "end": "ACTIVE",        # close-game
    "pressure": "ACTIVE",   # apply-force
    "split": "ACTIVE",      # sidelane-threat
    # PASSIVE-SCALE - reactive: hold, wait, stay safe.
    "farm": "PASSIVE",      # cs-scale
    "scale": "PASSIVE",     # grow
    "safe": "PASSIVE",      # de-risk
    "hold": "PASSIVE",      # stay
    "wait": "PASSIVE",      # delay
    "back": "PASSIVE",      # retreat
    "defend": "PASSIVE",    # protect
    "recall": "PASSIVE",    # reset
    "base": "PASSIVE",      # reset
    "disengage": "PASSIVE",  # break-off
}
# Deliberately EXCLUDED as register-ambiguous (each appears in BOTH proactive and
# reactive live prose): vision / ward (information), position (locational),
# objective (the noun acted on). Inflected variants (grouped / regroup / forces /
# backline / endgame / rotation) are NOT keys either - base imperative forms only;
# adding them is sub-1% scope creep, and the whole-token guard means they never
# leak (rotation != rotate, backline != back).

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


def classify_register(text) -> Optional[str]:
    """Map a macro / objective directive to one action register ("ACTIVE" /
    "PASSIVE") - or None when no register keyword hits.

    Pipeline: strip markup -> normalize -> earliest WHOLE-TOKEN register wins.
    No skip-clause de-leak (measured 0.556% impact, below the keep-it-simple
    floor) and no fallback tier - a single earliest-token pass."""
    if not text or not isinstance(text, str):
        return None
    norm = _normalize_text(_strip_markup(text))
    if not norm:
        return None
    for tok in norm.split():
        reg = _KEYWORD_REGISTER.get(tok)
        if reg is not None:
            return reg
    return None


def _both_present(rec: dict) -> bool:
    """True when the record carries BOTH a deterministic macro_line AND a
    native_objective - the only rows where the two surfaces can be compared."""
    return bool(rec.get("macro_line")) and bool(rec.get("native_objective"))


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
    """HEADLINE - deterministic-macro register vs native objective register over
    EVERY both-present row (no row dropping). Also reports the det and native
    register distributions and the unclassified counts (a None on either side
    counts as NOT aligned but is NOT excluded)."""
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
        det_reg = classify_register(rec.get("macro_line"))
        nat_reg = classify_register(rec.get("native_objective"))
        det_dist[det_reg or "none"] += 1
        native_dist[nat_reg or "none"] += 1
        if det_reg is None:
            det_unclassified += 1
        if nat_reg is None:
            native_unclassified += 1
        if det_reg is not None and nat_reg is not None and det_reg == nat_reg:
            aligned += 1
    return {
        "both_present": both,
        "aligned": aligned,
        "alignment_rate": round(aligned / both, 4) if both else 0.0,
        "det_register_dist": dict(det_dist.most_common()),
        "native_register_dist": dict(native_dist.most_common()),
        "det_unclassified": det_unclassified,
        "native_unclassified": native_unclassified,
    }


def summarize_by_lead_state(records: list[dict]) -> dict:
    """Per-lead_state register view - the REAL signal, since the deterministic
    register is a near-constant of lead_state. For each lead: both-present
    count, the (constant) det register, the native register distribution, and
    the within-lead alignment rate. A lead where det is ACTIVE but Haiku is
    PASSIVE (or vice versa) at high volume is the do-not-flip blocker even when
    the headline clears."""
    by_lead: dict[str, dict] = {}
    det_seen: dict[str, Counter] = {}
    for rec in records:
        if not _both_present(rec):
            continue
        lead = str(rec.get("lead_state") or "?")
        det_reg = classify_register(rec.get("macro_line"))
        nat_reg = classify_register(rec.get("native_objective"))
        slot = by_lead.setdefault(
            lead,
            {"both_present": 0, "det_register": "none",
             "native_register_dist": Counter(), "aligned": 0},
        )
        det_seen.setdefault(lead, Counter())[det_reg or "none"] += 1
        slot["both_present"] += 1
        slot["native_register_dist"][nat_reg or "none"] += 1
        if det_reg is not None and nat_reg is not None and det_reg == nat_reg:
            slot["aligned"] += 1
    out: dict[str, dict] = {}
    for lead, slot in sorted(by_lead.items()):
        both = slot["both_present"]
        # det is constant per lead in practice; take the most-common defensively.
        det_reg = det_seen[lead].most_common(1)[0][0] if det_seen.get(lead) else "none"
        out[lead] = {
            "both_present": both,
            "det_register": det_reg,
            "native_register_dist": dict(slot["native_register_dist"].most_common()),
            "aligned": slot["aligned"],
            "alignment_rate": round(slot["aligned"] / both, 4) if both else 0.0,
        }
    return out


def summarize_confusion(records: list[dict]) -> dict:
    """CONFUSION matrix det-register -> native-register over both-present rows,
    most-common first. An "agree" pair needs both sides classified AND equal
    (an unclassified "none" on either side is never an agreement)."""
    counts: dict[tuple[str, str], int] = {}
    for rec in records:
        if not _both_present(rec):
            continue
        det_reg = classify_register(rec.get("macro_line"))
        nat_reg = classify_register(rec.get("native_objective"))
        d = det_reg or "none"
        n = nat_reg or "none"
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
    HOLD (do-not-flip-blind): a REVIEW needs register alignment >= the floor
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
            f"HOLD - register alignment {rate:.0%} < {_MIN_ALIGN:.0%}; Haiku's "
            "macro register diverges at these ticks, so flipping the served "
            "field onto the deterministic macro line would change it"
        )
    return (
        f"REVIEW - register alignment {rate:.0%} over {both} rows clears the "
        "floor; operator gate before any flip (check the per-lead_state block - "
        "a single lead can be 0% even when the headline clears)"
    )


def build_report(path: Path) -> dict:
    """Assemble the full macro_response_shadow report dict from the log."""
    records = load_jsonl(path)
    coverage = _coverage_block(records)
    alignment = summarize_alignment(records)
    by_lead = summarize_by_lead_state(records)
    confusion = summarize_confusion(records)
    return {
        "schema": "macro_response_shadow_report/v1",
        "coverage": coverage,
        "alignment": alignment,
        "by_lead_state_register": by_lead,
        "confusion": confusion,
        "flip_ready_hint": _flip_hint(coverage, alignment),
    }


def _print_human(report: dict) -> None:
    cov = report.get("coverage") or {}
    al = report.get("alignment") or {}
    bl = report.get("by_lead_state_register") or {}
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
    if al.get("det_register_dist"):
        dd = ", ".join(f"{k} x{v}" for k, v in al["det_register_dist"].items())
        print(f"    det register: {dd}")
    if al.get("native_register_dist"):
        nd = ", ".join(
            f"{k} x{v}" for k, v in al["native_register_dist"].items()
        )
        print(f"    native register: {nd}")
    print(
        f"    unclassified: det={al.get('det_unclassified', 0)} "
        f"native={al.get('native_unclassified', 0)}"
    )
    if bl:
        print("[by-lead register]")
        for lead, s in bl.items():
            nat = ", ".join(
                f"{k} x{v}" for k, v in s.get("native_register_dist", {}).items()
            )
            print(
                f"    {lead}: det={s.get('det_register')} "
                f"native {nat} -> align {s.get('alignment_rate', 0.0)} "
                f"({s.get('aligned', 0)}/{s.get('both_present', 0)})"
            )
    mism = (cf.get("mismatch_top") or [])[:6]
    for c in mism:
        print(f"    MISMATCH det={c['det']} -> native={c['native']} x{c['n']}")
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
