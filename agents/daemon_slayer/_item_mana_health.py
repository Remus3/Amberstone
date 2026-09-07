"""Per-item MANA -> MAX-HEALTH ("Awe") registry, keyed by item id.

The ITEM-SIDE lane of the R46 stacking-HP passive axis
(``_passive_health_overrides.passive_health_stack_hp``): a clean
EHP-NUMERATOR flat max-HP term, but sourced from an ITEM passive instead of a
champion passive. Winter's Approach (3119) / Fimbulwinter (3121) grant bonus
MAXIMUM HEALTH equal to a percent of the wielder's BONUS mana via the "Awe"
passive, and that mana-derived HP earns ZERO EHP credit today.

Why a NEW registry / seam (not the champion ``_passive_health_overrides``): that
registry is keyed by ``(champion_id, ability_key, form_index)`` so an ITEM can
never match it - the exact structural gap the ``_item_revive`` /
``_item_survival_window`` / ``_item_spell_shield_overrides`` registries fill for
the champion revive / survival-window / spell-shield axes.

Why NOT ``build_champion`` (unlike the always-on Awe-AD / Awe-AP walks): the
engine already folds mana -> bonus AD (Manamune / Muramana ``bonus_ad_pct_max_mp``,
``engine.py`` ~line 362) and bonus mana -> AP (Archangel's / Seraph's
``bonus_ap_pct_bonus_mp``, ~line 383), but it has NO mana -> HP walk and no
``_effects_types.ItemEffect`` mana -> HP field, so the mana-derived HP is absent
from the resolved stat block (a live probe: Rell L13 with Fimbulwinter carries
only the item's FLAT health stat, not +0.15 * bonus mana). This lane credits it
as a DEFAULT-OFF opt-in EHP-numerator term (mirroring ``assume_item_revive`` /
``assume_item_stasis`` / ``apply_item_spell_shield`` / ``assume_passive_health_stacks``)
rather than promoting it to an always-on ``build_champion`` walk, to keep the
default EHP math BYTE-IDENTICAL and let a future live-flip / a build_champion
promotion be a separate operator-gated decision.

Mechanic: "Awe - Grants bonus health equal to 15% bonus mana." (verbatim
``data/daemon_slayer/16.13.1/items_meraki.json`` for 3119 and 3121, identical
text). "bonus mana" = item-contributed max mana (the champion's own base mana at
level is EXCLUDED), the same base the AP-side Awe (Archangel's / Seraph's) keys
off. The caller computes ``bonus_mana = max(0.0, total_max_mana - base_max_mana)``
from the resolved stats and passes it in. The credit is EXACT (a deterministic
stat conversion), so - unlike the revive / stasis mults - there is NO amortization
midpoint.

Unique-passive semantics: "Awe" is a UNIQUE passive (only the highest-percent
instance applies) AND, in the DS item pool, at most one family member is ever
equipped (Winter's Approach builds INTO Fimbulwinter; the mode-mirrors are
mutually exclusive). So the credited fraction is the MAX registered percent among
the equipped family items (not a sum), which cannot double-count the SHARED bonus
mana pool if a synthetic build lists two.

Registered ids (each confirmed present in the DS item index
``data/daemon_slayer/16.13.1/items.json`` before adding; the exhaustive Meraki
passives scan for 'health' + 'mana' co-occurrence returned exactly this family):
  * 3119   - Winter's Approach (base; carries Awe HP + the Manaflow mana-stack).
  * 3121   - Fimbulwinter (base; Awe HP + a separate current-mana Empowered Shield,
    which is NOT this credit).
  * 223119 / 223121 - Arena mode-mirrors (same nominal; the ``_item_revive`` /
    ``_item_survival_window`` Arena-mirror convention).
  * 323119 / 323121 - ARAM mode-mirrors. UNLIKE ``_item_revive``'s dropped ARAM
    Guardian-Angel mirror (323026, absent from the index), these ARAM mirrors ARE
    present in the DS item index, so they are included.

DOCUMENTED EXCLUSIONS (scanned, deliberately NOT seeded - with the reason class):
  * MANA -> DAMAGE "Awe" twins (Manamune 3004 / Muramana 3042 = 2% max mana as
    bonus AD; Archangel's Staff 3003 / Seraph's Embrace 3040 = 1% / 2% bonus mana
    as AP): the SAME "Awe" name but they convert mana to OFFENSE, already folded
    into ``ad_flat`` / ``ap_flat`` by ``build_champion`` - a different target, not
    bonus max health.
  * SERAPH'S LIFELINE SHIELD (3040): an 18%-max-mana SHIELD, a throughput shield
    (the ``assume_seraphs_shield`` lane), not a bonus-max-HEALTH grant.
  * TIME-STACKING FLAT STATS (Rod of Ages 6657 Timeless: +10 HP / +30 mana / +3 AP
    per minute): grants flat HP and flat mana INDEPENDENTLY by time, not an HP
    conversion of mana.
  * MANA-REGEN / HEAL-ON-SPEND (Catalyst of Aeons 3803 Eternity heal-from-mana-
    spent; Diadem of Songs 2530 ally heal from your max mana): heal throughput /
    ally grants, not a self bonus-max-HP conversion.

R144 MIRROR-COVERAGE RE-MEASURE (16.14.1, slice C). Re-audited against
``core.daemon_slayer_resolver.name_to_id`` - the resolver hands the engine
mirror ids, and a registry keyed on bare ids alone falls through to a silent
0.0 (the R143 / f7c49de5 defect class). This registry came back COMPLETE: the
index carries exactly six ids across the two names (``3119`` / ``223119`` /
``323119`` and ``3121`` / ``223121`` / ``323121``), and all six were already
registered. Pinned by ``tests/test_r144_mirror_slice_c.py``. Note the resolver
never actually emits the ``32xxxx`` pair for these names - both 32 mirrors
declare ``maps["11"]`` only, and the bare id wins the first-write-wins per-mode
index - so those two rows are defensive coverage rather than a live path.

OPEN, NOT ACTED ON (R144): the Arena mirrors' DDragon copy reads "Gain bonus
Health equal to Total Mana" where the SR/ARAM line reads "bonus mana", and the
Arena stat blocks are genuinely retuned (223119 carries 600 mana / 400 HP vs
the base 500 / 550). DDragon strips the numeral from the Awe tooltip and Meraki
keys base ids only, so the catalog cannot settle whether the Arena percent or
its mana BASE differs from 15% of BONUS mana. The base nominal is therefore
carried unchanged rather than retuned on a guess; settling it needs a live
Arena probe, not another catalog pass.

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: the ``apply_item_mana_health`` seam on
``compute_ehp`` defaults False; with it OFF the credited HP is 0.0 and every EHP
numerator is unchanged. The live default-ON flip is operator-gated (mirrors
``assume_item_revive`` / ``assume_item_stasis`` / ``apply_item_spell_shield``).

Keyed by string item_id to match the engine's ``resolved.item_ids`` tuple shape
(strings throughout).
"""

from __future__ import annotations

from typing import Iterable


# item_id -> fraction of BONUS mana granted as bonus MAX HEALTH by the "Awe"
# passive. All six family ids carry the same 15% (0.15) of BONUS mana (the two
# base tooltips are byte-identical; the mode-mirrors carry the base nominal).
_ITEM_MANA_HEALTH_PCT: dict[str, float] = {
    "3119":   0.15,  # Winter's Approach - Awe (15% bonus mana as bonus health)
    "3121":   0.15,  # Fimbulwinter - Awe
    "223119": 0.15,  # Winter's Approach (Arena mirror; base nominal)
    "223121": 0.15,  # Fimbulwinter (Arena mirror; base nominal)
    "323119": 0.15,  # Winter's Approach (ARAM mirror; base nominal)
    "323121": 0.15,  # Fimbulwinter (ARAM mirror; base nominal)
}


def item_mana_health_hp(item_ids: Iterable[str | int], bonus_mana: float) -> float:
    """Return the bonus MAX HP from item mana -> HP "Awe" passives.

    ``bonus_mana`` is the build's item-contributed (bonus) max mana - the caller
    computes it as ``max(0.0, total_max_mana - base_max_mana)`` from the resolved
    stats (the champion's own base mana at level is excluded, matching the
    verbatim "15% bonus mana" tooltip and the AP-side Awe base). The credited HP
    is ``max_registered_pct * bonus_mana``.

    The MAX (not the sum) over the equipped registered items reflects the "Awe"
    UNIQUE passive (only the highest instance applies) and shares a single bonus
    mana pool, so a synthetic build listing two family items cannot double-count.
    In a real DS build at most one family item is ever equipped (Winter's Approach
    builds into Fimbulwinter; the mode-mirrors are mutually exclusive), so the MAX
    equals the single match.

    Items not in the registry contribute 0. This is a clean EHP-NUMERATOR flat
    max-HP term (a real pool increase, folded next to ``ext_flat_hp``), distinct
    from the revive / stasis multipliers and the cc-only spell-shield fraction.
    Non-positive ``bonus_mana`` (a manaless build) yields 0.0. The default-OFF
    gating lives in ``compute_ehp`` (this function is only called when
    ``apply_item_mana_health`` is True).
    """
    bm = max(0.0, float(bonus_mana))
    if bm <= 0.0:
        return 0.0
    max_pct = 0.0
    for iid in item_ids:
        pct = _ITEM_MANA_HEALTH_PCT.get(str(iid))
        if pct is not None and pct > max_pct:
            max_pct = pct
    return max_pct * bm
