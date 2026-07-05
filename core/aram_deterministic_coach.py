# arch: deterministic ARAM coach block assembler (Stage 2) | section=core | frozen=no
"""Deterministic ARAM coach block assembler (Stage 2, Tier-1, no live wiring).

PURPOSE
    Assemble the WHOLE deterministic per-tick ARAM coach block - the same
    fields the live ARAM Haiku call writes to ``data/aram_coaching_data.json``
    (``action`` / ``fight_rule`` / ``risk`` / ``reset_item`` / ``item_build`` /
    ``item_build_reasons`` / ``item_extra`` / ``objective`` plus ``choices``,
    the A/B array) - from the Stage 1 pure rules plus the existing ARAM build /
    hint surfaces. ``choices`` is derived from the block's own action +
    fight_rule via the SAME core.coach_choices synthesizer the served chip UI
    uses. This is the assembler the operator can later
    eyeball, shadow-logged side-by-side with the live Haiku block; the live
    coach FLIP is a separate, operator-gated stage. This module changes NO
    served output and makes NO network call.

    The fields come from:
      * action              <- core.aram_action_rule.decide_action(...)
      * fight_rule / risk   <- core.aram_fight_risk (over the enemy-CC threat
                               line / ranked entries)
      * item_build /
        item_build_reasons  <- passed-in build-table strings + the anti-tank /
                               heal-threat reason strings folded into the map
      * reset_item          <- the ARAM-no-recall fact anchored to the next
                               build item
      * item_extra          <- the ARAM "7th-item else omit" filler, resolved
                               from the owned-item count (declines to fabricate
                               a Pot/Shard consumable pick)
      * objective           <- a deterministic tower-HP state machine over
                               my_tower_hp / enemy_tower_hp

PURE + PARTIAL-READ + FAIL-SOFT (this is the design, not a bug)
    ``build_block`` takes PRIMITIVES (so it is trivially unit-testable and the
    impure file/engine reads stay in the dashboard wiring layer) and works from
    WHATEVER inputs are actually present on a given tick:
      * hp_pct absent / non-coercible -> action = "" (no action signal).
        (Note: the underlying decide_action neutral-defaults to HOLD on an
        unusable hp_pct; the assembler instead emits "" for a TOTALLY-ABSENT
        hp_pct so the shadow row honestly shows nothing was computable. A
        present-but-garbage hp_pct also yields "".)
      * wave_pct absent -> decide_action just gets None (no tier shift).
      * cc_threat_line absent / empty -> fight_rule = risk = "".
      * item_build absent -> item fields = "".
      * next_item_name absent -> reset_item = "" (no item to anchor the
        no-recall fact to).
    On ANY internal failure each field independently degrades to "" / {}.
    ``build_block`` NEVER raises.
"""
from __future__ import annotations

import math

from core import aram_action_rule, aram_fight_risk
from core.coach_choices import CoachChoice, synthesize_simple_choices, to_jsonable

# ARAM has no shop trips mid-lane: the only "reset" is a death back to fountain.
# This is the standing ARAM fact the reset_item line anchors the next item to.
_ARAM_NO_RECALL_PREFIX = "No fountain trips"

# Canonical ARAM action label -> its (A label, B label) A/B pair. These are the
# EXACT 5 labels core.aram_action_rule.decide_action returns; the A/B is ARAM-
# appropriate (no recall option - ARAM has no shop trips mid-lane). Marks the
# deterministic ARAM rule with source_tag "aram_rule" so the chip UI can tell it
# apart from the synth / native / haiku paths.
_ARAM_CHOICE_LABELS = {
    "ALL-IN": ("All-in", "Poke instead"),
    "POKE": ("Poke", "Hold"),
    "HOLD": ("Hold", "Reposition"),
    "DISENGAGE": ("Disengage", "Trade back"),
    "FALL BACK": ("Fall back", "Hold under turret"),
}


def _has_usable_number(value: object) -> bool:
    """True only when ``value`` coerces to a finite float (not NaN/inf).

    Used to decide whether an ACTION signal exists at all. A None or a
    non-coercible / NaN hp_pct means "no action computable" -> action "".
    """
    if value is None:
        return False
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return not (math.isnan(out) or math.isinf(out))


def _safe_action(hp_pct: object, wave_pct: object, low_enemy_count: object) -> str:
    """decide_action over the inputs, but "" when no HP signal is present.

    decide_action itself never raises and neutral-defaults to HOLD on an
    unusable hp_pct; we gate on a usable hp_pct first so a no-data tick logs
    an empty action instead of a misleading HOLD.
    """
    if not _has_usable_number(hp_pct):
        return ""
    try:
        return aram_action_rule.decide_action(hp_pct, wave_pct, low_enemy_count)
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


def _safe_choices(action: str, fight_rule: str) -> list[dict]:
    """Derive the deterministic A/B choices from the block's own action + fight_rule.

    Maps ALL 5 canonical ARAM action labels (ALL-IN / POKE / HOLD / DISENGAGE /
    FALL BACK) through ``_ARAM_CHOICE_LABELS`` to an ARAM-appropriate 2-entry
    A/B, each tagged source_tag "aram_rule" so the served chip UI can tell the
    deterministic ARAM rule apart from the synth / native / haiku paths. This
    SUPERSEDES the earlier narrow reuse of synthesize_simple_choices (which
    mapped only ALL-IN + FALL BACK), lifting choices coverage toward parity with
    the live Haiku surface. A B outcome carries the passed fight_rule when
    present, else a safe default. An EMPTY or UNKNOWN (non-canonical) action
    falls back to synthesize_simple_choices (which returns [] for empty/unknown),
    so nothing regresses off the canonical labels. Never raises.
    """
    try:
        key = action.strip().upper() if isinstance(action, str) else ""
        pair = _ARAM_CHOICE_LABELS.get(key)
        if pair is None:
            # Empty / unknown action: keep the old synth fallback (-> [] here).
            return to_jsonable(
                synthesize_simple_choices({"action": action, "fight_rule": fight_rule})
            )
        a_lbl, b_lbl = pair
        b_outcome = (
            fight_rule.strip()
            if isinstance(fight_rule, str) and fight_rule.strip()
            else "play safe; reassess next tick"
        )
        choice_a = CoachChoice(
            key="A",
            label=a_lbl,
            expected_outcome="follow the coach call",
            confidence="mid",
            source_tag="aram_rule",
        )
        choice_b = CoachChoice(
            key="B",
            label=b_lbl,
            expected_outcome=b_outcome,
            confidence="mid",
            source_tag="aram_rule",
        )
        return to_jsonable([choice_a, choice_b])
    except Exception:  # noqa: BLE001 - fail-soft contract: never raises
        return []


def _clean_str(value: object) -> str:
    """Return a stripped string, or "" for non-str / empty / whitespace."""
    return value.strip() if isinstance(value, str) and value.strip() else ""


# How many completed items the assembled build path shows. The ARAM build-order
# table is a curated 6-item path (boots + legendaries, already ward/jungle-free
# upstream), so 6 is the natural cap; a shorter real order just shows fewer.
_MAX_BUILD_ITEMS = 6


def _build_path_from_order(build_order: object) -> str:
    """Join the first up-to-6 COMPLETED item names from ``build_order``.

    ``build_order`` is the full ordered list of completed-item display NAMES for
    the champion+mode (as the ARAM build-order table provides it). Non-str /
    blank / None entries (components or gaps) are skipped; the result is a
    ", "-joined string of at most _MAX_BUILD_ITEMS names. A non-list order, an
    empty list, or an all-blank list yields "" - the fail-soft default that
    leaves item_build unchanged. Never raises.
    """
    if not isinstance(build_order, list):
        return ""
    names: list[str] = []
    for entry in build_order:
        name = _clean_str(entry)
        if not name:
            continue
        names.append(name)
        if len(names) >= _MAX_BUILD_ITEMS:
            break
    return ", ".join(names)


def _reset_line(next_item_name: object, next_item_remaining_gold: object) -> str:
    """Compose the ARAM reset/item line, or "" when no next item is known.

    ARAM has no recall, so the line states that fact and names the next core
    item to save toward, with the remaining gold when it is a clean number.
    """
    name = _clean_str(next_item_name)
    if not name:
        return ""
    try:
        gold = int(next_item_remaining_gold)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        gold = None
    if gold is not None and gold > 0:
        return f"{_ARAM_NO_RECALL_PREFIX}; save toward {name} ({gold}g remaining)."
    return f"{_ARAM_NO_RECALL_PREFIX}; save toward {name}."


def _build_reasons(
    item_build_reasons: object,
    antitank_hint: object,
    heal_threat_line: object,
) -> dict:
    """Merge the per-item reason map with the anti-tank / heal-threat reasons.

    The base map (item -> why-this-item) is copied so the caller's dict is
    never mutated. The anti-tank + heal-threat reason strings ride in under
    stable, non-colliding keys so the operator sees the full build rationale.
    A non-dict base / blank hint each degrades to absent, never raises.
    """
    out: dict = {}
    if isinstance(item_build_reasons, dict):
        for k, v in item_build_reasons.items():
            out[str(k)] = v
    at = _clean_str(antitank_hint)
    if at:
        out["anti-tank"] = at
    heal = _clean_str(heal_threat_line)
    if heal:
        out["anti-heal"] = heal
    return out


def _safe_item_extra(owned_item_count: object) -> str:
    """The ARAM "7th-item else omit" filler, deterministically resolved.

    The live Haiku emits "omit" when a 7th legendary already fills the slot,
    else a "Pot: X" / "Shard: X" consumable pick (coaches/aram_coach.py:332).
    Our deterministic build path caps at _MAX_BUILD_ITEMS (6) and never emits a
    7th item, and picking a SPECIFIC consumable is a judgment call we DECLINE
    rather than fabricate (do-not-flip-blind: a wrong precompute is worse than a
    Haiku call). So the safe, never-misleading resolution is: a known
    non-negative owned-item count -> the literal "omit" (the exact value the
    live coach itself emits for this state); no count signal / garbage /
    negative -> "" (honest empty, same as every other absent-input field here).
    Never raises.
    """
    if not _has_usable_number(owned_item_count):
        return ""
    try:
        count = int(float(owned_item_count))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    return "omit" if count >= 0 else ""


# objective tower-HP thresholds (percent; 0 = tower destroyed, <=25 = in danger).
_TOWER_DEAD = 0.0
_TOWER_DANGER = 25.0

# The deterministic ARAM objective lines, one per tower-HP state. Faithful to
# the coaches/aram_coach.py:295-298 OBJECTIVE prompt (defend your T1 / push once
# enemy T1 falls / force the Nexus once the inhibitor is open). ARAM exposes one
# nearest-tower HP per side, so these key on my_tower_hp + enemy_tower_hp only.
_OBJ_ENEMY_DEAD = (
    "Enemy tower down - push to their base; group only with a numbers lead."
)
_OBJ_MY_DEAD = "Your tower fell - hold the inhibitor; group up, never solo-push."
_OBJ_MY_DANGER = "Defend your tower - a death to save it (1min+ respawn) is worth it."
_OBJ_ENEMY_LOW = (
    "Enemy tower is low - siege it with your team; do not dive without numbers."
)
_OBJ_ENEMY_ALIVE = "Poke the enemy tower; do not chase past T1 range without allies."
_OBJ_MY_HEALTHY = "Hold and poke; wait for a pick before you commit."


def _coerce_tower_hp(value: object) -> float | None:
    """Coerce a tower-HP percent to a float, or None when it is not usable."""
    if not _has_usable_number(value):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _safe_objective(my_tower_hp: object, enemy_tower_hp: object) -> str:
    """Deterministic ARAM objective from the two nearest-tower HP percents.

    Priority (first match wins), faithful to the OBJECTIVE prompt:
      1. enemy T1 destroyed             -> push to their base
      2. your T1 destroyed              -> hold the inhibitor, group up
      3. your T1 in danger (<=25)       -> defend it (a death to save it is worth it)
      4. enemy T1 low (<=25)            -> siege it with the team
      5. enemy T1 healthy               -> poke phase, do not chase past T1
      6. only your T1 known + healthy   -> hold and poke for a pick
    Neither side usable -> "" (tower HP is vision-only and often absent
    server-side, like wave_pct). The defensive branches (2, 3) OUTRANK the
    enemy-tower branches so that losing your own tower - which opens your base -
    is always the higher priority. Never raises.
    """
    try:
        my_hp = _coerce_tower_hp(my_tower_hp)
        en_hp = _coerce_tower_hp(enemy_tower_hp)
        if my_hp is None and en_hp is None:
            return ""
        if en_hp is not None and en_hp <= _TOWER_DEAD:
            return _OBJ_ENEMY_DEAD
        if my_hp is not None and my_hp <= _TOWER_DEAD:
            return _OBJ_MY_DEAD
        if my_hp is not None and my_hp <= _TOWER_DANGER:
            return _OBJ_MY_DANGER
        if en_hp is not None and en_hp <= _TOWER_DANGER:
            return _OBJ_ENEMY_LOW
        if en_hp is not None:
            return _OBJ_ENEMY_ALIVE
        return _OBJ_MY_HEALTHY
    except Exception:  # noqa: BLE001 - fail-soft contract: never raises
        return ""


def build_block(
    hp_pct: object = None,
    wave_pct: object = None,
    low_enemy_count: object = None,
    *,
    cc_threat_line: object = None,
    item_build: object = None,
    build_order: object = None,
    item_build_reasons: object = None,
    next_item_name: object = None,
    next_item_remaining_gold: object = None,
    antitank_hint: object = None,
    heal_threat_line: object = None,
    owned_item_count: object = None,
    my_tower_hp: object = None,
    enemy_tower_hp: object = None,
) -> dict:
    """Assemble the deterministic ARAM coach block (the six live-coach fields).

    All arguments are optional primitives; the assembler works from whatever
    is present and degrades each field independently to "" / {} on absence or
    failure. NEVER raises.

    Args:
        hp_pct: self HP percent 0..100. Absent / non-coercible -> action "".
        wave_pct: minion-wave position 0..100 (vision-only; often absent
            server-side). Absent -> no tier shift in decide_action.
        low_enemy_count: count of low-HP enemies (>=2 enables the ALL-IN top
            tier). Non-int -> treated as 0 by decide_action.
        cc_threat_line: the ``enemy_cc_threat_line`` string OR a ranked
            iterable of CC entries (see core.aram_fight_risk). Drives
            fight_rule + risk. Absent / malformed -> both "".
        item_build: an explicit ARAM build-path string (e.g. "BorK -> Kraken").
            When non-empty it WINS and is used verbatim. Absent / blank ->
            assembled from ``build_order`` instead (then "").
        build_order: the full ordered list of completed-item display NAMES for
            this champion+mode (as the ARAM build-order table provides). Used to
            assemble ``item_build`` (first up-to-6 names, ", "-joined) only when
            ``item_build`` is blank. Empty / None / non-list -> item_build "".
        item_build_reasons: a {item_name: reason} dict. Absent -> {} (then
            possibly populated by the hint reasons below).
        next_item_name: display name of the next un-bought core item. Anchors
            the no-recall reset line; absent -> reset_item "".
        next_item_remaining_gold: gold remaining to afford next_item_name.
        antitank_hint: the ds_antitank_hint "hint" string. Folded into reasons.
        heal_threat_line: the heal_threat_callout "line" string. Folded in.
        owned_item_count: count of COMPLETED items the player owns. Drives
            item_extra: a known non-negative count -> "omit"; absent /
            garbage / negative -> "".
        my_tower_hp: your nearest-tower HP percent 0..100 (vision-only; null
            when not visible). Drives objective.
        enemy_tower_hp: enemy nearest-tower HP percent 0..100 (vision-only).
            Drives objective. Both towers absent -> objective "".

    Returns:
        dict with exactly the keys action, fight_rule, risk, reset_item,
        item_build, item_build_reasons, choices (the A/B array derived from
        action + fight_rule; [] when no binary verb maps), item_extra (the
        ARAM 7th-item "omit" filler), and objective (the deterministic
        tower-HP state-machine line; "" when no tower HP is known).
    """
    try:
        # Compute action + fight_rule ONCE so choices reuses them without
        # double-calling the underlying rules.
        action = _safe_action(hp_pct, wave_pct, low_enemy_count)
        fight_rule = _safe_fight_rule(cc_threat_line)
        return {
            "action": action,
            "fight_rule": fight_rule,
            "risk": _safe_risk(cc_threat_line),
            "reset_item": _reset_line(next_item_name, next_item_remaining_gold),
            "item_build": _clean_str(item_build) or _build_path_from_order(
                build_order
            ),
            "item_build_reasons": _build_reasons(
                item_build_reasons, antitank_hint, heal_threat_line
            ),
            "choices": _safe_choices(action, fight_rule),
            "item_extra": _safe_item_extra(owned_item_count),
            "objective": _safe_objective(my_tower_hp, enemy_tower_hp),
        }
    except Exception:  # noqa: BLE001 - total fail-soft: empty block
        return {
            "action": "",
            "fight_rule": "",
            "risk": "",
            "reset_item": "",
            "item_build": "",
            "item_build_reasons": {},
            "choices": [],
            "item_extra": "",
            "objective": "",
        }


__all__ = ["build_block"]
