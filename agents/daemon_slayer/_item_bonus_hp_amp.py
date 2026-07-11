"""Per-item BONUS-HP-AMP ("Warmog's Vitality") registry, keyed by item id.

The ITEM-SIDE lane of the R46 stacking-HP passive axis
(``_passive_health_overrides.passive_health_stack_hp``): a clean EHP-NUMERATOR
flat max-HP term, but sourced from an ITEM passive that AMPLIFIES the wielder's
own item-granted health. Warmog's Armor (3083) grants bonus MAXIMUM HEALTH equal
to a percent of the wielder's item-contributed bonus health via the "Warmog's
Vitality" passive, and that amplified HP earns ZERO EHP credit today.

A genuinely NEW survivability axis - an HP -> HP self-amplifier - distinct from the
seven saturated item-side survivability families (omnivamp / item-shield /
item-revive / item-stasis / item-spell-shield / item mana->HP R105 / item
conditional resist-grant R106). Unlike R105 (mana -> HP) this converts the build's
own item HP into more HP.

Why a NEW registry / seam (not the champion ``_passive_health_overrides``): that
registry is keyed by ``(champion_id, ability_key, form_index)`` so an ITEM can
never match it - the exact structural gap the ``_item_revive`` /
``_item_survival_window`` / ``_item_spell_shield_overrides`` / ``_item_mana_health``
registries fill for the champion revive / survival-window / spell-shield / mana-HP
axes.

Why NOT ``build_champion`` (unlike the always-on flat item HP): the engine already
folds each item's FLAT health stat into the resolved block, and it walks bonus-HP
-> bonus-AD (Overlord's Bloodmail / Sterak's "Tyranny", ``bonus_ad_pct_bonus_hp``,
``engine.py`` ~line 404), but it has NO bonus-HP -> bonus-HP self-amp walk and no
``_effects_types.ItemEffect`` field for it, so the Vitality HP is absent from the
resolved stat block. A live probe (Sion L13 with Warmog's + Heartsteel + Sunfire:
resolved ``hp - base_hp`` == the raw item flat-HP sum EXACTLY, +0.12 * item HP
absent - R107 / LEDGER 852) confirmed the miss. This lane credits it as a
DEFAULT-OFF opt-in EHP-NUMERATOR term (mirroring ``apply_item_mana_health`` /
``assume_passive_health_stacks``) rather than promoting it to an always-on
``build_champion`` walk, to keep the default EHP math BYTE-IDENTICAL and leave a
future live-flip / a ``build_champion`` promotion (which in live League would also
feed the Tyranny / Atma / Riftmaker bonus-HP consumers, so walk-ordering matters)
a separate operator-gated decision.

Mechanic: "Gain bonus health equal to 12% bonus health from items." (verbatim
``data/daemon_slayer/16.13.1/items_meraki.json`` for 3083, passive "Warmog's
Vitality", unique). "bonus health from items" = the build's item-contributed max
health; the caller computes ``bonus_hp = max(0.0, total_max_hp - base_max_hp)``
from the resolved stats (the champion's own base health at level is EXCLUDED,
matching the "bonus health from items" wording and the engine's own
``bonus_hp_from_items`` = item flat HP in the Tyranny walk). For an item-only DS
build (no runes) that equals the item flat HP the tooltip scopes; any item
percent-bonus-HP amp (Cinderhulk) is carried in the resolved HP by
``build_champion`` and rides the same total-minus-base convention as the sibling
R105 mana->HP credit. The credit is EXACT (a deterministic stat conversion), so -
unlike R106's ramping resist grant - there is NO amortization midpoint.

Unique-passive semantics: "Warmog's Vitality" is a UNIQUE passive AND, in the DS
item pool, at most one Warmog's is ever equipped (the base and its Arena mirror are
mutually exclusive). So the credited fraction is the MAX registered percent among
the equipped items (not a sum), which cannot double-count the SHARED bonus-HP pool
if a synthetic build lists both a base and its mirror.

Registered ids (each confirmed present in the DS item index
``data/daemon_slayer/16.13.1/items.json`` before adding; a live snapshot probe
resolved 3083 + 443083 and found 223083 / 323083 ABSENT):
  * 3083   - Warmog's Armor (base; carries Warmog's Vitality + Warmog's Heart regen).
  * 443083 - Warmog's Armor (Arena mirror; base nominal - the ``_item_mana_health`` /
    ``_item_resist_grants`` Arena-mirror convention). No 22xxxx / 32xxxx mirror exists
    in the index, so only the base + the 44xxxx Arena id are registered.

DOCUMENTED EXCLUSIONS (same item, NOT this credit):
  * Warmog's HEART (3083 passive "Warmog's Heart"): an out-of-combat HP-REGEN
    grant gated at 2000 bonus health - a regen throughput mechanic, not a bonus
    max-HP pool add (the ``_effects_data`` 3083 entry already notes the regen).

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: the ``apply_item_bonus_hp_amp`` seam on
``compute_ehp`` defaults False; with it OFF the credited HP is 0.0 and every EHP
numerator is unchanged. The live default-ON flip is operator-gated (mirrors
``apply_item_mana_health`` / ``assume_item_revive`` / ``apply_item_resist_grants``).

Keyed by string item_id to match the engine's ``resolved.item_ids`` tuple shape
(strings throughout).
"""

from __future__ import annotations

from typing import Iterable


# item_id -> fraction of BONUS-HP-FROM-ITEMS granted as bonus MAX HEALTH by the
# "Warmog's Vitality" passive. Both registered ids carry the same 12% (0.12); the
# Arena mirror carries the base nominal.
_ITEM_BONUS_HP_AMP_PCT: dict[str, float] = {
    "3083":   0.12,  # Warmog's Armor - Warmog's Vitality (12% bonus health from items)
    "443083": 0.12,  # Warmog's Armor (Arena mirror; base nominal)
}


def item_bonus_hp_amp_hp(
    item_ids: Iterable[str | int], bonus_hp_from_items: float
) -> float:
    """Return the bonus MAX HP from item bonus-HP-amp ("Warmog's Vitality") passives.

    ``bonus_hp_from_items`` is the build's item-contributed (bonus) max health - the
    caller computes it as ``max(0.0, total_max_hp - base_max_hp)`` from the resolved
    stats (the champion's own base health at level is excluded, matching the "bonus
    health from items" tooltip and the engine's own ``bonus_hp_from_items``). The
    credited HP is ``max_registered_pct * bonus_hp_from_items``.

    The MAX (not the sum) over the equipped registered items reflects the "Warmog's
    Vitality" UNIQUE passive over a shared bonus-HP pool, so a synthetic build listing
    the base plus its Arena mirror cannot double-count. In a real DS build at most one
    Warmog's is ever equipped (the base and the mirror are mutually exclusive), so the
    MAX equals the single match.

    Items not in the registry contribute 0. This is a clean EHP-NUMERATOR flat max-HP
    term (a real pool increase, folded next to ``ext_flat_hp`` / ``item_mana_health_hp``),
    distinct from the revive / stasis multipliers and the cc-only spell-shield fraction.
    Non-positive ``bonus_hp_from_items`` yields 0.0. The default-OFF gating lives in
    ``compute_ehp`` (this function is only called when ``apply_item_bonus_hp_amp`` is
    True).
    """
    bh = max(0.0, float(bonus_hp_from_items))
    if bh <= 0.0:
        return 0.0
    max_pct = 0.0
    for iid in item_ids:
        pct = _ITEM_BONUS_HP_AMP_PCT.get(str(iid))
        if pct is not None and pct > max_pct:
            max_pct = pct
    return max_pct * bh
