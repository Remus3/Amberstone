# arch: deterministic Arena coach block assembler (Stage 2) | section=core | frozen=no
"""Deterministic Arena coach block assembler (Stage 2, Tier-1, no live wiring).

PURPOSE
    Assemble the WHOLE deterministic per-tick Arena coach block - the same
    seven fields the live Arena Haiku call writes to
    ``data/arena_coaching_data.json`` (``action`` / ``round_strategy`` /
    ``fight_rule`` / ``augment_advice`` / ``anvil_advice`` /
    ``target_priority`` / ``risk``; artifact keys read from
    ``coaches/arena_coach.py:781-787``) - from the Stage 1 pure rules plus
    the shared CC-threat parsers. This is the assembler the operator can
    later eyeball, shadow-logged side-by-side with the live Haiku block;
    the live coach FLIP is a separate, operator-gated stage. This module
    changes NO served output and makes NO network call.

    The seven fields come from:
      * action            <- core.arena_action_rule.decide_action(...)
      * round_strategy    <- a bounded template over the action's approach
                             plus the HP / alive-teams clauses
      * fight_rule / risk <- core.aram_fight_risk (the CC-threat-line
                             parsers are mode-generic; Arena reuses them)
      * augment_advice    <- "" ALWAYS in v1 (documented degrade below)
      * anvil_advice      <- the head of the remaining-build list
      * target_priority   <- core.arena_target_rule.target_priority(...)

PURE + PARTIAL-READ + FAIL-SOFT (this is the design, not a bug)
    ``build_block`` takes PRIMITIVES (so it is trivially unit-testable and
    the impure file/engine reads stay in the dashboard wiring layer) and
    works from WHATEVER inputs are actually present on a given tick:
      * hp_pct absent / non-coercible AND camp_phase not truthy ->
        action = "" (no action signal; a truthy camp_phase alone IS a
        real signal - BUY ITEMS needs no HP).
      * low_opp_count absent -> decide_action just gets None (the ALL IN
        promotion stays dormant; no live opponent-HP source exists yet).
      * alive_teams absent / non-coercible -> the teams clause is omitted
        from round_strategy, the rest of the line still renders.
      * cc_threat_line absent / empty -> fight_rule = risk = "".
      * alive_opponents / build_remaining absent -> those fields "".
    On ANY internal failure each field independently degrades to "".
    ``build_block`` NEVER raises.
"""
from __future__ import annotations

import math

from core import aram_fight_risk, arena_action_rule, arena_target_rule
from core.coach_choices import CoachChoice, synthesize_simple_choices, to_jsonable

# Action label -> the approach clause the round_strategy template ends
# with. 1:1 with the decide_action vocabulary; ALL IN shares the
# standard-fight approach because the prompt's own high-HP-opponent line
# is "trade efficiently and kite" (coaches/arena_coach.py:138).
_APPROACH = {
    "BUY ITEMS": "spend gold, heal at campfire",
    "KITE BACK": "kite, disengage, survive",
    "PLAY AGGRO": "make plays, take risks",
    "FIGHT SMART": "trade efficiently and kite",
    "ALL IN": "trade efficiently and kite",
}

# Canonical Arena action label -> its (A label, B label) A/B pair. These are
# the EXACT five labels core.arena_action_rule.decide_action returns; the A/B
# is Arena-appropriate (a shop/anvil phase between rounds, no ARAM no-recall
# constraint). Mirrors core.aram_deterministic_coach._ARAM_CHOICE_LABELS and
# marks the deterministic Arena rule with source_tag "arena_rule" so the chip
# UI can tell it apart from the synth / native / haiku paths.
_ARENA_CHOICE_LABELS = {
    "BUY ITEMS": ("Buy items now", "Bank for the anvil"),
    "KITE BACK": ("Kite back", "Disengage fully"),
    "ALL IN": ("All-in", "Trade and kite"),
    "PLAY AGGRO": ("Play aggressive", "Play it safe"),
    "FIGHT SMART": ("Trade efficiently", "Disengage"),
}


def _has_usable_number(value: object) -> bool:
    """True only when ``value`` coerces to a finite float (not NaN/inf).

    Used to decide whether an HP-based ACTION signal exists at all. A
    None or a non-coercible / NaN hp_pct means "no action computable"
    unless the camp phase supplies its own signal.
    """
    if value is None:
        return False
    try:
        out = float(value)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 - a raising __float__ is still 'no signal'
        return False
    return not (math.isnan(out) or math.isinf(out))


def _truthy(value: object) -> bool:
    """bool(value), but a raising __bool__ counts as falsy (fail-soft)."""
    try:
        return bool(value)
    except Exception:  # noqa: BLE001 - hard fail-soft contract
        return False


def _safe_action(hp_pct: object, camp_phase: object, low_opp_count: object) -> str:
    """decide_action over the inputs, but "" when no signal is present.

    decide_action itself never raises and neutral-defaults to FIGHT SMART
    on an unusable hp_pct; we gate on (usable hp OR truthy camp phase)
    first so a no-data tick logs an empty action instead of a misleading
    FIGHT SMART. Camp phase counts as a signal because BUY ITEMS needs
    no HP at all.
    """
    if not _has_usable_number(hp_pct) and not _truthy(camp_phase):
        return ""
    try:
        return arena_action_rule.decide_action(hp_pct, camp_phase, low_opp_count)
    except Exception:  # noqa: BLE001 - hard fail-soft contract
        return ""


def _safe_fight_rule(threats: object) -> str:
    try:
        out = aram_fight_risk.fight_rule(threats)
        return out if isinstance(out, str) else ""
    except Exception:  # noqa: BLE001
        return ""


def _safe_risk(threats: object) -> str:
    try:
        out = aram_fight_risk.risk(threats)
        return out if isinstance(out, str) else ""
    except Exception:  # noqa: BLE001
        return ""


def _coerce_teams(value: object):
    """Best-effort finite-int coercion for alive_teams. None on failure."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 - a raising __float__ omits the clause
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return int(out)


def _clamp_words(text: str, max_words: int) -> str:
    """Trim to at most ``max_words`` whitespace-delimited words."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


def _round_strategy(action: str, hp_pct: object, alive_teams: object) -> str:
    """Bounded template: "Your HP {hp}%; {teams} teams left - {approach}".

    Each leading clause is independently optional so a partial tick still
    renders: the HP clause needs a usable hp_pct (a BUY ITEMS verdict can
    come from camp_phase alone), the teams clause needs a coercible
    alive_teams. No action -> "" (nothing was computable). Kept <=20
    words - the prompt's own budget for this field.
    """
    approach = _APPROACH.get(action, "")
    if not approach:
        return ""
    parts = []
    if _has_usable_number(hp_pct):
        parts.append(f"Your HP {float(hp_pct):.0f}%")  # type: ignore[arg-type]
    teams = _coerce_teams(alive_teams)
    if teams is not None:
        parts.append(f"{teams} teams left")
    head = "; ".join(parts)
    out = f"{head} - {approach}" if head else approach
    return _clamp_words(out, 20)


def _anvil_line(build_remaining: object) -> str:
    """Name the next build target from the remaining-build head, or "".

    Only the head is coached - the prompt's own anvil rule is "complete
    carry item first", and the wiring layer already orders the remaining
    list that way. A non-list / empty / blank-head input degrades to "".
    """
    if not isinstance(build_remaining, list) or not build_remaining:
        return ""
    head = build_remaining[0]
    if not isinstance(head, str) or not head.strip():
        return ""
    return f"Build toward {head.strip()} next."


def _safe_choices(action: str, fight_rule: str) -> list[dict]:
    """Derive the deterministic A/B choices from the block's own action + fight_rule.

    Mirrors core.aram_deterministic_coach._safe_choices: maps each of the five
    canonical Arena action labels (BUY ITEMS / KITE BACK / ALL IN / PLAY AGGRO /
    FIGHT SMART) through ``_ARENA_CHOICE_LABELS`` to an Arena-appropriate 2-entry
    A/B, each tagged source_tag "arena_rule" so the served chip UI can tell the
    deterministic Arena rule apart from the synth / native / haiku paths. The B
    outcome carries the passed fight_rule when present, else a safe default. An
    EMPTY or UNKNOWN (non-canonical) action falls back to
    synthesize_simple_choices (which returns [] for empty / unknown), so nothing
    regresses off the canonical labels. Never raises.
    """
    try:
        key = action.strip().upper() if isinstance(action, str) else ""
        pair = _ARENA_CHOICE_LABELS.get(key)
        if pair is None:
            return to_jsonable(
                synthesize_simple_choices({"action": action, "fight_rule": fight_rule})
            )
        a_lbl, b_lbl = pair
        b_outcome = (
            fight_rule.strip()
            if isinstance(fight_rule, str) and fight_rule.strip()
            else "play safe; reassess next round"
        )
        choice_a = CoachChoice(
            key="A",
            label=a_lbl,
            expected_outcome="follow the coach call",
            confidence="mid",
            source_tag="arena_rule",
        )
        choice_b = CoachChoice(
            key="B",
            label=b_lbl,
            expected_outcome=b_outcome,
            confidence="mid",
            source_tag="arena_rule",
        )
        return to_jsonable([choice_a, choice_b])
    except Exception:  # noqa: BLE001 - fail-soft contract: never raises
        return []


def _safe_target(alive_opponents: object, frontline_names: object) -> str:
    try:
        out = arena_target_rule.target_priority(alive_opponents, frontline_names)
        return out if isinstance(out, str) else ""
    except Exception:  # noqa: BLE001
        return ""


def build_block(
    hp_pct: object = None,
    camp_phase: object = None,
    low_opp_count: object = None,
    *,
    alive_teams: object = None,
    cc_threat_line: object = None,
    alive_opponents: object = None,
    frontline_names: object = None,
    build_remaining: object = None,
) -> dict:
    """Assemble the deterministic Arena coach block (the seven live fields).

    All arguments are optional primitives; the assembler works from
    whatever is present and degrades each field independently to "" on
    absence or failure. NEVER raises.

    Args:
        hp_pct: self HP percent 0..100. Unusable AND no camp phase ->
            action "".
        camp_phase: truthy = between-round camp/shop phase; wins over any
            HP band and is a valid action signal on its own.
        low_opp_count: count of low-HP alive opponents. NO live source
            exists today - callers pass None and the ALL IN promotion
            stays dormant (same shape as ARAM's low_enemy_count).
        alive_teams: teams still alive this round; only decorates the
            round_strategy line. Non-coercible -> clause omitted.
        cc_threat_line: the ``enemy_cc_threat_line`` string OR a ranked
            iterable of CC entries (see core.aram_fight_risk). Drives
            fight_rule + risk. Absent / malformed -> both "".
        alive_opponents: ordered opponent display-name list for the
            kill-order line. Absent / malformed -> target_priority "".
        frontline_names: names among alive_opponents already classified
            frontline by the wiring layer (set/list/None all accepted).
        build_remaining: ordered not-yet-built item-name list; the head
            anchors anvil_advice. Absent / empty / non-list -> "".

    Returns:
        dict with exactly the keys action, round_strategy, fight_rule,
        augment_advice, anvil_advice, target_priority, risk, choices. All
        seven string columns plus ``choices`` (the list-typed A/B array
        derived from action + fight_rule; [] on no signal).
    """
    try:
        # Compute action + fight_rule ONCE so choices reuses them without
        # re-deriving (same shape as the ARAM assembler).
        action = _safe_action(hp_pct, camp_phase, low_opp_count)
        fight_rule = _safe_fight_rule(cc_threat_line)
        return {
            "action": action,
            "round_strategy": _round_strategy(action, hp_pct, alive_teams),
            "fight_rule": fight_rule,
            # augment_advice is a DOCUMENTED v1 degrade: there is no honest
            # per-tick deterministic source for augment PLAY advice (the
            # discrete augment-SELECT event is covered elsewhere), so the
            # field stays "" rather than guessing.
            "augment_advice": "",
            "anvil_advice": _anvil_line(build_remaining),
            "target_priority": _safe_target(alive_opponents, frontline_names),
            "risk": _safe_risk(cc_threat_line),
            # choices: the deterministic A/B array derived from action +
            # fight_rule (the eighth, list-typed column). Empty on no signal.
            "choices": _safe_choices(action, fight_rule),
        }
    except Exception:  # noqa: BLE001 - total fail-soft: empty block
        return {
            "action": "",
            "round_strategy": "",
            "fight_rule": "",
            "augment_advice": "",
            "anvil_advice": "",
            "target_priority": "",
            "risk": "",
            "choices": [],
        }


__all__ = ["build_block"]
