"""R59 (ENGINE 1.170.0, 2026-07-02) - target-side Lifeline shield magnitude.

Shared helper for the ``assume_lifeline_shield`` seam in ``burst.compute_burst
_damage`` and ``dps.compute_dps``. Where ``ehp.py`` already values the WIELDER's
own Lifeline shield (Phase 1.5, ENGINE 1.27.0), this closes the symmetric
OFFENSE-side omission: a modeled TARGET holding a Lifeline item first gains a
low-HP shield that absorbs part of the incoming burst, so the burst actually
delivered is smaller than the raw combo total.

Magnitude reuses the Phase-1.5 ``ItemShield`` already extracted from Meraki into
``_effects_data.ITEM_EFFECTS`` (no re-parse of wiki-template effect strings) for
the three lifeline items this helper models on the TARGET side:

  * Immortal Shieldbow 6673 - ANY shield, flat 400 (<=L9) lerp-> 700 (>=L18),
    ranged x0.80. Pure level-scaled flat, NO wielder-stat dependency -> the
    canonical representative a modeled target is assumed to hold (an exact
    magnitude that needs zero extra target-build assumptions; conservative -
    it never overshoots Sterak/Maw whose stat-scaling terms it omits).
  * Sterak's Gage 3053 - ANY shield, 60% of the target's bonus HP.
  * Maw of Malmortius 3156 - MAGICAL shield, flat 200 + 150% bonus AD, ranged
    x0.75.

Byte-identical when the seam is OFF: callers only invoke this helper inside the
``assume_lifeline_shield`` branch. Live default-ON flip is operator-gated
(docs/LIVE_GAME_GATED_SYNC.md).
"""
from __future__ import annotations

from ._effects_data import ITEM_EFFECTS

# Target-side modeled subset, NOT a census of the family. The
# unique_passive_key="lifeline" family is 12 items today (measured 2026-09-03):
# 10 carry an ItemShield, and 2 - Protoplasm Harness 2525 / 222525 - grant
# maximum Health plus a heal instead, so their shield=None is correct. These
# three are the ones modeled here and each of the three does carry an
# ItemShield. Do NOT widen this tuple into a derived family census: pulling a
# shield-less member into a target-shield assumption would invent EHP that
# does not exist.
LIFELINE_ITEM_IDS: tuple[str, ...] = ("6673", "3053", "3156")

# Canonical representative Lifeline item a modeled target is assumed to hold.
# Shieldbow's shield is level-scaled flat with no wielder-stat dependency, so
# resolve_magnitude(level) alone is Meraki-exact with no target-build guess.
ASSUME_LIFELINE_TARGET_ITEM_ID = "6673"


def target_lifeline_shield(
    level: int,
    item_id: str = ASSUME_LIFELINE_TARGET_ITEM_ID,
    target_bonus_hp: float = 0.0,
    target_bonus_ad: float = 0.0,
    target_is_ranged: bool = False,
) -> float:
    """Meraki-exact one-shot Lifeline shield magnitude for ``item_id``.

    Delegates to ``ItemShield.resolve_magnitude`` (level lerp + bonus-HP / bonus
    -AD scaling + ranged modifier, floored at 0). Returns 0.0 for an unknown
    item id or an item that carries no ``shield`` (the 99% case).
    """
    eff = ITEM_EFFECTS.get(str(item_id))
    if eff is None or eff.shield is None:
        return 0.0
    return eff.shield.resolve_magnitude(
        level=int(level),
        bonus_hp=float(target_bonus_hp),
        bonus_ad=float(target_bonus_ad),
        is_ranged=bool(target_is_ranged),
    )
