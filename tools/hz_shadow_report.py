#!/usr/bin/env python
# arch: HZ-C validation report over the precompute shadow logs | section=tools | frozen=no
"""HZ shadow-validation report - the flip-readiness gate for the precomputed
A/B choice-coach (charter 4b "do not flip blind").

HZ-C1 (``core.hz_choice_shadow`` -> data/hz_choice_shadow.jsonl) and HZ-C2
(``core.hz_build_shadow`` -> data/hz_build_shadow.jsonl) record, on every real
in-game tick, what the PRECOMPUTED laning + build tables WOULD offer - including
whether the seed table even COVERED the matchup. Before any coach is flipped off
its live Haiku call, the operator needs to know:

  * COVERAGE - what fraction of real-game ticks the seed table actually covered
    (a seed sample only holds ~10 champions; a low coverage rate means most live
    games fall through to the existing Haiku path, so a flip would be premature).
  * DISTRIBUTION - what the precompute recommends (laning verdict labels; build
    anti_tank vs anti_squishy lean), so a degenerate "always back_off" / "always
    anti_squishy" table is caught before it reaches a live game.
  * PER-CHAMPION coverage - which champions are exercised by real games, so the
    next coverage-expansion generation run can prioritise the gaps.

This is a READ-ONLY report (no engine, no network, no write). Fail-soft: a
missing / empty / malformed log yields a zeroed section, never an exception.

AGREEMENT - precompute-vs-Haiku (does the deterministic verdict match what
Haiku said for the same tick) is LIVE since item 369 (2026-06-09): shadow
records now carry the live coach output - ``native_action`` (Haiku prose
action string, e.g. "TRADE") + ``native_choices`` (Haiku A/B chip dicts) -
and this report classifies both sides into a coarse verdict (trade / all_in /
back_off / recall / hold) and scores agreement over covered comparable ticks.
Records logged BEFORE a precompute table existed are permanently
covered=false (``covered`` is baked at log time), so agreement accrues on
NEW live games only.

USAGE
    python tools/hz_shadow_report.py            # human summary, default paths
    python tools/hz_shadow_report.py --json     # machine-readable JSON
    python tools/hz_shadow_report.py --choice-path X --build-path Y
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
DEFAULT_CHOICE_PATH = _DATA / "hz_choice_shadow.jsonl"
DEFAULT_BUILD_PATH = _DATA / "hz_build_shadow.jsonl"


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


def _coverage_block(records: list[dict]) -> dict:
    """Total / covered / rate + comparable count + per-champion coverage.

    ``comparable`` counts records that carry the live coach signal (a native
    action or native A/B choices), i.e. records where the precompute CAN be
    compared against what Haiku said - the sample size for the eventual
    precompute-vs-Haiku validation."""
    total = len(records)
    covered = sum(1 for r in records if r.get("covered"))
    comparable = sum(
        1 for r in records if r.get("native_choices") or r.get("native_action")
    )
    by_champ: dict[str, dict] = {}
    for r in records:
        champ = str(r.get("my_champion") or "?")
        slot = by_champ.setdefault(champ, {"total": 0, "covered": 0})
        slot["total"] += 1
        if r.get("covered"):
            slot["covered"] += 1
    return {
        "total": total,
        "covered": covered,
        "coverage_rate": round(covered / total, 4) if total else 0.0,
        "comparable": comparable,
        "by_champion": dict(sorted(by_champ.items())),
    }


def _first_choice_label(rec: dict) -> Optional[str]:
    """The recommended (A) choice label from a shadow record, or None."""
    choices = rec.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        label = choices[0].get("label")
        if label:
            return str(label)
    return None


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


def classify_verdict(text) -> Optional[str]:
    """Map free text (a precompute A-label or Haiku prose/chip label) to one
    coarse verdict: "trade" / "all_in" / "back_off" / "recall" / "hold" -
    or None when no keyword hits (unclassifiable)."""
    if not text or not isinstance(text, str):
        return None
    norm = _normalize_verdict_text(text)
    if not norm:
        return None
    for phrase, verdict in _VERDICT_PHRASES:
        if phrase in norm:
            return verdict
    return None


def _native_choice_label(rec: dict) -> Optional[str]:
    """The first native (Haiku) A/B chip label from a shadow record, or None."""
    choices = rec.get("native_choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        label = choices[0].get("label")
        if label:
            return str(label)
    return None


def _has_native_signal(rec: dict) -> bool:
    """True when the record carries any live coach output (item 369 capture)."""
    return bool(rec.get("native_choices") or rec.get("native_action"))


def _native_verdict(rec: dict) -> Optional[str]:
    """Classify the native (Haiku) side: prose action first, then the first
    native A/B chip label as fallback."""
    verdict = classify_verdict(rec.get("native_action"))
    if verdict is None:
        verdict = classify_verdict(_native_choice_label(rec))
    return verdict


def record_agreement(rec: dict) -> Optional[dict]:
    """Classify both sides of one shadow record.

    precompute = verdict of the recommended (A) choice label, only when the
    record is covered and carries choices; native = verdict of the Haiku
    output. Returns {"precompute", "native", "agree"} when BOTH sides
    classified, else None (record excluded from the agreement sample)."""
    precompute = None
    if rec.get("covered"):
        precompute = classify_verdict(_first_choice_label(rec))
    native = _native_verdict(rec)
    if precompute is None or native is None:
        return None
    return {"precompute": precompute, "native": native,
            "agree": precompute == native}


def summarize_agreement(records: list[dict]) -> dict:
    """Precompute-vs-Haiku agreement over the comparable covered sample.

    unclassified_native = covered records with a native signal the classifier
    could not map; uncovered_with_native = records with a native signal the
    seed table did not cover (the table-gap denominator)."""
    comparable = 0
    agree = 0
    by_mode: dict[str, dict] = {}
    by_native: dict[str, dict] = {}
    unclassified_native = 0
    uncovered_with_native = 0
    for rec in records:
        has_native = _has_native_signal(rec)
        if has_native and not rec.get("covered"):
            uncovered_with_native += 1
        pair = record_agreement(rec)
        if pair is None:
            if (has_native and rec.get("covered")
                    and _native_verdict(rec) is None):
                unclassified_native += 1
            continue
        comparable += 1
        agreed = bool(pair["agree"])
        if agreed:
            agree += 1
        mode = str(rec.get("mode") or "?")
        slot = by_mode.setdefault(mode, {"comparable": 0, "agree": 0})
        slot["comparable"] += 1
        if agreed:
            slot["agree"] += 1
        nslot = by_native.setdefault(pair["native"], {"n": 0, "agree": 0})
        nslot["n"] += 1
        if agreed:
            nslot["agree"] += 1
    for slot in by_mode.values():
        slot["rate"] = (round(slot["agree"] / slot["comparable"], 4)
                        if slot["comparable"] else 0.0)
    return {
        "comparable_covered": comparable,
        "agree": agree,
        "agreement_rate": round(agree / comparable, 4) if comparable else 0.0,
        "by_mode": dict(sorted(by_mode.items())),
        "by_native": dict(sorted(by_native.items())),
        "unclassified_native": unclassified_native,
        "uncovered_with_native": uncovered_with_native,
    }


def summarize_laning(records: list[dict]) -> dict:
    """Coverage + band distribution + recommended-A-label histogram (laning)."""
    block = _coverage_block(records)
    covered = [r for r in records if r.get("covered")]
    bands = Counter(str(r.get("band") or "?") for r in covered)
    recs = Counter(
        lbl for lbl in (_first_choice_label(r) for r in covered) if lbl
    )
    block["by_band"] = dict(sorted(bands.items()))
    block["by_recommendation"] = dict(recs.most_common())
    return block


def summarize_build(records: list[dict]) -> dict:
    """Coverage + anti_tank/anti_squishy lean distribution (build).

    ``by_lean`` counts every covered ROW. The shadow dedup signature includes
    item_count + a 5s game-time bucket, so one long game emits many rows for the
    same comp and ``by_lean`` over-weights long games (a single durable game can
    dominate the tally). ``by_lean_per_game`` first collapses each distinct
    (mode, my_champion, enemy_comp) game-instance to a single lean, giving the
    honest per-game balance the do-not-flip-blind decision actually needs."""
    block = _coverage_block(records)
    covered = [r for r in records if r.get("covered")]
    leans = Counter(str(r.get("lean") or "?") for r in covered)
    block["by_lean"] = dict(sorted(leans.items()))
    per_game: dict = {}
    for r in covered:
        gkey = (
            str(r.get("mode") or "?"),
            str(r.get("my_champion") or "?"),
            tuple(r.get("enemy_comp") or ()),
        )
        per_game[gkey] = str(r.get("lean") or "?")
    block["distinct_games"] = len(per_game)
    block["by_lean_per_game"] = dict(sorted(Counter(per_game.values()).items()))
    return block


def build_report(choice_path: Path, build_path: Path) -> dict:
    """Assemble the full HZ shadow report dict from the two log paths."""
    choice_records = load_jsonl(choice_path)
    build_records = load_jsonl(build_path)
    laning = summarize_laning(choice_records)
    build = summarize_build(build_records)
    agreement = {
        "laning": summarize_agreement(choice_records),
        "build": summarize_agreement(build_records),
    }
    return {
        "schema": "hz_shadow_report/v2",
        "laning": laning,
        "build": build,
        "agreement": agreement,
        "flip_ready_hint": _flip_hint(laning, build, agreement),
    }


def _flip_hint(laning: dict, build: dict, agreement: Optional[dict] = None) -> str:
    """A coarse human read of flip-readiness. NOT a flip authorization - the
    operator decides; this only flags the obvious not-ready states."""
    lt, bt = laning.get("total", 0), build.get("total", 0)
    if lt == 0 and bt == 0:
        return "no shadow data yet - play real games to accrue coverage"
    lr = laning.get("coverage_rate", 0.0)
    br = build.get("coverage_rate", 0.0)
    if max(lr, br) < 0.5:
        return ("low seed coverage (<50%) - expand the precompute champion set "
                "before considering a flip")
    comparable = 0
    agreed = 0
    for sec in (agreement or {}).values():
        comparable += sec.get("comparable_covered", 0)
        agreed += sec.get("agree", 0)
    if comparable > 0:
        pct = round(100.0 * agreed / comparable)
        return (f"coverage accruing - agreement {pct}% over {comparable} "
                "comparable ticks - review distribution before any flip "
                "(operator gate)")
    return "coverage accruing - review distribution before any flip (operator gate)"


def _print_human(report: dict) -> None:
    agreement = report.get("agreement") or {}
    for key in ("laning", "build"):
        sec = report.get(key) or {}
        print(f"[{key}] {sec.get('covered', 0)}/{sec.get('total', 0)} covered "
              f"(rate {sec.get('coverage_rate', 0.0)}), "
              f"{sec.get('comparable', 0)} comparable")
        if key == "laning" and sec.get("by_recommendation"):
            for lbl, n in sec["by_recommendation"].items():
                print(f"    rec: {lbl} x{n}")
        if key == "build" and sec.get("by_lean"):
            for lean, n in sec["by_lean"].items():
                print(f"    lean: {lean} x{n}")
            if sec.get("by_lean_per_game"):
                pg = ", ".join(
                    f"{lean} x{n}" for lean, n in sec["by_lean_per_game"].items()
                )
                print(f"    lean per-game ({sec.get('distinct_games', 0)} "
                      f"distinct): {pg}")
        agr = agreement.get(key) or {}
        print(f"    agreement: {agr.get('agree', 0)}/"
              f"{agr.get('comparable_covered', 0)} "
              f"({agr.get('agreement_rate', 0.0)}) comparable-covered, "
              f"{agr.get('uncovered_with_native', 0)} uncovered-with-native")
        print(f"    native unclassified (covered): "
              f"{agr.get('unclassified_native', 0)}")
    print(f"hint: {report.get('flip_ready_hint')}")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--choice-path", default=str(DEFAULT_CHOICE_PATH))
    ap.add_argument("--build-path", default=str(DEFAULT_BUILD_PATH))
    ap.add_argument("--json", action="store_true", help="emit JSON not a summary")
    args = ap.parse_args(argv)
    report = build_report(Path(args.choice_path), Path(args.build_path))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
