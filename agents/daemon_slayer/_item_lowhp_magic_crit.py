"""Per-item LOW-HP MAGIC/TRUE damage amp ("Cinderbloom") registry, keyed by item id.

Shadowflame's "Cinderbloom" passive amplifies the wielder's MAGIC and TRUE damage
against a target below 40% health - "Magic and true damage Critically Strikes
enemies below 40% Health, dealing 20% increased damage" (DDragon 16.13.1). The
engine models Shadowflame's 15 flat magic pen but NOT this low-HP gate:
``_effects_data.py`` self-documents the omission on both ids ("Cinderbloom magic
crit <40% HP (low-HP gate not modeled)", lines ~1035 / ~3778), and no
magic-crit / can-crit path exists anywhere in ``agents/daemon_slayer/``. A live
delta==0 probe (Xerath L11 + [4645], SR) confirmed ``total_burst_damage`` is
byte-identical at target ``hp_pct`` 0.41 vs 0.39 today - the +20% never fires.

A genuinely NEW damage-layer axis, distinct from every credited amp:
  * It is GATED on the TARGET's current HP (< 40%) - a NEW gate condition no
    item-effects amp uses. ``total_magic_amp_multiplier`` (Abyssal Mask) is
    ALWAYS-ON and MAGIC-only; the existing target-HP gates in ``burst.py``
    (giant_slayer / target_bonus_hp anti-tank) are the INVERSE HIGH-HP direction;
    the only sub-40% amp today is a RUNE keystone (Coup de Grace / Cut Down),
    unreachable by an item id.
  * It amplifies TRUE damage as well as MAGIC - a reach no existing amp performs
    (``magic_amp`` is MAGIC-only). This is the distinguishing feature.

EXACT, NOT amortized (unlike R108's general-DR uptime midpoint): the amp is a
deterministic conditional - when the target is below the 40% threshold the credit
is EXACTLY the item's stated percent, and identity (1.0) at/above it. The gate is
the target-HP state the caller already supplies to ``compute_burst_damage``
(``target_current_hp_pct``, the same fixed-target-state convention burst.py uses
for its keystone / missing-HP amps), so there is no uptime assumption - only the
magnitude, which is directly DDragon-sourced.

MAGNITUDES (per-id, NOT identical - the SR and Arena mirrors differ, each
directly DDragon-verified at 16.13.1; no Meraki-vs-DDragon conflict since
Shadowflame is DDragon-only in the item index):
  * 4645   - Shadowflame (SR, ``maps.11``; 110 AP / 15 magic pen): +0.20.
  * 224645 - Shadowflame (Arena mirror, ``maps.30``; 90 AP / 10 magic pen): +0.15.
Both gate at the SAME 40% threshold; the amp value is the ONLY per-id difference.

DOCUMENTED EXCLUSIONS (scanned, deliberately NOT seeded - with the reason class):
  * 324645 - ARAM/mode mirror id: ABSENT from the 16.13.1 item index (not
    Cinderbloom-bearing this patch), so no constant to seed (mirrors R107's
    exclusion of absent mirror ids - never seed an unverifiable value).
  * The RUNE keystone low-HP amps (Coup de Grace / Cut Down): champion/rune-keyed,
    a separate axis already partly threaded via ``keystone_amp`` - NOT an item.
  * Physical damage + the auto-attack crit path: Cinderbloom is MAGIC/TRUE ONLY;
    physical damage is never amplified (asserted by the excluded-type test).

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: the ``assume_item_lowhp_magic_crit`` seam on
``compute_burst_damage`` defaults False; with it OFF (or the target at/above 40%,
or no registered item equipped) the multiplier is the identity 1.0 and every burst
component is unchanged. The live default-ON flip is operator-gated (mirrors the
R77 / R80 / R86 / R105 / R106 / R107 / R108 item seams).

Keyed by string item_id to match the engine's resolved item-id tuple shape
(strings throughout).
"""

from __future__ import annotations

from typing import Iterable


# Target-HP gate: the amp fires only against a target BELOW this fraction of max
# HP (DDragon "enemies below 40% Health"). A hard threshold, not an uptime - the
# caller supplies the fixed target-HP state (target_current_hp_pct), the same
# convention burst.py already uses for its keystone / missing-HP amps.
_LOWHP_THRESHOLD: float = 0.40


# item_id -> the fractional MAGIC/TRUE damage increase against a sub-threshold
# target. UNIQUE passive over a shared "Cinderbloom" name -> MAX over carriers
# (never a product), so a synthetic build listing two Shadowflames cannot
# double-count.
_ITEM_LOWHP_MAGIC_CRIT: dict[str, float] = {
    "4645":   0.20,  # Shadowflame (SR, maps.11) - Cinderbloom +20% (DDragon 16.13.1)
    "224645": 0.15,  # Shadowflame (Arena mirror, maps.30) - Cinderbloom +15% (DDragon 16.13.1)
}


def item_lowhp_magic_crit_amp(
    item_ids: Iterable[str | int],
    target_current_hp_pct: float,
    assume_item_lowhp_magic_crit: bool = False,
) -> float:
    """MAGIC/TRUE damage multiplier from item-keyed low-HP "Cinderbloom" amp.

    Returns ``1.0`` (identity) - BYTE-IDENTICAL - when any of:
      * ``assume_item_lowhp_magic_crit`` is False (the default),
      * the target is AT OR ABOVE the 40% HP threshold (the gate is not met), or
      * no equipped item carries a registered Cinderbloom passive.

    Otherwise returns ``1 + max_amp``, the STRONGEST single registered amp (MAX,
    never a product - a unique passive over a shared pool). The caller multiplies
    this into MAGIC and TRUE damage ONLY (never physical, never the AA crit path);
    a ``> 1.0`` value increases the burst against a low-HP target, the correct
    "executes squishies harder" direction and the axis's distinguishing TRUE reach.

    Items not in the registry contribute nothing. The default-OFF gating short-
    circuits to identity before any item is inspected when the flag is False.
    """
    if not assume_item_lowhp_magic_crit:
        return 1.0
    if target_current_hp_pct >= _LOWHP_THRESHOLD:
        return 1.0
    max_amp = 0.0
    for iid in item_ids:
        amp = _ITEM_LOWHP_MAGIC_CRIT.get(str(iid))
        if amp is not None and amp > max_amp:
            max_amp = amp
    if max_amp <= 0.0:
        return 1.0
    return 1.0 + max_amp
