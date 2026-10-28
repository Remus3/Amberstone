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
      * augment_advice    <- core.arena_augment_playline.play_line(...) over
                             the augments the player OWNS ("" when none are
                             known; the v1 always-empty degrade is closed)
      * anvil_advice      <- the head of the remaining-build list
      * target_priority   <- core.arena_target_rule.target_priority(...)

PURE + PARTIAL-READ + FAIL-SOFT (this is the design, not a bug)
    ``build_block`` takes PRIMITIVES (so it is trivially unit-testable and
    the impure file/engine reads stay in the dashboard wiring layer) and
    works from WHATEVER inputs are actually present on a given tick:
      * hp_pct not a reading AND camp_phase not True -> action = "" (no
        action signal; a True camp_phase alone IS a real signal - BUY
        ITEMS needs no HP).
      * low_opp_count not a reading -> decide_action gets 0 (the ALL IN
        promotion stays dormant; no live opponent-HP source exists yet).
      * alive_teams not a reading -> the teams clause is omitted from
        round_strategy, the rest of the line still renders.
      * cc_threat_line absent / empty -> fight_rule = risk = "".
      * alive_opponents / build_remaining absent -> those fields "".
    A numeric READING is a finite int / float (never a bool, never a str) in
    its band: hp_pct 0..150 (shown capped at 100%), alive_teams a whole 1..8,
    low_opp_count a whole 0..14. camp_phase is a signal only when it is the
    bool True (the producer's vision schema admits a bool and nothing else).
    The anvil head is a str of at most 64 characters after whitespace is
    collapsed. On ANY internal failure each field independently degrades to
    "" ([] for choices). ``build_block`` NEVER raises.
"""
from __future__ import annotations

from core import (
    aram_fight_risk,
    arena_action_rule,
    arena_augment_playline,
    arena_target_rule,
)
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


# Reading bands. hp_pct tops out at 150 because the producer
# (dashboard/_deterministic_coaching.py _hp_fraction) admits hp up to 1.5x max:
# a transient over-max reading is full HP, not junk, and is SHOWN as 100%.
# Arena fields eight teams of two (coaches/arena_coach.py defaults alive_teams
# to 8), so at most 14 opponents can be low; an item name is far shorter than
# 64 characters.
_HP_PCT_MAX = 150.0
_HP_SHOWN_MAX = 100.0
_MAX_TEAMS = 8
_MAX_LOW_OPPONENTS = 14
_MAX_ITEM_NAME = 64


def _real_number(value: object, lo: float, hi: float) -> float | None:
    """A finite int / float in ``lo..hi`` as a float, else None. Never raises.

    Strict on purpose (core/aram_deterministic_coach.py _real_number is the
    sibling gate): a bool is a flag, not a measurement (True hp read "Your HP
    1%" and KITE BACK), a str is not a reading (" 6e1 " read 60%), and an int
    past the float range is no reading rather than an OverflowError. hp is
    read through here BEFORE the per-field guards, so the whole gate sits in
    one try: a number subclass whose __float__ raises, or an object whose
    __class__ lookup raises inside isinstance, is no reading too, never a
    raise out of build_block.
    """
    try:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        out = float(value)
        # The bounds are finite, so this also rejects NaN (every comparison
        # is False) and +/-inf.
        if not lo <= out <= hi:
            return None
    except Exception:  # noqa: BLE001 - OverflowError or any raising dunder
        return None
    return out


def _whole_number(value: object, lo: int, hi: int) -> int | None:
    """An int, or an integral float, in ``lo..hi``, else None. Never raises.

    A fractional count is not a count: 2.7 alive teams used to read 2.
    """
    num = _real_number(value, lo, hi)
    if num is None or num != int(num):
        return None
    return int(num)


def _in_camp(camp_phase: object) -> bool:
    """True only for the bool True.

    The producer writes a bool (the arena vision schema in
    coaches/arena_coach.py rejects anything else), so a NaN, a "false" str
    or a [0] list is junk, not a camp phase: each used to be truthy and
    routed BUY ITEMS over any HP band.
    """
    return camp_phase is True


def _safe_action(hp: float | None, in_camp: bool, low_opp_count: object) -> str:
    """decide_action over the validated inputs, but "" when no signal is present.

    decide_action itself neutral-defaults to FIGHT SMART on an unusable
    hp_pct; we gate on (a reading of hp OR a True camp phase) first so a
    no-data tick logs an empty action instead of a misleading FIGHT SMART.
    Camp phase counts as a signal because BUY ITEMS needs no HP at all. The
    low-opponent count is validated HERE: anything but a whole 0..14 is 0, so
    a 10**400 count no longer promotes ALL IN and an integral 2.0 does.
    """
    if hp is None and not in_camp:
        return ""
    low = _whole_number(low_opp_count, 0, _MAX_LOW_OPPONENTS) or 0
    return arena_action_rule.decide_action(hp, in_camp, low)


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


def _clamp_words(text: str, max_words: int) -> str:
    """Trim to at most ``max_words`` whitespace-delimited words."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


def _round_strategy(action: str, hp: float | None, alive_teams: object) -> str:
    """Bounded template: "Your HP {hp}%; {teams} teams left - {approach}".

    Each leading clause is independently optional so a partial tick still
    renders: the HP clause needs a reading of hp (a BUY ITEMS verdict can
    come from camp_phase alone) and shows at most 100%, the teams clause
    needs a whole 1..8 alive_teams (a str, a fraction, -5, 0 or 1000000
    teams used to be printed). No action -> "" (nothing was computable).
    Kept <=20 words - the prompt's own budget for this field.
    """
    approach = _APPROACH.get(action, "")
    if not approach:
        return ""
    parts = []
    if hp is not None:
        parts.append(f"Your HP {min(hp, _HP_SHOWN_MAX):.0f}%")
    teams = _whole_number(alive_teams, 1, _MAX_TEAMS)
    if teams is not None:
        parts.append(f"{teams} teams left")
    head = "; ".join(parts)
    out = f"{head} - {approach}" if head else approach
    return _clamp_words(out, 20)


def _anvil_line(build_remaining: object) -> str:
    """Name the next build target from the remaining-build head, or "".

    Only the head is coached - the prompt's own anvil rule is "complete
    carry item first", and the wiring layer already orders the remaining
    list that way. A list or tuple is an order; anything else, an empty
    order or a blank / non-str head degrades to "". The head's whitespace
    is collapsed to single spaces (a newline used to be coached verbatim)
    and a head longer than 64 characters is not an item name.
    """
    if not isinstance(build_remaining, (list, tuple)) or not build_remaining:
        return ""
    head = build_remaining[0]
    if not isinstance(head, str):
        return ""
    name = " ".join(head.split())
    if not name or len(name) > _MAX_ITEM_NAME:
        return ""
    return f"Build toward {name} next."


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


def _safe_augment_advice(owned_augments: object) -> str:
    try:
        out = arena_augment_playline.play_line(owned_augments)
        return out if isinstance(out, str) else ""
    except Exception:  # noqa: BLE001
        return ""


def _safe_target(alive_opponents: object, frontline_names: object) -> str:
    try:
        out = arena_target_rule.target_priority(alive_opponents, frontline_names)
        return out if isinstance(out, str) else ""
    except Exception:  # noqa: BLE001
        return ""


def _field(helper, default, *args):
    """``helper(*args)`` when it returns the default's type, else ``default``.

    The per-field fail-soft guard: a raise or a wrong-typed result degrades
    ONLY this field. Never raises.
    """
    try:
        out = helper(*args)
    except Exception:  # noqa: BLE001 - hard per-field fail-soft contract
        return default
    return out if isinstance(out, type(default)) else default


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
    owned_augments: object = None,
) -> dict:
    """Assemble the deterministic Arena coach block (the seven live fields).

    All arguments are optional primitives; the assembler works from
    whatever is present and degrades each field independently to "" on
    absence or failure. NEVER raises.

    Args:
        hp_pct: self HP percent, a number in 0..150 (over-max HP is shown
            as 100%). Not a reading AND no camp phase -> action "".
        camp_phase: True = between-round camp/shop phase; wins over any
            HP band and is a valid action signal on its own. Anything but
            the bool True is no camp phase.
        low_opp_count: count of low-HP alive opponents, a whole 0..14. NO
            live source exists today - callers pass None and the ALL IN
            promotion stays dormant (same shape as ARAM's low_enemy_count).
        alive_teams: teams still alive this round, a whole 1..8; only
            decorates the round_strategy line. Not a reading -> clause
            omitted.
        cc_threat_line: the ``enemy_cc_threat_line`` string OR a ranked
            iterable of CC entries (see core.aram_fight_risk). Drives
            fight_rule + risk. Absent / malformed -> both "".
        alive_opponents: ordered opponent display-name list for the
            kill-order line. Absent / malformed -> target_priority "".
        frontline_names: names among alive_opponents already classified
            frontline by the wiring layer (set/list/None all accepted).
        build_remaining: ordered not-yet-built item-name list; the head
            anchors anvil_advice. Absent / empty / non-list -> "".
        owned_augments: the augments the player currently HOLDS, as apiNames
            (the shape ``state["augments"]`` carries) and/or display names.
            Drives augment_advice via core.arena_augment_playline. Absent /
            empty / unresolvable -> "" (never a guess).

    Returns:
        dict with exactly the keys action, round_strategy, fight_rule,
        augment_advice, anvil_advice, target_priority, risk, choices. All
        seven string columns plus ``choices`` (the list-typed A/B array
        derived from action + fight_rule; [] on no signal).
    """
    # Read hp and the camp phase ONCE, so every field sees the same values.
    hp = _real_number(hp_pct, 0.0, _HP_PCT_MAX)
    in_camp = _in_camp(camp_phase)
    # Compute action + fight_rule ONCE so choices reuses them without
    # re-deriving (same shape as the ARAM assembler). Each field runs under
    # its own guard: one raising helper used to blank all eight.
    action = _field(_safe_action, "", hp, in_camp, low_opp_count)
    fight_rule = _field(_safe_fight_rule, "", cc_threat_line)
    return {
        "action": action,
        "round_strategy": _field(_round_strategy, "", action, hp, alive_teams),
        "fight_rule": fight_rule,
        "augment_advice": _field(_safe_augment_advice, "", owned_augments),
        "anvil_advice": _field(_anvil_line, "", build_remaining),
        "target_priority": _field(_safe_target, "", alive_opponents, frontline_names),
        "risk": _field(_safe_risk, "", cc_threat_line),
        # choices: the deterministic A/B array derived from action +
        # fight_rule (the eighth, list-typed column). Empty on no signal.
        "choices": _field(_safe_choices, [], action, fight_rule),
    }


__all__ = ["build_block"]
