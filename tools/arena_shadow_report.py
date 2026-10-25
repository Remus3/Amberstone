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

PRIMARY AXIS - deterministic.action vs live_haiku.action, scored on a shared
action CLASS (RM-868). Both labels are NORMALIZED (upper / strip / collapse
internal whitespace) and then mapped by ``action_class`` into one vocabulary:
SHOP / DEFENSIVE / NEUTRAL / AGGRESSIVE / NONCOMBAT. The deterministic side is
a closed 5-label set (core/arena_action_rule.py), Haiku writes free text
(28+ distinct labels in the live log), so an exact-string compare scored BUY
ITEMS vs CAMP PHASE - the same shop verdict - as a disagreement. A label with
no class (free text the map does not know) is UNCLASSIFIED, never a
disagreement. The exact-label rate stays as a secondary column, and
``fight_axis`` scores the rows where both sides gave a fight verdict.

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

  * a tick is dead-state ONLY on an unambiguous statement that the PLAYER is
    dead or spectating NOW (RM-868): the Haiku action is a spectate / "when
    you respawn" state or its head word is DEAD / ELIMINATED, OR one clause of
    the Haiku action / round_strategy says "you are dead / eliminated /
    spectating" or "you and X are dead" with no conditional or future word
    ("if", "will", "dead in 3s", "next round") and no other subject ("enemy",
    "they", an [E] tag), OR the deterministic round_strategy reads "hp 0%".
    A partner death, an enemy death, a bare "both dead" and a warning never
    count.

FOCUS-BOARD RE-LOGS (RM-854) - core.arena_coach_shadow writes a row a second
time, ONCE, marked "focus_board_relog": true, when its focus_board column was
not ready at the first write. That row repeats the same tick key and the same
deterministic-vs-Haiku pair; its only new data is the focus_board column,
which this report never scores. So a re-log is NOT a sample: it is skipped by
every coverage / agreement / gate count (``_coverage_block`` and
``summarize_agreement`` each skip it, so the MIN_SAMPLE gate never sees it)
and tallied only as ``coverage["focus_board_relogs"]``. Only a literal true
marker is skipped.

This is a READ-ONLY report (no engine, no network, no write). Fail-soft: a
missing / empty / malformed log yields an awaiting-accrual state and exit 0,
never an exception.

MIN_SAMPLE + FLIP_GATE - below MIN_SAMPLE live-fight comparable rounds the
flip-readiness verdict reads "awaiting_accrual"; at / above it, ``ready`` is
True only when the class agreement also clears FLIP_GATE (0.70, the bar the
ARAM and champ-select reports use) - state "ready", else "not_ready". Before
RM-868 a met sample alone read ready=True, so 3/438 (0.7%) printed
"sample_met". It is NOT a flip authorization - the operator decides; this
only flags the obvious not-ready states.

USAGE
    python tools/arena_shadow_report.py            # human summary, default path
    python tools/arena_shadow_report.py --json     # machine-readable JSON
    python tools/arena_shadow_report.py --path X --min-sample N
"""
from __future__ import annotations

import argparse
import json
import re
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

# Agreement floor before a flip is even discussable - the same 70% bar as
# tools/aram_shadow_report.py FLIP_GATE and tools/champ_select_shadow_report.py
# FLIP_GATE (RM-868). Compared against the unrounded agree / comparable.
FLIP_GATE = 0.70


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


# RM-854: the marker core.arena_coach_shadow puts on a focus-board re-log.
RELOG_KEY = "focus_board_relog"


def is_focus_board_relog(rec) -> bool:
    """True for a focus-board re-log row (a column update, never a sample)."""
    return isinstance(rec, dict) and rec.get(RELOG_KEY) is True


def _samples(records: list[dict]) -> list[dict]:
    """The rows that are agreement samples: every row but a re-log."""
    return [rec for rec in records if not is_focus_board_relog(rec)]


def _norm_action(text) -> str:
    """Uppercase + strip + collapse internal whitespace runs to one space, so
    "KITE BACK" and " kite  back " normalize to the same label. Non-str / empty
    -> "" (an unlabelled side)."""
    if not isinstance(text, str):
        return ""
    return " ".join(text.upper().split())


# -- shared action class map (RM-868) -------------------------------------------
# One vocabulary for BOTH sides. Census of the live
# data/arena_coach_shadow.jsonl (617 rows, 2026-10-25) is cited as "live xN".
SHOP = "SHOP"
DEFENSIVE = "DEFENSIVE"
NEUTRAL = "NEUTRAL"
AGGRESSIVE = "AGGRESSIVE"
NONCOMBAT = "NONCOMBAT"

# The deterministic side's closed set - every label decide_action can return
# (core/arena_action_rule.py module docstring rule order, :14-26).
DET_ACTION_CLASS: dict[str, str] = {
    "BUY ITEMS": SHOP,          # rule 1: camp_phase -> the shop / campfire
    "KITE BACK": DEFENSIVE,     # rule 2: hp < 25, never all-in
    "ALL IN": AGGRESSIVE,       # rule 3: hp > 70 + a low-HP opponent
    "PLAY AGGRO": AGGRESSIVE,   # rule 4: hp > 70
    "FIGHT SMART": NEUTRAL,     # rule 5: the 25..70 band, standard fight
}

# Free-text Haiku labels: whole-word keyword rules, FIRST MATCH WINS. The
# order mirrors decide_action, where the camp phase beats every HP band
# (core/arena_action_rule.py:68-76), so a phase word wins over a posture word
# ("SURVIVE CAMP PHASE" is SHOP). DEFENSIVE precedes AGGRESSIVE and NEUTRAL so
# "DISENGAGE" and "DO NOT FIGHT" never read as ENGAGE / FIGHT.
_CLASS_RULES: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    # CAMP PHASE live x367, BUY ITEMS x22, AUGMENT SELECT x6, WAIT CAMP PHASE
    # x5, AUGMENT SELECT + BUY ITEMS / WAIT FOR CAMP PHASE / RESPAWN BUY ITEMS /
    # RESPAWN CAMP PHASE / SURVIVE CAMP PHASE / AUGMENT PHASE x2, WAIT SHOP x1;
    # the Haiku prompt names CAMP PHASE / BUY ITEMS as Action labels and an
    # anvil as a camp event (coaches/arena_coach.py _SYSTEM_PROMPT "Action:"
    # and "Anvil phase" lines).
    (SHOP, re.compile(r"\b(?:CAMP|BUY|AUGMENT|SHOP|ANVIL)\b")),
    # KITE BACK live x18, KITE PERIMETER x2, KITE SURVIVE x1, SURVIVE TO NEXT
    # ROUND x3, SURVIVE ROUND x3, DISENGAGE IMMEDIATE x1; the prompt's low-HP
    # rule and det KITE BACK's approach are "kite, disengage, survive"
    # (core/arena_deterministic_coach.py _APPROACH). WAIT / DO NOT FIGHT x1 is
    # an explicit no-engage order (its live row: HP 7%, "Do NOT engage", det
    # KITE BACK), so DEFENSIVE, not a wait. HOLD POSITION x1 is DEFENSIVE too:
    # its live row says "survive until next camp phase, avoid skirmish engage"
    # - a hold, not a trade (it was NEUTRAL in the first cut).
    (DEFENSIVE, re.compile(
        r"\b(?:KITE|SURVIVE|DISENGAGE|HOLD)\b|\bDO NOT (?:FIGHT|ENGAGE)\b")),
    # SCAN THEN ENGAGE live x2; ALL IN / FOCUS CARRY are the prompt's Action
    # examples; PLAY AGGRO / ALL IN are det rules 3-4.
    (AGGRESSIVE, re.compile(
        r"\bALL IN\b|\b(?:AGGRO|AGGRESSIVE|ENGAGE)\b|\bFOCUS CARRY\b")),
    # FIGHT SMART is det rule 5 (the prompt's "standard fight" band).
    (NEUTRAL, re.compile(r"\bFIGHT\b")),
    # Pre-round waits with no fight verdict: WAIT FOR RESPAWN x7, WAIT RESPAWN
    # x7, RESPAWN WAIT x5, WAIT FOR MATCHUP / SPAWN WAIT x3, SCOUT OPPONENT /
    # WAIT OBJECTIVE / WAIT SPAWN / REVIVE PRIORITY / SKIP ROUND x2, WAIT FOR
    # OPPONENT / RESPAWN PENDING x1. The det side has no such label, so these
    # score as a disagreement (conservative - never routed out like a death).
    # REVIVE PRIORITY stays here: both live rows are a dead player waiting to
    # respawn ("You are DEAD (0% HP)", det HP 0%), so they route dead first and
    # the class only matters for a living-player use of the word.
    (NONCOMBAT, re.compile(r"\b(?:WAIT|SPAWN|RESPAWN|SCOUT|SKIP|REVIVE)\b")),
)

# DEFENSIVE < NEUTRAL < AGGRESSIVE: the three fight bands, in HP-band order,
# for the fight_axis "within one band" read.
_FIGHT_BAND = {DEFENSIVE: 0, NEUTRAL: 1, AGGRESSIVE: 2}


def action_class(label) -> Optional[str]:
    """The shared class of one action label, or None (unclassified).

    The deterministic side's five labels map exactly (DET_ACTION_CLASS); any
    other label goes through the ordered whole-word rules in _CLASS_RULES.
    A non-str / empty label, or free text no rule names (live: "ARENA ROUND
    ~23 ANALYSIS", "CRITICAL CONTEXT MISMATCH DETECTED"), is None."""
    norm = _norm_action(label)
    if not norm:
        return None
    if norm in DET_ACTION_CLASS:
        return DET_ACTION_CLASS[norm]
    for cls, pattern in _CLASS_RULES:
        if pattern.search(norm):
            return cls
    return None


def _block(rec: dict, side: str) -> dict:
    """Return the deterministic / live_haiku sub-block as a dict (fail-soft {})."""
    blk = rec.get(side)
    return blk if isinstance(blk, dict) else {}


# Haiku ACTION substrings (normalized lowercase) that already name the player's
# own state without ambiguity: a spectate state (live "SPECTATE ROUND" /
# "SPECTATE NEXT ROUND" x36 - the player watches only while dead) and a respawn
# the player waits for. RM-868 dropped "you are dead" (now the clause test
# below, which refuses "you are dead in 3s if you stay") and "cannot fight"
# (live round_strategy "Syndra is dead - you cannot fight 1v2 safely" is a
# LIVING player whose partner died; no live action used it).
_HAIKU_DEAD_MARKERS: tuple[str, ...] = (
    "spectate",
    "when you respawn",
)

# Deterministic dead / down marker. The deterministic round_strategy is a
# closed template, "Your HP {hp}%; {teams} teams left - {approach}"
# (core/arena_deterministic_coach.py _round_strategy over _APPROACH), so
# "hp 0%" there is the artifact's current HP of zero - the player is down
# (live example: "Your HP 0%; 3 teams left - kite, disengage, survive").
# RM-868 dropped "you are dead" and "respawn": that template cannot emit
# either, so they were dormant.
_DET_DEAD_MARKERS: tuple[str, ...] = (
    "hp 0%",
    "hp 0 %",
)

# RM-868: a Haiku text counts as "the player is dead NOW" only through one
# clause that (a) is a player-subject present-state statement and (b) carries
# no conditional / future word and no other subject. Clauses split on . ; ! ? |
# and a spaced dash, never on a comma (so "you are dead, if you engage" stays
# one conditional clause).
_CLAUSE_SPLIT_RE = re.compile(
    r"[.;!?|\n]|\s-\s|[\N{EN DASH}\N{EM DASH}]")
# Conditional / future phrasing: "you are dead next round if you engage" (live
# x2), "dead in 3s", "will be dead".
_NOT_NOW_RE = re.compile(
    r"\b(?:if|unless|will|would|could|might|when|once)\b"
    r"|\bgoing to\b|\babout to\b|\bnext (?:round|fight)\b|\bdead in\b"
    r"|\bin \d+\s*(?:s|sec|secs|seconds)\b")
# Another subject: "enemy duo both dead", "they are both dead", an [E] tag.
_OTHER_SUBJECT_RE = re.compile(
    r"\b(?:enemy|enemies|opponents?|they|them|their)\b|\[e\]")
# Player-subject present state, in any field: "you are dead at 0% hp" (live
# x3), "you are dead this round" (x2), "you're dead", "you are spectating",
# "you and syndra are dead" (x3).
_PLAYER_DEAD_RES: tuple["re.Pattern[str]", ...] = (
    re.compile(r"\byou(?: are|['\N{RIGHT SINGLE QUOTATION MARK}]re)(?: both)?"
               r"(?: currently| now| already)? (?:dead|eliminated|spectating)\b"),
    re.compile(r"\byou and [^.;,|]{1,30}? are (?:both )?(?:dead|eliminated)\b"),
)
# ACTION field only: a label whose HEAD word is DEAD / ELIMINATED names the
# player's own state (the action slot is the player's instruction; live
# ELIMINATED x11, DEAD - WAIT RESPAWN x4, DEAD - SKIP ROUND x2, DEAD WAIT
# RESPAWN x2, ELIMINATED - CAMP PHASE x1). A bare "both dead" is NOT counted
# anywhere: its subject is unstated (live "Both dead [2%]" is the player, but
# "enemy duo both dead" is not).
_ACTION_HEAD_DEAD_RE = re.compile(r"^(?:dead|eliminated)\b")


def _says_player_dead(text: str, *, action: bool = False) -> bool:
    """True when some clause of ``text`` (already lowercased) says the PLAYER
    is dead or spectating NOW - see _NOT_NOW_RE / _OTHER_SUBJECT_RE for what
    never counts. ``action`` also accepts a DEAD / ELIMINATED head word."""
    for clause in _CLAUSE_SPLIT_RE.split(text):
        clause = clause.strip()
        if not clause:
            continue
        if _NOT_NOW_RE.search(clause) or _OTHER_SUBJECT_RE.search(clause):
            continue
        if action and _ACTION_HEAD_DEAD_RE.search(clause):
            return True
        if any(p.search(clause) for p in _PLAYER_DEAD_RES):
            return True
    return False


def _norm_lower(text) -> str:
    """Lowercase + collapse whitespace for substring marker checks."""
    if not isinstance(text, str):
        return ""
    return " ".join(text.lower().split())


def is_dead_state(rec: dict) -> bool:
    """True when this tick is a dead / non-combat tick (a category mismatch, not
    a real fight-verdict disagreement) and must be routed OUT of the honest
    combat agreement sample.

    Three independent signals, any one sufficient:
      * the Haiku action is a spectate / respawn-wait state or says the
        player is dead now (a DEAD / ELIMINATED head word, RM-868), OR
      * the Haiku round_strategy says the PLAYER is dead or spectating now
        (RM-868; never conditional / future phrasing, never another subject),
        OR
      * the deterministic round_strategy reads HP 0%.
    See module docstring for the rationale."""
    haiku = _block(rec, "live_haiku")
    det = _block(rec, "deterministic")
    haiku_action = _norm_lower(haiku.get("action"))
    if any(m in haiku_action for m in _HAIKU_DEAD_MARKERS):
        return True
    if _says_player_dead(haiku_action, action=True):
        return True
    if _says_player_dead(_norm_lower(haiku.get("round_strategy"))):
        return True
    det_strategy = _norm_lower(det.get("round_strategy"))
    if any(m in det_strategy for m in _DET_DEAD_MARKERS):
        return True
    return False


def record_agreement(rec: dict) -> Optional[dict]:
    """Classify one LIVE-FIGHT shadow record on the primary action axis.

    Returns {"det", "haiku", "det_class", "haiku_class", "agree", "exact"}
    when BOTH sides carry a label with a class (action_class): ``agree`` is
    class agreement (RM-868), ``exact`` the normalized-label match kept as a
    secondary column. A missing / empty label or a label with no class -> None
    (unclassified, excluded from the sample). Dead-state ticks are NOT
    filtered here (the caller routes them first); this scores whatever
    fight-round record it is handed."""
    det = _norm_action(_block(rec, "deterministic").get("action"))
    haiku = _norm_action(_block(rec, "live_haiku").get("action"))
    if not det or not haiku:
        return None
    det_class = action_class(det)
    haiku_class = action_class(haiku)
    if det_class is None or haiku_class is None:
        return None
    return {"det": det, "haiku": haiku, "det_class": det_class,
            "haiku_class": haiku_class, "agree": det_class == haiku_class,
            "exact": det == haiku}


def _coverage_block(records: list[dict]) -> dict:
    """Total rows, distinct champs, distinct rounds, live-fight vs dead-state
    counts. dead_state + live_fight partition every SAMPLE row exactly once;
    focus-board re-logs (RM-854) are outside the sample and only counted."""
    samples = _samples(records)
    relogs = len(records) - len(samples)
    records = samples
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
        "focus_board_relogs": relogs,
    }


def summarize_agreement(records: list[dict]) -> dict:
    """Deterministic-vs-Haiku action agreement over the LIVE-FIGHT sample.

    Dead-state ticks are counted (dead_state) but NEVER scored. A live-fight
    record where either side has no classifiable action label is
    comparable=excluded but still counted as unclassified. The honest combat
    agreement_rate is CLASS agree / comparable over live-fight rounds only
    (RM-868); exact_agree / exact_agreement_rate keep the old exact-label
    read over the same comparable rows. ``confusion`` is per label pair (its
    ``agree`` is the class verdict), ``class_confusion`` per class pair, and
    ``fight_axis`` scores only the rows where BOTH classes are fight bands
    (DEFENSIVE / NEUTRAL / AGGRESSIVE), with a within-one-band count.
    Focus-board re-logs (RM-854) repeat a sample already counted and are
    skipped."""
    records = _samples(records)
    dead_state = 0
    comparable = 0
    agree = 0
    exact_agree = 0
    unclassified = 0
    fight = {"comparable": 0, "agree": 0, "within_one_band": 0}
    by_champ: dict[str, dict] = {}
    confusion: dict[tuple[str, str], list] = {}
    class_confusion: dict[tuple[str, str], int] = {}
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
        if pair["exact"]:
            exact_agree += 1
        champ = str(rec.get("champ") or "?")
        slot = by_champ.setdefault(champ, {"comparable": 0, "agree": 0})
        slot["comparable"] += 1
        if agreed:
            slot["agree"] += 1
        key = (pair["det"], pair["haiku"])
        confusion.setdefault(key, [0, agreed])[0] += 1
        ckey = (pair["det_class"], pair["haiku_class"])
        class_confusion[ckey] = class_confusion.get(ckey, 0) + 1
        dband = _FIGHT_BAND.get(pair["det_class"])
        hband = _FIGHT_BAND.get(pair["haiku_class"])
        if dband is not None and hband is not None:
            fight["comparable"] += 1
            if dband == hband:
                fight["agree"] += 1
            if abs(dband - hband) <= 1:
                fight["within_one_band"] += 1
    for slot in by_champ.values():
        slot["rate"] = (round(slot["agree"] / slot["comparable"], 4)
                        if slot["comparable"] else 0.0)
    fight["agreement_rate"] = (round(fight["agree"] / fight["comparable"], 4)
                               if fight["comparable"] else 0.0)
    return {
        "comparable": comparable,
        "agree": agree,
        "agreement_rate": round(agree / comparable, 4) if comparable else 0.0,
        "exact_agree": exact_agree,
        "exact_agreement_rate": (round(exact_agree / comparable, 4)
                                 if comparable else 0.0),
        "dead_state": dead_state,
        "unclassified": unclassified,
        "by_champion": dict(sorted(by_champ.items())),
        "confusion": [
            {"det": dv, "haiku": hv, "n": n, "agree": ok}
            for (dv, hv), (n, ok) in sorted(
                confusion.items(), key=lambda kv: (-kv[1][0], kv[0])
            )
        ],
        "class_confusion": [
            {"det_class": dc, "haiku_class": hc, "n": n, "agree": dc == hc}
            for (dc, hc), n in sorted(
                class_confusion.items(), key=lambda kv: (-kv[1], kv[0])
            )
        ],
        "fight_axis": fight,
    }


def _flip_readiness(coverage: dict, agreement: dict, min_sample: int) -> dict:
    """A coarse human read of flip-readiness. NOT a flip authorization - the
    operator decides; this only flags the obvious not-ready states.

    Below min_sample LIVE-FIGHT comparable rounds -> awaiting_accrual. At /
    above it, ready=True ONLY when the class agreement also clears FLIP_GATE
    (state "ready"); a met sample below the gate is "not_ready" (RM-868; the
    state names are tools/champ_select_shadow_report.py _state_and_hint's)."""
    comparable = agreement.get("comparable", 0)
    gate_pct = round(100 * FLIP_GATE)
    if coverage.get("total", 0) == 0:
        return {
            "ready": False,
            "state": "awaiting_accrual",
            "reason": "no shadow data yet - play real Arena games to accrue",
            "comparable": 0,
            "min_sample": min_sample,
            "flip_gate": FLIP_GATE,
        }
    if comparable < min_sample:
        return {
            "ready": False,
            "state": "awaiting_accrual",
            "reason": (f"awaiting accrual ({comparable}/{min_sample} live-fight "
                       "comparable rounds) - keep playing before a flip read"),
            "comparable": comparable,
            "min_sample": min_sample,
            "flip_gate": FLIP_GATE,
        }
    agree = agreement.get("agree", 0)
    pct = round(100.0 * agree / comparable)
    gate_met = agree / comparable >= FLIP_GATE
    if gate_met:
        reason = (f"class agreement {pct}% over {comparable} live-fight "
                  f"comparable rounds (>={gate_pct}% gate MET) - NOT a flip "
                  "authorization (operator gate; review the distribution)")
    else:
        reason = (f"class agreement {pct}% over {comparable} live-fight "
                  f"comparable rounds - below the {gate_pct}% gate; do not flip")
    return {
        "ready": gate_met,
        "state": "ready" if gate_met else "not_ready",
        "reason": reason,
        "agreement_pct": pct,
        "comparable": comparable,
        "min_sample": min_sample,
        "flip_gate": FLIP_GATE,
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
        "flip_gate": FLIP_GATE,
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
    if cov.get("focus_board_relogs"):
        print(f"    {cov['focus_board_relogs']} focus-board re-log row(s) "
              "skipped (a column update, not a sample)")
    print(f"    class agreement: {agr.get('agree', 0)}/"
          f"{agr.get('comparable', 0)} ({agr.get('agreement_rate', 0.0)}) "
          f"live-fight comparable, {agr.get('unclassified', 0)} unclassified "
          f"(gate {round(100 * report.get('flip_gate', FLIP_GATE))}%)")
    print(f"    exact-label agreement: {agr.get('exact_agree', 0)}/"
          f"{agr.get('comparable', 0)} ({agr.get('exact_agreement_rate', 0.0)})")
    fa = agr.get("fight_axis") or {}
    if fa.get("comparable"):
        print(f"    fight axis (both sides a fight band): {fa.get('agree', 0)}/"
              f"{fa['comparable']} same band, {fa.get('within_one_band', 0)} "
              "within one band")
    if agr.get("by_champion"):
        for champ, slot in agr["by_champion"].items():
            print(f"    champ {champ}: {slot.get('agree', 0)}/"
                  f"{slot.get('comparable', 0)} ({slot.get('rate', 0.0)})")
    cmism = [c for c in (agr.get("class_confusion") or []) if not c["agree"]]
    for c in cmism[:6]:
        print(f"    CLASS MISMATCH det={c['det_class']} -> "
              f"haiku={c['haiku_class']} x{c['n']}")
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
