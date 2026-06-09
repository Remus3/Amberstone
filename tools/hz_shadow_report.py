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

NOTE - the precompute-vs-Haiku AGREEMENT metric (does the deterministic verdict
match what Haiku said for the same tick) is a documented FUTURE: it needs the
live coach output captured alongside the precompute in the shadow record, which
the v1 HZ-C1/C2 records do not yet carry. This report covers coverage +
distribution, the gates that do not depend on that capture.

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
    """Coverage + anti_tank/anti_squishy lean distribution (build)."""
    block = _coverage_block(records)
    covered = [r for r in records if r.get("covered")]
    leans = Counter(str(r.get("lean") or "?") for r in covered)
    block["by_lean"] = dict(sorted(leans.items()))
    return block


def build_report(choice_path: Path, build_path: Path) -> dict:
    """Assemble the full HZ shadow report dict from the two log paths."""
    laning = summarize_laning(load_jsonl(choice_path))
    build = summarize_build(load_jsonl(build_path))
    return {
        "schema": "hz_shadow_report/v1",
        "laning": laning,
        "build": build,
        "flip_ready_hint": _flip_hint(laning, build),
    }


def _flip_hint(laning: dict, build: dict) -> str:
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
    return "coverage accruing - review distribution before any flip (operator gate)"


def _print_human(report: dict) -> None:
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
