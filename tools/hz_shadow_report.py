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


def _is_even_precompute_label(rec: dict) -> bool:
    """True when the precompute A-label is the ``even`` verdict ("Even trade on
    your cd window", core/precomputed_laning_coach.py). classify_verdict now
    maps this to its own ``even`` bucket (item 508), and record_agreement counts
    an even precompute as agreement against a Haiku ``hold`` (the even verdict's
    B-option is "Hold position"). This breakdown still tallies which native
    verdict the even ticks faced, by native verdict."""
    label = _first_choice_label(rec)
    if not label:
        return False
    return "even" in _normalize_verdict_text(label)


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


# Objective / macro map-calls that are NOT laning trade verdicts: mid/late-game
# directives the live coach emits (SETUP DRAKE, TAKE BARON, DEFEND MID TOWER,
# CRASH/FREEZE/PUSH a wave, END GAME, CAMP/ROTATE/POSITION for an objective).
# The precompute laning A/B only ever emits trade/all_in/back_off/even/hold plus
# an economy recall, so an objective tick has NO laning counterpart. Left in, it
# biases the flip-readiness gate two ways: its A/B chip carries a hold-ish label
# scored as a false comparable "hold", or it floods unclassified_native (on the
# live hz_choice_shadow log: ~8.3k false comparable leaks + ~20.8k mislabeled
# unclassified). Unlike the STATE markers above (absolute), these are guarded in
# _is_non_laning_native_state by classify_verdict(action) is None, so a COMPOUND
# action that itself states a lane verdict ("SETUP LANE TRADE" -> trade, "PUSH
# LANE POKE" -> trade) is preserved, never over-excluded. Anti-circularity: this
# de-biases the sample, it is NOT tuned to move the agreement rate (measured
# effect was a small DROP, macro "hold" leaks were inflating agreement).
_NON_LANING_ACTION_MARKERS: tuple[str, ...] = (
    "baron", "drake", "dragon", "herald", "grub", "nexus", "elder",
    "soul", "siege", "objective", "end game", "camp", "rotate",
    "defend", "setup", "position", "crash", "freeze", "push",
    "split", "roam", "gank", "group",
)


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


# The precompute's ECONOMY/recall signal lives in choice B, never choice A
# (core/precomputed_laning_coach._build_choices: A is the laning-combat verdict,
# B is the economy recall directive when the cell's economy.recall is set).
# These are the two economy recall labels from
# core/precomputed_laning_coach._RECALL_LABELS (recall_now -> "Recall now",
# back_soon -> "Back soon"), normalized. Hardcoded (not imported) so this report
# stays a stdlib-only standalone tool - a top-level "from core ..." import
# breaks "python tools/hz_shadow_report.py" because tools/ is on sys.path, not
# the repo root. If a third recall label is ever added to _RECALL_LABELS, mirror
# it here. classify_verdict maps "Recall now" -> recall but MISSES "Back soon"
# (it hits no _VERDICT_PHRASES keyword), so detection checks BOTH.
_RECALL_DIRECTIVE_LABELS: frozenset = frozenset({"recall now", "back soon"})


def _is_recall_directive_label(label) -> bool:
    """True when a choice label is an economy-recall directive - either it
    classifies to the ``recall`` verdict (e.g. "Recall now") OR its normalized
    form is in the precompute economy recall set ("back soon", which
    classify_verdict alone does NOT catch)."""
    if not label or not isinstance(label, str):
        return False
    if classify_verdict(label) == "recall":
        return True
    return _normalize_verdict_text(label) in _RECALL_DIRECTIVE_LABELS


# Build-lean keyword tables - the BUILD shadow agreement runs on a DIFFERENT
# axis than laning: the precompute side is the stored ``lean`` field
# (anti_tank / anti_squishy), and the native (Haiku) side is the live
# ``item_build`` text. classify_build_lean maps that free build text to the
# same two-value lean by item-name / phrasing keywords. Disjoint sets; a build
# that signals neither (a plain crit/AP core) or BOTH equally -> None
# (excluded), the same "only score a clear signal" contract classify_verdict
# uses. This is what makes the build flip-readiness gate measurable at all -
# before item 502 the build native captured the LANING action (wrong axis), so
# build agreement was structurally 0/0.
_ANTI_TANK_KW: tuple[str, ...] = (
    "anti tank", "dominik", "mortal reminder", "last whisper", "serylda",
    "black cleaver", "cleaver", "void staff", "liandry", "demonic embrace",
    "blade of the ruined king", "botrk", "kraken", "giant slayer", "wits end",
    "terminus", "divine sunderer", "max health", "max hp", "percent hp",
    "shred", "armor pen", "armor penetration", "magic pen", "magic penetration",
    "their tanks", "vs tank", "tanky",
)
_ANTI_SQUISHY_KW: tuple[str, ...] = (
    "anti squishy", "lethality", "youmuu", "duskblade", "edge of night",
    "serpent", "eclipse", "prowler", "opportunity", "hubris", "profane",
    "collector", "axiom", "ghostblade", "burst", "squish", "one shot",
    "oneshot", "assassinate",
)


def classify_build_lean(text) -> Optional[str]:
    """Map free build text (a precompute lean label or Haiku item_build prose)
    to one coarse lean: "anti_tank" / "anti_squishy" - or None when no keyword
    hits or the two leans tie (ambiguous hybrid build). Majority of distinct
    keyword hits wins; a tie or zero hits returns None so only a clear lean is
    ever scored."""
    if not text or not isinstance(text, str):
        return None
    norm = _normalize_verdict_text(text)
    if not norm:
        return None
    at = sum(1 for kw in _ANTI_TANK_KW if kw in norm)
    asq = sum(1 for kw in _ANTI_SQUISHY_KW if kw in norm)
    if at == asq:
        return None
    return "anti_tank" if at > asq else "anti_squishy"


def _is_non_laning_native_state(rec: dict) -> bool:
    """True when the native (Haiku) signal is not a laning verdict at all -
    excluded from EVERY agreement metric (neither comparable, unclassified-
    native, nor the uncovered-with-native table-gap denominator).

    Two classes: (1) a coach status/overlay STATE - a dead player's "WAIT
    RESPAWN" or a policy "COACHING DISABLED" - matched absolutely (cycle-53
    false-0% finding). (2) an objective/macro MAP-CALL ("SETUP DRAKE FIGHT",
    "END GAME", "DEFEND MID TOWER", "CRASH BOT WAVE") that does NOT itself
    state a lane verdict - guarded on classify_verdict(action) is None so a
    compound action naming a real lane verdict ("SETUP LANE TRADE" -> trade)
    is preserved, never over-excluded."""
    action = rec.get("native_action")
    if not isinstance(action, str):
        return False
    norm = _normalize_verdict_text(action)
    if any(marker in norm for marker in _NON_LANING_STATE_MARKERS):
        return True
    if classify_verdict(action) is None and any(
        marker in norm for marker in _NON_LANING_ACTION_MARKERS
    ):
        return True
    return False


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


def _precompute_offers_recall(rec: dict) -> bool:
    """True when the precompute's economy block recommended a back for this tick
    - i.e. ANY choice label in the record is a recall directive. Choice B
    carries the economy recall in _build_choices, but every choice is scanned to
    be robust. Used only to score native-recall ticks against the precompute
    economy block in the laning economy sub-block."""
    choices = rec.get("choices")
    if not isinstance(choices, list):
        return False
    return any(
        isinstance(ch, dict) and _is_recall_directive_label(ch.get("label"))
        for ch in choices
    )


def _is_native_recall(rec: dict) -> bool:
    """True when the native (Haiku) side classifies to the ``recall`` verdict -
    a cross-axis economy decision, not a laning-combat verdict."""
    return _native_verdict(rec) == "recall"


def record_agreement(rec: dict) -> Optional[dict]:
    """Classify both sides of one shadow record.

    precompute = verdict of the recommended (A) choice label, only when the
    record is covered and carries choices; native = verdict of the Haiku
    output. Returns {"precompute", "native", "agree"} when BOTH sides
    classified, else None (record excluded from the agreement sample).

    even<->hold mapping (item 508): the precompute "even" verdict's A-chip
    B-option is literally "Hold position", so a precompute "even" counts as
    agreement against a Haiku "hold" as well as a Haiku "even"; every other
    pair agrees only on exact match (unchanged).

    native recall (cross-axis): a native "recall" is an ECONOMY decision, not a
    laning-combat verdict, and the precompute combat-A can never be "recall", so
    such a pair is excluded here (returns None) and scored separately in
    summarize_agreement's economy sub-block."""
    precompute = None
    if rec.get("covered"):
        precompute = classify_verdict(_first_choice_label(rec))
    native = _native_verdict(rec)
    if precompute is None or native is None:
        return None
    if native == "recall":
        return None
    agree = (precompute == native) or (precompute == "even" and native == "hold")
    return {"precompute": precompute, "native": native, "agree": agree}


# The report drops covered ticks whose native (Haiku) signal the keyword
# classifier cannot map (unclassified_native), but the raw count alone gives the
# next classifier pass no target. These surface the top offenders by count so a
# recurring unmapped phrase ("ward the river", a build the lean tables miss) is
# visible instead of silently deflating the flip-readiness denominator. Same
# diagnostic class as the confusion matrix: show WHERE the gate loses signal.
_UNCLASSIFIED_SAMPLE_LIMIT = 10  # distinct strings kept in the JSON report
_SAMPLE_PRINT_HEAD = 8           # distinct strings shown in the human summary
_SAMPLE_PRINT_WIDTH = 80         # human-print truncation (JSON keeps full text)


def _unclassified_native_text(rec: dict) -> Optional[str]:
    """The native (Haiku) string that failed to classify - the prose action
    first, then the first native A/B chip label (the same order _native_verdict
    tried). Used only to surface WHICH phrasings the classifier misses."""
    text = rec.get("native_action") or _native_choice_label(rec)
    if not text or not isinstance(text, str):
        return None
    return text


def _top_samples(counter: Counter, limit: int = _UNCLASSIFIED_SAMPLE_LIMIT) -> list:
    """Counter -> deterministic [[text, count], ...] ordered count desc then text
    asc, so the report is byte-stable across runs on the same log."""
    ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return [[text, n] for text, n in ranked[:limit]]


def summarize_agreement(records: list[dict]) -> dict:
    """Precompute-vs-Haiku agreement over the comparable covered sample.

    unclassified_native = covered records with a native signal the classifier
    could not map; unclassified_native_samples = the top unmapped strings by
    count (the classifier-gap target); uncovered_with_native = records with a
    native signal the seed table did not cover (the table-gap denominator)."""
    comparable = 0
    agree = 0
    by_mode: dict[str, dict] = {}
    by_native: dict[str, dict] = {}
    by_precompute: dict[str, int] = {}
    confusion: dict[tuple[str, str], int] = {}
    even_by_native: dict[str, int] = {}
    unclassified_native = 0
    unclassified_samples: Counter = Counter()
    uncovered_with_native = 0
    native_recall = 0
    economy_precompute_also_recall = 0
    for rec in records:
        if _is_non_laning_native_state(rec):
            continue  # dead-state / policy-disabled overlay - not a laning tick
        has_native = _has_native_signal(rec)
        if has_native and not rec.get("covered"):
            uncovered_with_native += 1
        pair = record_agreement(rec)
        if pair is None:
            if has_native and rec.get("covered") and _is_native_recall(rec):
                # cross-axis economy decision - tallied in the economy sub-block,
                # not the laning-combat comparable (record_agreement dropped it)
                native_recall += 1
                if _precompute_offers_recall(rec):
                    economy_precompute_also_recall += 1
            elif (has_native and rec.get("covered")
                    and _native_verdict(rec) is None):
                unclassified_native += 1
                text = _unclassified_native_text(rec)
                if text:
                    unclassified_samples[text] += 1
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
        pv, nv = pair["precompute"], pair["native"]
        by_precompute[pv] = by_precompute.get(pv, 0) + 1
        confusion[(pv, nv)] = confusion.get((pv, nv), 0) + 1
        if _is_even_precompute_label(rec):
            even_by_native[nv] = even_by_native.get(nv, 0) + 1
    for slot in by_mode.values():
        slot["rate"] = (round(slot["agree"] / slot["comparable"], 4)
                        if slot["comparable"] else 0.0)
    return {
        "comparable_covered": comparable,
        "agree": agree,
        "agreement_rate": round(agree / comparable, 4) if comparable else 0.0,
        "by_mode": dict(sorted(by_mode.items())),
        "by_native": dict(sorted(by_native.items())),
        "by_precompute": dict(sorted(by_precompute.items())),
        "confusion": [
            {"precompute": pv, "native": nv, "n": n, "agree": pv == nv}
            for (pv, nv), n in sorted(
                confusion.items(), key=lambda kv: (-kv[1], kv[0])
            )
        ],
        "unclassified_native": unclassified_native,
        "unclassified_native_samples": _top_samples(unclassified_samples),
        "uncovered_with_native": uncovered_with_native,
        "even_precompute_by_native": dict(sorted(even_by_native.items())),
        "economy": {
            "native_recall": native_recall,
            "precompute_also_recall": economy_precompute_also_recall,
        },
    }


def summarize_build_agreement(records: list[dict]) -> dict:
    """Precompute-vs-Haiku agreement for the BUILD lane, on the lean axis.

    Unlike laning (a trade verdict), the build precompute side is the stored
    ``lean`` field (anti_tank / anti_squishy) and the native side is the live
    Haiku ``item_build`` text classified by classify_build_lean. A record is
    comparable when it is covered, carries a non-None precompute lean, AND the
    native build text classifies to a lean. Same return shape as
    summarize_agreement so the report + printer treat both lanes uniformly.

    unclassified_native = covered records with a precompute lean + a native
    build signal the classifier could not lean; unclassified_native_samples =
    the top unmapped build strings by count (the lean-classifier-gap target);
    uncovered_with_native = records with a native build signal the seed table did
    not cover."""
    comparable = 0
    agree = 0
    by_mode: dict[str, dict] = {}
    by_native: dict[str, dict] = {}
    by_precompute: dict[str, int] = {}
    confusion: dict[tuple[str, str], int] = {}
    unclassified_native = 0
    unclassified_samples: Counter = Counter()
    uncovered_with_native = 0
    for rec in records:
        native_text = rec.get("native_action")
        has_native = bool(native_text)
        precompute = rec.get("lean") if rec.get("covered") else None
        native = classify_build_lean(native_text)
        # Dead-state / macro overlay ("WAIT RESPAWN", "COACHING DISABLED", a
        # SETUP DRAKE macro call) that is NOT itself a build lean -> drop it from
        # every bucket, mirroring the laning guard's de-bias intent. GATED on
        # native is None so a REAL build that merely mentions "respawn"/"setup" as
        # buy-timing (e.g. "Complete Mortal Reminder on respawn") still classifies
        # to a lean and stays comparable - the build-lean classifier is the
        # comparability arbiter here, unlike laning where classify_verdict doubles
        # as both the verdict AND the guard axis. Pure de-bias: no comparable tick
        # is ever dropped, so comparable_covered + agree (the rate) never move.
        if native is None and _is_non_laning_native_state(rec):
            continue
        if has_native and not rec.get("covered"):
            uncovered_with_native += 1
        if precompute is None:
            continue
        if native is None:
            if has_native:
                unclassified_native += 1
                if isinstance(native_text, str):
                    unclassified_samples[native_text] += 1
            continue
        comparable += 1
        agreed = precompute == native
        if agreed:
            agree += 1
        mode = str(rec.get("mode") or "?")
        slot = by_mode.setdefault(mode, {"comparable": 0, "agree": 0})
        slot["comparable"] += 1
        if agreed:
            slot["agree"] += 1
        nslot = by_native.setdefault(native, {"n": 0, "agree": 0})
        nslot["n"] += 1
        if agreed:
            nslot["agree"] += 1
        by_precompute[precompute] = by_precompute.get(precompute, 0) + 1
        confusion[(precompute, native)] = confusion.get((precompute, native), 0) + 1
    for slot in by_mode.values():
        slot["rate"] = (round(slot["agree"] / slot["comparable"], 4)
                        if slot["comparable"] else 0.0)
    return {
        "comparable_covered": comparable,
        "agree": agree,
        "agreement_rate": round(agree / comparable, 4) if comparable else 0.0,
        "by_mode": dict(sorted(by_mode.items())),
        "by_native": dict(sorted(by_native.items())),
        "by_precompute": dict(sorted(by_precompute.items())),
        "confusion": [
            {"precompute": pv, "native": nv, "n": n, "agree": pv == nv}
            for (pv, nv), n in sorted(
                confusion.items(), key=lambda kv: (-kv[1], kv[0])
            )
        ],
        "unclassified_native": unclassified_native,
        "unclassified_native_samples": _top_samples(unclassified_samples),
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
        "build": summarize_build_agreement(build_records),
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
        for text, n in (agr.get("unclassified_native_samples") or [])[:_SAMPLE_PRINT_HEAD]:
            show = text if len(text) <= _SAMPLE_PRINT_WIDTH else text[:_SAMPLE_PRINT_WIDTH]
            print(f'      unclassified sample: "{show}" x{n}')
        econ = agr.get("economy")
        if econ:
            print(f"    economy (native recall, off combat axis): "
                  f"{econ.get('native_recall', 0)} native-recall, "
                  f"{econ.get('precompute_also_recall', 0)} precompute also recall")
        if agr.get("by_precompute"):
            pv = ", ".join(f"{k} x{v}" for k, v in agr["by_precompute"].items())
            print(f"    precompute verdicts: {pv}")
        if agr.get("even_precompute_by_native"):
            ev = ", ".join(f"{k} x{v}"
                           for k, v in agr["even_precompute_by_native"].items())
            print(f"    even-precompute by native (gated even<->hold map): {ev}")
        mism = [c for c in (agr.get("confusion") or []) if not c["agree"]]
        for c in mism[:6]:
            print(f"    MISMATCH pre={c['precompute']} -> "
                  f"native={c['native']} x{c['n']}")
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
