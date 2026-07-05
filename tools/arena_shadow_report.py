#!/usr/bin/env python
# arch: Arena shadow-validation report over the deterministic-vs-Haiku log | section=tools | frozen=no
"""Arena shadow-validation report - the flip-readiness gate for the Arena
deterministic coach (the SR/ARAM sibling is tools/hz_shadow_report.py).

core.arena_coach_shadow (-> data/arena_coach_shadow.jsonl) records, on every
real in-game Arena tick, BOTH sides side-by-side WITHOUT changing any live
output: the deterministic Arena block and the live Haiku block (each the seven
fields action / round_strategy / fight_rule / augment_advice / anvil_advice /
target_priority / risk). Before the deterministic block is flipped live in
place of the Haiku call, the operator needs an honest read of how often the two
sides already AGREE on the primary fight verdict.

PRIMARY AXIS - deterministic.action vs live_haiku.action. Both are compared on
a NORMALIZED label (upper / strip / collapse internal whitespace) so "KITE
BACK" and " kite  back " match.

DE-BIAS - dead / non-combat ticks are a category mismatch, not a real
fight-verdict disagreement, and must NOT drag the honest agreement rate down.
In Arena, when the player is dead the deterministic side emits an HP-0% survive
/ kite directive while Haiku emits a SPECTATE / "you are dead" observe state
(live example: deterministic round_strategy "Your HP 0%; ... kite, disengage,
survive" against Haiku action "SPECTATE ROUND" / round_strategy "You are
dead."). These are two different KINDS of tick, not two different verdicts, so
this report detects a dead-state tick and routes it to a SEPARATE dead_state
block; the combat agreement rate is computed only over LIVE-FIGHT rounds. This
mirrors the SR/ARAM report's _NON_LANING_STATE_MARKERS guard (its cycle-53
"WAIT RESPAWN" false-0% finding). The rule is intentionally simple + keyword
based - no NLP:

  * a tick is dead-state when the Haiku action is a spectate / dead state
    (SPECTATE / "you are dead" / "when you respawn" / "cannot fight"), OR the
    deterministic round_strategy signals the player is down ("hp 0%" / "you are
    dead" / "respawn").

This is a READ-ONLY report (no engine, no network, no write). Fail-soft: a
missing / empty / malformed log yields an awaiting-accrual state and exit 0,
never an exception.

MIN_SAMPLE gate - below MIN_SAMPLE live-fight rounds the flip-readiness verdict
reads "awaiting accrual"; at / above it emits an agreement percentage + a
coarse flip-readiness verdict. It is NOT a flip authorization - the operator
decides; this only flags the obvious not-ready states. The live log currently
holds only a handful of rows (all dead-state), far below the gate.

USAGE
    python tools/arena_shadow_report.py            # human summary, default path
    python tools/arena_shadow_report.py --json     # machine-readable JSON
    python tools/arena_shadow_report.py --path X --min-sample N
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
DEFAULT_PATH = _DATA / "arena_coach_shadow.jsonl"

# Flip-readiness needs a floor of honest live-fight samples before an agreement
# percentage means anything - mirror the SR/ARAM report's min-sample spirit.
# Counts LIVE-FIGHT rounds only (dead-state ticks are excluded from the gate).
MIN_SAMPLE = 20


def load_jsonl(path: Path) -> list[dict]:
    """Read a jsonl file into a list of dicts (fail-soft to []).

    A missing file or any unreadable / malformed LINE is skipped, never raised
    - the same robustness core.arena_coach_shadow itself promises. json decodes
    unicode transparently, so the Haiku free-text em-dashes in the live log
    load fine even though this tool's own source stays 7-bit ASCII."""
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


def _norm_action(text) -> str:
    """Uppercase + strip + collapse internal whitespace runs to one space, so
    "KITE BACK" and " kite  back " normalize to the same label. Non-str / empty
    -> "" (an unlabelled side)."""
    if not isinstance(text, str):
        return ""
    return " ".join(text.upper().split())


def _block(rec: dict, side: str) -> dict:
    """Return the deterministic / live_haiku sub-block as a dict (fail-soft {})."""
    blk = rec.get(side)
    return blk if isinstance(blk, dict) else {}


# Haiku dead / spectate state markers (normalized-lowercase substrings). When
# the Haiku side reads one of these it is observing a dead player, not calling a
# fight verdict. Live example: action "SPECTATE ROUND" + round_strategy "You are
# dead. ...". Kept deliberately small + defensible (no NLP).
_HAIKU_DEAD_MARKERS: tuple[str, ...] = (
    "spectate",
    "you are dead",
    "when you respawn",
    "cannot fight",
    "you cannot fight",
)

# Deterministic dead / down markers - the deterministic side surfaces HP 0% and
# a survive / kite directive while the player is down. round_strategy carries
# the signal (live example: "Your HP 0%; 3 teams left - kite, disengage,
# survive").
_DET_DEAD_MARKERS: tuple[str, ...] = (
    "hp 0%",
    "hp 0 %",
    "you are dead",
    "respawn",
)


def _norm_lower(text) -> str:
    """Lowercase + collapse whitespace for substring marker checks."""
    if not isinstance(text, str):
        return ""
    return " ".join(text.lower().split())


def is_dead_state(rec: dict) -> bool:
    """True when this tick is a dead / non-combat tick (a category mismatch, not
    a real fight-verdict disagreement) and must be routed OUT of the honest
    combat agreement sample.

    Two independent signals, either sufficient:
      * the Haiku action is a spectate / dead state, OR
      * the deterministic round_strategy signals the player is down (HP 0% /
        dead / respawn).
    See module docstring for the rationale."""
    haiku = _block(rec, "live_haiku")
    det = _block(rec, "deterministic")
    haiku_action = _norm_lower(haiku.get("action"))
    if any(m in haiku_action for m in _HAIKU_DEAD_MARKERS):
        return True
    det_strategy = _norm_lower(det.get("round_strategy"))
    if any(m in det_strategy for m in _DET_DEAD_MARKERS):
        return True
    return False


def record_agreement(rec: dict) -> Optional[dict]:
    """Classify one LIVE-FIGHT shadow record on the primary action axis.

    Returns {"det", "haiku", "agree"} over the normalized action labels when
    BOTH sides carry a non-empty action, else None (excluded from the sample).
    Dead-state ticks are NOT filtered here (the caller routes them first); this
    scores whatever fight-round record it is handed."""
    det = _norm_action(_block(rec, "deterministic").get("action"))
    haiku = _norm_action(_block(rec, "live_haiku").get("action"))
    if not det or not haiku:
        return None
    return {"det": det, "haiku": haiku, "agree": det == haiku}


def _coverage_block(records: list[dict]) -> dict:
    """Total rows, distinct champs, distinct rounds, live-fight vs dead-state
    counts. dead_state + live_fight partition every row exactly once."""
    total = len(records)
    champs = set()
    rounds = set()
    dead = 0
    live_fight = 0
    for rec in records:
        champ = rec.get("champ")
        if isinstance(champ, str) and champ.strip():
            champs.add(champ.strip())
        rnd = rec.get("round")
        if rnd is not None:
            rounds.add(str(rnd))
        if is_dead_state(rec):
            dead += 1
        else:
            live_fight += 1
    return {
        "total": total,
        "distinct_champs": len(champs),
        "distinct_rounds": len(rounds),
        "live_fight": live_fight,
        "dead_state": dead,
    }


def summarize_agreement(records: list[dict]) -> dict:
    """Deterministic-vs-Haiku action agreement over the LIVE-FIGHT sample.

    Dead-state ticks are counted (dead_state) but NEVER scored. A live-fight
    record where either side has no action label is comparable=excluded but
    still counted as unclassified. The honest combat agreement_rate is
    agree / comparable over live-fight rounds only."""
    dead_state = 0
    comparable = 0
    agree = 0
    unclassified = 0
    by_champ: dict[str, dict] = {}
    confusion: dict[tuple[str, str], int] = {}
    for rec in records:
        if is_dead_state(rec):
            dead_state += 1
            continue
        pair = record_agreement(rec)
        if pair is None:
            unclassified += 1
            continue
        comparable += 1
        agreed = bool(pair["agree"])
        if agreed:
            agree += 1
        champ = str(rec.get("champ") or "?")
        slot = by_champ.setdefault(champ, {"comparable": 0, "agree": 0})
        slot["comparable"] += 1
        if agreed:
            slot["agree"] += 1
        confusion[(pair["det"], pair["haiku"])] = (
            confusion.get((pair["det"], pair["haiku"]), 0) + 1
        )
    for slot in by_champ.values():
        slot["rate"] = (round(slot["agree"] / slot["comparable"], 4)
                        if slot["comparable"] else 0.0)
    return {
        "comparable": comparable,
        "agree": agree,
        "agreement_rate": round(agree / comparable, 4) if comparable else 0.0,
        "dead_state": dead_state,
        "unclassified": unclassified,
        "by_champion": dict(sorted(by_champ.items())),
        "confusion": [
            {"det": dv, "haiku": hv, "n": n, "agree": dv == hv}
            for (dv, hv), n in sorted(
                confusion.items(), key=lambda kv: (-kv[1], kv[0])
            )
        ],
    }


def _flip_readiness(coverage: dict, agreement: dict, min_sample: int) -> dict:
    """A coarse human read of flip-readiness. NOT a flip authorization - the
    operator decides; this only flags the obvious not-ready states.

    Below min_sample LIVE-FIGHT comparable rounds -> awaiting accrual. At / above
    -> ready=True with the agreement percentage + a verdict string."""
    comparable = agreement.get("comparable", 0)
    if coverage.get("total", 0) == 0:
        return {
            "ready": False,
            "state": "awaiting_accrual",
            "reason": "no shadow data yet - play real Arena games to accrue",
            "comparable": 0,
            "min_sample": min_sample,
        }
    if comparable < min_sample:
        return {
            "ready": False,
            "state": "awaiting_accrual",
            "reason": (f"awaiting accrual ({comparable}/{min_sample} live-fight "
                       "comparable rounds) - keep playing before a flip read"),
            "comparable": comparable,
            "min_sample": min_sample,
        }
    pct = round(100.0 * agreement.get("agree", 0) / comparable)
    return {
        "ready": True,
        "state": "sample_met",
        "reason": (f"agreement {pct}% over {comparable} live-fight comparable "
                   "rounds - review distribution before any flip (operator gate)"),
        "agreement_pct": pct,
        "comparable": comparable,
        "min_sample": min_sample,
    }


def build_report(path: Path, min_sample: int = MIN_SAMPLE) -> dict:
    """Assemble the full Arena shadow report dict from the log path."""
    records = load_jsonl(path)
    coverage = _coverage_block(records)
    agreement = summarize_agreement(records)
    return {
        "schema": "arena_shadow_report/v1",
        "path": str(path),
        "min_sample": min_sample,
        "coverage": coverage,
        "agreement": agreement,
        "flip_readiness": _flip_readiness(coverage, agreement, min_sample),
    }


def _print_human(report: dict) -> None:
    cov = report.get("coverage") or {}
    agr = report.get("agreement") or {}
    fr = report.get("flip_readiness") or {}
    print(f"[arena shadow] {cov.get('total', 0)} rows, "
          f"{cov.get('distinct_champs', 0)} champs, "
          f"{cov.get('distinct_rounds', 0)} rounds")
    print(f"    ticks: {cov.get('live_fight', 0)} live-fight, "
          f"{cov.get('dead_state', 0)} dead-state (excluded from agreement)")
    print(f"    agreement: {agr.get('agree', 0)}/{agr.get('comparable', 0)} "
          f"({agr.get('agreement_rate', 0.0)}) live-fight comparable, "
          f"{agr.get('unclassified', 0)} unclassified")
    if agr.get("by_champion"):
        for champ, slot in agr["by_champion"].items():
            print(f"    champ {champ}: {slot.get('agree', 0)}/"
                  f"{slot.get('comparable', 0)} ({slot.get('rate', 0.0)})")
    mism = [c for c in (agr.get("confusion") or []) if not c["agree"]]
    for c in mism[:6]:
        print(f"    MISMATCH det={c['det']} -> haiku={c['haiku']} x{c['n']}")
    print(f"flip-readiness: {fr.get('state')} - {fr.get('reason')}")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--path", default=str(DEFAULT_PATH),
                    help="shadow jsonl path (default data/arena_coach_shadow.jsonl)")
    ap.add_argument("--json", action="store_true", help="emit JSON not a summary")
    ap.add_argument("--min-sample", type=int, default=MIN_SAMPLE,
                    help=f"live-fight comparable rounds gate (default {MIN_SAMPLE})")
    args = ap.parse_args(argv)
    report = build_report(Path(args.path), min_sample=args.min_sample)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
