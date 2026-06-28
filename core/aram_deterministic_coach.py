# arch: deterministic ARAM coach block assembler (Stage 2) | section=core | frozen=no
"""Deterministic ARAM coach block assembler (Stage 2, Tier-1, no live wiring).

PURPOSE
    Assemble the WHOLE deterministic per-tick ARAM coach block - the same six
    fields the live ARAM Haiku call writes to ``data/aram_coaching_data.json``
    (``action`` / ``fight_rule`` / ``risk`` / ``reset_item`` / ``item_build`` /
    ``item_build_reasons``) - from the Stage 1 pure rules plus the existing
    ARAM build / hint surfaces. This is the assembler the operator can later
    eyeball, shadow-logged side-by-side with the live Haiku block; the live
    coach FLIP is a separate, operator-gated stage. This module changes NO
    served output and makes NO network call.

    The six fields come from:
      * action              <- core.aram_action_rule.decide_action(...)
      * fight_rule / risk   <- core.aram_fight_risk (over the enemy-CC threat
                               line / ranked entries)
      * item_build /
        item_build_reasons  <- passed-in build-table strings + the anti-tank /
                               heal-threat reason strings folded into the map
      * reset_item          <- the ARAM-no-recall fact anchored to the next
                               build item

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

# ARAM has no shop trips mid-lane: the only "reset" is a death back to fountain.
# This is the standing ARAM fact the reset_item line anchors the next item to.
_ARAM_NO_RECALL_PREFIX = "No fountain trips"


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


def _clean_str(value: object) -> str:
    """Return a stripped string, or "" for non-str / empty / whitespace."""
    return value.strip() if isinstance(value, str) and value.strip() else ""


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


def build_block(
    hp_pct: object = None,
    wave_pct: object = None,
    low_enemy_count: object = None,
    *,
    cc_threat_line: object = None,
    item_build: object = None,
    item_build_reasons: object = None,
    next_item_name: object = None,
    next_item_remaining_gold: object = None,
    antitank_hint: object = None,
    heal_threat_line: object = None,
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
        item_build: the ARAM build-path string (e.g. "BorK -> Kraken"). Absent
            -> "".
        item_build_reasons: a {item_name: reason} dict. Absent -> {} (then
            possibly populated by the hint reasons below).
        next_item_name: display name of the next un-bought core item. Anchors
            the no-recall reset line; absent -> reset_item "".
        next_item_remaining_gold: gold remaining to afford next_item_name.
        antitank_hint: the ds_antitank_hint "hint" string. Folded into reasons.
        heal_threat_line: the heal_threat_callout "line" string. Folded in.

    Returns:
        dict with exactly the keys action, fight_rule, risk, reset_item,
        item_build, item_build_reasons.
    """
    try:
        return {
            "action": _safe_action(hp_pct, wave_pct, low_enemy_count),
            "fight_rule": _safe_fight_rule(cc_threat_line),
            "risk": _safe_risk(cc_threat_line),
            "reset_item": _reset_line(next_item_name, next_item_remaining_gold),
            "item_build": _clean_str(item_build),
            "item_build_reasons": _build_reasons(
                item_build_reasons, antitank_hint, heal_threat_line
            ),
        }
    except Exception:  # noqa: BLE001 - total fail-soft: empty block
        return {
            "action": "",
            "fight_rule": "",
            "risk": "",
            "reset_item": "",
            "item_build": "",
            "item_build_reasons": {},
        }


__all__ = ["build_block"]
