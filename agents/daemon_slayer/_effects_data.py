"""Static per-item ItemEffect registry for Daemon Slayer (ITEM_EFFECTS).

Split out of effects.py (s246, behavior-preserving): this is the
patch-pinned multi-thousand-line data table. effects.py keeps the
logic functions and re-exports ITEM_EFFECTS from here. Patch-pinned
per data/daemon_slayer/current.txt - refresh on patch bump (the
extractor manifest is the trigger), exactly as before the split.
"""

from __future__ import annotations

import dataclasses

from ._effects_types import (
    ANY,
    CallContext,
    ItemEffect,
    ItemHeal,
    ItemShield,
    MAGICAL,
    PHYSICAL,
    PeriodicProc,
    TRUE,
)


# Patch 16.9.1 - refresh on patch bump (extractor manifest is the trigger).
ITEM_EFFECTS: dict[str, ItemEffect] = {
    # ----------------------------------------------- crit / DPS-positive
    "3031": ItemEffect(
        item_id="3031",
        name="Infinity Edge",
        crit_damage_bonus=0.30,
        note="Infinity Edge: +30% bonus crit damage",
    ),
    "3072": ItemEffect(
        item_id="3072",
        name="Bloodthirster",
        defensive_only=True,
        # ENGINE 1.28.0 (2026-05-21): Phase 6 healing throughput - BT's
        # Ichorshield modeled as a steady-state ANY shield (overheal from
        # lifesteal builds the shield between fights; full-cap is the
        # sustained-fight assumption mirroring the engine's other full-
        # stack approximations). Meraki 16.10.1 "Ichorshield: shield up
        # to 165 + (315-165)/10*(x-1) for 1;9 to 20 by 1" -> L1 hold at
        # 165, L9-L18 ramp 165 -> 315. Same lerp convention as Immortal
        # Shieldbow 6673 (anchor at flat, ramp from level_lerp_low to
        # level_lerp_high). NO ``unique_passive_key="lifeline"`` - BT's
        # Ichorshield is a DIFFERENT unique passive (overheal/lifesteal
        # accrual, not low-HP trigger) and can stack with any single
        # lifeline shield in real builds.
        shield=ItemShield(
            damage_type=ANY,
            flat=165.0,
            level_lerp_low=9,
            level_lerp_high=18,
            level_lerp_high_value=315.0,
        ),
        note=(
            "Bloodthirster: Ichorshield 165 (L1) -> 315 (L18) ANY shield "
            "(overheal full-cap steady-state); no DPS contribution"
        ),
    ),
    "3097": ItemEffect(
        item_id="3097",
        name="Stormrazor",
        periodics=(PeriodicProc(
            name="Energized Bolt",
            # Meraki bulk items (patch 16.10.1) "Bolt": fully Energized
            # next basic deals 100 bonus magic damage on-hit. Was 120
            # (stale magnitude).
            bonus_damage=100.0,
            damage_type=MAGICAL,
            every_n_seconds=4.0,
        ),),
        note="Stormrazor: Energized Bolt +100 bonus magic dmg every ~4s",
    ),
    "6672": ItemEffect(
        item_id="6672",
        name="Kraken Slayer",
        periodics=(PeriodicProc(
            name="Bring It Down",
            # Meraki bulk items (patch 16.10.1) "Bring It Down": every
            # 3rd basic (2 stacks build, 3rd consumes) deals a melee
            # base of cdragon ramp "150 + (200-150)/10*(x-1) for 13" -
            # i.e. 150 at L1, +5 per level, capped after 10 steps
            # (level 11) at 200; the "for 13" only bounds the level
            # range. Was a flat 100 (stale magnitude). Engine uses the
            # melee value (same convention as Hullbreaker / the Bring
            # It Down family). The target's-missing-HP amplifier
            # (0-75%) stays unmodeled - it is a target-state proc, same
            # deliberate clamp as BotRK's %-current-HP.
            bonus_damage=lambda c: 150.0 + 5.0 * (min(c.level, 11) - 1),
            damage_type=PHYSICAL,
            every_n_attacks=3,
        ),),
        note=(
            "Kraken Slayer: Bring It Down 150 (L1) -> 200 (L11+) physical "
            "every 3rd attack"
        ),
    ),
    "6673": ItemEffect(
        item_id="6673",
        name="Immortal Shieldbow",
        defensive_only=True,
        # Phase 4 batch 12 (2026-05-04): Lifeline is unique-passive in
        # current League - only one Lifeline shield triggers per low-HP
        # threshold. Deduped against Sterak's Gage (3053) + Maw of
        # Malmortius (3156). All 3 are defensive_only so dedup only
        # affects DpsResult.notes (no proc to drop). When/if any
        # Lifeline item gets a DPS proc later, the order-dependence
        # gating from batch 11 (Essence Reaver) applies - re-evaluate.
        unique_passive_key="lifeline",
        # ENGINE 1.27.0 (2026-05-21): Phase 1.5 shield throughput. Meraki
        # 16.10.1 "400 to 700 for 11 levels" with levels=1;9 to 18 -
        # holds at 400 from L1-L8, ramps 400 -> 700 across L9-L18.
        # Ranged is 80% of melee (Meraki: "400*0.8 to 700*0.8"). Damage
        # type ANY: absorbs all 3 components.
        shield=ItemShield(
            damage_type=ANY,
            flat=400.0,
            level_lerp_low=9,
            level_lerp_high=18,
            level_lerp_high_value=700.0,
            ranged_modifier=0.80,
            note="Immortal Shieldbow Lifeline (Meraki 16.10.1)",
        ),
        note="Immortal Shieldbow: Lifeline (low-HP shield); no DPS contribution",
    ),

    # -- Phase 4 expansion 2026-05-03: energized family + scaling procs --

    "3087": ItemEffect(
        item_id="3087",
        name="Statikk Shiv",
        periodics=(PeriodicProc(
            name="Electrospark",
            # Meraki bulk items (patch 16.10.1) "Electrospark": next 3
            # basic attacks within 8s deal 60 bonus magic damage on-hit
            # each (85 vs non-champions, chained to up to 5 targets).
            # Cooldown ramps 25s at L1 down to 10s at L6+ (pp|25 to 10
            # for 6). Engine pins the L6+ steady-state cooldown (10s)
            # and the per-cycle payload (3 * 60 = 180 magic), modeled as
            # 180 every 10s = 18 magic/s (same convention as the
            # Kraken / Stormrazor energized-family encoding: payload-
            # per-cooldown-cycle, NOT per-attack). Was bonus_damage=110
            # every 3s (~36.7/s; iter-7 era stale magnitude that pre-
            # dated the Meraki 16.10.1 Electrospark spec, ~2x too high).
            bonus_damage=180.0,
            damage_type=MAGICAL,
            every_n_seconds=10.0,
        ),),
        note="Statikk Shiv: Electrospark 3x60 bonus magic dmg per 10s cooldown cycle (Meraki 16.10.1)",
    ),
    "3094": ItemEffect(
        item_id="3094",
        name="Rapid Firecannon",
        periodics=(PeriodicProc(
            name="Sharpshooter",
            # Meraki bulk items (patch 16.10.1) "Sharpshooter": fully
            # Energized next basic deals 40 bonus magic damage on-hit.
            # Was 120 (stale magnitude).
            bonus_damage=40.0,
            damage_type=MAGICAL,
            every_n_seconds=3.0,
        ),),
        note="Rapid Firecannon: Sharpshooter +40 bonus magic dmg every ~3s",
    ),
    "3091": ItemEffect(
        item_id="3091",
        name="Wit's End",
        periodics=(PeriodicProc(
            name="Fray",
            # Meraki bulk items (patch 16.10.1): "Basic attacks deal 45
            # bonus magic damage on-hit." Flat and level-independent in
            # the current patch - the old 15->80 level ramp was a stale
            # formula from an earlier Wit's End iteration.
            bonus_damage=45.0,
            damage_type=MAGICAL,
            every_n_attacks=1,
        ),),
        note="Wit's End: Fray +45 bonus magic damage on-hit (flat, every AA)",
    ),
    "3085": ItemEffect(
        item_id="3085",
        name="Runaan's Hurricane",
        periodics=(PeriodicProc(
            name="Wind's Fury",
            # Meraki bulk items (patch 16.10.1) "Wind's Fury": fires up
            # to 2 extra bolts, each dealing 55% AD physical (Riot "AD"
            # is TOTAL AD = base + bonus). Old model (0.60 * bonus_ad)
            # was wrong on both the coefficient and the base. Still
            # assumes both bolts find a target (max-uptime convention).
            bonus_damage=lambda c: 2.0 * 0.55 * (c.base_ad + c.bonus_ad),
            damage_type=PHYSICAL,
            every_n_attacks=1,
            # B1 (1.141.0): bolts fire on RANGED basics only - gated off melee
            # autos when compute_dps(apply_melee_aa_gate=True).
            ranged_only=True,
        ),),
        note="Runaan's Hurricane: 2 extra bolts on-hit, 55% total AD each",
    ),
    "3078": ItemEffect(
        item_id="3078",
        name="Trinity Force",
        periodics=(PeriodicProc(
            name="Spellblade",
            # Spellblade: next basic after spell deals 200% base AD bonus
            # physical. Approximation: fires ~once per 3s in active rotations
            # (real CD is 1.5s after spell cast, gated by ability cadence).
            bonus_damage=lambda c: 2.0 * c.base_ad,
            damage_type=PHYSICAL,
            every_n_seconds=3.0,
        ),),
        # Phase 4 batch 11 (2026-05-04): Spellblade is unique-passive in
        # current League - only one Spellblade proc fires per attack.
        # Deduped against Lich Bane (3100) and, as of Phase 4 batch 21
        # (2026-05-04), Essence Reaver (3508). Sundered Sky (6610) uses
        # its own "Lightshield Strike" label, not Spellblade - distinct
        # mechanic, no dedup.
        unique_passive_key="spellblade",
        note="Trinity Force: Spellblade ~200% base AD on-hit, ~once per 3s in rotation",
    ),
    "6699": ItemEffect(
        item_id="6699",
        name="Voltaic Cyclosword",
        periodics=(PeriodicProc(
            name="Firmament",
            # Iter 15 (2026-05-20): Meraki bulk items 16.10.1 - Firmament
            # is now a flat 100 bonus physical damage, the 25% bonus AD
            # scaling clause is stale (it was a pre-rework formula).
            # Slow utility unchanged + unmodeled. Charges over 4s of
            # moving / attacking.
            bonus_damage=100.0,
            damage_type=PHYSICAL,
            every_n_seconds=4.0,
        ),),
        # Phase 4 batch 30 (2026-05-04): 10 Lethality piece added via the
        # lethality plumbing schema. Was unmodeled prior - Voltaic's stat
        # block in DDragon doesn't carry the lethality value; description
        # lists it. Pipeline now accounts for the level-scaled flat pen
        # alongside the existing Energized periodic proc.
        lethality=10.0,
        note="Voltaic Cyclosword: Energized release 100 flat bonus physical every ~4s + 10 Lethality (level-scaled flat pen)",
    ),
    "6610": ItemEffect(
        item_id="6610",
        name="Sundered Sky",
        periodics=(PeriodicProc(
            name="Lightshield Strike",
            # Iter 16 (2026-05-20) recalibration vs Meraki 16.10.1:
            # Meraki text: "next basic attack against a champion is
            # empowered to critically strike for 60-80 bonus damage +
            # 80% total critical damage". Old encoding "20 + 200%
            # base_ad" was the pre-rework flat-magnitude estimate.
            # New encoding tracks the empowered-crit delta-vs-normal-AA:
            #   70 flat (midpoint of the 60-80 bonus damage band)
            #   + 80% of TOTAL AD (the 80% total-crit-damage modifier
            #     applied to the AA hit). At default 175% crit damage,
            #     a guaranteed crit on a 1.0 total_AD AA does 1.75x
            #     damage; +80% of that is ~ 0.8 * total_AD additional
            #     above the normal-AA baseline that compute_dps
            #     already counts. This is a CALIBRATION fix - same
            #     periodic shape, same 8s cadence; structural
            #     re-encoding as a crit-guarantee proc on the burst
            #     side is deferred (would touch burst.py + dps.py +
            #     CallContext crit-damage field).
            bonus_damage=lambda c: 70.0 + 0.8 * (c.base_ad + c.bonus_ad),
            damage_type=PHYSICAL,
            every_n_seconds=8.0,
        ),),
        # ENGINE 1.28.0 (2026-05-21): Phase 6 healing throughput - Lightshield
        # Strike heal piece. Meraki 16.10.1: "heal you for 100% base AD melee
        # / 50% base AD ranged (+ 6% missing health) (10s cooldown per
        # target)". One-trigger-per-fight model (10s CD per target > typical
        # 6s fight window). Phase 6.5 (2026-05-21): missing-HP additive
        # wired via ItemHeal.missing_hp_pct + ehp.py's
        # _MISSING_HP_SHARE_FOR_HEALS=0.5 mid-fight convention. Closes the
        # Phase 6 deliberate-omission (4) on Sundered Sky.
        heal=ItemHeal(
            base_ad_scaling=1.0,
            missing_hp_pct=0.06,
            ranged_modifier=0.5,
            note="Sundered Sky Lightshield Strike base AD heal + 6% missing HP",
        ),
        note=(
            "Sundered Sky: Lightshield Strike ~70 + 80% total AD bonus on "
            "guaranteed-crit empowered AA, every ~8s (calibrated to "
            "Meraki 16.10.1 60-80 + 80% total-crit-damage) + 100% base AD "
            "heal melee / 50% ranged + 6% missing HP per trigger "
            "(mid-fight 50% HP share assumption at consumer site)"
        ),
    ),
    "3124": ItemEffect(
        item_id="3124",
        name="Guinsoo's Rageblade",
        periodics=(
            PeriodicProc(
                name="Wrath",
                # Iter 12 (2026-05-20): Wrath flat-magic on-hit was
                # missing. DDragon 16.10.1 entry 3124 SR description:
                # "Wrath: Attacks deal 30 bonus magic damage on-hit."
                # Permanent passive, every AA, flat 30 magic - distinct
                # from Phantom Hit. Was unmodeled pre-iter-12 (only
                # Phantom Hit fired); a real drift, not a modeling
                # choice. Adds ~30 magic per attack at every level.
                bonus_damage=30.0,
                damage_type=MAGICAL,
                every_n_attacks=1,
            ),
            PeriodicProc(
                name="Phantom Hit",
                # Every 3rd attack triggers an extra on-hit. Approximated as
                # 50% bonus AD physical - under-counts on-hit stacking with
                # other items (BotRK, Wit's End) but those self-stack via
                # their own periodic entries.
                bonus_damage=lambda c: 0.50 * c.bonus_ad,
                damage_type=PHYSICAL,
                every_n_attacks=3,
            ),
        ),
        # R66 (2026-07-03): Seething Strike on the R42 conditional-AS lane,
        # full-stack steady-state pin (Meraki 16.13.1: 8% bonus AS per basic
        # attack, stacks to 4 = 32%). Ungated per Gemini director - same
        # no-flag convention as Yun Tal Flurry on this field.
        bonus_as_conditional=0.32,
        note="Guinsoo's Rageblade: Wrath +30 magic on-hit every AA + Phantom Hit every 3rd attack ~50% bonus AD physical + Seething Strike 8%x4 = 32% bonus AS at full stacks (Meraki 16.13.1)",
    ),

    # -- Phase 4 expansion: armor pen / reduction --

    "3036": ItemEffect(
        item_id="3036",
        name="Lord Dominik's Regards",
        armor_pen_pct=0.35,
        # Phase 4 batch 19 (2026-05-04): Giant Slayer promoted via the
        # target-conditional amp schema. DDragon: "Deal up to 15% bonus
        # damage against champions based on their bonus Health. Maximum
        # damage bonus reached at 1500 bonus Health." Caller supplies
        # target_bonus_hp; engine scales linearly to 15% at 1500, then
        # caps. Stacks multiplicatively with damage_amp_pct items
        # (Riftmaker, future Conqueror-style amps).
        target_bonus_hp_amp_max_pct=0.15,
        target_bonus_hp_amp_cap=1500.0,
        unique_passive_key="last_whisper",
        note="Lord Dominik's Regards: 35% armor pen (physical) + Giant Slayer up to 15% damage scaling with target_bonus_hp (capped at 1500)",
    ),
    "3033": ItemEffect(
        item_id="3033",
        name="Mortal Reminder",
        armor_pen_pct=0.30,
        unique_passive_key="last_whisper",
        note="Mortal Reminder: 30% armor pen + Grievous Wounds (heal-cut not modeled)",
    ),
    # Phase 4 batch 25 (2026-05-04): Serylda's Grudge added to ITEM_EFFECTS
    # as a new entry (was unmodeled - stats-only via item aggregation prior).
    # DDragon snapshot 16.9.1: "+45 Attack Damage / 35% Armor Penetration /
    # 15 Ability Haste". Same shape as LDR (3036) - % armor pen sits in the
    # same pipeline layer (reduction -> % pen -> flat pen). Coefficient 0.35
    # matches LDR; LDR additionally carries Giant Slayer (target_bonus_hp
    # amp); Serylda has Bitter Cold instead, which is a 30% slow on
    # damaging-ability hits to enemies below 50% HP - pure utility, not
    # damage. Stays unmodeled per the s77/s78 utility-without-damage rule
    # (same call as Stridebreaker's Halting Slash and Iceborn's frost field).
    # unique_passive_key="last_whisper" (2026-07-12): LDR / Mortal Reminder /
    # Serylda's are the completed members of DDragon MaxGroupOwnable:1 group
    # "LastWhisper" - only ONE can be owned. The engine's sole no-double hook
    # is unique_passive_key, so without it the ranker recommended 2-3 of them
    # vs tanky targets (Jhin + ~9 AD carries). Keying the COMPLETED items only
    # (NOT the 3035 Last Whisper component, whose component->completed upgrade
    # must stay recommendable) makes collect_effects dedup the pen (no fantasy
    # 70% stack) AND filter_shared_uniques drop the 2nd from candidates.
    "6694": ItemEffect(
        item_id="6694",
        name="Serylda's Grudge",
        armor_pen_pct=0.35,
        unique_passive_key="last_whisper",
        note="Serylda's Grudge: 35% armor pen (physical) + Bitter Cold ability slow on <50% HP targets (utility, not modeled)",
    ),
    "3071": ItemEffect(
        item_id="3071",
        name="Black Cleaver",
        # 6% armor reduction per stack, max 5 stacks = 30%. Modeled at
        # sustained DPS (full stacks); burst rotations see less.
        armor_reduction_pct=0.30,
        note="Black Cleaver: 30% armor reduction at full 5 stacks (sustained DPS assumption)",
    ),

    # -- Phase 4 expansion: defensive_only entries (proof of coverage) --

    "3046": ItemEffect(
        item_id="3046",
        name="Phantom Dancer",
        defensive_only=True,
        # NOT tagged "lifeline" - DDragon's actual passive label is
        # "Spectral Waltz" (Ghost effect, not a shield). Older RC notes
        # called this Lifeline by mistake. Different mechanic, no shared
        # unique-passive with Shieldbow / Sterak's / Maw.
        note="Phantom Dancer: Spectral Waltz (Ghost on low HP); no DPS contribution",
    ),
    "6676": ItemEffect(
        item_id="6676",
        name="The Collector",
        lethality=10.0,
        # DSV2 (1.125.0): Death execute valued by the kill-state finisher seam
        # (compute_burst_damage assume_takedown). Meraki 16.12.1: "If you deal
        # post-mitigation damage that would leave a champion below 5% of their
        # maximum health, execute them". Credited as 5% target max HP true
        # damage in the execute window; still NOT a sustained-DPS proc
        # (compute_dps ignores it). Taxes (25g/kill) stays out-of-combat.
        execute_max_hp_pct=0.05,
        note="The Collector: 50 AD + 10 Lethality + 25% Crit stat block; "
             "Death execute below 5% HP valued as a kill-state finisher under "
             "assume_takedown; Taxes passive (25g per kill) is out-of-combat. The "
             "lethality stat feeds the rest of the rotation.",
    ),
    "3142": ItemEffect(
        item_id="3142",
        name="Youmuu's Ghostblade",
        # Phase 4 batch 30 (2026-05-04): promoted from defensive_only via
        # the lethality plumbing schema. Stat block carries 18 Lethality
        # in description (NOT in DDragon's stats keys); the active MS
        # boost stays utility-only - not modeled (same rule as Stridebreaker's
        # Halting Slash, Iceborn's frost field).
        lethality=18.0,
        note="Youmuu's Ghostblade: 18 Lethality (level-scaled flat pen) + active MS bonus (utility, not modeled)",
    ),
    "3814": ItemEffect(
        item_id="3814",
        name="Edge of Night",
        # Phase 4 batch 30 (2026-05-04): promoted from defensive_only via
        # the lethality plumbing schema. 15 Lethality in description; the
        # Spellshield piece stays non-DPS (deduped against Banshee's Veil
        # could be a future call, but Spellshield is shield-style mechanic
        # and Banshee's is also separate - different proc shapes).
        lethality=15.0,
        note="Edge of Night: 15 Lethality (level-scaled flat pen) + Spellshield (defensive, not modeled)",
    ),
    "6695": ItemEffect(
        item_id="6695",
        name="Serpent's Fang",
        defensive_only=True,
        # R152 lethality stat-block parity: DDragon 16.14.1 <stats> carries
        # 15 Lethality; previously credited 0.0. defensive_only stays True -
        # it is doc-only (zero engine consumers) and the lethality fold in
        # effective_target_armor does not filter on it.
        lethality=15.0,
        # R75 DSV9 (1.179.0): Meraki 16.13.1 Shield Reaver, byte-grounded -
        # "Dealing damage to an enemy champion inflicts them with venom for
        # 3 seconds, reducing any shields they gain within the duration by
        # 50%|35% (rd = melee|ranged), and if the target was not already
        # afflicted by the venom, reducing all of their active shields by
        # the same amount." Pinned because the one-time ACTIVE-shield cut
        # on first affliction is a real burst-window magnitude: it is
        # valued by the NEW DSV9 assume_shielded_target burst seam against
        # an assumed target shield pool. The sustained shields-gained
        # reduction within the 3s venom stays UNMODELED (needs live target
        # shield-income, a CLOSED arc). defensive_only stays True - the
        # flag is doc-only, zero engine consumers (verified R69,
        # re-verified R74).
        shield_cut_melee_pct=0.50,
        shield_cut_ranged_pct=0.35,
        note=(
            "Serpent's Fang: Shield Reaver venom 3s - cuts ACTIVE shields "
            "once by 50% melee / 35% ranged on first affliction, valued by "
            "the DSV9 assume_shielded_target seam; the sustained "
            "shields-gained reduction within the venom stays unmodeled "
            "(Meraki 16.13.1)"
        ),
    ),
    "6701": ItemEffect(
        item_id="6701",
        name="Opportunity",
        # Phase 4 batch 30 (2026-05-04): promoted from defensive_only via
        # the lethality plumbing schema. 18 base Lethality in description;
        # the takedown-bonus-lethality piece is event-bound and stays
        # not-modeled (same rule as Hubris's Eminence). The 18 base
        # alone is a steady-state DPS contribution.
        lethality=18.0,
        note="Opportunity: 18 base Lethality (level-scaled flat pen) + takedown-bonus-lethality (conditional, not modeled)",
    ),
    "3053": ItemEffect(
        item_id="3053",
        name="Sterak's Gage",
        unique_passive_key="lifeline",
        # Phase 4 batch 20 (2026-05-04): "The Claws that Catch" promoted
        # from unmodeled. Meraki bulk items snapshot resolves the
        # numeric scaling DDragon stripped: "Gain bonus attack damage
        # equal to 45% base AD". This is a stat layer (not a proc) -
        # always-on flat AD added at build time, scales with the
        # leveled champion base AD (e.g. Sett base AD ~76 at lvl 11 ->
        # +34 bonus AD from Sterak's). Engine wires this in
        # ``build_champion`` via the ``bonus_ad_pct_base_ad`` field.
        # The Lifeline shield piece (unique_passive_key="lifeline")
        # remains non-DPS - deduped against Shieldbow / Maw / Sterak.
        # Engine still treats the item as having a non-DPS lifeline
        # piece + a DPS-positive Claws piece, both modeled correctly.
        bonus_ad_pct_base_ad=0.45,
        # ENGINE 1.27.0 (2026-05-21): Phase 1.5 shield throughput.
        # Meraki 16.10.1: "absorbs damage equal to 60% of bonus
        # health". Damage type ANY (lifeline absorbs all 3 components).
        # No ranged modifier (Sterak's is melee-only practically; the
        # scaling is pure bonus_hp share).
        shield=ItemShield(
            damage_type=ANY,
            bonus_hp_scaling=0.60,
            note="Sterak's Gage Lifeline 60% bonus HP (Meraki 16.10.1)",
        ),
        note=(
            "Sterak's Gage: The Claws that Catch +45% base AD as bonus AD "
            "(stat layer) + Lifeline (low-HP shield, deduped)"
        ),
    ),
    "3156": ItemEffect(
        item_id="3156",
        name="Maw of Malmortius",
        defensive_only=True,
        unique_passive_key="lifeline",
        # ENGINE 1.27.0 (2026-05-21): Phase 1.5 shield throughput.
        # Meraki 16.10.1: melee 200 + 150% bonus AD; ranged 150 + 112.5%
        # bonus AD (ratio 0.75 across both terms). Magic-only damage
        # absorption - landed only into magical_ehp.
        shield=ItemShield(
            damage_type=MAGICAL,
            flat=200.0,
            bonus_ad_scaling=1.50,
            ranged_modifier=0.75,
            note="Maw of Malmortius Lifeline magic shield (Meraki 16.10.1)",
        ),
        note="Maw of Malmortius: Lifeline magic shield; no DPS contribution",
    ),
    "3181": ItemEffect(
        item_id="3181",
        name="Hullbreaker",
        # Phase 4 batch 20 (2026-05-04): promoted from defensive_only.
        # Meraki bulk items snapshot (items_meraki.json) carries the
        # numeric formula DDragon strips:
        #   "Basic attacks on-hit grant a stack for 10s, stacking up to
        #    5 times. At maximum stacks, your next basic attack consumes
        #    all stacks to deal 120% base AD + 5% maximum health bonus
        #    physical damage."
        # Engine modeling:
        # - every_n_attacks=5 (4 build stacks + 5th attack consumes; same
        #   shape as Kraken Slayer's 3rd-attack proc, just at 5).
        # - bonus_damage = 1.20 * base_ad + 0.05 * caster_max_hp.
        # - "maximum health" is unqualified in Meraki's text -> caster's
        #   max HP (League convention; Hullbreaker is a side-laner HP-
        #   stacker item, design intent is wielder's HP). Same shape as
        #   Heartsteel's `0.06 * c.caster_max_hp`.
        # Approximations:
        # - Real proc only fires vs champions/epic monsters/structures.
        #   Engine has no champion-only target gate today (same trade-off
        #   as Kraken Slayer); over-counts vs minion-only rotations,
        #   noise band <DPS error of every other approximation.
        # - Increased structure damage (300% base AD + 10% max HP) not
        #   modeled - engine targets are champions, not structures.
        # - Boarding Party (ally-side siege minion buff) is non-DPS.
        periodics=(PeriodicProc(
            name="Skipper",
            bonus_damage=lambda c: 1.20 * c.base_ad + 0.05 * c.caster_max_hp,
            damage_type=PHYSICAL,
            every_n_attacks=5,
        ),),
        note=(
            "Hullbreaker: Skipper every-5th-attack 120% base AD + 5% caster "
            "max HP bonus physical (champ/epic/structure-gated; engine over-"
            "counts vs minion rotations) + Boarding Party (ally-side, no DPS)"
        ),
    ),
    "3110": ItemEffect(
        item_id="3110",
        name="Frozen Heart",
        defensive_only=True,
        # R86 (1.182.0): Winter's Caress -20% nearby enemy AS (DDragon 16.13.1)
        # -> 20% less incoming basic-attack RATE -> physical-EHP credit behind
        # the default-OFF ``assume_item_enemy_as_slow`` seam. DPS side stays inert.
        enemy_attack_speed_slow=0.20,
        note="Frozen Heart: AS-slow aura (-20% enemy AS) + armor; no DPS contribution",
    ),
    "3011": ItemEffect(
        item_id="3011",
        name="Chemtech Putrifier",
        defensive_only=True,
        note="Chemtech Putrifier: Grievous Wounds on damage (AP support, no DPS)",
    ),
    "3153": ItemEffect(
        item_id="3153",
        name="Blade of The Ruined King",
        periodics=(PeriodicProc(
            name="Mist's Edge",
            # 9% target current HP on-hit (Meraki 16.10.1 melee value; ranged
            # is 6%). Pipeline-A audit (2026-05-19) caught this stale 8%/5%
            # comment; engine pins to the melee value the same way Eclipse
            # 6% / Kraken / Hullbreaker do. Steady-state DPS approximation:
            # current_hp ~ max_hp at the start of a fight, so we model with
            # target_max_hp - slight over-count as the target gets chunked
            # through the rotation, explicit current_hp_pct field is a
            # future batch. Riot's 100 cap vs minions/monsters is not
            # modeled (champion DPS only).
            # DS target-current-HP% lever: this IS a current-HP proc, so the
            # magnitude scales by c.target_current_hp_pct (default 1.0 =
            # steady-state current==max, byte-identical to pre-lever).
            bonus_damage=lambda c: 0.09 * c.target_max_hp * c.target_current_hp_pct,
            damage_type=PHYSICAL,
            every_n_attacks=1,
        ),),
        note="Blade of the Ruined King: Mist's Edge 9% target HP on-hit (Meraki melee, steady-state approx)",
    ),
    "3302": ItemEffect(
        item_id="3302",
        name="Terminus",
        # Phase 4 batch 13 (2026-05-04): promoted from defensive_only.
        # The "alternating physical/magical" wording in the prior note
        # was incorrect - DDragon shows Shadow is a constant on-hit
        # (30 magic, every basic), and Juxtaposition is the alternating
        # part (Light buff = caster resists, defensive; Dark buff = pen).
        # R67 (2026-07-03): Meraki 16.13.1 says Dark hits grant 10%
        # armor pen AND magic pen per stack, "stacks up to 3 times" =
        # "30% resistances penetration at maximum stacks". The prior
        # 0.10 encoded a single stack; per the full-stack sustained-DPS
        # convention (Black Cleaver 3071 5-stack 0.30 shred, Guinsoo
        # 3124 4-stack 0.32 cond-AS) the Dark 3-stack steady state pins
        # at 0.30 armor pen + 0.30 magic pen. Light hits (6-8 bonus
        # armor+MR per stack, level pp 1;11;14 -> 18/21/24 at the 3-stack
        # cap) are caster-side and so belong to the EHP DENOMINATOR, not
        # to this DPS-side effect row: they are CREDITED in
        # ``_item_resist_grants`` row "3302" (level_scaled, prob 1.0 to
        # match this row's unamortized full-stack Dark half), reached via
        # the DEFAULT-OFF ``apply_item_resist_grants`` seam on
        # ``compute_ehp``. The older "no item-keyed resist-grant path
        # exists (_passive_resist_overrides.py is champion-keyed only);
        # FUTURE" note was stale - that path landed 2026-07-11 (R106,
        # ENGINE 1.199.0).
        periodics=(PeriodicProc(
            name="Shadow",
            bonus_damage=30.0,
            damage_type=MAGICAL,
            every_n_attacks=1,
        ),),
        armor_pen_pct=0.30,
        magic_pen_pct=0.30,
        note=(
            "Terminus: Shadow on-hit ~30 magic damage per attack + "
            "Juxtaposition Dark 3-stack steady-state 30% armor pen + "
            "30% magic pen (BC full-stack convention); the Light caster-side "
            "18/21/24 bonus armor+MR half is credited on the EHP denominator "
            "in _item_resist_grants row 3302 (DEFAULT-OFF seam), not here"
        ),
    ),
    "6692": ItemEffect(
        item_id="6692",
        name="Eclipse",
        periodics=(PeriodicProc(
            name="Ever Rising Moon",
            # 6% target max HP physical, gated on hitting the same target
            # with two damage instances within 1.5s. In an active basic-
            # attack rotation the 2-attack gate is the binding constraint,
            # so every_n_attacks=2 is the right shape. Note: real proc
            # has a 6s CD per target - under-counts when sustained, but
            # most rotations don't fire 2 procs within 6s anyway.
            bonus_damage=lambda c: 0.06 * c.target_max_hp,
            damage_type=PHYSICAL,
            every_n_attacks=2,
        ),),
        # R97 (2026-07-10): the uncredited SHIELD half of Ever Rising Moon (the
        # damage half above is already modeled). Credited via the default-OFF
        # assume_eclipse_shield seam - a burst-window shield on a 6s/target CD,
        # conservatively opt-in like Kaenic R92 rather than the always-on pool.
        shield=ItemShield(
            damage_type=ANY,
            flat=160.0,
            bonus_ad_scaling=0.40,
            ranged_modifier=0.5,
            default_off=True,
            note="Eclipse Ever Rising Moon 160 (+40% bonus AD) generic shield 2s; 0.5x ranged -> 80 (+20%); Meraki 16.13.1",
        ),
        note="Eclipse: Ever Rising Moon ~6% target max HP every 2 attacks (physical)",
    ),

    # -- Phase 4 expansion 2026-05-04: high-pickrate SR legendaries --
    # All defensive_only - passives are non-DPS (active utilities, lifeline
    # shields, sustain, damage-storage, ability-CDR stacks). Promote to
    # periodic / armor-pen / amp entries when the relevant Phase 4+ hooks
    # land (target HP, magic pen layer, ability scaling).

    "6333": ItemEffect(
        item_id="6333",
        name="Death's Dance",
        # ENGINE 1.57.0 (2026-05-25): Phase 6.5+ Defy heal-on-takedown.
        # Meraki 16.10.1 passive Defy: "If an enemy champion dies within
        # 3 seconds of you damaging them, removes Ignore Pain's remaining
        # stored damage and heals you for 75% bonus AD over 2 seconds".
        # The heal is takedown-gated; consumer-side multiplies by
        # _TAKEDOWN_RATE_PER_FIGHT (default 0.5). NOT defensive_only any
        # more - this contributes to EHP throughput on the heal lane.
        # Ignore Pain (the damage-storing piece) is still not modeled
        # at the EHP layer: it shifts damage from instant -> 3s spread,
        # which is a timing transform rather than a magnitude reduction;
        # the EHP scorer is a magnitude model. Future Phase 6.5+ work
        # MAY model Ignore Pain as a soft damage smoothing factor but
        # that is a separate axis (and intentionally out of scope here).
        heal=ItemHeal(
            bonus_ad_scaling=0.75,
            takedown_gated=True,
            note="Death's Dance Defy: 75% bonus AD heal on takedown (3s window)",
        ),
        note=(
            "Death's Dance: Ignore Pain stores 30% damage as bleed over 3s "
            "(timing-shift, not modeled at EHP layer); Defy heals 75% bonus "
            "AD over 2s on takedown - gated by _TAKEDOWN_RATE_PER_FIGHT"
        ),
    ),
    "3161": ItemEffect(
        item_id="3161",
        name="Spear of Shojin",
        defensive_only=True,
        # Phase 4 batch 16 (2026-05-04): note corrected against DDragon
        # snapshot. Prior note named "Veteran's Resolve stacks reduce
        # ability CDs" which is from an older patch - current passives
        # are "Dragonforce" (25 basic ability haste, stat-side) and
        # "Focused Will" (3% damage amp per stack to abilities/passives,
        # max 4 stacks = 12%). The amp is ABILITY-only, not auto-attack.
        # DSV4 (1.127.0): Focused Will is now valued via the
        # ability_damage_amp_* fields, consumed by the assume_ability_amp
        # seam on the ability scorers (default-OFF byte-identical). The
        # generic damage_amp_pct stays unused since it would amp AAs too.
        # defensive_only stays True - the item's STATS are defensive; the
        # amp is a conditional ability-scorer seam, not a direct DPS proc.
        ability_damage_amp_per_stack=0.03,
        ability_damage_amp_max_stacks=4,
        note="Spear of Shojin: Dragonforce (25 basic AH, stat) + Focused Will (3% per stack ability/passive amp, max 4 stacks = 12%; valued on the ability scorers via assume_ability_amp, DSV4)",
    ),
    # Phase 4 batch 21 (2026-05-04): ER promoted from defensive_only via
    # the new CallContext.crit_chance schema. Per Meraki bulk text:
    #   "Spellblade - After using an Ability, your next basic attack
    #    within 10s deals 125% base AD (+ 0 to 50 based on critical
    #    strike chance, scaling 0.5 damage per 1% crit) bonus physical
    #    damage on-hit and restores mana equal to half that amount."
    # Crit-chance scaling: 0.5 damage per 1% crit -> 50 * crit_chance
    # (where crit_chance is 0.0-1.0). At 0% crit ER procs for 1.25 *
    # base_ad; at 100% crit, +50 flat on top. Cooldown 1.5s real, but
    # rotation cadence is ability-cast-frequency-bound - match the
    # ~3s assumption already pinned for Trinity Force / Lich Bane (see
    # batch 11 commentary on Spellblade dedup).
    "3508": ItemEffect(
        item_id="3508",
        name="Essence Reaver",
        periodics=(PeriodicProc(
            name="Spellblade",
            bonus_damage=lambda c: 1.25 * c.base_ad + 50.0 * c.crit_chance,
            damage_type=PHYSICAL,
            every_n_seconds=3.0,
        ),),
        # Spellblade unique-passive - same key as Trinity Force (3078)
        # and Lich Bane (3100). First-seen-wins ordering: a build with
        # [TF, ER] keeps TF's spellblade; [ER, TF] keeps ER's. The pre-
        # promotion comment on TF flagged this exact dedup question;
        # batch 21 closes it by joining the family.
        unique_passive_key="spellblade",
        note="Essence Reaver: Spellblade 125% base AD + 0.5/crit% bonus physical on-hit, ~once per 3s in rotation",
    ),
    "3084": ItemEffect(
        item_id="3084",
        name="Heartsteel",
        periodics=(PeriodicProc(
            name="Colossal Consumption",
            # Flat 70 + 6% caster max HP physical, every 3.5s of in-
            # combat-with-champion charge time. DDragon 16.9.1 description:
            # "70 plus 6% of your max Health". The level-scaling lerp
            # (70 + 90*(level-1)/17 = 70-160) carried here through batch 16
            # was from a prior patch and was wrong on current data. The
            # HP-on-damage permanent stack (10% of damage as max HP) is not
            # modeled HERE - that's stat-side, not proc-side. It IS modelled as
            # of R137 / ENGINE 1.226.0 in ``_item_health_stack.py``, behind the
            # DEFAULT-OFF ``assume_item_health_stacks`` EHP-numerator seam.
            # NOTE the coefficient: this comment previously read 8%, inherited
            # from ``items_meraki.json``, which is FROZEN at content patch 25.15
            # (its body is byte-identical across all five vendored patch dirs).
            # DDragon 16.14.1, CommunityDragon 16.14 and the wiki all read 10%,
            # and the wiki's dated V26.11 note ("increased to 10% from 8%")
            # matches the 8 -> 10 flip visible between the vendored 16.10.1 and
            # 16.11.1 dirs. Do NOT re-source this number from Meraki.
            # CADENCE CORRECTED (RM-99b / A-04, operator-flipped 2026-07-24).
            # This carried every_n_seconds=3.5 - neither the 3s charge nor the
            # 30s PER-TARGET cooldown - so a single-target rotation over-procced
            # by exactly 30/3.5 = 8.5714x (MEASURED at shipped build depth, not
            # at an empty build; the proc supplied 13-32 pct of total credited
            # auto DPS on shipped bruiser builds). The 30.0 below is the real
            # per-target gate, sourced from the Meraki passive text quoted in the
            # seam block at the bottom of this file, and is now the SHIPPED
            # DEFAULT for SR: correcting the data table needs no consumer wire,
            # since all six scorers read ITEM_EFFECTS directly.
            # KNOWN live effect: Heartsteel falls from #1-#2 to #6-#43 on
            # /rank-bruiser and it sits in 49 of 173 shipped SR build orders.
            # The ARENA mirror 223084 is deliberately NOT corrected here - its
            # 30s is unsourced on its own feed. See HEARTSTEEL_CADENCE_FIX_IDS.
            bonus_damage=lambda c: 70.0 + 0.06 * c.caster_max_hp,
            damage_type=PHYSICAL,
            every_n_seconds=30.0,
        ),),
        note=(
            "Heartsteel: Colossal Consumption flat 70 + 6% caster max HP "
            "physical, 30s per-target cooldown"
        ),
    ),
    "3083": ItemEffect(
        item_id="3083",
        name="Warmog's Armor",
        defensive_only=True,
        note="Warmog's Armor: out-of-combat HP regen; no DPS contribution",
    ),
    "3139": ItemEffect(
        item_id="3139",
        name="Mercurial Scimitar",
        defensive_only=True,
        note="Mercurial Scimitar: active cleanse + bonus MS; no DPS contribution",
    ),
    "3026": ItemEffect(
        item_id="3026",
        name="Guardian Angel",
        defensive_only=True,
        note="Guardian Angel: revive after lethal damage; no DPS contribution (the Rebirth EHP-numerator revive is now credited item-side via the _item_revive registry behind the default-OFF assume_item_revive compute_ehp seam)",
    ),
    "3102": ItemEffect(
        item_id="3102",
        name="Banshee's Veil",
        defensive_only=True,
        note="Banshee's Veil: spellshield blocks next ability; no DPS contribution",
    ),
    "3157": ItemEffect(
        item_id="3157",
        name="Zhonya's Hourglass",
        defensive_only=True,
        note="Zhonya's Hourglass: active stasis (untargetable for 2.5s); no DPS contribution",
    ),
    # Phase 4 batch 21 (2026-05-04): Stridebreaker promoted from
    # defensive_only via the same multi-target rotation layer Ravenous
    # Hydra (3074) uses. Per Meraki bulk, Cleave deals "40% AD (melee) /
    # 20% AD (ranged) physical damage to other enemies in a 350 radius
    # centered around the target" on every basic on-hit. Same shape and
    # per-rotation isolation as Ravenous; coefficient is 40% vs Ravenous's
    # 35%. Halting Slash active (dash + slow) stays utility - not modeled.
    # Melee values pinned; ranged variant under-counts (same trade-off as
    # Ravenous and Titanic).
    "6631": ItemEffect(
        item_id="6631",
        name="Stridebreaker",
        periodics=(PeriodicProc(
            name="Cleave",
            # Melee: 40% total AD physical to other enemies (primary
            # already lands via the basic attack itself). At
            # targets_in_rotation=1.0 the cleave hits 0 enemies and adds
            # zero DPS - preserves the historic single-target shape for
            # all-n=1 rotations.
            bonus_damage=lambda c: max(0.0, c.targets_in_rotation - 1.0)
                * 0.40 * (c.base_ad + c.bonus_ad),
            damage_type=PHYSICAL,
            every_n_attacks=1,
        ),),
        # Iter 3 (2026-05-19): "Unique - Cleave" family. In live League a
        # build with 2+ Tiamat-tree items only procs Cleave once per AA
        # (highest-priority hydra wins). The previous comment claimed
        # ranker build-legality checks enforced this; they do not - the
        # ranker has no Tiamat-tree dedup. Tag the family so the existing
        # ``collect_effects`` first-seen-wins dedup + the ranker's
        # ``shares_dead_unique`` filter handle both layers in one shot.
        unique_passive_key="hydra_cleave",
        physical_burst_total_ad_ratio=0.80,
        note="Stridebreaker: Cleave ~40% AD physical to other enemies in 350 radius (melee, scales with rotation targets); Breaking Shockwave active 80% total AD physical AoE now modeled - rides the DSV8 assume_physical_burst burst window (Meraki 16.13.1, R113)",
    ),
    # Phase 4 batch 24 (2026-05-04): Profane Hydra (6698) added to
    # ITEM_EFFECTS as a new entry (was stats-only via item aggregation
    # prior - assassin-tagged Tiamat upgrade). Per Meraki bulk, Cleave
    # deals "40% AD (melee) / 20% AD (ranged) physical damage to other
    # enemies in a 350 radius centered around the target" on every
    # damaging basic on-hit. Same shape and per-rotation isolation as
    # Stridebreaker / Ravenous; coefficient pinned at 40% (melee value)
    # to match Stridebreaker's call. Heretical Cleave active (80% total AD
    # physical AoE) is NOW modeled on the DSV8 assume_physical_burst seam
    # (R113, 1.210.0) via ``physical_burst_total_ad_ratio`` - same as
    # Goredrinker's base-AD Thirsting Slash, which also has a null Meraki
    # cooldown: the one-cast burst-window shape overrode the earlier s77/s78
    # actives-without-CD-pin defer.
    # Iter 3 (2026-05-19): Tiamat-tree exclusivity ("Unique - Cleave") is
    # NOW enforced by ``unique_passive_key="hydra_cleave"`` so
    # ``collect_effects`` first-seen-wins drops the second hydra's proc
    # and the ranker filters double-hydra recommendations. The original
    # claim that this was "enforced by the ranker's build legality
    # checks" was wishful thinking - those checks (terminal / purchasable
    # / mode-legal / budget) have no Tiamat-tree awareness.
    "6698": ItemEffect(
        item_id="6698",
        name="Profane Hydra",
        # R152 lethality stat-block parity: DDragon 16.14.1 description
        # <stats> carries 18 Lethality (NOT in DDragon's stats keys, and
        # stats.ITEM_STAT_KEY_MAP has no lethality key) - so ITEM_EFFECTS
        # is the only credit path and this entry read 0.0 flat pen.
        lethality=18.0,
        periodics=(PeriodicProc(
            name="Cleave",
            # Melee: 40% total AD physical to other enemies (primary
            # already lands via the basic attack itself). At
            # targets_in_rotation=1.0 the cleave hits 0 enemies and adds
            # zero DPS - preserves the historic single-target shape for
            # all-n=1 rotations.
            bonus_damage=lambda c: max(0.0, c.targets_in_rotation - 1.0)
                * 0.40 * (c.base_ad + c.bonus_ad),
            damage_type=PHYSICAL,
            every_n_attacks=1,
        ),),
        unique_passive_key="hydra_cleave",
        physical_burst_total_ad_ratio=0.80,
        note="Profane Hydra: Cleave ~40% AD physical to other enemies in 350 radius (melee, scales with rotation targets); Heretical Cleave active 80% total AD physical AoE now modeled - rides the DSV8 assume_physical_burst burst window (Meraki 16.13.1, R113)",
    ),

    # -- Phase 4 batch 3 (2026-05-04): AP-aware CallContext + spellblade --
    # CallContext.ap (added this batch) lets spellblade and AP-on-hit procs
    # promote out of defensive_only. Two items unlock; five AP-stat siblings
    # land here as documented defensive_only because their effects don't
    # fit the periodic / on-hit shape (active utility, ability-bound,
    # combat-state amp, %-current-HP magic crit).

    "3100": ItemEffect(
        item_id="3100",
        name="Lich Bane",
        periodics=(PeriodicProc(
            name="Spellblade",
            # 75% base AD + 40% AP bonus magic on next basic after ability.
            # Real CD 1.5s; rotation cadence approx ~3s same as Trinity Force
            # spellblade (gated by ability cast frequency, not item CD).
            # AP coefficient verified against Meraki bulk 16.10.1
            # (pre-2026-05-20 the engine had 50% AP - drifted).
            bonus_damage=lambda c: 0.75 * c.base_ad + 0.40 * c.ap,
            damage_type=MAGICAL,
            every_n_seconds=3.0,
        ),),
        # Phase 4 batch 11 (2026-05-04): Spellblade unique-passive - see
        # the note on Trinity Force (3078) for the full reasoning. First-
        # seen-wins ordering: building [TF, LB] keeps TF's spellblade,
        # building [LB, TF] keeps LB's. Both are reasonable approximations
        # of a single in-game spellblade firing.
        unique_passive_key="spellblade",
        note="Lich Bane: Spellblade ~75% base AD + 40% AP magic, ~once per 3s in rotation",
    ),
    "6662": ItemEffect(
        item_id="6662",
        name="Iceborn Gauntlet",
        # Phase 4 batch 23 (2026-05-04): added to ITEM_EFFECTS as a new
        # entry (was not in the table at all - stats-only via item
        # aggregation prior to this batch). Iceborn's Spellblade variant
        # deals 150% base AD bonus physical on the next basic after an
        # ability. Real CD is 1.5s post-empowered-attack; rotation
        # cadence approx ~3s same as Trinity Force / Lich Bane / Essence
        # Reaver (gated by ability cast frequency, not item CD). The
        # frost field's 25% slow is utility, not damage - not modeled.
        # Joins the spellblade unique-passive dedup family.
        periodics=(PeriodicProc(
            name="Spellblade",
            bonus_damage=lambda c: 1.50 * c.base_ad,
            damage_type=PHYSICAL,
            every_n_seconds=3.0,
        ),),
        # Spellblade unique-passive - same key as Trinity Force (3078),
        # Lich Bane (3100), and Essence Reaver (3508). First-seen-wins
        # ordering: [TF, IBG] keeps TF (200% > 150%, but order rules);
        # [IBG, TF] keeps IBG. Same caveat as the rest of the family -
        # the engine doesn't pick "best", it picks "first" - and that
        # behavior is documented and intentional.
        unique_passive_key="spellblade",
        note="Iceborn Gauntlet: Spellblade ~150% base AD on-hit, ~once per 3s in rotation",
    ),
    "3115": ItemEffect(
        item_id="3115",
        name="Nashor's Tooth",
        periodics=(PeriodicProc(
            name="Icathian Bite",
            # 15 + 15% AP bonus magic per basic. Per-attack proc (every_n=1).
            # AP coefficient verified against Meraki bulk 16.10.1 (the
            # engine had drifted to 20% AP; current League math is 15% AP).
            bonus_damage=lambda c: 15.0 + 0.15 * c.ap,
            damage_type=MAGICAL,
            every_n_attacks=1,
        ),),
        note="Nashor's Tooth: Icathian Bite on-hit ~15 + 15% AP magic per attack",
    ),

    "3146": ItemEffect(
        item_id="3146",
        name="Hextech Gunblade",
        # Phase 4 batch 22 (2026-05-04): promoted from defensive_only.
        # Lightning Bolt active deals 175->253 (level 1->18, linear) +
        # 30% AP magic damage, 40s cooldown. Meraki text:
        #   "175 + (253-175)/17*(x-1) for 20" + 30% AP magic damage.
        # Cooldown sourced from in-game / wiki (Meraki bulk has the
        # cooldown field null on this item); 40s pins the in-game value.
        # Modeled as a long-CD periodic proc - same shape as Sundered
        # Sky's Lightshield Strike (8s) just with a far longer cadence.
        # Slow (25% / 1.5s) is utility, not damage - not modeled. Per the
        # batch 21 stat-property pattern, c.ap is build-derived and lives
        # on CallContext at compute_dps construction time; pre-batch
        # callers that don't pass it get the 0.0 default and the lambda
        # gracefully falls back to flat level-scaled damage.
        periodics=(PeriodicProc(
            name="Lightning Bolt",
            bonus_damage=lambda c: 175.0 + (253.0 - 175.0) / 17.0 * (c.level - 1) + 0.30 * c.ap,
            damage_type=MAGICAL,
            every_n_seconds=40.0,
        ),),
        note="Hextech Gunblade: Lightning Bolt 175->253 + 30% AP magic, 40s CD (slow not modeled)",
    ),
    "6655": ItemEffect(
        item_id="6655",
        name="Luden's Echo",
        # Phase 4 batch 52 (2026-05-04): promoted. Meraki confirms:
        # "75 (+ 5% AP) bonus magic damage, 12s CD." Primary-target DPS only -
        # multi-target splash (one additional enemy per Echo stack beyond first)
        # not modeled (requires target-count context). every_n_seconds=12.0
        # represents per-champion cooldown; in solo target fight this is exact.
        periodics=(PeriodicProc(
            name="Echo",
            bonus_damage=lambda c: 75.0 + 0.05 * c.ap,
            damage_type=MAGICAL,
            every_n_seconds=12.0,
        ),),
        # DSV6 (1.152.0): single-Echo burst-window magnitude for the on-cast
        # magic-burst seam (assume_magic_burst). Same Meraki 75 (+5% AP) as the
        # periodic; credited once per burst combo by compute_burst_damage. The
        # periodic above owns the sustained-DPS valuation in compute_dps (no
        # double-count - the one-shot magnitude lives only in the burst window).
        magic_burst_base=75.0,
        magic_burst_ap_ratio=0.05,
        note="Luden's Echo: Echo 75 (+5% AP) magic / 12s primary target (Meraki confirmed; AoE splash not modeled)",
    ),
    "4633": ItemEffect(
        item_id="4633",
        name="Riftmaker",
        # Phase 4 batch 14 (2026-05-04): promoted via damage_amp_pct.
        # Void Corruption ramps to 8% bonus damage after 4s in combat
        # (sustained-DPS approximation pins the full-ramp value).
        # Phase 4 batch 15 (2026-05-04): Void Infusion HP->AP wired via
        # ap_per_bonus_hp_pct = 0.02 (always-on passive, not gated by
        # combat - DDragon: "Gain 2% of your bonus Health as Ability
        # Power"). Compounds with Heartsteel / Titanic Hydra HP stacks
        # to lift Lich Bane / Nashor's Tooth proc damage. The omnivamp at max
        # Void Corruption stacks (10% melee / 6% ranged) is credited to the EHP
        # SUSTAIN axis behind ehp.compute_ehp's default-OFF
        # assume_max_stacks_omnivamp seam (via the _item_omnivamp registry); the
        # DPS engine still does not model the heal, and this ItemEffect's
        # damage_amp_pct / ap_per_bonus_hp_pct are unchanged.
        damage_amp_pct=0.08,
        ap_per_bonus_hp_pct=0.02,
        note="Riftmaker: Void Corruption ~8% damage amp at full ramp + Void Infusion 2% bonus HP -> AP (always on)",
    ),
    "3128": ItemEffect(
        item_id="3128",
        name="Deathfire Grasp",
        defensive_only=True,
        note="Deathfire Grasp: active 15% target max HP - active item, not in auto rotation",
    ),

    # -- Phase 4 batch 4 (2026-05-04): magic pen layer --
    # Symmetric to the armor pen pipeline. Void Staff / Cryptbloom carry
    # % pen; Sorcerer's Shoes / Shadowflame carry flat pen. Shadowflame
    # also has a magic-crit-on-low-HP effect (target HP not modeled in
    # Phase 4); the 15 flat pen IS modeled here, so it's no longer
    # defensive_only - the pen contribution alone is real DPS uplift.

    "3135": ItemEffect(
        item_id="3135",
        name="Void Staff",
        magic_pen_pct=0.40,
        unique_passive_key="void_pen",
        note="Void Staff: 40% magic pen (magical)",
    ),
    "3137": ItemEffect(
        item_id="3137",
        name="Cryptbloom",
        magic_pen_pct=0.30,
        unique_passive_key="void_pen",
        note="Cryptbloom: 30% magic pen + Life from Death heal-on-takedown (heal not DPS-modeled)",
    ),
    "3020": ItemEffect(
        item_id="3020",
        name="Sorcerer's Shoes",
        magic_pen_flat=12.0,
        note="Sorcerer's Shoes: 12 flat magic pen",
    ),
    "4645": ItemEffect(
        item_id="4645",
        name="Shadowflame",
        magic_pen_flat=15.0,
        note="Shadowflame: 15 flat magic pen + Cinderbloom magic crit <40% HP (low-HP gate not modeled)",
    ),

    # -- Phase 4 batch 6 (2026-05-04): caster HP layer --
    # CallContext.caster_max_hp / caster_bonus_hp (engine-derived from
    # resolved stats) lets caster-HP-scaling procs land. Heartsteel
    # promotes from defensive_only above. Titanic Hydra is a new add.
    # Ravenous Hydra deferred - current-patch Cleave is nearby-enemies-
    # only (no primary-target bonus); contributes 0 in single-target DPS.

    "3748": ItemEffect(
        item_id="3748",
        name="Titanic Hydra",
        periodics=(
            PeriodicProc(
                name="Cleave (primary)",
                # Iter 8 (2026-05-19): Meraki bulk items (patch 16.10.1):
                # "Basic attacks on-hit deal 1% (ranged 0.5%) maximum
                # health bonus physical damage to the target". Engine
                # prior: 5 + 1.5% caster_bonus_hp - drifted on three
                # axes (flat 5 -> 0, bonus_hp -> max_hp, 1.5% -> 1.0%).
                # Engine pins the melee value (1%), same convention as
                # BotRK 9% / Eclipse 6% / Hullbreaker / Kraken.
                bonus_damage=lambda c: 0.01 * c.caster_max_hp,
                damage_type=PHYSICAL,
                every_n_attacks=1,
            ),
            # Iter 8 (2026-05-19): Meraki bulk items (patch 16.10.1):
            # "... and 3% (ranged 1.5%) maximum health physical damage
            # to other enemies in a cone". Engine prior was 40% total
            # AD - reshaped to 3% maximum health (melee). Multiplier
            # max(0, n-1) keeps the "extra targets only" shape; the
            # primary target already takes the primary-proc damage.
            PeriodicProc(
                name="Cleave (to nearby)",
                bonus_damage=lambda c: max(0.0, c.targets_in_rotation - 1.0)
                    * 0.03 * c.caster_max_hp,
                damage_type=PHYSICAL,
                every_n_attacks=1,
            ),
        ),
        # Iter 3 (2026-05-19): hydra_cleave family - see Stridebreaker.
        # Both Titanic Cleave procs share one in-game passive ("Sterak
        # of Bork": Titanic's two-proc shape models primary + cleave-to-
        # nearby pieces of the same Cleave; only the FIRST hydra in the
        # build keeps both, the rest are dropped).
        unique_passive_key="hydra_cleave",
        note="Titanic Hydra: Cleave 1% max HP primary on-hit + 3% max HP to nearby (Meraki 16.10.1 melee values)",
    ),

    # -- Phase 4 batch 7 (2026-05-04): multi-target rotations --
    # CallContext.targets_in_rotation (engine-derived from each rotation's
    # numberOfTargets) lets cleave-to-others procs land. ~6% of lolmath
    # rotations carry n>1; the other 94% pass n=1.0 unchanged.

    "3074": ItemEffect(
        item_id="3074",
        name="Ravenous Hydra",
        periodics=(PeriodicProc(
            name="Cleave",
            # Melee: 40% total AD physical to other enemies (primary
            # already lands via the basic attack itself). At
            # targets_in_rotation=1.0 the cleave hits 0 enemies and adds
            # zero DPS - preserves the historic single-target shape for
            # all-n=1 rotations.
            # R193: read 0.35 (with a stale 21% ranged remark) while its
            # two byte-identical-text siblings 6631 / 6698 were already at
            # 0.40. Meraki 16.14.1 items.3074 Cleave = "40% AD / 20% AD",
            # so 0.35 was stale-patch drift. The family pins the melee
            # value - no ranged split, same call as 6631 / 6698.
            bonus_damage=lambda c: max(0.0, c.targets_in_rotation - 1.0)
                * 0.40 * (c.base_ad + c.bonus_ad),
            damage_type=PHYSICAL,
            every_n_attacks=1,
        ),),
        # Iter 3 (2026-05-19): hydra_cleave family - see Stridebreaker.
        unique_passive_key="hydra_cleave",
        physical_burst_total_ad_ratio=0.80,
        note="Ravenous Hydra: Cleave ~40% AD physical to other enemies in 350 radius (melee, scales with rotation targets); Ravenous Crescent active 80% total AD physical AoE now modeled - rides the DSV8 assume_physical_burst burst window (Meraki 16.14.1, R193)",
    ),

    # -- Phase 4 batch 9 (2026-05-04): Immolate items --
    # Sunfire Aegis (3068) and Hollow Radiance (6664) share the same
    # Immolate aura passive: after taking or dealing damage, deal
    # ~12 + 1.5% bonus HP magic damage per second to nearby enemies for 3s.
    # In any DPS rotation (basic attacks every ~1s, all rotations >=2s),
    # the 1s charge + 3s active window are continuously refreshed - modeled
    # as a per-second tick over the full rotation duration. The
    # AoE-incl-primary multiplier is c.targets_in_rotation (Sunfire's aura
    # damages every nearby enemy, primary included). Caster bonus HP
    # scaling reuses the batch-6 caster-HP layer.
    #
    # NOTE: Riot enforces unique-passive on Immolate (stacking Sunfire +
    # Hollow Radiance does NOT double the proc). The engine currently
    # treats all procs independently, so a build with both items will
    # double-count this contribution. Unique-passive enforcement is its
    # own architectural change - out of scope for this batch.
    #
    # Both items pass-through CallContext.targets_in_rotation: at n=1 the
    # Immolate still ticks for 1x damage (the primary target IS counted).
    # At n=3 it ticks for 3x damage. This is the AoE-incl-primary idiom
    # pinned in batch 7's tests.

    "3068": ItemEffect(
        item_id="3068",
        name="Sunfire Aegis",
        periodics=(PeriodicProc(
            name="Immolate",
            # Iter 8 (2026-05-19): Meraki bulk items (patch 16.10.1) -
            # "Deal 20 (+ 1% bonus health) magic damage per second".
            # Engine prior: 12 + 1.5% bonus_hp - stale magnitude on both
            # the base (12 -> 20) and the bonus_hp coefficient
            # (1.5% -> 1.0%).
            bonus_damage=lambda c: c.targets_in_rotation
                * (20.0 + 0.010 * c.caster_bonus_hp),
            damage_type=MAGICAL,
            every_n_seconds=1.0,
        ),),
        unique_passive_key="immolate",
        note="Sunfire Aegis: Immolate 20 + 1% bonus HP magic per second to nearby (Meraki 16.10.1)",
    ),
    "6664": ItemEffect(
        item_id="6664",
        name="Hollow Radiance",
        periodics=(PeriodicProc(
            name="Immolate",
            # Iter 8 (2026-05-19): Meraki bulk items (patch 16.10.1) -
            # "Deal 15 (+ 1% bonus health) magic damage per second".
            # Engine prior: 12 + 1.5% bonus_hp - stale magnitude on both
            # the base (12 -> 15) and the bonus_hp coefficient
            # (1.5% -> 1.0%).
            bonus_damage=lambda c: c.targets_in_rotation
                * (15.0 + 0.010 * c.caster_bonus_hp),
            damage_type=MAGICAL,
            every_n_seconds=1.0,
        ),),
        unique_passive_key="immolate",
        # R70 (2026-07-03): Desolate champion-takedown eruption - Meraki
        # 16.13.1: takedown within 3s of damaging a champion erupts for
        # 400% of Immolate (15*4 = 60 base + 1%*4 = 4% bonus health) magic
        # within 500 units. Burst-only via the default-OFF assume_takedown
        # seam; the Immolate periodic above is untouched.
        takedown_eruption_base=60.0,
        takedown_eruption_bonus_hp_ratio=0.04,
        note=(
            "Hollow Radiance: Immolate 15 + 1% bonus HP magic per second "
            "to nearby (Meraki 16.10.1). Desolate champion-takedown eruption "
            "modeled R70 on assume_takedown: 400% Immolate = 60 + 4% bonus "
            "HP magic within 500 (Meraki 16.13.1); the 200% non-champion "
            "kill eruption stays unmodeled (farm math, not fight math)"
        ),
    ),

    # -- Phase 4 batch 26 (2026-05-04): item-effect-contributed crit chance --
    # CallContext.crit_chance was added in batch 21 for Essence Reaver. This
    # batch adds the *production* path - items that themselves contribute to
    # the build's crit chance (Yun Tal at full Wildarrows stacks; Atma's
    # Big Hands scaling with caster bonus HP). Engine sums each effect's
    # contribution into the resolved crit at compute_dps time and clamps at
    # 1.0; auto-attack crit + ER spellblade scaling + future crit-readers
    # all see the boosted total. /stats output is unchanged - same
    # cross-derivation pattern as Riftmaker's HP->AP from batch 15.

    "3032": ItemEffect(
        item_id="3032",
        name="Yun Tal Wildarrows",
        # Practice Makes Lethal: gain crit on-attack permanently, capped at
        # 25%. Pinned at full stacks (the steady-state assumption - same
        # call as Black Cleaver's "30% reduction at 5 stacks sustained" and
        # Riftmaker's "8% at full ramp"). DDragon stat block carries 0%
        # base crit; Wildarrows is the entire crit story for this item.
        crit_chance_bonus_flat=0.25,
        # Flurry: on-attacking an enemy champion, +30% AS for 6s (30s CD;
        # attacks reduce CD by 1s, crits by 2s). Phase 4 batch 54
        # (2026-05-04): uptime model: at 1.3 attacks/s with 25% crit ->
        # CD drains 1.625s/s. Cycle = 6s active + 16.2s inactive = 22.2s;
        # uptime = 6/22.2 ~ 27%. Effective sustained AS = 0.30 x 0.27 ~ 0.08.
        bonus_as_conditional=0.08,
        note=(
            "Yun Tal Wildarrows: Practice Makes Lethal +25% crit (full stacks); "
            "Flurry +30% AS for 6s on-champion-attack (30s CD); "
            "sustained ~8% effective bonus AS (27% uptime model)"
        ),
    ),

    "3039": ItemEffect(
        item_id="3039",
        name="Atma's Reckoning",
        # Big Hands: 1% crit per 100 bonus HP, capped at 30% at 3000 bonus
        # HP (LoL wiki, V25.21 - Meraki bulk has the passive list null,
        # external source pinned 2026-05-04). Linear ramp; same shape as
        # batch 19's target_bonus_hp_amp (LDR Giant Slayer) on the caster
        # side. The 700 HP / 20% crit / 10 AH stat block lands via item
        # aggregation; Atma's stats alone don't reach the 3000 cap (700
        # bonus HP from Atma itself ~ 0.07 ramp = 7% Big Hands), so
        # multi-HP-item builds (Heartsteel, Titanic Hydra, Warmog's,
        # Sterak's HP) drive most of the contribution.
        crit_chance_bonus_max_pct=0.30,
        crit_chance_bonus_per_bonus_hp_cap=3000.0,
        note="Atma's Reckoning: Big Hands +1% crit per 100 bonus HP, max 30% at 3000 bonus HP",
    ),

    # -- Phase 4 batch 27 (2026-05-04): Manamune / Muramana family --
    # Mana-scaling damage. Awe (2% max mana -> bonus AD) is a stat layer
    # mirroring batch 20's Sterak's bonus_ad_pct_base_ad wiring; Shock
    # (Muramana only - 1.2% max mana per-attack physical) uses the
    # existing periodic schema with a new caster_max_mp CallContext field.
    # Manamune transforms into Muramana at +360 max-mana-stacks in real
    # League - engine doesn't model the transformation, so the two items
    # are independent ITEM_EFFECTS entries. Manaflow (the stacking
    # mana-on-attack mechanism that drives the transformation) is
    # intentionally not modeled; same call as Yun Tal's Practice Makes
    # Lethal stack-up - pin the steady-state assumption (the item's own
    # listed max-mana stat) and let build_champion handle the mana
    # block. Muramana's ability damage piece (3-4% max mana on damaging
    # abilities) stays not-modeled per the ability-bound rule.

    "3004": ItemEffect(
        item_id="3004",
        name="Manamune",
        # Awe: 2% max mana as bonus AD. Stat block: 35 AD / 500 mana / 15 AH
        # (DDragon 16.9.1, mirrors Meraki bulk passive text). The 500 mana
        # contribution lands via item aggregation; Awe converts the build's
        # total max mana (champion base + items + Manamune's own 500) into
        # +AD at engine resolution time.
        # Manaflow stack-up not modeled - caller's build represents either
        # "post-transformation Muramana" (use 3042) or "pre-transformation
        # Manamune" (use 3004), not the in-flight stacking state. Engine's
        # build is steady-state; Manaflow stays utility-adjacent.
        bonus_ad_pct_max_mp=0.02,
        note="Manamune: Awe +2% max mana as bonus AD (Manaflow stack-up not modeled - steady-state)",
    ),

    "3042": ItemEffect(
        item_id="3042",
        name="Muramana",
        # Awe: 2% max mana as bonus AD (same coefficient as Manamune).
        # Shock: 1.2% max mana bonus physical per-attack vs champions.
        # Engine has no champion-only target gate (same trade-off as
        # Kraken Slayer, Hullbreaker) - over-counts vs minion-only
        # rotations; noise band <DPS error of every other approximation.
        # Ability damage piece (3-4% max mana on damaging abilities)
        # stays not-modeled per the ability-bound rule (same as Liandry).
        # Stat block: 35 AD / 1000 mana / 15 AH (Muramana's mana pool is
        # 2x Manamune's - the entire point of the transformation in real
        # League). Awe + Shock both scale linearly with the larger mana
        # pool, so Muramana's DPS uplift on the same caster is roughly
        # 2x Manamune's at the same mana baseline.
        bonus_ad_pct_max_mp=0.02,
        periodics=(PeriodicProc(
            name="Shock",
            bonus_damage=lambda c: 0.012 * c.caster_max_mp,
            damage_type=PHYSICAL,
            every_n_attacks=1,
        ),),
        note=(
            "Muramana: Awe +2% max mana as bonus AD + Shock 1.2% max mana "
            "per-attack physical (champ-only gate not enforced; ability "
            "damage piece not modeled)"
        ),
    ),

    # -- Phase 4 batch 28 (2026-05-04): Archangel's Staff / Seraph's Embrace --
    # AP-side Awe twins of the Manamune family (batch 27). Same "Awe" name,
    # but different math - Archangel/Seraph's are keyed off BONUS mana
    # (item-contributed only), while Manamune/Muramana are keyed off MAX
    # mana (champion base + items). The new
    # ``bonus_ap_pct_bonus_mp`` field captures the AP-side variant; engine.py
    # walks it after the existing Awe-AD walk, targeting ap_flat instead of
    # ad_flat, sourced from ``item_totals.get("mp_flat", 0.0)`` (which is
    # the build's bonus mana sum). Manaflow stack-up + Archangel's
    # transformation into Seraph's at +360 max mana stacks intentionally
    # not modeled - same call as Manamune (steady-state assumption).

    "3003": ItemEffect(
        item_id="3003",
        name="Archangel's Staff",
        # Awe: 1% bonus mana as Ability Power. Stat block: 70 AP / 600 mana
        # / 25 AH (DDragon 16.9.1; Meraki passive text confirms 1% bonus
        # mana). Ezreal lvl 11 + Archangel: champion base mp ~ 1075 not
        # counted; bonus mana = 600 -> Awe AP = 0.01 * 600 = 6 AP. Stack
        # mana items to lift further (Manamune adds 500 bonus mana -> +5
        # AP from Archangel's Awe; Tear of the Goddess builds from this
        # baseline).
        bonus_ap_pct_bonus_mp=0.01,
        # No unique_passive_key - Archangel/Seraph's are one-of-two, but
        # build-legality (transformation gate prevents owning both) is
        # ranker-owned per the s81 pattern.
        note="Archangel's Staff: Awe +1% bonus mana as AP (Manaflow stack-up not modeled - steady-state)",
    ),

    "3040": ItemEffect(
        item_id="3040",
        name="Seraph's Embrace",
        # Awe: 2% bonus mana as AP (post-transformation form, double the
        # Archangel coefficient). Stat block: 70 AP / 1000 mana / 25 AH
        # - Seraph's adds 1000 bonus mana baseline, so its Awe alone
        # contributes 0.02 * 1000 = 20 AP from the item's own mana, lifting
        # further with each additional mana item in the build.
        # Lifeline shield (18% max mana generic shield at <30% HP, Meraki
        # 16.13.1) is non-DPS - it now feeds EHP via the default-off
        # ItemShield seam (assume_seraphs_shield); tagged
        # ``unique_passive_key="lifeline"`` so collect_effects dedups against
        # Shieldbow / Sterak's / Maw / Phantom Dancer (which uses Spectral
        # Waltz, NOT lifeline - see batch 12). The Awe walk lives in engine.py
        # and bypasses collect_effects, so the AP contribution survives any
        # lifeline dedup.
        bonus_ap_pct_bonus_mp=0.02,
        unique_passive_key="lifeline",
        shield=ItemShield(max_mana_scaling=0.18, damage_type=ANY, default_off=True),
        note=(
            "Seraph's Embrace: Awe +2% bonus mana as AP + Lifeline: 18% max "
            "mana generic shield at <30% HP (Meraki 16.13.1), default-off opt-in"
        ),
    ),
    # -- Phase 4 batch 29 (2026-05-04): coverage batch - defensive_only +
    # 2 partial promotions (Liandry's Suffering damage amp, Stormsurge
    # flat magic pen). Coverage-completeness; no new schema fields. The
    # 4 defensive_only entries surface "we considered this and decided
    # no DPS contribution applies" with one-line notes - same template
    # as the existing high-pickrate defensive_only entries from batches
    # 1-3. The 2 partial promotions reuse existing schema (damage_amp_pct
    # from batch 14, magic_pen_flat from batch 4).

    "6697": ItemEffect(
        item_id="6697",
        name="Hubris",
        # Phase 4 batch 30 (2026-05-04): promoted from defensive_only via
        # the lethality plumbing schema. 18 Lethality is now level-scaled
        # via effective_target_armor's level parameter.
        lethality=18.0,
        # DSV2 (1.125.0): Eminence is now valued by the takedown / kill-state
        # OFFENSE seam (compute_dps / compute_burst_damage assume_takedown).
        # Meraki 16.12.1: "Scoring a takedown ... generates a permanent stack
        # and grants you 15 (+2 per stack) bonus attack damage for 90 seconds".
        takedown_bonus_ad_base=15.0,
        takedown_bonus_ad_per_stack=2.0,
        note=(
            "Hubris: 18 Lethality (level-scaled flat pen) + Eminence "
            "takedown bonus AD 15 (+2/stack), 90s - valued under assume_takedown"
        ),
    ),

    "3065": ItemEffect(
        item_id="3065",
        name="Spirit Visage",
        # 400 HP + 50 MR + 10 AH + 100% base regen. Boundless Vitality
        # (heal/shield amp 25%) is non-DPS - engine doesn't model healing
        # output. Pure defensive.
        defensive_only=True,
        # ENGINE 1.28.0 (2026-05-21): Phase 6 healing throughput - "Boundless
        # Vitality" +25% self-heal/regen amp. Applied multiplicatively in
        # ``compute_ehp`` via _total_heal_amp() to the heal pool ONLY (item-
        # passive heals + lifesteal-derived heal). Phase 1.5 shield pipeline
        # (Sterak/Shieldbow/Maw/Hexdrinker/BT) is NOT amped in this engine -
        # see _effects_types.py ItemEffect.heal_amp_pct docstring for the
        # deferred-to-Phase-6.5 boundary rationale.
        heal_amp_pct=0.25,
        note=(
            "Spirit Visage: Boundless Vitality (heal/shield +25%; engine "
            "amps heal pool only, Phase 1.5 shields deferred to 6.5)"
        ),
    ),

    "2504": ItemEffect(
        item_id="2504",
        name="Kaenic Rookern",
        # 400 HP + 80 MR + 100% regen. Magebane: gain magic shield after
        # 15s of not taking magic damage. Pure defensive - no DPS path.
        defensive_only=True,
        # R92 (2026-07-10): Magebane magic shield = 15% of TOTAL max HP (Meraki
        # 16.13.1). Credited via the default-OFF assume_kaenic_shield seam
        # (default_off=True) - the "no magic damage for 15s" uptime is
        # anti-correlated with magic fights, unlike the always-on lifelines
        # (Sterak/Maw/Shieldbow), so this credit is conservatively opt-in.
        shield=ItemShield(
            damage_type=MAGICAL,
            max_hp_scaling=0.15,
            default_off=True,
            note="Kaenic Rookern Magebane 15% max HP magic shield (Meraki 16.13.1)",
        ),
        note="Kaenic Rookern: Magebane (low-MR-uptime magic shield); no DPS contribution",
    ),

    "6653": ItemEffect(
        item_id="6653",
        name="Liandry's Torment",
        # 60 AP + 300 HP stat block. Two passives:
        # - Torment: ability damage burns the target for 6% of its MAXIMUM
        #   health total magic damage over 3 seconds (16.12.1 Meraki champ
        #   value; vs monsters 1%/0.5s capped 20/tick). DSV1 (P6-G5 residual
        #   1): modeled as the sustained periodic burn it is - 2% max HP / s -
        #   the exact sibling of Demonic Embrace's Azakana's Gaze (1%/s, 4637)
        #   under the "always-active convention" (ability-triggered burn kept
        #   up across the fight). The prior "ability-bound, not modeled" rule
        #   was inconsistent with Azakana / Blackfire, which already modeled
        #   the identical ability-triggered burn as sustained.
        # - Suffering: 2% bonus damage per second in combat, max 3
        #   stacks = 6%. Generic damage amp, not ability-restricted -
        #   applies to autos + procs same as Riftmaker's Void Corruption
        #   (batch 14). Steady-state DPS pin = 6% (full ramp after 3s
        #   in combat). Promoted via the existing damage_amp_pct schema.
        damage_amp_pct=0.06,
        periodics=(
            PeriodicProc(
                name="Torment",
                every_n_seconds=1.0,
                bonus_damage=lambda c: 0.02 * c.target_max_hp,
                damage_type=MAGICAL,
                ability_dot=True,
            ),
        ),
        note=(
            "Liandry's Torment: Suffering ~6% damage amp at full ramp "
            "(3s in champ combat; sustained-DPS approximation) + Torment "
            "2% target max HP/s magic burn (6% over 3s; ability-trigger "
            "modeled sustained per the always-active convention, sibling "
            "of Azakana's Gaze)"
        ),
    ),

    "4629": ItemEffect(
        item_id="4629",
        name="Cosmic Drive",
        # 70 AP + 350 HP + 25 AH + 4% MS stat block. Spelldance: 20 bonus
        # MS for 4s on dealing magic/true damage to champions. Pure
        # utility (movement speed); no DPS contribution.
        defensive_only=True,
        note="Cosmic Drive: Spelldance (MS bonus on magic/true damage); no DPS contribution",
    ),

    "4646": ItemEffect(
        item_id="4646",
        name="Stormsurge",
        # 90 AP + 15 flat magic pen + 6% MS. Squall (125 + 10% AP magic)
        # fires 2s after Stormraider triggers. Modeled via every_n_seconds=30
        # (the passive recharge CD), same sustained-DPS doctrine as Luden's
        # (12s) and Night Harvester (10s). Phase 4 batch 53 (2026-05-04).
        magic_pen_flat=15.0,
        periodics=(PeriodicProc(
            name="Squall",
            bonus_damage=lambda c: 125.0 + 0.10 * c.ap,
            damage_type=MAGICAL,
            every_n_seconds=30.0,
        ),),
        # DSV6 (1.152.0): single-Squall burst-window magnitude for the on-cast
        # magic-burst seam. Same Meraki 125 (+10% AP) as the periodic; credited
        # once per burst combo by compute_burst_damage (the periodic owns the
        # sustained-DPS valuation, no double-count).
        magic_burst_base=125.0,
        magic_burst_ap_ratio=0.10,
        note=(
            "Stormsurge: 15 flat magic pen + Squall 125 (+10% AP) magic / 30s "
            "(Stormraider gate modeled at minimum-CD sustained rate; Meraki confirmed)"
        ),
    ),

    # -- Phase 4 batch 30 (2026-05-04): lethality plumbing - new entries --
    # Axiom Arc and Umbral Glaive were unmodeled prior; now land via the
    # lethality schema alongside the 5 in-place updates above (Hubris,
    # Voltaic, Edge of Night, Youmuu's, Opportunity). All 7 lethality items
    # in current League now carry the level-scaled flat pen contribution.

    "6696": ItemEffect(
        item_id="6696",
        name="Axiom Arc",
        # 55 AD + 18 Lethality + 20 AH stat block (lethality in description,
        # NOT in DDragon's stats keys). Flux passive: takedown within 3s of
        # damage refunds Ultimate Ability cooldown. Pure utility (CDR is
        # not modeled; no DPS proc). Defensive_only=False because the 18
        # Lethality alone is real DPS contribution.
        lethality=18.0,
        note=(
            "Axiom Arc: 18 Lethality (level-scaled flat pen) + Flux ult-CDR "
            "on takedown (utility, not modeled)"
        ),
    ),

    "3179": ItemEffect(
        item_id="3179",
        name="Umbral Glaive",
        # 60 AD + 18 Lethality + 15 AH stat block. Two passives:
        # - Nightstalker: after-stealth next attack vs champion deals
        #   bonus true damage. Stealth-conditional + after-event - same
        #   "ability-bound burst" rule that defers Stormsurge's Squall.
        # - Blackout: reveal stealth wards / bonus damage to wards. Pure
        #   utility / target-type-restricted (engine targets champions).
        # Lethality alone is the modeled DPS piece.
        lethality=18.0,
        note=(
            "Umbral Glaive: 18 Lethality (level-scaled flat pen) + "
            "Nightstalker after-stealth true damage (conditional, not "
            "modeled) + Blackout ward damage (utility, not modeled)"
        ),
    ),


    # -- Phase 4 batch 31 (2026-05-04): support / ramp item coverage sweep --
    # 21 items. 2 partial promotions (Dead Man's Plate Shipwrecker physical proc;
    # Spectral Cutlass ARAM-only lethality - same schema as batch 30). 19
    # defensive_only entries: support-role items, sustain amplifiers, conditional-
    # or-ability-bound passives that don't fit the basic-auto DPS model.
    # Defensive_only count: 21 -> 40.

    # --- Dead Man's Plate - Shipwrecker stack-ramp discharge (ENGINE 1.26.0) ---
    # 350 HP + 55 armor + 4% MS stat block. Two passives:
    # - Shipwrecker (REWORKED): while moving, build Momentum stacks
    #   (7/0.25s = 28/s, cap 100 stacks in ~3.57s; grants up to 20 bonus
    #   MS). Basic attacks consume all stacks to deal:
    #     0.4 * stacks (capped at 40 flat) + stacks% (capped at 100%) of
    #     base AD bonus physical damage.
    #   Meraki 16.10.1 spec is a DUAL-TRACK formula: stack-scaled flat
    #   damage PLUS stack-scaled %-base-AD modifier.
    # - Unsinkable: 15% slow resistance - utility.
    #
    # ENGINE 1.26.0 (2026-05-21) - closes the iter-16 (2026-05-20) deferral
    # via the new ``PeriodicProc.stack_ramp_seconds`` schema lift. Sustained
    # model: Momentum ramps to 100 stacks in ~3.57s of movement; the next
    # basic attack consumes all stacks for a full-stack discharge; ramp
    # restarts. In sustained combat the discharge fires once per
    # ``max(stack_ramp_seconds=3.57, attack_period_s)`` interval - the
    # _periodic_proc_dps consumer enforces this gate. Full-stack discharge
    # damage = ``0.4 * 100 (cap 40) + 1.0 * base_ad = 40 + base_ad``
    # (PHYSICAL, since Meraki spec says "physical damage"). The burst path
    # (``_per_attack_proc_damage``) intentionally skips stack-ramp-gated
    # procs (3.57s ramp vs 2-3s burst window; this is a tank item with
    # incidental DPS - the sustained model is what matters). Other items
    # that would benefit from the same schema in future iterations: any
    # build-up -> discharge passive that ramps over seconds of movement
    # or in-combat state without per-tick stack tracking (e.g. Sterak's
    # Lifeline once an EHP-vs-CC sim lands, hypothetical future ramp
    # items). The ``every_n_attacks=1`` keeps the model honest: each
    # attack discharges WHATEVER stacks have accumulated; the ramp gate
    # ensures sustained model fires at most once per ramp interval.
    "3742": ItemEffect(
        item_id="3742",
        name="Dead Man's Plate",
        periodics=(
            PeriodicProc(
                name="Shipwrecker",
                bonus_damage=lambda c: 40.0 + c.base_ad,
                damage_type=PHYSICAL,
                every_n_attacks=1,
                stack_ramp_seconds=3.57,
            ),
        ),
        note=(
            "Dead Man's Plate: Shipwrecker full-stack discharge 40 + "
            "base_ad physical on first attack post-ramp; stack_ramp=3.57s "
            "(ENGINE 1.26.0 stack-ramp schema)"
        ),
    ),

    # --- Spectral Cutlass - ARAM-only lethality promotion -------------------
    # 50 AD + 15 Lethality + 4% MS stat block (ARAM-only, map 12 only).
    # Soul Anchor active (0s listed CD in DDragon): marks current location;
    # returns you there after 4s or on recast. Pure repositioning utility -
    # not modeled (same rule as all other utility actives in this batch).
    # Lethality modeled via the batch-30 level-scaled schema (same 15 Lethality
    # coefficient as Edge of Night). Item available on map 12 (ARAM) only;
    # aram_coach's resolver uses mode='aram' and DDragon map 12 index.
    "4004": ItemEffect(
        item_id="4004",
        name="Spectral Cutlass",
        lethality=15.0,
        note=(
            "Spectral Cutlass: 15 Lethality (level-scaled flat pen, ARAM-only) "
            "+ Soul Anchor repositioning active (utility, not modeled)"
        ),
    ),

    # --- Support / enchanter items - defensive_only --------------------------
    # All entries below have effects that are non-DPS (ally healing/shielding
    # triggers, ally-proc-bound damage, enemy-on-champion-only burst gated by
    # ability casts, MS/AS conditional on ally link, etc.). No direct
    # basic-auto DPS contribution from any passive here.

    "3109": ItemEffect(
        item_id="3109",
        name="Knight's Vow",
        defensive_only=True,
        note="Knight's Vow: Worthy tether (damage redirect + ally tankiness); no DPS contribution",
    ),
    "3222": ItemEffect(
        item_id="3222",
        name="Mikael's Blessing",
        defensive_only=True,
        note="Mikael's Blessing: active CC cleanse + heal; no DPS contribution",
    ),
    "3107": ItemEffect(
        item_id="3107",
        name="Redemption",
        defensive_only=True,
        # Active calls a heal beam after 2.5s - the healing dominates the
        # use-case; the incidental magic damage to enemies is negligible
        # (10% target max HP, CD null in Meraki, per-heal-not-per-auto).
        note="Redemption: active AoE heal beam (incidental enemy damage; ability-bound); no sustained DPS contribution",
    ),
    "3190": ItemEffect(
        item_id="3190",
        name="Locket of the Iron Solari",
        defensive_only=True,
        note="Locket of the Iron Solari: active AoE shield; no DPS contribution",
    ),
    "3504": ItemEffect(
        item_id="3504",
        name="Ardent Censer",
        defensive_only=True,
        # Healer-triggered AS/on-hit buff to allies. Caster's own AS +
        # on-hit magic buff applies only after healing/shielding an ally -
        # not a sustained per-auto DPS proc.
        note="Ardent Censer: Sanctified (heal/shield triggers AS + on-hit AP buff); no standalone DPS contribution",
    ),
    "6616": ItemEffect(
        item_id="6616",
        name="Staff of Flowing Water",
        defensive_only=True,
        note="Staff of Flowing Water: heal/shield grants Rapids (AP + AH) to allies; no DPS contribution",
    ),
    "6620": ItemEffect(
        item_id="6620",
        name="Echoes of Helia",
        defensive_only=True,
        # Soul Siphon: damage dealt generates Soul Charges used for target
        # healing pulses. Converts DPS into sustain - not a damage amplifier.
        note="Echoes of Helia: Soul Siphon (damage -> Soul Charges -> heal pulses); no DPS contribution",
    ),
    "6617": ItemEffect(
        item_id="6617",
        name="Moonstone Renewer",
        defensive_only=True,
        note="Moonstone Renewer: Starlit Grace (heal chains to nearby allies in combat); no DPS contribution",
    ),
    "6621": ItemEffect(
        item_id="6621",
        name="Dawncore",
        defensive_only=True,
        note="Dawncore: support scaling (AP scales with heal/shield power); no DPS contribution",
    ),
    "4005": ItemEffect(
        item_id="4005",
        name="Imperial Mandate",
        defensive_only=True,
        # Coordinated Fire: ability-CC marks target; ALLIED champion attack
        # on marked target deals bonus damage. Requires ally proc - not a
        # self-basic-auto DPS contribution.
        note="Imperial Mandate: Coordinated Fire (ally proc on CC'd target); no solo DPS contribution",
    ),
    "6657": ItemEffect(
        item_id="6657",
        name="Rod of Ages",
        defensive_only=True,
        # Eternity converts damage taken -> mana; mana used -> HP. Stacked
        # passive HP/MP/AP ramping (30 stacks over 6 min). Sustain and
        # scaling, not a DPS proc.
        note="Rod of Ages: Eternity (damage->mana, mana->HP sustain ramp); no DPS contribution",
    ),
    "3119": ItemEffect(
        item_id="3119",
        name="Winter's Approach",
        defensive_only=True,
        # 400 HP + 500 mana + 15 AH. Awe (same name as Manamune family):
        # gain HP = 8% of max mana. HP-conversion, not AD or AP.
        # Same transformation mechanic as the Manamune family (transforms
        # into Fimbulwinter at +700 stacked mana); stays defensive_only
        # because the HP contribution doesn't affect DPS.
        note="Winter's Approach: Awe (8% max mana as bonus HP); no DPS contribution",
    ),
    "3121": ItemEffect(
        item_id="3121",
        name="Fimbulwinter",
        defensive_only=True,
        # 400 HP + 1000 mana + 15 AH. Post-transformation form of Winter's
        # Approach. Awe (8% max mana as HP) is credited separately by the
        # _item_mana_health seam. Everlasting (Meraki 16.13.1): immobilizing (or
        # slowing, if melee) an enemy champion grants a 100 (+4.5% current mana)
        # GENERIC shield for 3s (8s CD). A per-fight-cooldown utility shield, so
        # opt-in + live-gated (assume_fimbulwinter_shield), NOT the always-on
        # lifeline pool - hence no unique_passive_key="lifeline" (it is an
        # independent shield that stacks with a lifeline). "current mana" is
        # resolved against MAX mana (steady-state convention; the trigger fires
        # while mana is typically high). The +80% multi-enemy arm is NOT modelled
        # (conservative base magnitude).
        shield=ItemShield(
            flat=100.0, max_mana_scaling=0.045, damage_type=ANY, default_off=True
        ),
        note="Fimbulwinter: Awe (8% max mana as HP, separate seam) + Everlasting (100 +4.5% max mana generic shield, opt-in); no DPS contribution",
    ),
    "4401": ItemEffect(
        item_id="4401",
        name="Force of Nature",
        defensive_only=True,
        # Steadfast: taking magic damage generates stacks (up to 8, +6 MR
        # each). Resistor: 30 bonus MR at 8 stacks. Pure defensive stacking.
        note="Force of Nature: Steadfast (MR stacks on magic-damage-taken); no DPS contribution",
    ),
    "3116": ItemEffect(
        item_id="3116",
        name="Rylai's Crystal Scepter",
        defensive_only=True,
        # Rimefrost: ability damage slows by 30% for 1s. CC utility -
        # not a damage proc (same rule as Stridebreaker's Halting Slash,
        # Serylda's Bitter Cold).
        note="Rylai's Crystal Scepter: Rimefrost (ability damage slow); no DPS contribution",
    ),
    "6665": ItemEffect(
        item_id="6665",
        name="Jak'Sho, The Protean",
        defensive_only=True,
        # Voidborn Resilience: gain stacks in combat each second, each granting
        # 2 armor + 2 MR (up to 8 stacks = 16 armor + 16 MR). Pure defensive.
        note="Jak'Sho, The Protean: Voidborn Resilience (stacking resists in combat); no DPS contribution",
    ),
    "3152": ItemEffect(
        item_id="3152",
        name="Hextech Rocketbelt",
        defensive_only=True,
        # R69 (1.176.0): Supersonic one-cast burst rides the DSV6
        # assume_magic_burst seam. Meraki 16.13.1: dash + rocket arc deals
        # "100 (+ 10% AP) magic damage ... once per cast" - a one-cast
        # magnitude, exactly what the burst-window seam credits. The DPS
        # side stays intentionally unmodeled: long-CD active, no
        # PeriodicProc, so no double-count anywhere. defensive_only stays
        # True - the flag documents "no sustained-DPS proc", which still
        # holds; it gates nothing in the engine.
        magic_burst_base=100.0,
        magic_burst_ap_ratio=0.10,
        note=(
            "Hextech Rocketbelt: Supersonic active 100 (+10% AP) magic once "
            "per cast - one-cast burst-window magnitude rides the DSV6 "
            "assume_magic_burst seam; DPS side intentionally unmodeled "
            "(long-CD active, no PeriodicProc, no double-count)"
        ),
    ),
    "3073": ItemEffect(
        item_id="3073",
        name="Experimental Hexplate",
        defensive_only=True,
        # Overdrive: ult cast triggers 50% bonus AS + 20% bonus MS for 8s
        # (30s CD). Conditional on ult usage - ability-cast schema blocker,
        # same rule as Spear of Shojin (batch 16). 30 ult haste is stat-side
        # only.
        note="Experimental Hexplate: Overdrive (ult-cast-triggered AS + MS burst); ability-cast schema blocker; no sustained DPS contribution",
    ),
    "8020": ItemEffect(
        item_id="8020",
        name="Abyssal Mask",
        magic_amp_pct=0.12,
        note=(
            "Abyssal Mask: Unmake 12% more magic damage taken by nearby enemies "
            "(700-unit aura; sustained-DPS assumption = always active; "
            "applies to magical proc DPS only via magic_amp_pct schema)"
        ),
    ),

    # -- Phase 4 batch 32 (2026-05-04): AP amplification + lethality + new schema --
    # 7 active promotions (2 new schema fields + 5 reuse existing):
    # Rabadon's Deathcap (ap_amp_pct=0.30), Dusk and Dawn (spellblade),
    # The Collector + Prowler's Claw + Bastionbreaker (lethality),
    # Overlord's Bloodmail (bonus_ad_pct_bonus_hp), Demonic Embrace
    # (ap_per_bonus_hp_pct). 8 defensive_only entries.

    "3089": ItemEffect(
        item_id="3089",
        name="Rabadon's Deathcap",
        ap_amp_pct=0.30,
        note=(
            "Rabadon's Deathcap: Magical Opus +30% total AP (multiplicative; "
            "amplifies all AP-scaling procs and pen formulas via CallContext.ap)"
        ),
    ),
    "2510": ItemEffect(
        item_id="2510",
        name="Dusk and Dawn",
        periodics=(PeriodicProc(
            name="Spellblade",
            bonus_damage=lambda c: 0.75 * c.base_ad + 0.10 * c.ap,
            damage_type=MAGICAL,
            every_n_seconds=1.5,
        ),),
        unique_passive_key="spellblade",
        note=(
            "Dusk and Dawn: Spellblade 75% base AD + 10% AP bonus magic "
            "damage every ~1.5s; joins Trinity Force / Lich Bane / ER / "
            "Iceborn Gauntlet spellblade dedup family; on-hit echo not modeled"
        ),
    ),
    "667666": ItemEffect(
        item_id="667666",
        name="The Collector",
        lethality=10.0,
        # DSV2 (1.125.0): Death execute valued by the kill-state finisher seam.
        execute_max_hp_pct=0.05,
        note=(
            "The Collector: 10 Lethality (level-scaled flat pen). "
            "Death execute (<5% HP) valued as a kill-state finisher under assume_takedown"
        ),
    ),
    "6693": ItemEffect(
        item_id="6693",
        name="Prowler's Claw",
        lethality=22.0,
        note=(
            "Prowler's Claw: 22 Lethality (level-scaled flat pen). "
            "Ambush Predator active is utility, not modeled"
        ),
    ),
    "2520": ItemEffect(
        item_id="2520",
        name="Bastionbreaker",
        # Phase 4 batch 59 (2026-05-04): promoted. Meraki confirms Shaped Charge:
        # 45s CD - "your next ability hit deals 15 (+ 0.75 per lethality) bonus
        # true damage" (ranged values; melee = 30 + 1.5/leth). Item CD = 45s is
        # the binding rate constraint (same CD-as-timer approach as HG active 40s).
        # Sabotage (takedown-conditional turret bonus) is utility-only.
        lethality=22.0,
        periodics=(PeriodicProc(
            name="Shaped Charge",
            bonus_damage=lambda c: 15.0 + 0.75 * c.caster_lethality,
            damage_type=TRUE,
            every_n_seconds=45.0,
        ),),
        note=(
            "Bastionbreaker: 22 Lethality + Shaped Charge 15 + 0.75 x lethality "
            "true damage every 45s (Meraki CD; ranged values; Sabotage takedown utility-only)"
        ),
    ),
    "2501": ItemEffect(
        item_id="2501",
        name="Overlord's Bloodmail",
        bonus_ad_pct_bonus_hp=0.025,
        missing_hp_ad_amp_max_pct=0.12,
        note=(
            "Overlord's Bloodmail: Tyranny 2.5% bonus HP as bonus AD "
            "(engine resolves at stat-build time via item_totals[hp_flat]). "
            "Retribution missing-HP-scaled AD (0-12% of total AD, ramping to 70% "
            "missing HP) modeled behind the R111 assume_caster_lowhp offense seam"
        ),
    ),
    "4637": ItemEffect(
        item_id="4637",
        name="Demonic Embrace",
        ap_per_bonus_hp_pct=0.02,
        periodics=(
            PeriodicProc(
                name="Azakana's Gaze",
                every_n_seconds=1.0,
                bonus_damage=lambda c: 0.01 * c.target_max_hp,
                damage_type=MAGICAL,
                ability_dot=True,
            ),
        ),
        note=(
            "Demonic Embrace: Dark Pact 2% bonus HP as AP (stat walk). "
            "Azakana's Gaze: 1% target max HP/s magic burn (ranged value; "
            "melee is 2%/s - conservative under sustained-DPS assumption; "
            "ability-trigger modeled as sustained per the always-active convention)"
        ),
    ),
    # -- defensive_only (8) --
    "3165": ItemEffect(
        item_id="3165",
        name="Morellonomicon",
        defensive_only=True,
        note="Morellonomicon: Grievous Wounds (anti-heal utility); no DPS contribution",
    ),
    "4628": ItemEffect(
        item_id="4628",
        name="Horizon Focus",
        defensive_only=True,
        note=(
            "Horizon Focus: Hypershot reveals ability-hit targets at 600+ range and Focus "
            "reveals nearby enemies (DDragon 16.13.1); the legacy damage amp was reworked "
            "out - pure vision/utility, no DPS contribution exists to model (R116)"
        ),
    ),
    "3118": ItemEffect(
        item_id="3118",
        name="Malignance",
        periodics=(
            PeriodicProc(
                name="Hatefog",
                # Zone under target deals (60+5%AP)/0.25s for 3s = 180+15%AP total per ult hit.
                # every_n_seconds=1.0 is a normalization anchor; multiplying by ult_casts_per_sec
                # makes this champion-aware without changing the PeriodicProc schema.
                bonus_damage=lambda c: (180.0 + 0.15 * c.ap) * c.ult_casts_per_sec,
                damage_type=MAGICAL,
                every_n_seconds=1.0,
            ),
        ),
        # DSV6 (1.152.0): one-ult-zone burst-window magnitude (180 + 15% AP) for
        # the on-cast magic-burst seam - NO ult_casts_per_sec rate factor (that
        # is the sustained-DPS rate concept the periodic owns). Credited once per
        # burst combo by compute_burst_damage; no double-count with the periodic.
        magic_burst_base=180.0,
        magic_burst_ap_ratio=0.15,
        note="Malignance Hatefog: (180+15%AP) magic per ult zone hit; rate from rewind_history spell4_casts",
    ),
    "2503": ItemEffect(
        item_id="2503",
        name="Blackfire Torch",
        periodics=(
            PeriodicProc(
                name="Baleful Blaze",
                every_n_seconds=0.5,
                # DSV1 Meraki re-pin (16.12.1): Baleful Blaze deals 60 (+6% AP)
                # magic TOTAL over 3 seconds across 6 ticks (every 0.5s) =
                # 10 (+1% AP) per tick. The prior 6 (+6% AP)/tick mis-read the
                # wiki {{ap|60/6}} tick-count (60 total / 6 ticks) as a
                # melee/ranged split, over-scaling AP 6x at the per-tick level.
                bonus_damage=lambda c: 10.0 + 0.01 * c.ap,
                damage_type=MAGICAL,
                ability_dot=True,
            ),
        ),
        note=(
            "Blackfire Torch: Baleful Blaze 10 + 1% AP magic damage every 0.5s "
            "(60 + 6% AP total over 3s / 6 ticks per 16.12.1 Meraki; "
            "ability-trigger modeled as sustained per the always-active convention; "
            "Blackfire AP stacking ramp utility-only)"
        ),
    ),
    "2517": ItemEffect(
        item_id="2517",
        name="Endless Hunger",
        defensive_only=True,
        note=(
            "Endless Hunger: Famine (bonus AD ability haste scaling) and "
            "Feast (takedown omnivamp) are utility; no DPS contribution"
        ),
    ),
    "6609": ItemEffect(
        item_id="6609",
        name="Chempunk Chainsword",
        defensive_only=True,
        note="Chempunk Chainsword: Hackshorn (Grievous Wounds from physical damage); no DPS contribution",
    ),
    "2523": ItemEffect(
        item_id="2523",
        name="Hexoptics C44",
        defensive_only=True,
        note=(
            "Hexoptics C44: Magnification up to 10% increased attack damage at 600 range "
            "(range-conditional, fight distance unknown); Arcane Aim takedown bonus is utility"
        ),
    ),
    "8010": ItemEffect(
        item_id="8010",
        name="Bloodletter's Curse",
        # Phase 4 batch 52 (2026-05-04): promoted. Meraki confirms: "Each stack
        # inflicts 7.5% magic resistance reduction, stacking up to 4 times -> 30%
        # MR reduction at full stacks." Same mechanism as Arena version 4010
        # (both are MR reduction, not magic penetration - note was wrong on "40%
        # magic pen"). Sustained-DPS pins full stacks (4 ability applications;
        # same doctrine as Black Cleaver's 30% at 5 stacks). Ability-triggered
        # application is the only difference vs Arena version which is any-hit.
        mr_reduction_pct=0.30,
        note=(
            "Bloodletter's Curse (SR 8010): Vile Decay 7.5% MR reduction x 4 "
            "ability-hit stacks = 30% at full stacks (same as Arena 4010; Meraki confirmed)"
        ),
    ),
    # -- Phase 4 batch 33 (2026-05-04): ability-burn promos + dual-pen + caster-HP burn --
    # Gambler's Blade (667101): 15 lethality + 15 magic pen flat (dual-pen item).
    # Adaptive Force (55) has a DDragon stats-block gap - not carried as AD or AP in
    # aggregate_item_stats. Contribution modeled via pen only.
    "667101": ItemEffect(
        item_id="667101",
        name="Gambler's Blade",
        lethality=15.0,
        magic_pen_flat=15.0,
        note=(
            "Gambler's Blade: 15 lethality + 15 magic pen flat (dual-pen). "
            "Adaptive Force 55 has DDragon stats-block gap - not in aggregate_item_stats; "
            "pen contribution only"
        ),
    ),
    # Unending Despair (2502): Anguish - 3% caster bonus HP magic damage every 4s.
    # Meraki: 3% bonus HP to self and nearest ally as magic. Using self-damage value only
    # (the ally component is utility). Caster-bonus-HP-scaled proc via caster_bonus_hp.
    "2502": ItemEffect(
        item_id="2502",
        name="Unending Despair",
        periodics=(
            PeriodicProc(
                name="Anguish",
                every_n_seconds=4.0,
                bonus_damage=lambda c: 0.03 * c.caster_bonus_hp,
                damage_type=MAGICAL,
            ),
        ),
        note=(
            "Unending Despair: Anguish 3% caster bonus HP magic damage every 4s "
            "(proc AoE to all enemy champions within 650u; the SELF-heal half is "
            "250% of the post-mitigation damage per champion hit - modeled in "
            "_item_proc_heal.py behind DEFAULT-OFF assume_item_proc_heal, NOT utility; "
            "caster_bonus_hp = item_totals[hp_flat] proxy same as Titanic/Heartsteel)"
        ),
    ),
    # -- defensive_only (7) --
    "4636": ItemEffect(
        item_id="4636",
        name="Night Harvester",
        # Phase 4 batch 52 (2026-05-04): promoted. SR DDragon strips the value
        # but Arena Meraki (444636) confirms: "125 (+ 15% AP) bonus magic damage,
        # 10s CD per champion." Used for SR, ARAM, and Arena SR-mirrors since
        # all Night Harvester variants share the Soulrend passive with the same
        # numbers. "Per champion" CD -> model as every_n_seconds=10 (worst-case:
        # single-target fight at this cadence; multi-target fights proc more often
        # but every_n_seconds is the minimum floor for any one target).
        periodics=(PeriodicProc(
            name="Soulrend",
            bonus_damage=lambda c: 125.0 + 0.15 * c.ap,
            damage_type=MAGICAL,
            every_n_seconds=10.0,
        ),),
        note="Night Harvester: Soulrend 125 (+15% AP) magic / 10s per champion (Meraki 444636 ref)",
    ),
    # Fiendhunter Bolts (2512): Opening Barrage CD=45s (Meraki confirmed).
    # After ult: next 3 attacks in 8s gain guaranteed crit bonus (60-80% total AD);
    # using 70% of total_AD as midpoint. Base AD from auto DPS already in rotation;
    # this models the additional crit bonus damage per proc window.
    "2512": ItemEffect(
        item_id="2512",
        name="Fiendhunter Bolts",
        unique_passive_key="fiendhunter_barrage",
        periodics=(PeriodicProc(
            name="Opening Barrage",
            damage_type=PHYSICAL,
            every_n_seconds=45.0,
            bonus_damage=lambda c: 3.0 * (c.base_ad + c.bonus_ad) * 0.70,
        ),),
        note="Fiendhunter Bolts: Opening Barrage 45s CD; 3 guaranteed crits = 3x(base_ad+bonus_ad)x0.70 physical/45s",
    ),
    "663060": ItemEffect(
        item_id="663060",
        name="Sword of the Divine",
        # R170 (2026-07-24) crit-sweep note refresh (NO math change): Sword of
        # the Divine is an ARENA-ONLY prismatic (Meraki lists it solely as
        # 443060; there is no 4-digit SR shop id - 3131 is inert/no-map). DDragon
        # 16.14.1 mislabels this 66xxxx alias maps["11"]=True, so it survives the
        # SR map-filter + alias dedup as the only same-name SR id. It stays
        # defensive_only so it does NOT pollute SR offensive beam/rank builds
        # (promoting its Excoriate crit-damage would surface a non-SR item on the
        # Rift AND KeyError the Meraki gold cross-check, which has no 663060 row).
        # The item's real offensive value IS credited on its Arena twin 443060
        # (crit_damage_bonus=0.25, EV of Excoriate's uniform 0-50%). The old
        # "Pact of the Blade" text described a removed item version; DDragon's
        # current 663060 line is the same Excoriate as 443060. Excluding the
        # broader 66xxxx Arena-orphan idspace from the SR pool is a separate
        # build-pool concern (see docs Findings log), NOT a crit-magnitude fix.
        defensive_only=True,
        note=(
            "Sword of the Divine (Arena-only; DDragon 66xxxx map11 quirk-alias): "
            "kept defensive_only to exclude from SR offensive builds. Real "
            "offensive value (Excoriate +25% crit damage EV) is modeled on the "
            "Arena twin 443060"
        ),
    ),
    "667112": ItemEffect(
        item_id="667112",
        name="Flesheater",
        # Phase 4 batch 50 (2026-05-04): promoted via armor_reduction_flat +
        # mr_reduction_flat. "Hack the Meat": dealing damage shreds 3 Armor and
        # MR for 5s, stacking up to 10 times. Sustained-DPS pins full stacks
        # (same doctrine as BC's armor_reduction_pct). 1s CD per-ability stack
        # application is not modeled - pins optimistically at full 10 stacks.
        # Adaptive Force DDragon gap: stats block omits the 55 AF; stat
        # aggregation is DDragon-driven so engine sees 0 physical/magic - fine
        # for DPS model since AF is a conditional-class stat anyway.
        armor_reduction_flat=30.0,
        mr_reduction_flat=30.0,
        note=(
            "Flesheater: Hack the Meat 30 flat armor+MR shred at 10 stacks "
            "(sustained-DPS approx); Cannibalize on-kill heal utility-only"
        ),
    ),
    "664011": ItemEffect(
        item_id="664011",
        name="Sword of Blossoming Dawn",
        defensive_only=True,
        note=(
            "Sword of Blossoming Dawn: Bloom passive is heal/shield (utility); "
            "no DPS contribution"
        ),
    ),
    "2522": ItemEffect(
        item_id="2522",
        name="Actualizer",
        defensive_only=True,
        note=(
            "Actualizer: Actualize damage amp requires ally within 1000 range "
            "(ally-proximity conditional not modelable without fight geometry)"
        ),
    ),
    # Phase 4 batch 62 (2026-05-04): Cruelty SR (667109) - promoted. Same Watch Them
    # Fall passive as Arena variant 447109: comet on CC, 6s CD, 50->150+40%AP+4%maxHP.
    # Meraki only has the Arena entry; DDragon description confirms identical passive.
    "667109": ItemEffect(
        item_id="667109",
        name="Cruelty",
        periodics=(PeriodicProc(
            name="Watch Them Fall",
            bonus_damage=lambda c: c.targets_in_rotation * (
                50.0 + (100.0 / 17.0) * (c.level - 1)
                + 0.40 * c.ap
                + 0.04 * c.caster_max_hp
            ),
            damage_type=MAGICAL,
            every_n_seconds=6.0,
        ),),
        note=(
            "Cruelty (SR 667109): Watch Them Fall - comet on immobilize/ground, "
            "50->150 + 40% AP + 4% caster max HP magic, 6s CD (Meraki 447109 confirms "
            "identical passive; DDragon 667109 description matches). "
            "CC-triggered; 6s CD is the binding constraint."
        ),
    ),
    # -- Phase 4 batch 35 (2026-05-04): missed-lethality + dual-pen + spellblade + on-hit --
    # Duskblade of Draktharr (6691): missed from batch-30 lethality sweep.
    # Nightstalker unique-proc (large burst on first attack after stealth) is
    # conditional on vision/stealth mechanics - not sustained, not modeled.
    "6691": ItemEffect(
        item_id="6691",
        name="Duskblade of Draktharr",
        lethality=18.0,
        note=(
            "Duskblade of Draktharr: 18 lethality (missed from batch 30 sweep). "
            "Nightstalker proc requires post-stealth first attack (stealth conditional, "
            "not sustained-DPS modelable)"
        ),
    ),
    # Perplexity (4015): 22% armor pen + 30% magic pen dual-pen + Giant Slayer
    # target HP advantage amp (Phase 4 batch 38). Giant Slayer: 0.6% per 100 HP
    # difference between target max HP and caster max HP, capped at 15%. Uses the
    # new giant_slayer_pct_per_100hp + giant_slayer_max_pct schema (distinct from
    # LDR's target_bonus_hp_amp which is keyed off bonus HP, not max HP difference).
    "4015": ItemEffect(
        item_id="4015",
        name="Perplexity",
        armor_pen_pct=0.22,
        magic_pen_pct=0.30,
        giant_slayer_pct_per_100hp=0.006,
        giant_slayer_max_pct=0.15,
        note=(
            "Perplexity: 22% armor pen + 30% magic pen (dual-pen). "
            "Giant Slayer 0-15% damage amp based on (target_max_hp - caster_max_hp) "
            "/ 100 x 0.6%, capped at 15% (2500 HP diff = cap). "
            "Key: MAX HP diff, not bonus HP - distinct from LDR Giant Slayer schema"
        ),
    ),
    # Divine Sunderer (6632): Spellblade physical variant - 125% base AD + 6% target max
    # HP bonus physical on next attack after ability cast, ~3s cadence. Joins the
    # "spellblade" unique-passive family (Trinity Force / Lich Bane / ER / Iceborn /
    # Dusk+Dawn). Heal component (Sandforce: same damage distributed across nearby
    # allies as HP) is utility-only. Patch 16.9.1 values.
    "6632": ItemEffect(
        item_id="6632",
        name="Divine Sunderer",
        periodics=(
            PeriodicProc(
                name="Spellblade",
                every_n_seconds=3.0,
                bonus_damage=lambda c: 1.25 * c.base_ad + 0.06 * c.target_max_hp,
                damage_type=PHYSICAL,
            ),
        ),
        unique_passive_key="spellblade",
        note=(
            "Divine Sunderer: Spellblade 125% base AD + 6% target max HP physical "
            "every ~3s (joins spellblade dedup family; Sandforce heal utility-only)"
        ),
    ),
    # Navori Flickerblade (6675): Meraki 16.13.1 lists a SINGLE passive -
    # Transcendence (basic attacks reduce basic-ability cooldowns 15% on-attack)
    # plus Quicken (CDR on crit). Both are ability-uptime utility with ZERO
    # on-hit damage. "Bring It Down" is Kraken Slayer's (6672) proc alone; the
    # prior 120->168 physical proc here was a 6672-vs-6675 key-collision
    # artifact (R119 refute), inconsistent with the item's own already-correct
    # Arena mirror 226675 and the 226672 correction comment below. Removing it
    # drops the phantom physical over-credit for crit-ability carries building
    # Navori (Yasuo / Yone / Zeri / Xayah). Navori's crit / AS / MS stats are
    # unaffected (they come from the raw stat block, not this passive layer).
    "6675": ItemEffect(
        item_id="6675",
        name="Navori Flickerblade",
        defensive_only=True,
        note=(
            "Navori Flickerblade: Transcendence on-attack basic-ability CDR + "
            "Quicken CDR-on-crit - ability-uptime utility, no DPS proc (Meraki 16.13.1)"
        ),
    ),
    # Hellfire Hatchet (4017): Char has a 15s CD (Meraki confirmed).
    # Burn formula: (5% + 5%*hp_diff/2000 + lethality*(0.2%+0.2%*hp_diff/2000))
    # of target current HP physical over 4s, where hp_diff=caster_max_hp-target_max_hp
    # clamped [0,2000]. Using target_max_hp as current-HP proxy (standard DPS model).
    "4017": ItemEffect(
        item_id="4017",
        name="Hellfire Hatchet",
        lethality=12.0,
        unique_passive_key="hellfire_char",
        periodics=(PeriodicProc(
            name="Char",
            damage_type=PHYSICAL,
            every_n_seconds=15.0,
            # DS target-current-HP% lever: Char scales off the target's
            # CURRENT HP, so the outer magnitude carries
            # c.target_current_hp_pct (default 1.0 = byte-identical). The
            # inner hd = caster_max_hp - target_max_hp term is a tankiness
            # comparison (NOT current HP) and stays max-HP based.
            bonus_damage=lambda c: (
                lambda hd: c.target_max_hp * c.target_current_hp_pct * (
                    (0.05 + 0.05 * hd / 2000.0)
                    + c.caster_lethality * (0.002 + 0.002 * hd / 2000.0)
                )
            )(min(2000.0, max(0.0, c.caster_max_hp - c.target_max_hp))),
        ),),
        note="Hellfire Hatchet: Char 15s CD; (5+5*hp_diff/2k)% + lethality*(0.2+0.2*hp_diff/2k)% target maxHP physical/15s",
    ),
    # -- defensive_only (6) --
    "6630": ItemEffect(
        item_id="6630",
        name="Goredrinker",
        defensive_only=True,
        # R74: note refreshed - Thirsting Slash leads with physical AoE
        # damage (not heal-only), but this legacy SR id is map-disabled
        # (every items.json map flag False) and ABSENT from Meraki 16.13.1,
        # so there is no truth to pin damage against - it stays UNPINNED.
        # The obtainable Arena 226630 entry carries the DSV8
        # assume_physical_burst pin.
        note=(
            "Goredrinker (legacy SR 6630): Thirsting Slash active leads with "
            "physical AoE damage plus a heal, but this id is map-disabled + "
            "absent from Meraki 16.13.1 (unobtainable) - stays UNPINNED; "
            "Arena 226630 carries the DSV8 pin; Resolve 8% omnivamp is "
            "lifesteal (utility); no sustained DPS proc"
        ),
    ),
    "6671": ItemEffect(
        item_id="6671",
        name="Galeforce",
        defensive_only=True,
        note=(
            "Galeforce: Cloudburst is an active ability (no passive proc); "
            "Courage speed-boost is utility; no DPS contribution"
        ),
    ),
    "3050": ItemEffect(
        item_id="3050",
        name="Zeke's Convergence",
        defensive_only=True,
        # R70 slice A: Frostfire Tempest per-cast total rides the DSV6
        # assume_magic_burst seam. Meraki 16.13.1: "Upon casting your
        # ultimate ability, you summon a storm of flame and ice around
        # you for 5 seconds, dealing 30/4 magic every 0.25s | 30*5 total
        # magic damage ... within 350 units ... (45 second cooldown,
        # starts on ultimate cast)" = 150 flat per ult cast, no AP ratio.
        # SELF-centered storm - 16.13.1 has NO ally tether (the old
        # "tether-ally" note was stale). Cryocombustion ult haste lives
        # in _item_ability_haste.py, not here. DPS side intentionally
        # unmodeled: 45s-CD ult-triggered, no PeriodicProc, no
        # double-count - the credit rides the burst pin only.
        # defensive_only stays True - documentation-only flag, no engine
        # gate, and batch-35 coverage pins it.
        magic_burst_base=150.0,
        magic_burst_ap_ratio=0.0,
        note=(
            "Zeke's Convergence: Frostfire Tempest SELF storm on ult cast "
            "(Meraki 16.13.1: 150 total flat magic over 5s, 45s CD, no "
            "ally tether) - per-cast total rides the DSV6 "
            "assume_magic_burst seam; Cryocombustion haste lives in "
            "_item_ability_haste.py; DPS side intentionally unmodeled "
            "(long-CD ult-triggered, no PeriodicProc, no double-count)"
        ),
    ),
    "4016": ItemEffect(
        item_id="4016",
        name="Wordless Promise",
        defensive_only=True,
        note=(
            "Wordless Promise: Promise heal/shield passive (utility); no DPS contribution"
        ),
    ),
    "4014": ItemEffect(
        item_id="4014",
        name="Frozen Mallet",
        defensive_only=True,
        note=(
            "Frozen Mallet: Icy slow on basic attacks (utility); no DPS contribution"
        ),
    ),
    "4013": ItemEffect(
        item_id="4013",
        name="Lightning Braid",
        defensive_only=True,
        note=(
            "Lightning Braid: Chain Lightning fires on ability hit (ability-cast schema gap); "
            "also applies -20% ability damage reduction (DPS-negative) so net contribution "
            "for casters is unclear; deferred"
        ),
    ),
    # -- Phase 4 batch 36 (2026-05-04): Arena item sweep + Rite of Ruin crit --
    # Detonation Orb (447113): 12 flat magic pen (Detonation Orb stat block).
    # The Bomb stored-damage passive requires ability damage tracking (deferred).
    "447113": ItemEffect(
        item_id="447113",
        name="Detonation Orb",
        magic_pen_flat=12.0,
        note=(
            "Detonation Orb: 12 flat magic pen (existing schema). "
            "The Bomb stored 20% ability damage release deferred (ability-cast schema gap)"
        ),
    ),
    # Reverberation (447114): Resonate on-hit - 10 + 2% caster bonus HP magic per attack.
    # Reverberate HP-at-combat-start and Rumble immobilize-stacks are utility/conditional.
    "447114": ItemEffect(
        item_id="447114",
        name="Reverberation",
        periodics=(
            PeriodicProc(
                name="Resonate",
                every_n_attacks=1,
                bonus_damage=lambda c: 10.0 + 0.02 * c.caster_bonus_hp,
                damage_type=MAGICAL,
            ),
        ),
        note=(
            "Reverberation: Resonate 10 + 2% caster bonus HP magic on-hit (same schema as "
            "Titanic Hydra Cleave, keyed off caster_bonus_hp). "
            "Reverberate HP-per-AS and Rumble stacks utility-only"
        ),
    ),
    # Pyromancer's Cloak (447118): Spark (5s CD) - attack or ability hit burns target
    # for 100->350 magic over 3s (total burn; Meraki melee value). Modeled as
    # every_n_seconds=5.0 with total_damage as bonus_damage (same convention as
    # Hextech Gunblade's Lightning Bolt). Cleansing Flame fireball AoE deferred.
    "447118": ItemEffect(
        item_id="447118",
        name="Pyromancer's Cloak",
        periodics=(
            PeriodicProc(
                name="Spark",
                every_n_seconds=5.0,
                bonus_damage=lambda c: 100.0 + 250.0 / 17.0 * (c.level - 1),
                damage_type=MAGICAL,
            ),
        ),
        note=(
            "Pyromancer's Cloak: Spark 100->350 magic burn over 3s every 5s "
            "(melee Meraki value; total burn modeled as single proc per event; "
            "Cleansing Flame fireball AoE deferred)"
        ),
    ),
    # Lightning Rod (447119): Call Lightning - autocast every 16s: 135->230 magic
    # + 30% bonus AD + 50% AP + 10% target max HP. Fully Automated reduces CD via
    # AH (not modeled; pins at 16s base). Uses level + bonus_ad + ap + target_max_hp -
    # all existing CallContext fields.
    "447119": ItemEffect(
        item_id="447119",
        name="Lightning Rod",
        periodics=(
            PeriodicProc(
                name="Call Lightning",
                every_n_seconds=16.0,
                bonus_damage=lambda c: (
                    (135.0 + 95.0 / 17.0 * (c.level - 1))
                    + 0.30 * c.bonus_ad
                    + 0.50 * c.ap
                    + 0.10 * c.target_max_hp
                ),
                damage_type=MAGICAL,
            ),
        ),
        note=(
            "Lightning Rod: Call Lightning 135->230 + 30% bonus AD + 50% AP + 10% target max HP "
            "magic every 16s (base CD; Fully Automated AH reduction not modeled, "
            "pins at 16s conservative value)"
        ),
    ),
    # Regicide (447115): 15 lethality. End the Line takedown-conditional bonus deferred.
    "447115": ItemEffect(
        item_id="447115",
        name="Regicide",
        lethality=15.0,
        note=(
            "Regicide: 15 lethality (existing schema). "
            "End the Line takedown-vs-Regent bonus deferred (takedown conditional)"
        ),
    ),
    # Rite of Ruin (3430): Wrath and Ruin - 2.5% crit per ability cast, up to 8 stacks
    # = 20% crit. Pinned at max stacks per sustained-DPS convention (same as Yun Tal
    # Wildarrows' flat-stacks pin). Salvage the Wreckage shield is utility-only.
    "3430": ItemEffect(
        item_id="3430",
        name="Rite Of Ruin",
        crit_chance_bonus_flat=0.20,
        note=(
            "Rite Of Ruin: Wrath and Ruin max 8 stacks = 20% bonus crit chance "
            "(pinned at full stacks per sustained-DPS convention; same schema as Yun Tal). "
            "Salvage the Wreckage ability-chance shield utility-only"
        ),
    ),
    # -- defensive_only (6) --
    "447108": ItemEffect(
        item_id="447108",
        name="Runecarver",
        defensive_only=True,
        note=(
            "Runecarver: Spiral Out fires missiles per Rune stack on Energized proc - "
            "Rune-stack layer on top of Energized mechanic is too complex for sustained model; "
            "deferred"
        ),
    ),
    "447116": ItemEffect(
        item_id="447116",
        name="Kinkou Jitte",
        defensive_only=True,
        note=(
            "Kinkou Jitte: Between the Ribs deals extra damage through positional weakpoint "
            "(directional conditional not modelable without fight geometry)"
        ),
    ),
    "447120": ItemEffect(
        item_id="447120",
        name="Diamond-Tipped Spear",
        defensive_only=True,
        note=(
            "Diamond-Tipped Spear: Sweet Spot 0-30% damage amp scales with fight distance "
            "(range conditional not modelable); Reach Weapon +75 range utility-only"
        ),
    ),
    "447121": ItemEffect(
        item_id="447121",
        name="Twilight's Edge",
        defensive_only=True,
        note=(
            "Twilight's Edge: The Path Between requires 130 bonus AD AND 180 AP threshold; "
            "randomly assigns Material/Spirit World effect - threshold + RNG not modelable"
        ),
    ),
    "447107": ItemEffect(
        item_id="447107",
        name="Decapitator",
        defensive_only=True,
        note=(
            "Decapitator: Anticipation stacks boost ultimate damage "
            "(ultimate-cast schema gap; no basic attack DPS proc)"
        ),
    ),
    "447100": ItemEffect(
        item_id="447100",
        name="Mirage Blade",
        defensive_only=True,
        note=(
            "Mirage Blade: Blur grants bonus MS and a brief untargetable dash illusion "
            "(movement utility + dodge mechanic; no DPS contribution)"
        ),
    ),
    # -- Phase 4 batch 37 (2026-05-04): TRUE damage type + Arena item sweep --
    # TRUE damage bypasses both armor and MR (resist=0.0 in _periodic_proc_dps).
    # Three active promotions; 14 defensive_only entries completing the Arena pool sweep.

    # Darksteel Talons (443054): Gash - every basic attack deals
    # (10->20 pp) + 20% bonus armor true damage (ranged Meraki values;
    # batch 58 adds caster_bonus_armor scaling). Melee would be 20->40
    # base + 25% bonus armor; ranged = 10->20 + 20% armor.
    "443054": ItemEffect(
        item_id="443054",
        name="Darksteel Talons",
        periodics=(
            PeriodicProc(
                name="Gash",
                every_n_attacks=1,
                bonus_damage=lambda c: (
                    (10.0 + 10.0 / 17.0 * (c.level - 1))
                    + 0.20 * c.caster_bonus_armor
                ),
                damage_type=TRUE,
            ),
        ),
        note=(
            "Darksteel Talons: Gash every basic attack (10->20 level-scaled) + 20% bonus armor "
            "true damage (ranged Meraki values; Batch 58 - caster_bonus_armor fully wired)"
        ),
    ),
    # Fulmination (443055): Dynamo - every 100th attack 13% CURRENT target HP magic damage.
    # target_max_hp used as upper-bound approximation (current HP unavailable in CallContext).
    # Polarity Energized mechanic (stacks via movement + attacks) deferred - same complexity
    # class as Stormrazor; not modeled at sustained-DPS level.
    "443055": ItemEffect(
        item_id="443055",
        name="Fulmination",
        periodics=(
            PeriodicProc(
                name="Dynamo",
                every_n_attacks=100,
                # DS target-current-HP% lever: Dynamo hits a % of the
                # target's CURRENT HP, so the magnitude scales by
                # c.target_current_hp_pct (default 1.0 = byte-identical).
                bonus_damage=lambda c: 0.13 * c.target_max_hp * c.target_current_hp_pct,
                damage_type=MAGICAL,
            ),
        ),
        note=(
            "Fulmination: Dynamo every 100th attack 13% CURRENT target HP magic "
            "(target_max_hp used as upper-bound; current HP unavailable). "
            "Polarity Energized mechanic deferred (movement-stack complexity)"
        ),
    ),
    # Reaper's Toll (443090): Reap - every basic attack 0.7% target max HP true damage
    # at base 0 stacks. Stacks infinitely per target (no cap) - pinned at base (0 stacks)
    # per conservative sustained-DPS convention. Sow on-kill heal utility-only.
    "443090": ItemEffect(
        item_id="443090",
        name="Reaper's Toll",
        periodics=(
            PeriodicProc(
                name="Reap",
                every_n_attacks=1,
                bonus_damage=lambda c: 0.007 * c.target_max_hp,
                damage_type=TRUE,
            ),
        ),
        note=(
            "Reaper's Toll: Reap every basic attack 0.7% target max HP true damage "
            "(pinned at 0 stacks - infinite per-target stacking deferred). "
            "Sow on-kill heal utility-only"
        ),
    ),
    # -- defensive_only (14) --
    "447101": ItemEffect(
        item_id="447101",
        name="Gambler's Blade",
        defensive_only=True,
        note=(
            "Gambler's Blade (447101): Money In The Bank 12% chance to store 30-240g on attack/ability - "
            "gold-economy mechanic, not a DPS proc; variable payout not modelable in sustained DPS"
        ),
    ),
    "447102": ItemEffect(
        item_id="447102",
        name="Reality Fracture",
        # Phase 4 batch 60 (2026-05-04): promoted. Meraki confirms ZZ'Rot passive:
        # "on attack/ability, summon 8 Voidmites (12s CD) that attack the target,
        # each dealing 6 (+ 4% AD) (+ 8% AP) magic damage." 'The target' singular
        # -> all 8 voidmites hit the same target (no targets_in_rotation spread).
        # 'your AD' in Meraki = total AD (base + bonus). '12s CD' is the rate
        # limiter; modeled as every_n_seconds=12.0.
        periodics=(PeriodicProc(
            name="ZZ'Rot",
            bonus_damage=lambda c: 8.0 * (6.0 + 0.04 * (c.base_ad + c.bonus_ad) + 0.08 * c.ap),
            damage_type=MAGICAL,
            every_n_seconds=12.0,
        ),),
        note=(
            "Reality Fracture: ZZ'Rot - 8 Voidmites every 12s each dealing "
            "6 + 4% total AD + 8% AP magic (Meraki confirmed; all 8 target same enemy)"
        ),
    ),
    "447103": ItemEffect(
        item_id="447103",
        name="Hemomancer's Helm",
        defensive_only=True,
        note=(
            "Hemomancer's Helm: Scarlet Allegiance conditional on lifesteal + omnivamp >= 30% "
            "grants 500 bonus HP and healing - HP/sustain gain, no DPS proc"
        ),
    ),
    # Innervating Locket (447104): Fill the Soul - 30 ability charges (self + allies
    # within 800 units) -> grants pp|100 to 250 AP at max charge for rest of round.
    # No CD; fires once per Arena round. Models as bonus_ap_stacked=175 (midpoint of
    # 100-250 AP across levels 1-18). In Arena, 30 stacks are reliably reached early
    # each round given ally casts; AP applies for most of the round.
    "447104": ItemEffect(
        item_id="447104",
        name="Innervating Locket",
        bonus_ap_stacked=175.0,
        unique_passive_key="innervating_fill",
        note="Innervating Locket: Fill the Soul 30-charge AP burst; pp|100-250 AP at max charge; 175 AP midpoint (Arena-only; ally casts count)",
    ),
    "447105": ItemEffect(
        item_id="447105",
        name="Empyrean Promise",
        defensive_only=True,
        note=(
            "Empyrean Promise: no passive effects in Meraki 16.9.1 - stat block only; "
            "defensive_only per zero-proc policy"
        ),
    ),
    "447106": ItemEffect(
        item_id="447106",
        name="Dragonheart",
        defensive_only=True,
        note=(
            "Dragonheart: Inner Flame grants random Dragon Soul every 2 Arena rounds + "
            "total stat scaling - Arena-round mechanic, not a basic-attack DPS proc"
        ),
    ),
    # Phase 4 batch 62 (2026-05-04): Cruelty Arena (447109) - promoted. Meraki confirms
    # Watch Them Fall: comet on CC, pp|50-150 + 40% AP + 4% caster max HP magic, 6s CD.
    "447109": ItemEffect(
        item_id="447109",
        name="Cruelty",
        periodics=(PeriodicProc(
            name="Watch Them Fall",
            bonus_damage=lambda c: c.targets_in_rotation * (
                50.0 + (100.0 / 17.0) * (c.level - 1)
                + 0.40 * c.ap
                + 0.04 * c.caster_max_hp
            ),
            damage_type=MAGICAL,
            every_n_seconds=6.0,
        ),),
        note=(
            "Cruelty (Arena 447109): Watch Them Fall - comet on immobilize/ground, "
            "50->150 + 40% AP + 4% caster max HP magic, 6s CD (Meraki confirmed). "
            "AoE via targets_in_rotation; CC-triggered proc at item-CD floor."
        ),
    ),
    "447110": ItemEffect(
        item_id="447110",
        name="Moonflair Spellblade",
        defensive_only=True,
        note=(
            "Moonflair Spellblade: Relentless resets basic attack timer and empowers "
            "next 2 attacks after ability cast - attack-reset/haste mechanic, "
            "not a simple damage proc (ability-cast schema gap)"
        ),
    ),
    "447112": ItemEffect(
        item_id="447112",
        name="Flesheater",
        # Phase 4 batch 50 (2026-05-04): Arena version. Same "Hack the Meat"
        # passive as 667112 - 3 armor+MR per hit, 10 stacks -> 30 flat each.
        # Arena version adds 20 Ability Haste and 70 AF (vs 55 AF SR).
        armor_reduction_flat=30.0,
        mr_reduction_flat=30.0,
        note=(
            "Flesheater (Arena 447112): Hack the Meat 30 flat armor+MR shred "
            "at 10 stacks; Cannibalize on-kill heal utility-only"
        ),
    ),
    "447122": ItemEffect(
        item_id="447122",
        name="Black Hole Gauntlet",
        defensive_only=True,
        note=(
            "Black Hole Gauntlet: Accretion stacks from on-hit + immobilize effects - "
            "stack-conditional with CC dependency; not a simple per-attack DPS proc"
        ),
    ),
    "447123": ItemEffect(
        item_id="447123",
        name="Puppeteer",
        defensive_only=True,
        note=(
            "Puppeteer: Pull Their Strings 4-stack on-hit conditional + ally buff utility passive - "
            "stack ramp + conditional trigger not modelable in sustained flat DPS"
        ),
    ),
    "443056": ItemEffect(
        item_id="443056",
        name="Demon King's Crown",
        defensive_only=True,
        note=(
            "Demon King's Crown: Supremacy percentage increase to total AD/AP/AS/max HP - "
            "Arena-round progression mechanic; not a simple stat add (multiplier interacts "
            "with full stat build; deferred)"
        ),
    ),
    "443060": ItemEffect(
        item_id="443060",
        name="Sword of the Divine",
        # Phase 4 batch 54 (2026-05-04): promoted. Excoriate grants random bonus
        # crit damage in [0%, 50%]; expected value of a uniform distribution =
        # 25%. Same expected-value approximation used by Hamstringer (batch 53)
        # for its crit-scaling bleed. Full 50% is never sustained; 0% is also
        # never sustained - EV is the right DPS model for a random-in-range
        # effect evaluated over many attacks.
        crit_damage_bonus=0.25,
        note=(
            "Sword of the Divine (Arena 443060): Excoriate +25% crit damage bonus "
            "(EV of uniform 0-50% range)"
        ),
    ),
    "443069": ItemEffect(
        item_id="443069",
        name="Hamstringer",
        # Phase 4 batch 53 (2026-05-04): promoted. Meraki formula:
        # "Critical strikes inflict a bleed: (20-80 by level) + 25% of the
        # crit instance." Crit-gated rate modeled as expected-value weighting:
        # bonus_damage per attack = crit_chance * (level_scale + 25% of
        # crit-bonus AD). Crit bonus assumed DEFAULT_CRIT_BONUS = 0.75
        # (175% crit); 25% x 0.75 = 0.1875 AD. Level scale: 20 at lvl 1,
        # 80 at lvl 18 -> slope = 60/17 per level.
        periodics=(PeriodicProc(
            name="Scour",
            bonus_damage=lambda c: c.crit_chance * (
                (20.0 + (60.0 / 17.0) * (c.level - 1))
                + 0.1875 * (c.base_ad + c.bonus_ad)
            ),
            damage_type=PHYSICAL,
            every_n_attacks=1,
        ),),
        note=(
            "Hamstringer: Scour - crit strikes inflict 2s physical bleed "
            "(20-80 by level) + 25% of crit-bonus AD; modeled as "
            "expected-value x crit_chance per attack (DEFAULT_CRIT_BONUS=0.75). "
            "Meraki 443069 confirmed."
        ),
    ),
    # -- Phase 4 batch 38 (2026-05-04): Giant Slayer schema + 228xxx/443xxx/SR sweep --
    # New schema: giant_slayer_pct_per_100hp + giant_slayer_max_pct (MAX HP diff keyed,
    # distinct from LDR's bonus-HP-keyed target_bonus_hp_amp). Perplexity updated in-place.
    # 3 active promotions; 17 defensive_only entries.

    # Wooglet's Witchcap (228002): Magical Opus - increase total AP by 50%.
    # Uses existing ap_amp_pct schema (same as Rabadon's Deathcap 30%). Stacks
    # multiplicatively via total_ap_amp_multiplier (1.50 x 1.30 if both in build).
    # Time Stop active (Zhonya's invulnerability) is utility-only, not modeled.
    "228002": ItemEffect(
        item_id="228002",
        name="Wooglet's Witchcap",
        ap_amp_pct=0.50,
        note=(
            "Wooglet's Witchcap: Magical Opus +50% total AP (Arena legendary). "
            "Stacks multiplicatively with Rabadon's via total_ap_amp_multiplier. "
            "Time Stop active (Zhonya's invulnerability) utility-only"
        ),
    ),
    # Deathblade (228003): Death and Taxes - execute below 7% HP (utility, not modeled).
    # Stat line carries 45% crit damage bonus + 20 lethality - both promotable via
    # existing schemas. crit_damage_bonus adds to DEFAULT_CRIT_BONUS (same as IE +0.30);
    # lethality folds into level-scaled flat pen via effective_target_armor.
    "228003": ItemEffect(
        item_id="228003",
        name="Deathblade",
        lethality=20.0,
        crit_damage_bonus=0.45,
        note=(
            "Deathblade: 20 lethality (level-scaled flat pen) + 45% bonus crit damage. "
            "Death and Taxes execute-below-7% utility-only (execute conditional not modeled). "
            "On-kill gold + heal utility-only"
        ),
    ),
    # Obsidian Cleaver (228005): Carve - dealing physical damage reduces target armor
    # by 6%, stacks 5 times = 30% max reduction. Same layer as Black Cleaver's
    # armor_reduction_pct (applied before % pen). Modeled at full stacks per sustained-
    # DPS convention. Fervor 20 MS utility-only.
    # Authored at 7% x 5 = 0.35 against the 16.10.1 snapshot, which did state 7%;
    # Riot cut Carve to 6% by 16.12.1 and the row went stale for four snapshots.
    # Landing on Black Cleaver's 30% is the mirror's OWN stat line agreeing, not the
    # base item's number inherited (R161 doctrine B). Guarded by
    # tests/test_stacking_pct_resist_reduction_drift.py, which re-derives the product
    # from the live DDragon description instead of pinning this literal.
    "228005": ItemEffect(
        item_id="228005",
        name="Obsidian Cleaver",
        armor_reduction_pct=0.30,
        note=(
            "Obsidian Cleaver: Carve 6% armor reduction per stack x 5 stacks = 30% max "
            "(same armor_reduction_pct layer as Black Cleaver, modeled at full stacks). "
            "Fervor 20 MS utility-only"
        ),
    ),
    # -- defensive_only (17) --
    "228001": ItemEffect(
        item_id="228001",
        name="Anathema's Chains",
        defensive_only=True,
        note=(
            "Anathema's Chains (Arena 228001): Vendetta - take reduced damage from "
            "Nemesis + reduce their Tenacity while near. Damage mitigation, not DPS"
        ),
    ),
    "228004": ItemEffect(
        item_id="228004",
        name="Adaptive Helm",
        defensive_only=True,
        note=(
            "Adaptive Helm: Voidborn Resilience - gain 2 armor + 2 MR per second "
            "in champion combat (combat-stacking tank passive, not a DPS proc)"
        ),
    ),
    "228006": ItemEffect(
        item_id="228006",
        name="Sanguine Blade",
        defensive_only=True,
        note=(
            "Sanguine Blade: Cleave attacks deal physical damage to nearby enemies - "
            "cleave coefficient absent from Meraki + DDragon 16.9.1; deferred. "
            "Ravenous Crescent AoE + life steal utility-only"
        ),
    ),
    "228008": ItemEffect(
        item_id="228008",
        name="Runeglaive",
        defensive_only=True,
        note=(
            "Runeglaive: no combat passive in DDragon 16.9.1 - stat block only "
            "(65 AD + 85 AP + 30% AS + 20% crit + 600 HP; contributes via aggregate_item_stats). "
            "defensive_only per zero-proc policy"
        ),
    ),
    "443058": ItemEffect(
        item_id="443058",
        name="Shield of Molten Stone",
        defensive_only=True,
        note=(
            "Shield of Molten Stone: Immovable as the Earth - increases total armor by 20% "
            "+ block chance per 200 total armor (up to 50%); tank defensive passive, no DPS proc"
        ),
    ),
    "443059": ItemEffect(
        item_id="443059",
        name="Cloak of Starry Night",
        defensive_only=True,
        note=(
            "Cloak of Starry Night: Limitless as the Stars - increases total MR by 20% "
            "+ reduces non-AA damage per 200 total MR (up to 50%); tank defensive, no DPS proc"
        ),
    ),
    "443061": ItemEffect(
        item_id="443061",
        name="Force of Entropy",
        defensive_only=True,
        note=(
            "Force of Entropy: Atrophy fires a crit-chance-weighted chance proc "
            "on immobilizing effects - CC-conditional trigger, no sustained DPS contribution"
        ),
    ),
    "443062": ItemEffect(
        item_id="443062",
        name="Sanguine Gift",
        defensive_only=True,
        note=(
            "Sanguine Gift: Patronage - stores 15% post-mitigation damage dealt, "
            "heals caster + nearest ally when stored exceeds 333. Sustain mechanic, no DPS"
        ),
    ),
    "443063": ItemEffect(
        item_id="443063",
        name="Eleisa's Miracle",
        defensive_only=True,
        note=(
            "Eleisa's Miracle: Enduring Vitality - heal/sustain mechanic; "
            "no basic-attack DPS proc"
        ),
    ),
    # PERMANENTLY UNMODELABLE - do not re-investigate on a catalog sweep.
    # 443064's DDragon description renders every stat line as a literal
    # "?" placeholder ("? || ?%" Magic Penetration) over an EMPTY stats
    # block. There is no static magnitude to credit on any axis, so a
    # digit-based sweep correctly skips it rather than missing it.
    "443064": ItemEffect(
        item_id="443064",
        name="Talisman of Ascension",
        defensive_only=True,
        note=(
            "Talisman of Ascension: adaptive stat item (adjusts to build); "
            "no fixed passive proc modelable in static engine"
        ),
    ),
    "443079": ItemEffect(
        item_id="443079",
        name="Turbo Chemtank",
        defensive_only=True,
        note=(
            "Turbo Chemtank: CC-immunity canister mechanic - ignore next immobilize, "
            "drop canister restoring 4% max HP. CC mitigation + heal, no DPS proc"
        ),
    ),
    "443080": ItemEffect(
        item_id="443080",
        name="Twin Mask",
        defensive_only=True,
        note=(
            "Twin Mask: Unanimity - gain 20% (or 35%) of teammate's AD/AP/AS/HP/armor/MR/AH. "
            "Teammate-dependent scaling not modelable in solo-caster DPS engine"
        ),
    ),
    "443081": ItemEffect(
        item_id="443081",
        name="Hexbolt Companion",
        defensive_only=True,
        note=(
            "Hexbolt Companion: Covering Fire - on-hit stacks trigger teammate ally-bolt. "
            "Teammate mechanic; ally contribution not modeled in single-caster engine"
        ),
    ),
    "443193": ItemEffect(
        item_id="443193",
        name="Gargoyle Stoneplate",
        defensive_only=True,
        note=(
            "Gargoyle Stoneplate: Unbreakable active - decaying shield + size increase. "
            "Shield mechanic, active-only, no DPS contribution"
        ),
    ),
    "2525": ItemEffect(
        item_id="2525",
        name="Protoplasm Harness",
        defensive_only=True,
        unique_passive_key="lifeline",
        note=(
            "Protoplasm Harness: Lifeline - triggered MAX-HEALTH grant when dropping below "
            "30% HP (gain maximum Health for 5s), then heal Health over that duration, "
            "plus a size/MS/tenacity boost. Grants NO shield - contrast Immortal Shieldbow 6673, "
            "whose Lifeline does grant a Shield, so shield=None on this row is correct. "
            "Joins lifeline unique-passive family (Immortal Shieldbow, Sterak's, Maw, Seraph's). "
            "Max-Health/sustain mechanic, no DPS"
        ),
    ),
    "3143": ItemEffect(
        item_id="3143",
        name="Randuin's Omen",
        defensive_only=True,
        # R77 (1.180.0): Resilience 30% reduced critical strike damage taken is
        # now EHP-credited (crit is physical -> folds into the physical
        # denominator via the default-OFF assume_item_crit_dr seam). Still
        # defensive_only (no DPS proc). Humility active 70% AoE slow stays
        # utility-only. WIN-anchor rewind_history.db: 344 builds, 54.7% WR.
        crit_damage_reduction=0.30,
        note=(
            "Randuin's Omen: Resilience 30% reduced crit damage taken (R77 EHP "
            "seam assume_item_crit_dr) + Humility active 70% AoE slow - damage "
            "mitigation + CC active, no DPS contribution"
        ),
    ),
    "8001": ItemEffect(
        item_id="8001",
        name="Anathema's Chains",
        defensive_only=True,
        note=(
            "Anathema's Chains (SR 8001): Vendetta stacks - up to 1% reduced damage "
            "per stack from Nemesis + Tenacity reduction at max stacks. "
            "Damage mitigation passive, not DPS; active global targeting utility-only"
        ),
    ),
    # -- Phase 4 batch 39 (2026-05-04): MR-reduction schema + Arena re-skin sweep --
    # New field mr_reduction_pct (magic-side Black Cleaver analogue) wired into
    # effective_target_mr before % pen step. 5 active promotions; 7 defensive_only.

    # Bloodletter's Curse (4010): Vile Decay - dealing magic damage reduces target's
    # MR by 7.5% for 6s, stacking up to 4 times = 30% max MR reduction.
    # Modeled at full stacks per sustained-DPS convention (same as Black Cleaver's
    # armor_reduction_pct=0.30 at 5 stacks). Applies before % magic pen in
    # effective_target_mr - mirrors the armor reduction -> % pen -> flat pen order.
    "4010": ItemEffect(
        item_id="4010",
        name="Bloodletter's Curse",
        mr_reduction_pct=0.30,
        note=(
            "Bloodletter's Curse: Vile Decay 7.5% MR reduction x 4 stacks = 30% max "
            "(modeled at full stacks; same layer as armor_reduction_pct but for MR). "
            "Applied before magic_pen_pct in effective_target_mr pipeline"
        ),
    ),
    # Divine Sunderer (446632, Arena variant): Spellblade - 180% base AD + 2% target
    # max HP (ranged value; Meraki shows rd|4%|2%) physical on ability-cast cadence ~3s.
    # Higher base AD coefficient than SR version (180% vs 125%) but lower HP % (2% vs 6%).
    # Joins the "spellblade" unique-passive family.
    "446632": ItemEffect(
        item_id="446632",
        name="Divine Sunderer",
        periodics=(
            PeriodicProc(
                name="Spellblade",
                every_n_seconds=3.0,
                bonus_damage=lambda c: 1.80 * c.base_ad + 0.02 * c.target_max_hp,
                damage_type=PHYSICAL,
            ),
        ),
        unique_passive_key="spellblade",
        note=(
            "Divine Sunderer (Arena 446632): Spellblade 180% base AD + 2% target max HP "
            "physical ~every 3s (ranged value; Arena version has higher base-AD coefficient "
            "than SR 6632's 125%). Joins spellblade unique-passive family. "
            "Sandforce heal utility-only"
        ),
    ),
    # Overlord's Bloodmail (447111, Arena variant): Tyranny - gain bonus AD equal to
    # 3% of bonus HP. Same bonus_ad_pct_bonus_hp schema as SR 2501 (2.5%) but higher
    # coefficient. Retribution (up to 17.5% AD increase based on % missing HP) is
    # modeled behind the R111 assume_caster_lowhp offense seam (missing_hp_ad_amp_max_pct).
    "447111": ItemEffect(
        item_id="447111",
        name="Overlord's Bloodmail",
        bonus_ad_pct_bonus_hp=0.03,
        missing_hp_ad_amp_max_pct=0.175,
        note=(
            "Overlord's Bloodmail (Arena 447111): Tyranny 3% bonus HP -> bonus AD "
            "(Arena variant; SR 2501 has 2.5%). "
            "Retribution up-to-17.5% AD based on missing HP modeled behind the "
            "R111 assume_caster_lowhp offense seam"
        ),
    ),
    # Atma's Reckoning (663039): Big Hands variant. Same passive as SR 3039 -
    # 0-30% bonus crit chance scaling with bonus HP (cap at 3000 bonus HP).
    # 663xxx prefix indicates an Arena re-skin of the base item.
    "663039": ItemEffect(
        item_id="663039",
        name="Atma's Reckoning",
        crit_chance_bonus_max_pct=0.30,
        crit_chance_bonus_per_bonus_hp_cap=3000.0,
        note=(
            "Atma's Reckoning (663039 Arena variant): Big Hands 0-30% bonus crit chance "
            "scaling with bonus HP (same coefficients as SR 3039, capped at 3000 bonus HP)"
        ),
    ),
    # Hextech Gunblade (663146, Arena variant): same Lightning Bolt active as SR 3146
    # (175->253 by level + 30% AP magic, 40s cooldown). 663xxx is an Arena re-skin.
    "663146": ItemEffect(
        item_id="663146",
        name="Hextech Gunblade",
        periodics=(
            PeriodicProc(
                name="Lightning Bolt",
                bonus_damage=lambda c: 175.0 + (253.0 - 175.0) / 17.0 * (c.level - 1) + 0.30 * c.ap,
                damage_type=MAGICAL,
                every_n_seconds=40.0,
            ),
        ),
        note=(
            "Hextech Gunblade (663146 Arena variant): Lightning Bolt same formula as SR 3146 "
            "(175->253 by level + 30% AP magic, 40s cooldown). 25%/1.5s slow utility-only"
        ),
    ),
    # -- defensive_only (7) --
    "444636": ItemEffect(
        item_id="444636",
        name="Night Harvester",
        # Phase 4 batch 52 (2026-05-04): promoted. Meraki confirms: "125 (+ 15%
        # AP) bonus magic damage, 10s CD per champion." Same values as SR 4636.
        periodics=(PeriodicProc(
            name="Soulrend",
            bonus_damage=lambda c: 125.0 + 0.15 * c.ap,
            damage_type=MAGICAL,
            every_n_seconds=10.0,
        ),),
        note="Night Harvester (Arena 444636): Soulrend 125 (+15% AP) magic / 10s (Meraki confirmed)",
    ),
    "444637": ItemEffect(
        item_id="444637",
        name="Demonic Embrace",
        # Phase 4 batch 56 (2026-05-04): promoted. Sinister Pact: +1.5% AP per 100
        # current HP, capped at 45% (3000 HP). Modeled using caster max HP as a
        # sustained-combat approximation (same convention as BotRK current-HP proc).
        # A build with 3000 HP reaches the full 45% AP amplification; 2000 HP -> 30%.
        # Distinct from SR 4637 which gives static bonus-HP -> bonus AP (additive);
        # this is multiplicative (same layer as Rabadon's), so it stacks with ap_amp_pct.
        ap_amp_pct_per_100_caster_hp=0.015,
        ap_amp_pct_per_100_caster_hp_cap=0.45,
        note=(
            "Demonic Embrace (444637 Arena): Sinister Pact +1.5% AP per 100 HP "
            "(cap 45% at 3000 HP; modeled at max HP as sustained approximation)"
        ),
    ),
    "446691": ItemEffect(
        item_id="446691",
        name="Duskblade of Draktharr",
        defensive_only=True,
        # R152 lethality stat-block parity: DDragon 16.14.1 <stats> carries
        # 20 Lethality; previously credited 0.0. The Nightstalker PASSIVE
        # stays deferred (ability-cast schema gap) - only the stat block
        # lands here. defensive_only stays True (doc-only flag).
        lethality=20.0,
        note=(
            "Duskblade of Draktharr (446691 Arena): 20 Lethality stat block now "
            "credited (R152); Nightstalker - ability damage amp based on target "
            "missing HP - remains an ability-cast schema gap and is deferred. "
            "Different passive mechanism from SR 6691 (which carries lethality only)"
        ),
    ),
    "446667": ItemEffect(
        item_id="446667",
        name="Radiant Virtue",
        defensive_only=True,
        note=(
            "Radiant Virtue: Judgment 30 ult haste + Guiding Light on-ult Transcend "
            "(max HP increase + ally heal boost for 9s); ult-cast schema gap + support mechanic"
        ),
    ),
    "443083": ItemEffect(
        item_id="443083",
        name="Warmog's Armor",
        defensive_only=True,
        note=(
            "Warmog's Armor (Arena 443083): Warmog's Heart - HP regen per second, "
            "enhanced out of combat. Requires 1350 bonus HP. Pure sustain, no DPS proc"
        ),
    ),
    "663056": ItemEffect(
        item_id="663056",
        name="Demon King's Crown",
        defensive_only=True,
        note=(
            "Demon King's Crown (663056): Supremacy - increases all stats by 20%, "
            "modified per takedown/death. Kill/death-event scaling not modelable in "
            "static sustained-DPS engine"
        ),
    ),
    "4011": ItemEffect(
        item_id="4011",
        name="Sword of Blossoming Dawn",
        defensive_only=True,
        note=(
            "Sword of Blossoming Dawn: Effervescence +1.2% AS per 1% H&S power "
            "(conditional AS, H&S power not tracked in engine) + Peppermint ally heal "
            "(teammate mechanic). Deferred - conditional AS schema gap"
        ),
    ),
    # -- Phase 4 batch 40 (2026-05-04): component items + final SR/Arena sweep --
    # 3 active promotions using existing schemas; ~15 defensive_only entries.

    # Last Whisper (3035): 18% armor pen. Component item for LDR / Mortal Reminder /
    # Serylda's; builds that carry it without upgrade still benefit from the pen layer.
    "3035": ItemEffect(
        item_id="3035",
        name="Last Whisper",
        armor_pen_pct=0.18,
        note="Last Whisper: 18% armor penetration (component of LDR, Mortal Reminder, Serylda's)",
    ),
    # The Brutalizer (2020): 5 lethality component. Upgrades into Youmuu's / Edge of Night /
    # Serrated Dirk path. Adds small level-scaled flat pen contribution to mid-game builds.
    "2020": ItemEffect(
        item_id="2020",
        name="The Brutalizer",
        lethality=5.0,
        note="The Brutalizer: 5 lethality (component; level-scaled flat pen via effective_target_armor)",
    ),
    # Haunting Guise (3147): Madness - 2% bonus damage per second in combat, up to 6%
    # at 3 seconds. Pinned at full stacks per sustained-DPS convention (same approach
    # as Liandry's Torment damage_amp_pct=0.06, which upgrades from this item).
    "3147": ItemEffect(
        item_id="3147",
        name="Haunting Guise",
        damage_amp_pct=0.06,
        note=(
            "Haunting Guise: Madness 2%/s bonus damage x 3s = 6% max amp "
            "(pinned at full stacks; same coefficient as Liandry's Torment 3151)"
        ),
    ),
    # -- defensive_only (15) --
    "444644": ItemEffect(
        item_id="444644",
        name="Crown of the Shattered Queen",
        defensive_only=True,
        note=(
            "Crown of the Shattered Queen (Arena 444644): Safeguard - reduce incoming "
            "champion damage by 90% until first champion damage taken. Damage reduction, "
            "no DPS proc"
        ),
    ),
    "446656": ItemEffect(
        item_id="446656",
        name="Everfrost",
        defensive_only=True,
        # R69 (1.176.0): Glaciate one-cast burst rides the DSV6
        # assume_magic_burst seam. Meraki 16.13.1 (only this DISTRIBUTED
        # Arena id carries an Everfrost entry - legacy 6656/226656 are
        # map-disabled with no Meraki truth and stay unpinned): cone deals
        # "300 magic damage (+ 85% AP)". One cast, one hit per enemy - the
        # burst-window magnitude. Root/slow CC stays unmodeled (CC utility,
        # not damage); DPS side intentionally unmodeled (long-CD active,
        # no PeriodicProc, no double-count). defensive_only stays True -
        # documentation-only flag, no engine gate.
        magic_burst_base=300.0,
        magic_burst_ap_ratio=0.85,
        note=(
            "Everfrost (Arena 446656): Glaciate active 300 (+85% AP) magic "
            "cone - one-cast burst-window magnitude rides the DSV6 "
            "assume_magic_burst seam; root/slow CC and DPS side "
            "intentionally unmodeled (long-CD active, no PeriodicProc)"
        ),
    ),
    "446671": ItemEffect(
        item_id="446671",
        name="Galeforce",
        defensive_only=True,
        note=(
            "Galeforce (Arena 446671): Cloudburst II - dash + execute. "
            "Execute conditional + active-cast schema gap; utility mobility"
        ),
    ),
    "664644": ItemEffect(
        item_id="664644",
        name="Crown of the Shattered Queen",
        defensive_only=True,
        note=(
            "Crown of the Shattered Queen (SR 664644): Safeguard - reduce incoming "
            "champion damage by 40% until first hit. Damage reduction, no DPS proc"
        ),
    ),
    "663058": ItemEffect(
        item_id="663058",
        name="Shield of Molten Stone",
        defensive_only=True,
        note=(
            "Shield of Molten Stone (SR 663058): same Immovable as the Earth passive "
            "as Arena 443058 - armor % amp + block chance. Tank defensive, no DPS proc"
        ),
    ),
    "663059": ItemEffect(
        item_id="663059",
        name="Cloak of Starry Night",
        defensive_only=True,
        note=(
            "Cloak of Starry Night (SR 663059): same Limitless as the Stars passive "
            "as Arena 443059 - MR % amp + damage reduction. Tank defensive, no DPS proc"
        ),
    ),
    "663172": ItemEffect(
        item_id="663172",
        name="Zephyr",
        defensive_only=True,
        note=(
            "Zephyr: Like the Wind - on-hit bonus Move Speed stacking for 6s + "
            "20% Tenacity. Utility/movement passive, no DPS contribution"
        ),
    ),
    "663193": ItemEffect(
        item_id="663193",
        name="Gargoyle Stoneplate",
        defensive_only=True,
        note=(
            "Gargoyle Stoneplate (SR 663193): Unbreakable active - decaying shield + "
            "size increase. Same mechanic as Arena 443193. Active-only, no DPS proc"
        ),
    ),
    "664403": ItemEffect(
        item_id="664403",
        name="The Golden Spatula",
        defensive_only=True,
        note=(
            "The Golden Spatula: massive stat stick (90 AD + 125 AP + 30% AS + 25% crit "
            "+ 250 HP + AH + armor + MR + mana). No passive proc - stats contribute via "
            "aggregate_item_stats; defensive_only per zero-proc policy"
        ),
    ),
    "3075": ItemEffect(
        item_id="3075",
        name="Thornmail",
        defensive_only=True,
        note=(
            "Thornmail: Thorns - when struck by an Attack, deal magic damage to attacker "
            "and apply 40% Wounds. Counter-damage on being HIT, not outgoing DPS; "
            "defensive-only"
        ),
    ),
    "3041": ItemEffect(
        item_id="3041",
        name="Mejai's Soulstealer",
        # Phase 4 batch 54 (2026-05-04): promoted. Glory grants 5 AP per
        # takedown stack; DDragon's FlatMagicDamageMod only carries the base
        # 20 AP. AP-scaling procs (Lich Bane, Nashor's) and Rabadon's
        # amplification both see the stacked total via compute_dps.
        #
        # RM-94 (2026-07-24): re-valued 125.0 -> 25.0. The original pin took
        # the 25-stack CAP and justified it with the sustained-peak convention
        # used for Black Cleaver's full-stack armor reduction and Riftmaker's
        # full ramp. That is a category error and the sibling registry
        # ``_item_health_stack`` already says so in-line ("the RM-94 Mejai's
        # failure mode"). BC and Riftmaker accrue from the caster's OWN combat
        # output inside one fight, saturate in seconds and reset out of combat,
        # so the modelled rotation generates every stack and full value IS the
        # steady state. Glory accrues from TAKEDOWNS across the whole game and
        # loses 10 stacks per death (DDragon 16.14.1: "Takedowns grant Glory,
        # up to 25. 10 Glory is lost on death. Gain 5 Ability Power per
        # Glory"). No simulated rotation produces a single stack; full stacks
        # is a game-state precondition - already having won - and pinning it
        # ranked Mejai's invariantly into the mage head at 2-5% real presence.
        #
        # THE COUNT IS THE ONLY JUDGEMENT (same framing as the
        # ``_item_health_stack`` proc curve: exact per-unit, conservative
        # assumed count). Per-stack AP is exact and sourced. The count is
        # bounded above by the item's own "ahead" threshold - Riot attaches the
        # move-speed bonus at 10+ Glory, and 10 is also the single-death loss,
        # so any sustained count >= 10 assumes the snowball already landed.
        # Assumed = midpoint of the not-yet-ahead band 0..10 = 5 stacks.
        # Deliberately LOW rather than centred on an unobservable takedown
        # distribution, matching the sibling curve's never-over-state rule, and
        # midpoint-of-band matches the field's only other occupant (Innervating
        # Locket 447104 = 175.0, midpoint of its 100-250 range).
        bonus_ap_stacked=25.0,
        note=(
            "Mejai's Soulstealer: Glory +25 stacked AP (assumed 5 of 25 stacks "
            "x 5 AP; expected-value, NOT the full-stack peak - Glory is earned "
            "across the game and 10 stacks are lost per death, so RM-94 rejects "
            "the Black Cleaver / Riftmaker single-fight ramp precedent)"
        ),
    ),
    "3140": ItemEffect(
        item_id="3140",
        name="Quicksilver Sash",
        defensive_only=True,
        note=(
            "Quicksilver Sash: Quicksilver - removes all CC debuffs. "
            "Active-only crowd-control cleanse; no DPS contribution"
        ),
    ),
    "3155": ItemEffect(
        item_id="3155",
        name="Hexdrinker",
        defensive_only=True,
        unique_passive_key="lifeline",
        # ENGINE 1.27.0 (2026-05-21): Phase 1.5 shield throughput.
        # Meraki 16.10.1: melee "110 to 280 for 11 levels" with levels=
        # 1;9 to 18 - same shape as Shieldbow / Maw family. Below L9 =
        # 110, lerp L9 -> L18 ramps 110 -> 280. Ranged is 75% (82.5 to
        # 210). Magic-only damage absorption.
        shield=ItemShield(
            damage_type=MAGICAL,
            flat=110.0,
            level_lerp_low=9,
            level_lerp_high=18,
            level_lerp_high_value=280.0,
            ranged_modifier=0.75,
            note="Hexdrinker Lifeline magic shield (Meraki 16.10.1)",
        ),
        note=(
            "Hexdrinker: Lifeline - when magic damage would drop HP below 30%, "
            "grants magic damage shield. Joins lifeline unique-passive family "
            "(Immortal Shieldbow, Sterak's, Maw, Seraph's, Protoplasm Harness)"
        ),
    ),
    "4632": ItemEffect(
        item_id="4632",
        name="Verdant Barrier",
        defensive_only=True,
        note=(
            "Verdant Barrier: Annul - grants a Spell Shield blocking the next enemy "
            "Ability. Active-like defensive mechanic, no DPS contribution"
        ),
    ),
    "3047": ItemEffect(
        item_id="3047",
        name="Plated Steelcaps",
        defensive_only=True,
        # R80 (1.181.0): Plating 10% incoming basic-attack damage reduction now
        # carries EHP credit via the physical-denominator item_aa_dr_multiplier
        # (default-OFF assume_item_aa_dr). Still no DPS proc.
        basic_attack_damage_reduction=0.10,
        note=(
            "Plated Steelcaps: Plating - reduces incoming basic-attack damage by 10% "
            "(Meraki 16.13.1). Incoming damage reduction, no DPS proc"
        ),
    ),

    # -- Phase 4 batch 41 (2026-05-04): Arena 226xxx mirrors --------------
    # All 28 missing 226xxx Arena pool items. DDragon maps 226xxx -> SR
    # counterpart via ID - 220000. Arena pool versions share the same
    # passive-effect coefficients as their SR counterparts unless otherwise
    # noted. 14 active + 14 defensive_only.

    # -- 14 active promotions (same schema as SR counterpart) --------------

    "226610": ItemEffect(
        item_id="226610",
        name="Sundered Sky",
        periodics=(PeriodicProc(
            name="Lightshield Strike",
            # Iter 16 (2026-05-20): mirrors SR 6610 recalibration vs
            # Meraki 16.10.1 - "70 + 80% total AD" tracks the
            # empowered-crit delta on the next AA.
            bonus_damage=lambda c: 70.0 + 0.8 * (c.base_ad + c.bonus_ad),
            damage_type=PHYSICAL,
            every_n_seconds=8.0,
        ),),
        # ENGINE 1.28.0 (2026-05-21): Phase 6 healing throughput - Arena
        # mirror of SR 6610 Lightshield Strike heal. 100% base AD melee /
        # 50% base AD ranged per trigger. Phase 6.5 (2026-05-21): missing-
        # HP additive 6% (mirror of SR 6610).
        heal=ItemHeal(
            base_ad_scaling=1.0,
            missing_hp_pct=0.06,
            ranged_modifier=0.5,
            note="Sundered Sky Arena Lightshield Strike base AD heal + 6% missing HP",
        ),
        note=(
            "Sundered Sky (Arena 226610): same as SR 6610 - Lightshield "
            "Strike 70 + 80% total AD damage every 8s + 100% base AD heal "
            "melee / 50% ranged + 6% missing HP per trigger"
        ),
    ),
    "226631": ItemEffect(
        item_id="226631",
        name="Stridebreaker",
        periodics=(PeriodicProc(
            name="Cleave",
            bonus_damage=lambda c: max(0.0, c.targets_in_rotation - 1.0)
                * 0.40 * (c.base_ad + c.bonus_ad),
            damage_type=PHYSICAL,
            every_n_attacks=1,
        ),),
        unique_passive_key="hydra_cleave",
        physical_burst_total_ad_ratio=0.80,
        note="Stridebreaker (Arena 226631): same as SR 6631 - Cleave 40% AD to other enemies; Breaking Shockwave active 80% total AD physical AoE now modeled - rides the DSV8 assume_physical_burst burst window (Meraki 16.13.1, R113)",
    ),
    "226653": ItemEffect(
        item_id="226653",
        name="Liandry's Anguish",
        damage_amp_pct=0.06,
        periodics=(
            PeriodicProc(
                name="Torment",
                every_n_seconds=1.0,
                bonus_damage=lambda c: 0.02 * c.target_max_hp,
                damage_type=MAGICAL,
                ability_dot=True,
            ),
        ),
        note="Liandry's Anguish (Arena 226653): same as SR 6653 - Suffering 6% damage amp + Torment 2% target max HP/s magic burn (DSV1)",
    ),
    "226662": ItemEffect(
        item_id="226662",
        name="Iceborn Gauntlet",
        periodics=(PeriodicProc(
            name="Spellblade",
            bonus_damage=lambda c: 1.50 * c.base_ad,
            damage_type=PHYSICAL,
            every_n_seconds=3.0,
        ),),
        unique_passive_key="spellblade",
        note="Iceborn Gauntlet (Arena 226662): same as SR 6662 - Spellblade 150% base AD, every ~3s",
    ),
    "226664": ItemEffect(
        item_id="226664",
        name="Hollow Radiance",
        periodics=(PeriodicProc(
            name="Immolate",
            # Iter 8 (2026-05-19): mirrors SR 6664 corrected to Meraki
            # 16.10.1 - 15 + 1% bonus_hp (was 12 + 1.5% bonus_hp).
            bonus_damage=lambda c: c.targets_in_rotation
                * (15.0 + 0.010 * c.caster_bonus_hp),
            damage_type=MAGICAL,
            every_n_seconds=1.0,
        ),),
        unique_passive_key="immolate",
        # R70 (2026-07-03): Desolate eruption mirrors SR 6664 exactly (Arena
        # mirror convention - 226664 has no own Meraki entry).
        # PROVENANCE (corrected 2026-08-08, note-only): 226664 is ABSENT from
        # items_meraki.json at EVERY patch on disk (16.10.1 - 16.15.1), and its
        # DDragon description leaves the Immolate magnitude placeholder EMPTY.
        # Both the Immolate formula and the Desolate eruption above are
        # therefore ASSUMED SR-parity inheritances from 6664, not measurements
        # of 226664. The STAT LINE is measured to DIVERGE: DDragon 16.15.1
        # gives 226664 450 HP / 40 MR / 10 AH with NO "100% Base Health Regen"
        # line, against SR 6664 400 HP / 40 MR / 10 AH / 100% Base Health
        # Regen. Per R161 doctrine B an Arena mirror credits its OWN DDragon
        # stat line, not the SR twin's.
        takedown_eruption_base=60.0,
        takedown_eruption_bonus_hp_ratio=0.04,
        note=(
            "Hollow Radiance (Arena 226664): Immolate 15+1% bonus HP per "
            "second is ASSUMED equal to SR 6664 - no source carries the Arena "
            "row (absent from Meraki at every patch on disk; DDragon magnitude "
            "placeholder empty). The stat line is MEASURED to differ from the "
            "twin (226664 450 HP / 40 MR / 10 AH and NO 100% base health "
            "regen, vs 6664 400 HP plus that regen), per R161 doctrine B. "
            "Desolate champion-takedown eruption modeled R70 on "
            "assume_takedown (400% Immolate = 60 + 4% bonus HP magic within "
            "500), likewise inherited; 200% non-champion kill eruption "
            "unmodeled"
        ),
    ),
    "226668": ItemEffect(
        item_id="226668",
        name="Ultra Hydra",
        # NET-NEW in DDragon 16.17.1 (absent from 16.16.1 entirely): an
        # Arena-only 6000g standalone (no from/into, maps {"12": True}).
        # <stats> block: 200 AD / 25 Ability Haste / 25 Lethality / 1000 HP
        # / 15% Omnivamp.
        #
        # Lethality is the ONLY magnitude credited here, for the R152 reason
        # Profane Hydra 6698 records: lethality has no DDragon stats key and
        # stats.ITEM_STAT_KEY_MAP has no lethality entry, so ITEM_EFFECTS is
        # the sole credit path and an unregistered id reads a silent 0.0 (the
        # R143 / f7c49de5 defect class).
        lethality=25.0,
        # Hydra family unique - shares the cleave lockout with 6698 / 3748 /
        # 6673 so a live inventory cannot double-credit two hydras.
        unique_passive_key="hydra_cleave",
        # DELIBERATELY NOT MODELLED: the "Ultra Hydra" active carries NO
        # magnitude anywhere in the DDragon description (unlike Profane
        # Hydra, whose 80% total-AD Heretical Cleave came from Meraki
        # 16.13.1), and Meraki has no 226668 row at all. Inventing a cleave
        # ratio here would be an unsourced number, so the active stays out
        # until a real magnitude source exists - start tight, widen on
        # evidence. Omnivamp likewise deferred: _item_omnivamp.py sources its
        # fractions from items_meraki.json, which does not carry this id.
        note="Ultra Hydra (Arena 226668, NEW at 16.17.1): 25 lethality credited; cleave active unmodelled (no DDragon/Meraki magnitude). Not yet a build candidate - absent from the pinned 16.15.1 DS snapshot, so it scores only when handed in a live inventory.",
    ),
    "226672": ItemEffect(
        item_id="226672",
        # DDragon 226672 == "Kraken Slayer" (Arena mirror of 6672), NOT
        # Navori Flickerblade - the prior name/note/formula were a
        # mislabel (Navori 6675's passive is Transcendence CDR, it has
        # no Bring It Down proc). Corrected to mirror SR 6672 exactly.
        name="Kraken Slayer",
        periodics=(PeriodicProc(
            name="Bring It Down",
            every_n_attacks=3,
            # Same melee ramp as SR 6672: 150 (L1) -> 200 (L11+).
            bonus_damage=lambda c: 150.0 + 5.0 * (min(c.level, 11) - 1),
            damage_type=PHYSICAL,
        ),),
        note=(
            "Kraken Slayer (Arena 226672): same as SR 6672 - Bring It "
            "Down 150 (L1) -> 200 (L11+) every 3rd attack"
        ),
    ),
    "226692": ItemEffect(
        item_id="226692",
        name="Eclipse",
        periodics=(PeriodicProc(
            name="Ever Rising Moon",
            bonus_damage=lambda c: 0.06 * c.target_max_hp,
            damage_type=PHYSICAL,
            every_n_attacks=2,
        ),),
        # R97 (2026-07-10): Arena mirror of 6692's shield half, same seam. The
        # damage half above is already modeled; the shield rides the default-OFF
        # assume_eclipse_shield seam identically to SR 6692.
        shield=ItemShield(
            damage_type=ANY,
            flat=160.0,
            bonus_ad_scaling=0.40,
            ranged_modifier=0.5,
            default_off=True,
            note="Eclipse (Arena 226692) Ever Rising Moon shield; mirrors SR 6692 (Meraki-absent; DDragon + SR-mirror grounding)",
        ),
        note="Eclipse (Arena 226692): same as SR 6692 - Ever Rising Moon 6% target max HP every 2 attacks",
    ),
    "226693": ItemEffect(
        item_id="226693",
        name="Prowler's Claw",
        lethality=22.0,
        note="Prowler's Claw (Arena 226693): same as SR 6693 - 22 lethality",
    ),
    "226694": ItemEffect(
        item_id="226694",
        name="Serylda's Grudge",
        # R161 doctrine B: Arena feed states 45% armor pen vs SR 6694's 35%;
        # the explicitly-stated Arena value wins over SR inheritance.
        # DDragon 16.17.1 moved the Arena magnitude 40% -> 45% while leaving
        # the SR twin at 35%; pen percent has no DDragon stats key, so the
        # <stats> description block is the only source and this entry is the
        # only credit path (same posture as the R152 lethality parity note).
        armor_pen_pct=0.45,
        unique_passive_key="last_whisper",
        note="Serylda's Grudge (Arena 226694): 45% armor penetration per the Arena feed at 16.17.1 (SR 6694 carries 35%)",
    ),
    "226696": ItemEffect(
        item_id="226696",
        name="Axiom Arc",
        lethality=18.0,
        note="Axiom Arc (Arena 226696): same as SR 6696 - 18 lethality",
    ),
    "226697": ItemEffect(
        item_id="226697",
        name="Hubris",
        lethality=18.0,
        # DSV2 (1.125.0): Arena mirror of SR 6697 Eminence takedown AD.
        takedown_bonus_ad_base=15.0,
        takedown_bonus_ad_per_stack=2.0,
        note="Hubris (Arena 226697): 18 lethality + Eminence takedown AD 15 (+2/stack)",
    ),
    "226698": ItemEffect(
        item_id="226698",
        name="Profane Hydra",
        # R152 lethality stat-block parity: DDragon 16.14.1 <stats> carries
        # 18 Lethality (same as SR 6698); previously credited 0.0.
        lethality=18.0,
        periodics=(PeriodicProc(
            name="Cleave",
            bonus_damage=lambda c: max(0.0, c.targets_in_rotation - 1.0)
                * 0.40 * (c.base_ad + c.bonus_ad),
            damage_type=PHYSICAL,
            every_n_attacks=1,
        ),),
        unique_passive_key="hydra_cleave",
        physical_burst_total_ad_ratio=0.80,
        note="Profane Hydra (Arena 226698): same as SR 6698 - Cleave 40% AD to other enemies; Heretical Cleave active 80% total AD physical AoE now modeled - rides the DSV8 assume_physical_burst burst window (Meraki 16.13.1, R113)",
    ),
    "226699": ItemEffect(
        item_id="226699",
        name="Voltaic Cyclosword",
        periodics=(PeriodicProc(
            name="Firmament",
            # Iter 15 (2026-05-20): mirror SR 6699 - Firmament is now
            # flat 100 bonus physical (Meraki 16.10.1), 25% bonus AD
            # scaling clause stripped.
            bonus_damage=100.0,
            damage_type=PHYSICAL,
            every_n_seconds=4.0,
        ),),
        # R161 doctrine B: Arena feed states 20 Lethality vs SR 6699's 10;
        # the explicitly-stated Arena value wins over SR inheritance. The
        # Firmament coefficient above still rides the SR mirror (Meraki has
        # no 226699 entry) - only the stated base stat line flips.
        lethality=20.0,
        note="Voltaic Cyclosword (Arena 226699): Energized 100 flat bonus physical (SR 6699 mirror) + 20 lethality per the Arena feed (SR 6699 carries 10)",
    ),
    "226701": ItemEffect(
        item_id="226701",
        name="Opportunity",
        # R161 doctrine B: Arena feed states 15 Lethality vs SR 6701's 18;
        # the explicitly-stated Arena value wins over SR inheritance.
        lethality=15.0,
        note="Opportunity (Arena 226701): 15 lethality per the Arena feed (SR 6701 carries 18)",
    ),

    # -- 14 defensive_only Arena mirrors -----------------------------------

    "226333": ItemEffect(
        item_id="226333",
        name="Death's Dance",
        # ENGINE 1.57.0 (2026-05-25): Arena mirror of SR 6333 Defy heal -
        # same takedown-gated 75% bonus AD over 2s schema. Arena fights
        # tend to be shorter (multi-round cycles) but the operator-tunable
        # _TAKEDOWN_RATE_PER_FIGHT constant is mode-agnostic by design;
        # mode-specific calibration can layer on top via a future per-mode
        # override. The Ignore Pain timing-shift piece is also not modeled
        # (parallel to SR). Promoted from defensive_only.
        heal=ItemHeal(
            bonus_ad_scaling=0.75,
            takedown_gated=True,
            note="Death's Dance Defy (Arena 226333): 75% bonus AD heal on takedown",
        ),
        note=(
            "Death's Dance (Arena 226333): Ignore Pain damage smoothing "
            "(timing-shift, not modeled) + Defy 75% bonus AD heal over 2s "
            "on takedown - gated by _TAKEDOWN_RATE_PER_FIGHT"
        ),
    ),
    "226609": ItemEffect(
        item_id="226609",
        name="Chempunk Chainsword",
        defensive_only=True,
        note="Chempunk Chainsword (Arena 226609): Grievous Wounds on damage - anti-heal utility, no DPS proc",
    ),
    "226616": ItemEffect(
        item_id="226616",
        name="Staff of Flowing Water",
        defensive_only=True,
        note="Staff of Flowing Water (Arena 226616): Rapids AP/AS aura - support enchant, no self DPS",
    ),
    "226617": ItemEffect(
        item_id="226617",
        name="Moonstone Renewer",
        defensive_only=True,
        note="Moonstone Renewer (Arena 226617): Starlit Grace heal aura - support enchant, no DPS",
    ),
    "226620": ItemEffect(
        item_id="226620",
        name="Echoes of Helia",
        defensive_only=True,
        note="Echoes of Helia (Arena 226620): Soul Siphon soul charge heal - support, no DPS",
    ),
    "226621": ItemEffect(
        item_id="226621",
        name="Dawncore",
        defensive_only=True,
        note="Dawncore (Arena 226621): empowers other enchanter items - support, no DPS proc",
    ),
    "226630": ItemEffect(
        item_id="226630",
        name="Goredrinker",
        defensive_only=True,
        # R74 (1.178.0): the old note ("sustain only, no DPS contribution")
        # was factually wrong - Thirsting Slash LEADS with damage. Meraki
        # 16.13.1: "Deal 175% '''base''' AD physical damage to enemies in a
        # 450 radius centered around you." That one-cast active magnitude
        # rides the NEW DSV8 assume_physical_burst seam (physical analogue
        # of the R69 Rocketbelt DSV6 pin; scales off BASE AD only, so no
        # flat term). The heal side (20% AD + 8% missing health per champion
        # hit) stays UNMODELED. DPS side intentionally unmodeled: long-CD
        # active, no PeriodicProc, no double-count. defensive_only stays
        # True - the flag documents "no sustained-DPS proc", which still
        # holds; it gates nothing in the engine (verified R69, re-verified
        # R74: doc-only, zero engine consumers).
        physical_burst_base_ad_ratio=1.75,
        note=(
            "Goredrinker (Arena 226630): Thirsting Slash active 175% base AD "
            "physical AoE (450 radius) once per cast - rides the DSV8 "
            "assume_physical_burst seam; heal (20% AD + 8% missing HP per "
            "champion hit) unmodeled; no PeriodicProc (Meraki 16.13.1)"
        ),
    ),
    "226655": ItemEffect(
        item_id="226655",
        name="Luden's Echo",
        # Phase 4 batch 52 (2026-05-04): promoted. Same Echo passive as SR 6655.
        # DDragon strips numbers but Arena mirrors SR; using Meraki SR values:
        # 75 (+5% AP) magic / 12s per champion.
        periodics=(PeriodicProc(
            name="Echo",
            bonus_damage=lambda c: 75.0 + 0.05 * c.ap,
            damage_type=MAGICAL,
            every_n_seconds=12.0,
        ),),
        # RM-323: single-Echo burst-window magnitude from THIS row's own note
        # (doctrine B). The Arena Echo mechanic TEXT differs from SR 6655's
        # (Arena consumes all charges across the primary plus one nearby target
        # per charge; SR fires remaining Echoes at 20%), but DDragon 16.15.1
        # publishes no magnitude on either id, so the note stands and the
        # unmodeled AoE spread stays unmodeled - the primary hit is credited.
        magic_burst_base=75.0,
        magic_burst_ap_ratio=0.05,
        note="Luden's Echo (Arena 226655): Echo 75 (+5% AP) magic / 12s (SR Meraki values; AoE splash not modeled)",
    ),
    "226657": ItemEffect(
        item_id="226657",
        name="Rod of Ages",
        defensive_only=True,
        note="Rod of Ages (Arena 226657): stat-stack ramp - no DPS proc; same as SR 6657",
    ),
    "226665": ItemEffect(
        item_id="226665",
        name="Jak'Sho, The Protean",
        defensive_only=True,
        note="Jak'Sho (Arena 226665): Voidborn Resilience stacking resist ramp - tank, no DPS",
    ),
    "226673": ItemEffect(
        item_id="226673",
        name="Immortal Shieldbow",
        defensive_only=True,
        unique_passive_key="lifeline",
        # RM-104 (2026-07-19): mirror carried the lifeline family key but no
        # shield field, so it credited ZERO EHP on every Arena build. Unlike
        # the Kaenic mirror this is always-on (default_off False, like its
        # base) and needs no flag. Magnitude INHERITED-UNSOURCED from SR 6673:
        # no repo feed states the mirror's curve. This is the one mirror of
        # the four whose base stats are identical to the SR item (55 AD, and
        # its shield is a flat level curve rather than a stat scaling), so
        # inheritance is safe on its face here.
        shield=ItemShield(
            damage_type=ANY,
            flat=400.0,
            level_lerp_low=9,
            level_lerp_high=18,
            level_lerp_high_value=700.0,
            ranged_modifier=0.80,
            note="Immortal Shieldbow (Arena 226673) Lifeline (INHERITED-UNSOURCED from SR 6673)",
        ),
        note="Immortal Shieldbow (Arena 226673): Lifeline shield; joins lifeline unique-passive family",
    ),
    "226675": ItemEffect(
        item_id="226675",
        name="Navori Flickerblades",
        defensive_only=True,
        note="Navori Flickerblades (Arena 226675): Quicken CDR-on-crit - utility, no DPS proc",
    ),
    "226676": ItemEffect(
        item_id="226676",
        name="The Collector",
        # R161 doctrine B: Arena feed states 12 Lethality vs SR 6676's 10;
        # the explicitly-stated Arena value wins over SR inheritance.
        lethality=12.0,
        # DSV2 (1.125.0): Arena mirror of SR 6676 Death execute finisher.
        execute_max_hp_pct=0.05,
        note="The Collector (Arena 226676): 12 Lethality per the Arena feed (SR 6676 carries 10); "
             "Death execute below 5% HP valued as a kill-state finisher under assume_takedown; "
             "Taxes (25g) is out-of-combat. lethality feeds the rotation.",
    ),
    "226695": ItemEffect(
        item_id="226695",
        name="Serpent's Fang",
        defensive_only=True,
        # R152 lethality stat-block parity: DDragon 16.14.1 <stats> carries
        # 19 Lethality for the Arena mirror while SR 6695 carries 15. That
        # divergence is real in the 16.14.1 feed, so each id is credited at
        # its OWN number - deliberately NOT normalized to the SR value.
        lethality=19.0,
        # R75 DSV9 (1.179.0): Arena mirror of SR 6695 Shield Reaver.
        # Meraki 16.13.1 carries NO 226695 entry, so the mirror truth is
        # DDragon items.json 226695 (map 30 only, same Shield Reaver
        # passive, explicit melee/ranged performance split) plus the
        # batch-42 Arena-mirror convention (mirrors share their SR
        # counterpart's passive coefficients). Pinned identical to SR
        # 6695: one-time ACTIVE-shield cut on first affliction, valued by
        # the DSV9 assume_shielded_target seam; the sustained
        # shields-gained reduction within the 3s venom stays UNMODELED.
        # defensive_only stays True (doc-only, zero engine consumers -
        # verified R69, re-verified R74).
        shield_cut_melee_pct=0.50,
        shield_cut_ranged_pct=0.35,
        note=(
            "Serpent's Fang (Arena 226695): mirrors SR 6695 Shield Reaver - "
            "venom 3s, cuts ACTIVE shields once by 50% melee / 35% ranged "
            "on first affliction (DSV9 assume_shielded_target seam); "
            "sustained shields-gained reduction unmodeled (SR 6695 Meraki "
            "16.13.1 + DDragon 226695 map-30 mirror)"
        ),
    ),

    # -- Phase 4 batch 42 (2026-05-04): 222xxx/224xxx Arena + 32xxxx ARAM mirrors --
    # 35 entries: 10 active + 25 defensive_only.
    # All share the same passive coefficients as their SR counterparts
    # (ID - 220000 for 22xxxx; ID - 320000 for 32xxxx).

    # -- 222xxx Arena mirrors (base 2xxx) ----------------------------------

    "222502": ItemEffect(
        item_id="222502",
        name="Unending Despair",
        periodics=(PeriodicProc(
            name="Anguish",
            every_n_seconds=4.0,
            bonus_damage=lambda c: 0.03 * c.caster_bonus_hp,
            damage_type=MAGICAL,
        ),),
        note="Unending Despair (Arena 222502): same as SR 2502 - Anguish 3% caster bonus HP magic every 4s; SELF-heal half in _item_proc_heal.py (DEFAULT-OFF)",
    ),
    "222503": ItemEffect(
        item_id="222503",
        name="Blackfire Torch",
        periodics=(PeriodicProc(
            name="Baleful Blaze",
            every_n_seconds=0.5,
            bonus_damage=lambda c: 10.0 + 0.01 * c.ap,
            damage_type=MAGICAL,
            ability_dot=True,
        ),),
        note="Blackfire Torch (Arena 222503): same as SR 2503 - Baleful Blaze 10+1% AP magic every 0.5s (60+6% AP total/3s, DSV1 Meraki re-pin)",
    ),
    "222504": ItemEffect(
        item_id="222504",
        name="Kaenic Rookern",
        defensive_only=True,
        # RM-104 (2026-07-19): this mirror had NO shield field, so
        # _collect_shields skipped it at the `eff.shield is None` continue
        # AND the default-OFF arming line armed only iid == "2504" - a
        # double gate, either half of which alone zeroed the credit.
        # Magnitude is INHERITED-UNSOURCED: DDragon carries 222504 but
        # scrubs the shield magnitude from its text, and items_meraki.json
        # (the only feed with shield formulas) has zero Arena mirror
        # entries, so no feed in this repo states it. Inheriting the base's
        # 15%-max-HP coefficient is deliberate, not assumed. The mirror's
        # smaller HP grant (350 vs the base's 400) still changes the OUTPUT,
        # because the coefficient is applied to the champion's resolved
        # max_hp - the retune flows through without touching this number.
        # Sourced-but-unmodelled retune: DDragon states the mirror's
        # Magebane window is 10s vs the base's 15s. ItemShield has no
        # uptime field (the gate is the binary default_off seam), so this
        # changes nothing numerically; it only makes the mirror's uptime
        # strictly better than the base's, i.e. default-OFF is if anything
        # MORE conservative here.
        shield=ItemShield(
            damage_type=MAGICAL,
            max_hp_scaling=0.15,
            default_off=True,
            note="Kaenic Rookern (Arena 222504) Magebane 15% max HP (INHERITED-UNSOURCED from SR 2504)",
        ),
        note="Kaenic Rookern (Arena 222504): Magebane magic-damage shield (15% max HP, default-OFF seam); no DPS contribution",
    ),
    "222510": ItemEffect(
        item_id="222510",
        name="Dusk and Dawn",
        periodics=(PeriodicProc(
            name="Spellblade",
            bonus_damage=lambda c: 0.75 * c.base_ad + 0.10 * c.ap,
            damage_type=MAGICAL,
            every_n_seconds=1.5,
        ),),
        unique_passive_key="spellblade",
        note="Dusk and Dawn (Arena 222510): same as SR 2510 - Spellblade 75% base AD + 10% AP magical every 1.5s",
    ),
    "222512": ItemEffect(
        item_id="222512",
        name="Fiendhunter Bolts",
        defensive_only=True,
        note="Fiendhunter Bolts (Arena 222512): anti-shield utility; no DPS contribution",
    ),
    "222517": ItemEffect(
        item_id="222517",
        name="Endless Hunger",
        defensive_only=True,
        note="Endless Hunger (Arena 222517): Famine haste + Feast omnivamp; no DPS contribution",
    ),
    "222522": ItemEffect(
        item_id="222522",
        name="Actualizer",
        defensive_only=True,
        note="Actualizer (Arena 222522): utility-focused stat stick; no DPS proc",
    ),
    "222523": ItemEffect(
        item_id="222523",
        name="Hexoptics C44",
        defensive_only=True,
        note="Hexoptics C44 (Arena 222523): vision/utility passive; no DPS contribution",
    ),
    "222525": ItemEffect(
        item_id="222525",
        name="Protoplasm Harness",
        defensive_only=True,
        unique_passive_key="lifeline",
        note=("Protoplasm Harness (Arena 222525): Lifeline max-Health grant then heal, NOT a shield; "
              "joins lifeline unique-passive family"),
    ),

    # -- 224xxx Arena mirrors (base 4xxx) ----------------------------------

    "224004": ItemEffect(
        item_id="224004",
        name="Spectral Cutlass",
        # R161 doctrine B: Arena feed states 21 Lethality vs SR 4004's 15;
        # the explicitly-stated Arena value wins over SR inheritance.
        lethality=21.0,
        note="Spectral Cutlass (Arena 224004): 21 lethality per the Arena feed (SR 4004 carries 15)",
    ),
    "224005": ItemEffect(
        item_id="224005",
        name="Imperial Mandate",
        defensive_only=True,
        note="Imperial Mandate (Arena 224005): Coordinated Fire mark - support proc, no self DPS",
    ),
    "224401": ItemEffect(
        item_id="224401",
        name="Force of Nature",
        defensive_only=True,
        note="Force of Nature (Arena 224401): Absorb MR-stack ramp - tank defensive; no DPS proc",
    ),
    "224628": ItemEffect(
        item_id="224628",
        name="Horizon Focus",
        defensive_only=True,
        note="Horizon Focus (Arena 224628): Hypershot reveal-only like SR 4628 (DDragon 16.13.1); legacy slow/immobilize amp reworked out, no DPS contribution exists to model (R116)",
    ),
    "224629": ItemEffect(
        item_id="224629",
        name="Cosmic Drive",
        defensive_only=True,
        note="Cosmic Drive (Arena 224629): Spelldance movement speed amp - utility, no DPS proc",
    ),
    "224633": ItemEffect(
        item_id="224633",
        name="Riftmaker",
        damage_amp_pct=0.08,
        ap_per_bonus_hp_pct=0.02,
        note="Riftmaker (Arena 224633): same as SR 4633 - Void Corruption 8% damage amp + 2% bonus HP -> AP",
    ),
    "224645": ItemEffect(
        item_id="224645",
        name="Shadowflame",
        # R161 doctrine B: Arena feed states 10 flat magic pen vs SR 4645's
        # 15; the explicitly-stated Arena value wins over SR inheritance.
        magic_pen_flat=10.0,
        note="Shadowflame (Arena 224645): Cinderbloom 10 flat magic pen per the Arena feed (SR 4645 carries 15)",
    ),
    "224646": ItemEffect(
        item_id="224646",
        name="Stormsurge",
        # Phase 4 batch 53 (2026-05-04): Squall proc added; mirrors SR 4646.
        magic_pen_flat=15.0,
        periodics=(PeriodicProc(
            name="Squall",
            bonus_damage=lambda c: 125.0 + 0.10 * c.ap,
            damage_type=MAGICAL,
            every_n_seconds=30.0,
        ),),
        # RM-323: single-Squall burst-window magnitude, taken from THIS row's
        # own note (doctrine B) - DDragon 16.15.1 gives the Squall text but no
        # number for 224646 or SR 4646. Credited once per burst combo; the
        # periodic above keeps the sustained-DPS valuation, so no double-count.
        magic_burst_base=125.0,
        magic_burst_ap_ratio=0.10,
        note="Stormsurge (Arena 224646): same as SR 4646 - 15 flat magic pen + Squall 125 (+10% AP) magic / 30s",
    ),

    # -- 32xxxx ARAM mirrors ------------------------------------------------

    "323003": ItemEffect(
        item_id="323003",
        name="Archangel's Staff",
        bonus_ap_pct_bonus_mp=0.01,
        note="Archangel's Staff (ARAM 323003): same as SR 3003 - Awe +1% bonus mana as AP",
    ),
    "323004": ItemEffect(
        item_id="323004",
        name="Manamune",
        bonus_ad_pct_max_mp=0.02,
        note="Manamune (ARAM 323004): same as SR 3004 - Awe +2% max mana as bonus AD",
    ),
    "323050": ItemEffect(
        item_id="323050",
        name="Zeke's Convergence",
        defensive_only=True,
        # R70 slice A: ARAM mirror of SR 3050 - same Frostfire Tempest
        # numbers per the mirror convention (no Meraki entry of its own).
        # SELF storm on ult cast, NOT the stale "Conduit ally aura".
        # Cryocombustion haste lives in _item_ability_haste.py; DPS side
        # intentionally unmodeled (long-CD ult-triggered, no
        # PeriodicProc, no double-count).
        magic_burst_base=150.0,
        magic_burst_ap_ratio=0.0,
        note=(
            "Zeke's Convergence (ARAM 323050): Frostfire Tempest SELF "
            "storm on ult cast (150 flat, mirrors SR 3050) on the DSV6 "
            "assume_magic_burst seam; Cryocombustion haste lives in "
            "_item_ability_haste.py; DPS side intentionally unmodeled"
        ),
    ),
    "323075": ItemEffect(
        item_id="323075",
        name="Thornmail",
        defensive_only=True,
        note="Thornmail (ARAM 323075): Thorns reflected damage - counter-damage on being hit; no self proc",
    ),
    "323107": ItemEffect(
        item_id="323107",
        name="Redemption",
        defensive_only=True,
        note="Redemption (ARAM 323107): Sanctify active AoE heal - support, no self DPS",
    ),
    "323109": ItemEffect(
        item_id="323109",
        name="Knight's Vow",
        defensive_only=True,
        note="Knight's Vow (ARAM 323109): Pledge ally bond - support, no self DPS",
    ),
    "323110": ItemEffect(
        item_id="323110",
        name="Frozen Heart",
        defensive_only=True,
        # R86 (1.182.0): mirror of SR 3110 - -20% nearby enemy AS physical-EHP seam.
        enemy_attack_speed_slow=0.20,
        note="Frozen Heart (ARAM 323110): Winter's Caress AS-slow aura - defensive, no DPS proc",
    ),
    "323119": ItemEffect(
        item_id="323119",
        name="Winter's Approach",
        defensive_only=True,
        note="Winter's Approach (ARAM 323119): stat-stack ramp to Fimbulwinter - no DPS proc",
    ),
    "323190": ItemEffect(
        item_id="323190",
        name="Locket of the Iron Solari",
        defensive_only=True,
        note="Locket (ARAM 323190): Consecrate/Devotion shield aura - support, no self DPS",
    ),
    "323222": ItemEffect(
        item_id="323222",
        name="Mikael's Blessing",
        defensive_only=True,
        note="Mikael's Blessing (ARAM 323222): Purify active CC cleanse - support, no self DPS",
    ),
    "323504": ItemEffect(
        item_id="323504",
        name="Ardent Censer",
        defensive_only=True,
        note="Ardent Censer (ARAM 323504): Sanctify heal/shield buff - support aura, no self DPS",
    ),
    "324005": ItemEffect(
        item_id="324005",
        name="Imperial Mandate",
        defensive_only=True,
        note="Imperial Mandate (ARAM 324005): Coordinated Fire - support proc, no self DPS",
    ),
    "326616": ItemEffect(
        item_id="326616",
        name="Staff of Flowing Water",
        defensive_only=True,
        note="Staff of Flowing Water (32xxxx 326616): Rapids aura - support enchanter, no self DPS",
    ),
    "326617": ItemEffect(
        item_id="326617",
        name="Moonstone Renewer",
        defensive_only=True,
        note="Moonstone Renewer (32xxxx 326617): Starlit Grace heal aura - support, no self DPS",
    ),
    "326620": ItemEffect(
        item_id="326620",
        name="Echoes of Helia",
        defensive_only=True,
        note="Echoes of Helia (32xxxx 326620): Soul Siphon soul charge - support, no self DPS",
    ),
    "326621": ItemEffect(
        item_id="326621",
        name="Dawncore",
        defensive_only=True,
        note="Dawncore (32xxxx 326621): empowers other enchanter items - support, no self DPS",
    ),
    "326657": ItemEffect(
        item_id="326657",
        name="Rod of Ages",
        defensive_only=True,
        note="Rod of Ages (32xxxx 326657): stat-stack ramp - no DPS proc",
    ),
    "328020": ItemEffect(
        item_id="328020",
        name="Abyssal Mask",
        magic_amp_pct=0.12,
        note="Abyssal Mask (ARAM 328020): same as SR 8020 - Unmake 12% more magic damage to nearby enemies",
    ),

    # -- Phase 4 batch 43 (2026-05-04): 223xxx Arena mirrors (base 3xxx) --
    # 58 entries: 33 active + 25 defensive_only.
    # Arena pool 223xxx items (ID - 220000 = SR counterpart 3xxx).

    # -- 33 active 223xxx promotions ---------------------------------------

    "223003": ItemEffect(
        item_id="223003",
        name="Archangel's Staff",
        bonus_ap_pct_bonus_mp=0.01,
        note="Archangel's Staff (Arena 223003): same as SR 3003 - Awe +1% bonus mana as AP",
    ),
    "223004": ItemEffect(
        item_id="223004",
        name="Manamune",
        bonus_ad_pct_max_mp=0.02,
        note="Manamune (Arena 223004): same as SR 3004 - Awe +2% max mana as bonus AD",
    ),
    "223020": ItemEffect(
        item_id="223020",
        name="Sorcerer's Shoes",
        # R161 doctrine B: Arena feed states 20 flat magic pen vs SR 3020's
        # 12; the explicitly-stated Arena value wins over SR inheritance.
        magic_pen_flat=20.0,
        note="Sorcerer's Shoes (Arena 223020): 20 flat magic pen per the Arena feed (SR 3020 carries 12)",
    ),
    "223031": ItemEffect(
        item_id="223031",
        name="Infinity Edge",
        crit_damage_bonus=0.30,
        note="Infinity Edge (Arena 223031): same as SR 3031 - Perfection +30% crit damage bonus",
    ),
    "223032": ItemEffect(
        item_id="223032",
        name="Yun Tal Wildarrows",
        crit_chance_bonus_flat=0.25,
        bonus_as_conditional=0.08,
        note=(
            "Yun Tal Wildarrows (Arena 223032): same as SR 3032 - "
            "25% crit (full stacks) + ~8% effective Flurry AS (27% uptime)"
        ),
    ),
    "223033": ItemEffect(
        item_id="223033",
        name="Mortal Reminder",
        armor_pen_pct=0.30,
        unique_passive_key="last_whisper",
        note="Mortal Reminder (Arena 223033): same as SR 3033 - Last Whisper 30% armor pen",
    ),
    "223036": ItemEffect(
        item_id="223036",
        name="Lord Dominik's Regards",
        # R161 doctrine B: Arena feed states 40% armor pen vs SR 3036's 35%;
        # the explicitly-stated Arena value wins over SR inheritance. The
        # Giant Slayer coefficients below still ride the SR mirror.
        armor_pen_pct=0.40,
        target_bonus_hp_amp_max_pct=0.15,
        target_bonus_hp_amp_cap=1500.0,
        unique_passive_key="last_whisper",
        note="Lord Dominik's (Arena 223036): 40% armor pen per the Arena feed (SR 3036 carries 35%) + Giant Slayer up to 15% at 1500 bonus HP (SR 3036 mirror)",
    ),
    "223039": ItemEffect(
        item_id="223039",
        name="Atma's Reckoning",
        crit_chance_bonus_max_pct=0.30,
        crit_chance_bonus_per_bonus_hp_cap=3000.0,
        note="Atma's Reckoning (Arena 223039): same as SR 3039 - Big Hands 0-30% crit over 0-3000 caster bonus HP",
    ),
    "223053": ItemEffect(
        item_id="223053",
        name="Sterak's Gage",
        bonus_ad_pct_base_ad=0.45,
        unique_passive_key="lifeline",
        # RM-104 (2026-07-19): mirror carried the Claws stat layer + the
        # lifeline family key but no shield field, so the Lifeline half
        # credited ZERO EHP on every Arena build. Always-on (default_off
        # False, like its base) - no flag needed. Magnitude
        # INHERITED-UNSOURCED from SR 3053; no repo feed states it. The
        # mirror grants 300 bonus HP vs the base's 400, but the coefficient
        # is applied to the champion's resolved bonus_hp, so that retune
        # already flows through the output without changing this number.
        shield=ItemShield(
            damage_type=ANY,
            bonus_hp_scaling=0.60,
            note="Sterak's Gage (Arena 223053) Lifeline 60% bonus HP (INHERITED-UNSOURCED from SR 3053)",
        ),
        note="Sterak's Gage (Arena 223053): same as SR 3053 - Lifeline + Primal Strength +45% base AD as bonus AD",
    ),
    "223068": ItemEffect(
        item_id="223068",
        name="Sunfire Aegis",
        periodics=(PeriodicProc(
            name="Immolate",
            # Iter 8 (2026-05-19): mirrors SR 3068 corrected to Meraki
            # 16.10.1 - 20 + 1% bonus_hp (was 12 + 1.5% bonus_hp).
            bonus_damage=lambda c: c.targets_in_rotation
                * (20.0 + 0.010 * c.caster_bonus_hp),
            damage_type=MAGICAL,
            every_n_seconds=1.0,
        ),),
        unique_passive_key="immolate",
        # PROVENANCE (corrected 2026-08-08, note-only): 223068 is ABSENT from
        # items_meraki.json at EVERY patch on disk (16.10.1 - 16.15.1; the
        # Meraki bulk carries 320 rows and none is an Arena mirror), and its
        # DDragon description leaves the Immolate magnitude placeholder EMPTY
        # ("deal <magicDamage> magic damage</magicDamage> per second"). The
        # formula above is therefore an ASSUMED SR-parity inheritance from
        # 3068, not a measurement of 223068. The STAT LINE is measured to
        # DIVERGE: DDragon 16.15.1 gives 223068 350 HP / 40 Armor / 10 AH
        # against SR 3068 350 HP / 50 Armor / 10 AH. Per R161 doctrine B an
        # Arena mirror credits its OWN DDragon stat line, not the SR twin's.
        note=(
            "Sunfire Aegis (Arena 223068): Immolate 20+1% bonus HP magic/s is "
            "ASSUMED equal to SR 3068 - no source carries the Arena row "
            "(absent from Meraki at every patch on disk; DDragon magnitude "
            "placeholder empty). The stat line is MEASURED to differ from the "
            "twin (223068 40 Armor vs 3068 50 Armor), per R161 doctrine B. "
            "immolate-key"
        ),
    ),
    "223071": ItemEffect(
        item_id="223071",
        name="Black Cleaver",
        armor_reduction_pct=0.30,
        note="Black Cleaver (Arena 223071): same as SR 3071 - Carve 30% armor reduction (6x5%, pinned full stacks)",
    ),
    "223074": ItemEffect(
        item_id="223074",
        name="Ravenous Hydra",
        periodics=(PeriodicProc(
            name="Cleave",
            # R193: mirrors the SR 3074 correction from 0.35 to the Meraki
            # 16.14.1 melee value. The family pins melee - no ranged split.
            bonus_damage=lambda c: max(0.0, c.targets_in_rotation - 1.0)
                * 0.40 * (c.base_ad + c.bonus_ad),
            damage_type=PHYSICAL,
            every_n_attacks=1,
        ),),
        unique_passive_key="hydra_cleave",
        physical_burst_total_ad_ratio=0.80,
        note="Ravenous Hydra (Arena 223074): same as SR 3074 - Cleave 40% AD to other enemies (melee pin); Ravenous Crescent active 80% total AD physical AoE now modeled - rides the DSV8 assume_physical_burst burst window (Meraki 16.14.1, R193)",
    ),
    "223078": ItemEffect(
        item_id="223078",
        name="Trinity Force",
        periodics=(PeriodicProc(
            name="Spellblade",
            bonus_damage=lambda c: 2.0 * c.base_ad,
            damage_type=PHYSICAL,
            every_n_seconds=3.0,
        ),),
        unique_passive_key="spellblade",
        note="Trinity Force (Arena 223078): same as SR 3078 - Spellblade 200% base AD every ~3s, spellblade-key",
    ),
    "223084": ItemEffect(
        item_id="223084",
        name="Heartsteel",
        periodics=(PeriodicProc(
            name="Colossal Consumption",
            bonus_damage=lambda c: 70.0 + 0.06 * c.caster_max_hp,
            damage_type=PHYSICAL,
            # CADENCE CAVEAT (RM-99b / A-04): still the SR twin's old 3.5, and
            # DELIBERATELY so. The SR entry 3084 was corrected to the real 30s
            # per-target gate (operator-flipped 2026-07-24) but this mirror was
            # held OFF: per R161 doctrine B the mirror's OWN feed was checked
            # first and states no cooldown (absent from Meraki; its DDragon text
            # renders "(0s) per target"), so 30s here would be INHERITED and
            # UNSOURCED - and Riot demonstrably retuned this mirror on other
            # axes (700 vs 900 Health, 2500g vs 3000g), so an SR magnitude is
            # not a safe default. Correcting it is opt-in via
            # ``apply_heartsteel_cadence_fix``. Re-source 223084's own cooldown
            # before flipping that seam's default.
            every_n_seconds=3.5,
        ),),
        note="Heartsteel (Arena 223084): same as SR 3084 - Colossal Consumption 70+6% caster max HP every 3.5s",
    ),
    "223085": ItemEffect(
        item_id="223085",
        name="Runaan's Hurricane",
        periodics=(PeriodicProc(
            name="Wind's Fury",
            # Mirrors SR 3085 - Meraki: 2 extra bolts, each 55% TOTAL
            # AD physical (was 0.60 * bonus_ad, wrong coefficient+base).
            bonus_damage=lambda c: 2.0 * 0.55 * (c.base_ad + c.bonus_ad),
            damage_type=PHYSICAL,
            every_n_attacks=1,
            # B1 (1.141.0): ranged-only bolts (mirror SR 3085).
            ranged_only=True,
        ),),
        note="Runaan's Hurricane (Arena 223085): same as SR 3085 - Wind's Fury 55% total AD x2 bolts",
    ),
    "223087": ItemEffect(
        item_id="223087",
        name="Statikk Shiv",
        periodics=(PeriodicProc(
            name="Electrospark",
            # Mirrors SR 3087 - Meraki 16.10.1 Electrospark: 3 attacks x
            # 60 magic per 10s cooldown cycle (was 110 magic every 3s).
            bonus_damage=180.0,
            damage_type=MAGICAL,
            every_n_seconds=10.0,
        ),),
        note="Statikk Shiv (Arena 223087): same as SR 3087 - Electrospark 3x60 magic per 10s cycle",
    ),
    "223089": ItemEffect(
        item_id="223089",
        name="Rabadon's Deathcap",
        ap_amp_pct=0.30,
        note="Rabadon's Deathcap (Arena 223089): same as SR 3089 - Gorilla's Rage 30% AP amplifier",
    ),
    "223091": ItemEffect(
        item_id="223091",
        name="Wit's End",
        periodics=(PeriodicProc(
            name="Fray",
            # Mirrors SR 3091 - Meraki flat 45 bonus magic on-hit
            # (level-independent in patch 16.10.1).
            bonus_damage=45.0,
            damage_type=MAGICAL,
            every_n_attacks=1,
        ),),
        note="Wit's End (Arena 223091): same as SR 3091 - Fray +45 bonus magic on-hit",
    ),
    "223094": ItemEffect(
        item_id="223094",
        name="Rapid Firecannon",
        periodics=(PeriodicProc(
            name="Sharpshooter",
            # Mirrors SR 3094 - Meraki 40 bonus magic on-hit when fully
            # Energized (was 120).
            bonus_damage=40.0,
            damage_type=MAGICAL,
            every_n_seconds=3.0,
        ),),
        note="Rapid Firecannon (Arena 223094): same as SR 3094 - Sharpshooter +40 magic every ~3s",
    ),
    "223100": ItemEffect(
        item_id="223100",
        name="Lich Bane",
        periodics=(PeriodicProc(
            name="Spellblade",
            # Arena mirror inherits the SR 75% base AD + 40% AP Meraki shape
            # (2026-05-20 fix - pre-fix was 50% AP across both 3100 and the
            # Arena mirror).
            bonus_damage=lambda c: 0.75 * c.base_ad + 0.40 * c.ap,
            damage_type=MAGICAL,
            every_n_seconds=3.0,
        ),),
        unique_passive_key="spellblade",
        note="Lich Bane (Arena 223100): same as SR 3100 - Spellblade 75% base AD + 40% AP magical every ~3s, spellblade-key",
    ),
    "223115": ItemEffect(
        item_id="223115",
        name="Nashor's Tooth",
        periodics=(PeriodicProc(
            name="Icathian Bite",
            # Arena mirror inherits the SR 15 + 15% AP Meraki shape
            # (2026-05-20 fix - pre-fix was 20% AP across both 3115 and
            # the Arena mirror).
            bonus_damage=lambda c: 15.0 + 0.15 * c.ap,
            damage_type=MAGICAL,
            every_n_attacks=1,
        ),),
        note="Nashor's Tooth (Arena 223115): same as SR 3115 - Icathian Bite 15+15% AP magic on-hit",
    ),
    "223124": ItemEffect(
        item_id="223124",
        name="Guinsoo's Rageblade",
        periodics=(
            PeriodicProc(
                name="Wrath",
                # Iter 14 (2026-05-20): mirrors iter-12 SR 3124 fix - Wrath
                # flat 30 magic on-hit every AA was missing on the arena
                # variant. DDragon 16.10.1 description applies on both maps.
                bonus_damage=30.0,
                damage_type=MAGICAL,
                every_n_attacks=1,
            ),
            PeriodicProc(
                name="Phantom Hit",
                bonus_damage=lambda c: 0.50 * c.bonus_ad,
                damage_type=PHYSICAL,
                every_n_attacks=3,
            ),
        ),
        # R66 (2026-07-03): Arena mirror inherits the SR 3124 Seething Strike
        # full-stack pin (8% x 4 = 32% bonus AS, Meraki 16.13.1) on the
        # ungated R42 conditional-AS lane.
        bonus_as_conditional=0.32,
        note="Guinsoo's Rageblade (Arena 223124): mirrors SR 3124 - Wrath +30 magic on-hit every AA + Phantom Hit every 3rd ~50% bonus AD + Seething Strike 8%x4 = 32% bonus AS at full stacks (Meraki 16.13.1)",
    ),
    "223135": ItemEffect(
        item_id="223135",
        name="Void Staff",
        magic_pen_pct=0.40,
        unique_passive_key="void_pen",
        note="Void Staff (Arena 223135): same as SR 3135 - Void Leech 40% magic pen",
    ),
    "223137": ItemEffect(
        item_id="223137",
        name="Cryptbloom",
        magic_pen_pct=0.30,
        unique_passive_key="void_pen",
        note="Cryptbloom (Arena 223137): same as SR 3137 - Draining Venom 30% magic pen",
    ),
    "223142": ItemEffect(
        item_id="223142",
        name="Youmuu's Ghostblade",
        # R161 doctrine B: the Arena mirror states its OWN stat line in the
        # DDragon 16.14.1 feed (22 Lethality vs SR 3142's 18). The feed value
        # wins - Arena mirrors no longer inherit SR base stat magnitudes.
        lethality=22.0,
        note="Youmuu's Ghostblade (Arena 223142): 22 lethality per the Arena feed (SR 3142 carries 18)",
    ),
    "223146": ItemEffect(
        item_id="223146",
        name="Hextech Gunblade",
        periodics=(PeriodicProc(
            name="Lightning Bolt",
            bonus_damage=lambda c: 175.0 + (253.0 - 175.0) / 17.0 * (c.level - 1) + 0.30 * c.ap,
            damage_type=MAGICAL,
            every_n_seconds=40.0,
        ),),
        note="Hextech Gunblade (Arena 223146): same as SR 3146 - Lightning Bolt 175->253+30% AP magic, 40s CD",
    ),
    "223153": ItemEffect(
        item_id="223153",
        name="Blade of The Ruined King",
        periodics=(PeriodicProc(
            name="Mist's Edge",
            bonus_damage=lambda c: 0.09 * c.target_max_hp,
            damage_type=PHYSICAL,
            every_n_attacks=1,
        ),),
        note="Blade of the Ruined King (Arena 223153): same as SR 3153 - Mist's Edge 9% target max HP on-hit (Meraki melee value)",
    ),
    "223181": ItemEffect(
        item_id="223181",
        name="Hullbreaker",
        periodics=(PeriodicProc(
            name="Skipper",
            bonus_damage=lambda c: 1.20 * c.base_ad + 0.05 * c.caster_max_hp,
            damage_type=PHYSICAL,
            every_n_attacks=5,
        ),),
        note="Hullbreaker (Arena 223181): same as SR 3181 - Skipper every-5th-attack 120% base AD + 5% caster max HP",
    ),
    "223302": ItemEffect(
        item_id="223302",
        name="Terminus",
        periodics=(PeriodicProc(
            name="Shadow",
            bonus_damage=30.0,
            damage_type=MAGICAL,
            every_n_attacks=1,
        ),),
        # R161 doctrine B: the Arena feed states Juxtaposition Dark at 8% pen
        # PER STACK (cap 3) vs SR 3302's 10% per stack, so full-stack steady
        # state is 0.24 here and stays 0.30 on the SR row.
        #
        # The Juxtaposition LIGHT half stays UNCREDITED on this row - and, unlike
        # SR 3302, is not credited in _item_resist_grants either. Not an oversight
        # and not a missing path: NO on-disk feed carries an Arena Light
        # magnitude. items.json 16.14.1 names the grant ("Light Attacks grant
        # Armor and Magic Resist for 5s") with no number, and items_meraki.json
        # holds zero *3302 mirror rows. Scaling the SR 18/21/24 by this row's
        # 8-vs-10 pen ratio would be inheritance by arithmetic, which doctrine B
        # forbids. Enumerated in _item_resist_grants._ITEM_RESIST_UNSOURCED_MIRRORS
        # so the R144 coverage guard reads it as a knowing exclusion.
        armor_pen_pct=0.24,
        magic_pen_pct=0.24,
        note="Terminus (Arena 223302): Shadow 30 magic on-hit (SR 3302 mirror) + Juxtaposition Dark 3-stack steady-state 24% armor+magic pen per the Arena feed's 8%/stack (SR 3302 is 10%/stack -> 30%); Light caster-side resists UNCREDITED on both this row and _item_resist_grants - no on-disk feed states an Arena Light magnitude (doctrine B, see _ITEM_RESIST_UNSOURCED_MIRRORS)",
    ),
    "223508": ItemEffect(
        item_id="223508",
        name="Essence Reaver",
        periodics=(PeriodicProc(
            name="Spellblade",
            bonus_damage=lambda c: 1.25 * c.base_ad + 50.0 * c.crit_chance,
            damage_type=PHYSICAL,
            every_n_seconds=3.0,
        ),),
        unique_passive_key="spellblade",
        note="Essence Reaver (Arena 223508): same as SR 3508 - Spellblade 125% base AD + 50/crit% every ~3s, spellblade-key",
    ),
    "223742": ItemEffect(
        item_id="223742",
        name="Dead Man's Plate",
        # ENGINE 1.26.0 (2026-05-21): mirrors SR 3742 Shipwrecker stack-
        # ramp discharge encoding. Arena map 30 keeps same passive math
        # as SR; full-stack discharge 40 + base_ad physical on first
        # attack post-ramp.
        periodics=(
            PeriodicProc(
                name="Shipwrecker",
                bonus_damage=lambda c: 40.0 + c.base_ad,
                damage_type=PHYSICAL,
                every_n_attacks=1,
                stack_ramp_seconds=3.57,
            ),
        ),
        note="Dead Man's Plate (Arena 223742): same as SR 3742 - Shipwrecker full-stack discharge (ENGINE 1.26.0)",
    ),
    "223748": ItemEffect(
        item_id="223748",
        name="Titanic Hydra",
        periodics=(
            PeriodicProc(
                name="Cleave (primary)",
                # Iter 8 (2026-05-19): mirrors SR 3748 corrected to
                # Meraki 16.10.1 - 1% caster_max_hp (was 5 + 1.5%
                # caster_bonus_hp).
                bonus_damage=lambda c: 0.01 * c.caster_max_hp,
                damage_type=PHYSICAL,
                every_n_attacks=1,
            ),
            PeriodicProc(
                name="Cleave (to nearby)",
                # Iter 8 (2026-05-19): mirrors SR 3748 corrected to
                # Meraki 16.10.1 - 3% caster_max_hp per extra target
                # (was 40% total AD).
                bonus_damage=lambda c: max(0.0, c.targets_in_rotation - 1.0)
                    * 0.03 * c.caster_max_hp,
                damage_type=PHYSICAL,
                every_n_attacks=1,
            ),
        ),
        unique_passive_key="hydra_cleave",
        note="Titanic Hydra (Arena 223748): same as SR 3748 - Cleave 1% max HP primary + 3% max HP to nearby (Meraki 16.10.1)",
    ),
    "223814": ItemEffect(
        item_id="223814",
        name="Edge of Night",
        # R161 doctrine B: Arena feed states 14 Lethality vs SR 3814's 15;
        # the explicitly-stated Arena value wins over SR inheritance.
        lethality=14.0,
        note="Edge of Night (Arena 223814): 14 lethality per the Arena feed (SR 3814 carries 15)",
    ),

    # -- 25 defensive_only 223xxx mirrors ---------------------------------

    "223026": ItemEffect(
        item_id="223026",
        name="Guardian Angel",
        defensive_only=True,
        note="Guardian Angel (Arena 223026): Rebirth passive revive - no DPS contribution (the Rebirth EHP-numerator revive is now credited item-side via the _item_revive registry behind the default-OFF assume_item_revive compute_ehp seam)",
    ),
    "223046": ItemEffect(
        item_id="223046",
        name="Phantom Dancer",
        defensive_only=True,
        note="Phantom Dancer (Arena 223046): Spectral Waltz dodge + lifeline-like shield; no DPS proc",
    ),
    "223047": ItemEffect(
        item_id="223047",
        name="Plated Steelcaps",
        defensive_only=True,
        # R80 (1.181.0): Arena mirror of SR 3047 - Plating 10% basic-attack DR
        # credited via item_aa_dr_multiplier behind default-OFF assume_item_aa_dr.
        basic_attack_damage_reduction=0.10,
        note="Plated Steelcaps (Arena 223047): Plating 10% incoming basic-attack damage reduction; no DPS proc",
    ),
    "223050": ItemEffect(
        item_id="223050",
        name="Zeke's Convergence",
        defensive_only=True,
        # R70 slice A: Arena map-30 mirror of SR 3050 - same Frostfire
        # Tempest numbers per the mirror convention (no Meraki entry of
        # its own). SELF storm on ult cast, NOT the stale "Conduit ally
        # aura". Cryocombustion haste lives in _item_ability_haste.py;
        # DPS side intentionally unmodeled (long-CD ult-triggered, no
        # PeriodicProc, no double-count).
        magic_burst_base=150.0,
        magic_burst_ap_ratio=0.0,
        note=(
            "Zeke's Convergence (Arena 223050): Frostfire Tempest SELF "
            "storm on ult cast (150 flat, mirrors SR 3050) on the DSV6 "
            "assume_magic_burst seam; Cryocombustion haste lives in "
            "_item_ability_haste.py; DPS side intentionally unmodeled"
        ),
    ),
    "223065": ItemEffect(
        item_id="223065",
        name="Spirit Visage",
        defensive_only=True,
        # ENGINE 1.28.0 (2026-05-21): Phase 6 healing throughput - Arena
        # mirror of SR 3065 Boundless Vitality. +25% to heal pool only;
        # Phase 1.5 shield amp deferred per ItemEffect.heal_amp_pct docs.
        heal_amp_pct=0.25,
        note=(
            "Spirit Visage (Arena 223065): Boundless Vitality +25% heal "
            "amp (heal pool only; Phase 1.5 shields deferred to 6.5); "
            "no DPS proc"
        ),
    ),
    "223072": ItemEffect(
        item_id="223072",
        name="Bloodthirster",
        defensive_only=True,
        # ENGINE 1.28.0 (2026-05-21): Phase 6 healing throughput - Arena
        # mirror of SR 3072 Ichorshield. Same level lerp 165 (L1) -> 315
        # (L18), ANY damage type, full-cap steady-state.
        shield=ItemShield(
            damage_type=ANY,
            flat=165.0,
            level_lerp_low=9,
            level_lerp_high=18,
            level_lerp_high_value=315.0,
        ),
        note=(
            "Bloodthirster (Arena 223072): Sanguine Shield overheal bubble "
            "165 (L1) -> 315 (L18) ANY shield (full-cap steady-state); "
            "no DPS proc"
        ),
    ),
    "223073": ItemEffect(
        item_id="223073",
        name="Experimental Hexplate",
        defensive_only=True,
        note="Experimental Hexplate (Arena 223073): Overdrive AS/MS burst on ult - conditional; no DPS proc",
    ),
    "223075": ItemEffect(
        item_id="223075",
        name="Thornmail",
        defensive_only=True,
        note="Thornmail (Arena 223075): Thorns reflected damage on being hit - no self attack DPS proc",
    ),
    "223102": ItemEffect(
        item_id="223102",
        name="Banshee's Veil",
        defensive_only=True,
        note="Banshee's Veil (Arena 223102): Annul spell shield - defensive utility, no DPS proc",
    ),
    "223107": ItemEffect(
        item_id="223107",
        name="Redemption",
        defensive_only=True,
        note="Redemption (Arena 223107): Sanctify active AoE heal - support, no self DPS",
    ),
    "223109": ItemEffect(
        item_id="223109",
        name="Knight's Vow",
        defensive_only=True,
        note="Knight's Vow (Arena 223109): Pledge ally bond - support, no self DPS",
    ),
    "223110": ItemEffect(
        item_id="223110",
        name="Frozen Heart",
        defensive_only=True,
        # R86 (1.182.0): mirror of SR 3110 - -20% nearby enemy AS physical-EHP seam.
        enemy_attack_speed_slow=0.20,
        note="Frozen Heart (Arena 223110): Winter's Caress AS-slow aura - defensive, no DPS proc",
    ),
    "223116": ItemEffect(
        item_id="223116",
        name="Rylai's Crystal Scepter",
        defensive_only=True,
        note="Rylai's Crystal Scepter (Arena 223116): Rimefrost ability slow - utility, no DPS proc",
    ),
    "223118": ItemEffect(
        item_id="223118",
        name="Malignance",
        periodics=(
            PeriodicProc(
                name="Hatefog",
                bonus_damage=lambda c: (180.0 + 0.15 * c.ap) * c.ult_casts_per_sec,
                damage_type=MAGICAL,
                every_n_seconds=1.0,
            ),
        ),
        # RM-323: the burst lane excludes periodic procs, so without these two
        # fields this row scored 0.00 magic burst while its note asserted a
        # magnitude. Credited from THIS row's own note per doctrine B - DDragon
        # 16.15.1 carries the Hatefog TEXT but no magnitude for 223118 OR 3118,
        # so the note is the only authority; it happens to match SR 3118.
        # No rate factor here (that is the periodic's sustained-DPS concept).
        magic_burst_base=180.0,
        magic_burst_ap_ratio=0.15,
        note="Malignance Arena mirror (223118) Hatefog: (180+15%AP) magic per ult zone hit",
    ),
    "223119": ItemEffect(
        item_id="223119",
        name="Winter's Approach",
        defensive_only=True,
        note="Winter's Approach (Arena 223119): stat-stack ramp to Fimbulwinter - no DPS proc",
    ),
    "223139": ItemEffect(
        item_id="223139",
        name="Mercurial Scimitar",
        defensive_only=True,
        note="Mercurial Scimitar (Arena 223139): Quicksilver CC cleanse active - utility, no DPS proc",
    ),
    "223143": ItemEffect(
        item_id="223143",
        name="Randuin's Omen",
        defensive_only=True,
        # R77 (1.180.0): Arena mirror of SR 3143 - same 30% crit-DR EHP credit
        # under the default-OFF assume_item_crit_dr seam.
        crit_damage_reduction=0.30,
        note="Randuin's Omen (Arena 223143): Resilience 30% crit-damage reduction (R77 EHP seam) + Humility active slow - defensive, no DPS",
    ),
    "223152": ItemEffect(
        item_id="223152",
        name="Hextech Rocketbelt",
        defensive_only=True,
        # R69 (1.176.0): Arena map-30 mirror of SR 3152 - same Supersonic
        # numbers per the mirror convention. One-cast burst-window
        # magnitude rides the DSV6 assume_magic_burst seam; DPS side
        # intentionally unmodeled (long-CD active, no PeriodicProc).
        magic_burst_base=100.0,
        magic_burst_ap_ratio=0.10,
        note=(
            "Hextech Rocketbelt (Arena 223152): Supersonic active 100 "
            "(+10% AP) magic once per cast - mirrors SR 3152 on the DSV6 "
            "assume_magic_burst seam; DPS side intentionally unmodeled"
        ),
    ),
    "223156": ItemEffect(
        item_id="223156",
        name="Maw of Malmortius",
        defensive_only=True,
        unique_passive_key="lifeline",
        # RM-104 (2026-07-19): mirror carried the lifeline family key but no
        # shield field, so it credited ZERO magical EHP on every Arena build.
        # Always-on (default_off False, like its base) - no flag needed.
        # Magnitude INHERITED-UNSOURCED from SR 3156; no repo feed states it.
        # The mirror grants 50 bonus AD vs the base's 60, but the scaling term
        # is applied to the champion's resolved bonus_ad, so that retune
        # already flows through the output. Only the flat 200 is a genuine
        # unsourced inheritance.
        shield=ItemShield(
            damage_type=MAGICAL,
            flat=200.0,
            bonus_ad_scaling=1.50,
            ranged_modifier=0.75,
            note="Maw of Malmortius (Arena 223156) Lifeline magic shield (INHERITED-UNSOURCED from SR 3156)",
        ),
        note="Maw of Malmortius (Arena 223156): Lifeline magic shield; joins lifeline unique-passive family",
    ),
    "223157": ItemEffect(
        item_id="223157",
        name="Zhonya's Hourglass",
        defensive_only=True,
        note="Zhonya's Hourglass (Arena 223157): Stasis active invulnerability - defensive utility, no DPS",
    ),
    "223161": ItemEffect(
        item_id="223161",
        name="Spear of Shojin",
        defensive_only=True,
        # DSV4 (1.127.0): mirror the SR 3161 Focused Will ability/passive amp
        # (3% per stack, 4 max = 12%), valued via the assume_ability_amp seam.
        ability_damage_amp_per_stack=0.03,
        ability_damage_amp_max_stacks=4,
        note="Spear of Shojin (Arena 223161): Dragonforce ability-CDR-on-hit + Focused Will (3% per stack ability/passive amp, max 4 stacks = 12%; valued via assume_ability_amp, DSV4)",
    ),
    "223165": ItemEffect(
        item_id="223165",
        name="Morellonomicon",
        defensive_only=True,
        note="Morellonomicon (Arena 223165): Affliction Grievous Wounds on ability - no DPS proc",
    ),
    "223190": ItemEffect(
        item_id="223190",
        name="Locket of the Iron Solari",
        defensive_only=True,
        note="Locket of the Iron Solari (Arena 223190): Devotion shield aura - support, no self DPS",
    ),
    "223222": ItemEffect(
        item_id="223222",
        name="Mikael's Blessing",
        defensive_only=True,
        note="Mikael's Blessing (Arena 223222): Purify active CC cleanse - support, no self DPS",
    ),
    "223504": ItemEffect(
        item_id="223504",
        name="Ardent Censer",
        defensive_only=True,
        note="Ardent Censer (Arena 223504): Sanctify heal/shield buff - support aura, no self DPS",
    ),

    # -- Phase 4 batch 44 (2026-05-04): DPS components + full items with procs --
    # 19 items: 5 proc components, 3 full items with DPS passive, 11 stats-only

    # --- proc-bearing components ---
    "3057": ItemEffect(
        item_id="3057",
        name="Sheen",
        periodics=(PeriodicProc(
            name="Spellblade",
            bonus_damage=lambda c: 1.00 * c.base_ad,
            damage_type=PHYSICAL,
            every_n_seconds=1.5,
        ),),
        unique_passive_key="spellblade",
        note="Sheen (3057): Spellblade 100% base AD physical bonus, 1.5s sustained cadence; shares spellblade-key",
    ),
    "3077": ItemEffect(
        item_id="3077",
        name="Tiamat",
        periodics=(PeriodicProc(
            name="Cleave",
            # Melee: 40% total AD physical to other enemies (primary
            # already lands via the basic attack itself). At
            # targets_in_rotation=1.0 the cleave hits 0 enemies and adds
            # zero DPS - preserves the historic single-target shape for
            # all-n=1 rotations. Melee-pinned like the rest of the
            # hydra_cleave family (Meraki 16.14.1 reads 40% / 20%).
            bonus_damage=lambda c: max(0.0, c.targets_in_rotation - 1.0)
                * 0.40 * (c.base_ad + c.bonus_ad),
            damage_type=PHYSICAL,
            every_n_attacks=1,
        ),),
        physical_burst_total_ad_ratio=0.75,
        note="Tiamat (3077): Cleave 40% total AD to nearby - zero in single-target, scales with targets_in_rotation; Crescent active 75% total AD physical AoE now modeled - rides the DSV8 assume_physical_burst burst window (Meraki 16.14.1, R193 sibling sweep of the R113 magnitude)",
    ),
    "3145": ItemEffect(
        item_id="3145",
        name="Hextech Alternator",
        periodics=(PeriodicProc(
            name="Revved",
            # Iter 15 (2026-05-20): Meraki bulk items 16.10.1 -
            # "Damaging an enemy champion deals 65 bonus magic damage."
            # Was 75 (stale magnitude from a prior patch).
            bonus_damage=65.0,
            damage_type=MAGICAL,
            every_n_seconds=5.0,
        ),),
        note="Hextech Alternator (3145): Revved 65 bonus magic damage, 5s ICD (Meraki 16.10.1)",
    ),
    "6660": ItemEffect(
        item_id="6660",
        name="Bami's Cinder",
        periodics=(PeriodicProc(
            name="Immolate",
            # Iter 8 (2026-05-19): Meraki bulk items (patch 16.10.1) -
            # "Deal 15 magic damage per second" (FLAT - no bonus_hp at
            # the components tier; HP scaling kicks in at the upgraded
            # items, Sunfire 20 + 1% bonus_hp / Hollow Radiance 15 + 1%
            # bonus_hp). Engine prior: 12 + 1% bonus_hp - both the base
            # (12 -> 15) and the bonus_hp coefficient (1% -> 0) drifted.
            bonus_damage=lambda c: c.targets_in_rotation * 15.0,
            damage_type=MAGICAL,
            every_n_seconds=1.0,
        ),),
        unique_passive_key="immolate",
        note="Bami's Cinder (6660): Immolate flat 15 magic/s (no HP scaling at component tier; Meraki 16.10.1); immolate-key",
    ),
    "6677": ItemEffect(
        item_id="6677",
        name="Rageknife",
        periodics=(PeriodicProc(
            name="Wrath",
            bonus_damage=20.0,
            damage_type=MAGICAL,
            every_n_attacks=1,
        ),),
        note="Rageknife (6677): Wrath 20 magic on-hit (150% on crit - base value modeled)",
    ),

    # --- full items with DPS passive ---
    # Cadence CORRECTED 15.0 -> 90.0 (2026-07-25). The old 15.0 was uncited: no
    # loaded feed states 15 seconds anywhere on this item. 3131 is ABSENT from
    # Meraki, so per R161 doctrine B the number is sourced from 3131's OWN
    # DDragon line in data/daemon_slayer/<patch>/items.json, which states the
    # active cooldown twice and consistently - the description renders it as
    # "(90(0s))" (authored 90, zeroed template) and effect.Effect5Amount is
    # "90". dps._periodic_proc_dps computes procs = duration / every_n_seconds,
    # so 15.0 credited 90 / 15 = 6x the real proc count.
    #
    # BLAST RADIUS - 3131's own feed line reports maps 11 / 12 / 30 / 35 ALL
    # false and only 21 true. Map 21 is NEXUS BLITZ, not the Howling Abyss
    # (ARAM is map 12): the map-21 pool on this feed is the classic Nexus Blitz
    # set - Ghostcrawlers 3005, Deathfire Grasp 3128, Innervating Locket 4402,
    # The Golden Spatula 4403, and this item. Nexus Blitz is not in
    # rank.MODE_MAP_ID, so _is_legal_in_mode rejects 3131 for SR / ARAM / ARENA
    # / BRAWL alike and it never reaches a candidate pool or a generated build
    # order. The over-credit was only reachable through an explicit compute_dps
    # item list. There is no id-suffix mirror - a scan of the full id feed
    # returns exactly ["3131"]. 443060 (Arena) and 663060 both share the display
    # NAME but are a DIFFERENT item (Excoriate bonus crit damage, no periodic)
    # and inherit nothing from here.
    #
    # The effect KIND is deliberately NOT remodelled in this slice. The real
    # active is a timed window - 100% Attack Speed AND 100% Critical Strike
    # Chance for 3 seconds or 3 basic attacks - and PeriodicProc can express
    # neither half faithfully. The crit half's MARGINAL value is
    # (1 - crit_chance)-scaled, so a literal 3-guaranteed-crit model collapses
    # to zero for exactly the high-crit builds that buy the item, while the
    # attack-speed half is a temporary stat buff with no damage field at all and
    # would stay uncredited - i.e. the "faithful" magnitude would trade one bias
    # for another. A correct model needs a timed-buff-window schema lift; that
    # is filed as its own row. Until then the single guaranteed-crit-worth proc
    # is kept as the conservative stand-in and only its firing rate is fixed.
    "3131": ItemEffect(
        item_id="3131",
        name="Sword of the Divine",
        lethality=18.0,
        periodics=(PeriodicProc(
            name="Divine Judgment",
            bonus_damage=lambda c: 0.75 * (c.base_ad + c.bonus_ad),
            damage_type=PHYSICAL,
            every_n_seconds=90.0,
        ),),
        note=(
            "Sword of the Divine (3131): 18 leth + Divine Blessing active - "
            "guaranteed-crit bonus (~75% AD extra) on the DDragon-stated 90s "
            "cooldown; Nexus Blitz only (maps 21 true, 11/12/30/35 false), so it "
            "is unbuyable in every mode the engine wires"
        ),
    ),
    "6700": ItemEffect(
        item_id="6700",
        name="Shield of the Rakkor",
        note="Shield of the Rakkor (6700): 50 AD + 30 Armor + 5% MS; Rakkor Strike armor pen conditional on active - not modeled",
    ),
    "3001": ItemEffect(
        item_id="3001",
        name="Evenshroud",
        damage_amp_pct=0.06,
        note="Evenshroud (3001): Coruscation - nearby enemies take 6% more damage; removed patch 13.3 (legacy DDragon entry)",
    ),

    # --- stats-only active items ---
    "3086": ItemEffect(
        item_id="3086",
        name="Zeal",
        note="Zeal (3086): 15% crit + 15% AS + 4% MS - stats only; no passive proc",
    ),
    "3134": ItemEffect(
        item_id="3134",
        name="Serrated Dirk",
        lethality=10.0,
        note="Serrated Dirk (3134): 20 AD + 10 lethality",
    ),
    "3133": ItemEffect(
        item_id="3133",
        name="Caulfield's Warhammer",
        note="Caulfield's Warhammer (3133): 20 AD + AH - no proc",
    ),
    "3123": ItemEffect(
        item_id="3123",
        name="Executioner's Calling",
        note="Executioner's Calling (3123): 15 AD + Grievous Wounds on-attack (no DPS proc modeled)",
    ),
    "3802": ItemEffect(
        item_id="3802",
        name="Lost Chapter",
        note="Lost Chapter (3802): 40 AP + 300 MP + AH - no proc",
    ),
    "3916": ItemEffect(
        item_id="3916",
        name="Oblivion Orb",
        note="Oblivion Orb (3916): 25 AP + Grievous Wounds on ability (no DPS proc modeled)",
    ),
    "3108": ItemEffect(
        item_id="3108",
        name="Fiendish Codex",
        note="Fiendish Codex (3108): 25 AP + AH - no proc",
    ),
    "3113": ItemEffect(
        item_id="3113",
        name="Aether Wisp",
        note="Aether Wisp (3113): 30 AP + 4% MS - no proc",
    ),
    "3051": ItemEffect(
        item_id="3051",
        name="Hearthbound Axe",
        note="Hearthbound Axe (3051): 20 AD + 20% AS - Flurry conditional on movement, not modeled",
    ),
    "3044": ItemEffect(
        item_id="3044",
        name="Phage",
        note="Phage (3044): 200 HP + 15 AD - Threaten slow passive, no DPS proc",
    ),
    "6029": ItemEffect(
        item_id="6029",
        name="Ironspike Whip",
        note="Ironspike Whip (6029): 30 AD + Crescent active only - no passive proc",
    ),

    # -- Phase 4 batch 45 (2026-05-04): Defensive full items + components + boots --
    # 21 items: 1 active (Berserker's Greaves AS), 20 defensive_only

    # --- defensive full items ---
    "6656": ItemEffect(
        item_id="6656",
        name="Everfrost",
        defensive_only=True,
        note="Everfrost (6656): 70 AP + 250 HP + 600 MP; Glaciate active and Rime passive not modeled",
    ),
    "6035": ItemEffect(
        item_id="6035",
        name="Silvermere Dawn",
        defensive_only=True,
        note="Silvermere Dawn (6035): 40 AD + 300 HP + 40 MR; QSS-like active not modeled",
    ),
    "6667": ItemEffect(
        item_id="6667",
        name="Radiant Virtue",
        defensive_only=True,
        note="Radiant Virtue (6667): 350 HP + 30 Armor + 30 MR; Noblesse post-ult aura - no self DPS",
    ),
    "4644": ItemEffect(
        item_id="4644",
        name="Crown of the Shattered Queen",
        defensive_only=True,
        note="Crown of the Shattered Queen (4644): 85 AP + 250 HP + 600 MP; Poise damage amp conditional - not modeled",
    ),
    "4012": ItemEffect(
        item_id="4012",
        name="Sin Eater",
        defensive_only=True,
        note="Sin Eater (4012): 300 HP + 45 Armor + 45 MR; healing passive - no DPS contribution",
    ),
    "4402": ItemEffect(
        item_id="4402",
        name="Innervating Locket",
        defensive_only=True,
        note="Innervating Locket (4402): 30 AD + 400 HP + 300 MP; support healing passive - no self DPS",
    ),
    "3193": ItemEffect(
        item_id="3193",
        name="Gargoyle Stoneplate",
        defensive_only=True,
        note="Gargoyle Stoneplate (3193): 60 Armor + 60 MR; Metallicize active shield - defensive, no DPS",
    ),
    "3002": ItemEffect(
        item_id="3002",
        name="Trailblazer",
        defensive_only=True,
        note="Trailblazer (3002): 250 HP + 40 Armor + 4% MS; Pathfinder proc conditional on dash - not modeled",
    ),

    # --- defensive components ---
    "3067": ItemEffect(
        item_id="3067",
        name="Kindlegem",
        defensive_only=True,
        note="Kindlegem (3067): 200 HP + AH - no DPS contribution",
    ),
    "3070": ItemEffect(
        item_id="3070",
        name="Tear of the Goddess",
        defensive_only=True,
        note="Tear of the Goddess (3070): 240 mana - no DPS; upgrades to Manamune / Archangel's Staff",
    ),
    "3211": ItemEffect(
        item_id="3211",
        name="Spectre's Cowl",
        defensive_only=True,
        note="Spectre's Cowl (3211): 35 MR + 200 HP - defensive, no DPS proc",
    ),
    "3024": ItemEffect(
        item_id="3024",
        name="Glacial Buckler",
        defensive_only=True,
        note="Glacial Buckler (3024): 300 MP + 25 Armor - defensive, no DPS contribution",
    ),
    "3076": ItemEffect(
        item_id="3076",
        name="Bramble Vest",
        defensive_only=True,
        note="Bramble Vest (3076): 50 Armor; Thorns reflects damage on being hit - not outgoing DPS",
    ),
    "3082": ItemEffect(
        item_id="3082",
        name="Warden's Mail",
        defensive_only=True,
        note="Warden's Mail (3082): 45 Armor; Cold Steel reduces attacker AS - defensive, no DPS proc",
    ),
    "3105": ItemEffect(
        item_id="3105",
        name="Aegis of the Legion",
        defensive_only=True,
        note="Aegis of the Legion (3105): 30 MR + 30 Armor + AH; Legion aura - defensive support, no self DPS",
    ),
    "3801": ItemEffect(
        item_id="3801",
        name="Crystalline Bracer",
        defensive_only=True,
        note="Crystalline Bracer (3801): 200 HP + HP regen - no DPS contribution",
    ),
    "3803": ItemEffect(
        item_id="3803",
        name="Catalyst of Aeons",
        defensive_only=True,
        note="Catalyst of Aeons (3803): 300 HP + 300 mana - no DPS; upgrades to Everfrost / Rod of Ages",
    ),

    # --- boots ---
    "3006": ItemEffect(
        item_id="3006",
        name="Berserker's Greaves",
        note="Berserker's Greaves (3006): 25% AS + 45 MS - AS contributes to on-attack DPS builds",
    ),
    "3009": ItemEffect(
        item_id="3009",
        name="Boots of Swiftness",
        defensive_only=True,
        note="Boots of Swiftness (3009): 55 flat MS - no DPS contribution",
    ),
    "3111": ItemEffect(
        item_id="3111",
        name="Mercury's Treads",
        defensive_only=True,
        note="Mercury's Treads (3111): 20 MR + 45 MS + tenacity - defensive utility, no DPS",
    ),
    "3158": ItemEffect(
        item_id="3158",
        name="Ionian Boots of Lucidity",
        defensive_only=True,
        note="Ionian Boots of Lucidity (3158): 45 MS + AH - no direct DPS contribution",
    ),

    # -- Phase 4 batch 46 (2026-05-04): 226xxx/228xxx/224xxx Arena mirrors + remaining SR --
    # 22 items: 9 active + 13 defensive_only

    # --- active items ---
    "226632": ItemEffect(
        item_id="226632",
        name="Divine Sunderer",
        periodics=(PeriodicProc(
            name="Spellblade",
            bonus_damage=lambda c: 1.25 * c.base_ad + 0.06 * c.target_max_hp,
            damage_type=PHYSICAL,
            every_n_seconds=3.0,
        ),),
        unique_passive_key="spellblade",
        note="Divine Sunderer (Arena 226632): same as SR 6632 - Spellblade 125% base AD + 6% target max HP physical every ~3s",
    ),
    "226660": ItemEffect(
        item_id="226660",
        name="Bami's Cinder",
        periodics=(PeriodicProc(
            name="Immolate",
            # Iter 8 (2026-05-19): mirrors SR 6660 corrected to Meraki
            # 16.10.1 - flat 15 magic/s (was 12 + 1% bonus_hp).
            bonus_damage=lambda c: c.targets_in_rotation * 15.0,
            damage_type=MAGICAL,
            every_n_seconds=1.0,
        ),),
        unique_passive_key="immolate",
        # PROVENANCE (corrected 2026-08-08, note-only): 226660 is ABSENT from
        # items_meraki.json at EVERY patch on disk (16.10.1 - 16.15.1), and its
        # DDragon description leaves the Immolate magnitude placeholder EMPTY.
        # The flat 15 above is therefore an ASSUMED SR-parity inheritance from
        # 6660, not a measurement of 226660. The STAT LINE is measured to
        # DIVERGE hard: DDragon 16.15.1 gives 226660 550 Health / 5 AH against
        # SR 6660 150 Health / 5 AH (226660 also carries an EMPTY name field in
        # the DDragon feed). Per R161 doctrine B an Arena mirror credits its
        # OWN DDragon stat line, not the SR twin's.
        note=(
            "Bami's Cinder (Arena 226660): Immolate flat 15 magic/s is ASSUMED "
            "equal to SR 6660 - no source carries the Arena row (absent from "
            "Meraki at every patch on disk; DDragon magnitude placeholder "
            "empty). The stat line is MEASURED to differ from the twin "
            "(226660 550 Health vs 6660 150 Health), per R161 doctrine B. "
            "Shares immolate-key"
        ),
    ),
    "226691": ItemEffect(
        item_id="226691",
        name="Duskblade of Draktharr",
        # R161 doctrine B: Arena feed states 22 Lethality vs SR 6691's 18.
        # Re-credited for catalog consistency even though maps={} makes this
        # id unbuyable and therefore inert at score time.
        lethality=22.0,
        note="Duskblade of Draktharr (Arena 226691): 22 lethality per the Arena feed (SR 6691 carries 18); maps={} so the row is inert",
    ),
    "228020": ItemEffect(
        item_id="228020",
        name="Abyssal Mask",
        magic_amp_pct=0.12,
        note="Abyssal Mask (Arena 228020): same as SR 8020 - Unmake 12% more magic damage to nearby enemies",
    ),
    "224637": ItemEffect(
        item_id="224637",
        name="Demonic Embrace",
        ap_per_bonus_hp_pct=0.02,
        periodics=(PeriodicProc(
            name="Azakana's Gaze",
            bonus_damage=lambda c: 0.010 * c.target_max_hp,
            damage_type=MAGICAL,
            every_n_seconds=1.0,
            ability_dot=True,
        ),),
        note="Demonic Embrace (Arena 224637): same as SR 4637 - Dark Pact 2% bonus HP as AP + Azakana's Gaze 1% target max HP/s magic",
    ),
    "6670": ItemEffect(
        item_id="6670",
        name="Noonquiver",
        note="Noonquiver (6670): 15 AD + 20% crit - stats only; no passive proc",
    ),
    "6690": ItemEffect(
        item_id="6690",
        name="Rectrix",
        note="Rectrix (6690): 15 AD + 4% MS - stats only; no passive proc",
    ),
    "4003": ItemEffect(
        item_id="4003",
        name="Lifeline",
        lethality=5.0,
        note="Lifeline (4003): 25 AD + 5 lethality + 4% MS - component item",
    ),
    "4630": ItemEffect(
        item_id="4630",
        name="Blighting Jewel",
        magic_pen_pct=0.13,
        note="Blighting Jewel (4630): 25 AP + 13% magic pen - component for Void Staff family",
    ),

    # --- defensive_only items ---
    "226656": ItemEffect(
        item_id="226656",
        name="Everfrost",
        defensive_only=True,
        note="Everfrost (Arena 226656): same as SR 6656 - Glaciate active not modeled",
    ),
    "226667": ItemEffect(
        item_id="226667",
        name="Radiant Virtue",
        defensive_only=True,
        note="Radiant Virtue (Arena 226667): same as SR 6667 - Noblesse aura, no self DPS",
    ),
    "226671": ItemEffect(
        item_id="226671",
        name="Galeforce",
        defensive_only=True,
        note="Galeforce (Arena 226671): same as SR 6671 - Cloudburst dash active, no passive DPS proc",
    ),
    "226035": ItemEffect(
        item_id="226035",
        name="Silvermere Dawn",
        defensive_only=True,
        note="Silvermere Dawn (Arena 226035): same as SR 6035 - QSS active not modeled",
    ),
    "224636": ItemEffect(
        item_id="224636",
        name="Night Harvester",
        defensive_only=True,
        note="Night Harvester (Arena 224636): Soul Flare proc requires ability-cast schema - not modeled",
    ),
    "224644": ItemEffect(
        item_id="224644",
        name="Crown of the Shattered Queen",
        defensive_only=True,
        note="Crown of the Shattered Queen (Arena 224644): same as SR 4644 - Poise conditional not modeled",
    ),
    "228009": ItemEffect(
        item_id="228009",
        name="Multitool",
        defensive_only=True,
        note="Multitool (Arena 228009): morphs into a random item each shopping phase - no static passive to model",
    ),
    "4635": ItemEffect(
        item_id="4635",
        name="Leeching Leer",
        defensive_only=True,
        note="Leeching Leer (4635): 20 AP + 250 HP + 5% omnivamp - sustain component, no DPS proc",
    ),
    "4403": ItemEffect(
        item_id="4403",
        name="The Golden Spatula",
        defensive_only=True,
        note="The Golden Spatula (4403): all-stat joke item - no DPS proc",
    ),
    "4638": ItemEffect(
        item_id="4638",
        name="Watchful Wardstone",
        defensive_only=True,
        note="Watchful Wardstone (4638): support vision item - no DPS contribution",
    ),
    "4641": ItemEffect(
        item_id="4641",
        name="Stirring Wardstone",
        defensive_only=True,
        note="Stirring Wardstone (4641): support/vision - no DPS contribution",
    ),
    "4642": ItemEffect(
        item_id="4642",
        name="Bandleglass Mirror",
        defensive_only=True,
        note="Bandleglass Mirror (4642): AP + mana regen support - no DPS proc",
    ),
    "4643": ItemEffect(
        item_id="4643",
        name="Vigilant Wardstone",
        defensive_only=True,
        note="Vigilant Wardstone (4643): support/vision - no DPS contribution",
    ),

    # -- Phase 4 batch 47 (2026-05-04): Arena 22xxxx/32xxxx remaining + 221xxx components --
    # ~42 items: 16 active, 26 defensive_only

    # --- active: 22xxxx/32xxxx mirrors with DPS procs ---
    "223001": ItemEffect(
        item_id="223001",
        name="Evenshroud",
        damage_amp_pct=0.06,
        note="Evenshroud (Arena 223001): same as SR 3001 - Coruscation 6% more damage (legacy removed item)",
    ),
    "223040": ItemEffect(
        item_id="223040",
        name="Seraph's Embrace",
        bonus_ap_pct_bonus_mp=0.02,
        unique_passive_key="lifeline",
        shield=ItemShield(max_mana_scaling=0.18, damage_type=ANY, default_off=True),
        note="Seraph's Embrace (Arena 223040): same as SR 3040 - Awe 2% bonus mana as AP + Lifeline 18% max mana generic shield at <30% HP (Meraki 16.13.1), default-off opt-in",
    ),
    "223042": ItemEffect(
        item_id="223042",
        name="Muramana",
        bonus_ad_pct_max_mp=0.02,
        periodics=(PeriodicProc(
            name="Shock",
            bonus_damage=lambda c: 0.012 * c.caster_max_mp,
            damage_type=PHYSICAL,
            every_n_attacks=1,
        ),),
        note="Muramana (Arena 223042): same as SR 3042 - Awe 2% max mana as AD + Shock 1.2% max mana physical on-hit",
    ),
    "223057": ItemEffect(
        item_id="223057",
        name="Sheen",
        periodics=(PeriodicProc(
            name="Spellblade",
            bonus_damage=lambda c: 1.00 * c.base_ad,
            damage_type=PHYSICAL,
            every_n_seconds=1.5,
        ),),
        unique_passive_key="spellblade",
        note="Sheen (Arena 223057): same as SR 3057 - Spellblade 100% base AD physical every 1.5s; spellblade-key",
    ),
    "223095": ItemEffect(
        item_id="223095",
        name="Stormrazor",
        periodics=(PeriodicProc(
            name="Stormraider",
            bonus_damage=lambda c: 0.75 * c.bonus_ad,
            damage_type=PHYSICAL,
            every_n_seconds=30.0,
        ),),
        note="Stormrazor (Arena 223095): Stormraider guaranteed-crit bonus (~75% bonus AD extra) every 30s; 25% crit + 50 AD + 20% AS",
    ),
    "223185": ItemEffect(
        item_id="223185",
        name="Guardian's Dirk",
        lethality=11.0,
        note="Guardian's Dirk (Arena 223185): 25 AD + 11 lethality - Arena component",
    ),
    "323040": ItemEffect(
        item_id="323040",
        name="Seraph's Embrace",
        bonus_ap_pct_bonus_mp=0.02,
        unique_passive_key="lifeline",
        shield=ItemShield(max_mana_scaling=0.18, damage_type=ANY, default_off=True),
        note="Seraph's Embrace (ARAM 323040): same as SR 3040 - Awe 2% bonus mana as AP + Lifeline 18% max mana generic shield at <30% HP (Meraki 16.13.1), default-off opt-in",
    ),
    "323042": ItemEffect(
        item_id="323042",
        name="Muramana",
        bonus_ad_pct_max_mp=0.02,
        periodics=(PeriodicProc(
            name="Shock",
            bonus_damage=lambda c: 0.012 * c.caster_max_mp,
            damage_type=PHYSICAL,
            every_n_attacks=1,
        ),),
        note="Muramana (ARAM 323042): same as SR 3042 - Awe 2% max mana as AD + Shock 1.2% max mana physical on-hit",
    ),

    # --- active: 221xxx Arena components (stats-only, no proc) ---
    "221011": ItemEffect(
        item_id="221011",
        name="Giant's Belt",
        note="Giant's Belt (Arena 221011): reduced-cost HP component - no DPS proc",
    ),
    "221026": ItemEffect(
        item_id="221026",
        name="Blasting Wand",
        note="Blasting Wand (Arena 221026): reduced-cost AP component - no DPS proc",
    ),
    "221031": ItemEffect(
        item_id="221031",
        name="Chain Vest",
        defensive_only=True,
        note="Chain Vest (Arena 221031): reduced-cost Armor component - no DPS proc",
    ),
    "221043": ItemEffect(
        item_id="221043",
        name="Recurve Bow",
        note="Recurve Bow (Arena 221043): reduced-cost AS + on-hit component - no passive proc",
    ),
    "221053": ItemEffect(
        item_id="221053",
        name="Vampiric Scepter",
        note="Vampiric Scepter (Arena 221053): reduced-cost AD + lifesteal component - no DPS proc",
    ),
    "221057": ItemEffect(
        item_id="221057",
        name="Negatron Cloak",
        defensive_only=True,
        note="Negatron Cloak (Arena 221057): reduced-cost MR component - no DPS proc",
    ),
    "221058": ItemEffect(
        item_id="221058",
        name="Needlessly Large Rod",
        note="Needlessly Large Rod (Arena 221058): reduced-cost AP component - no DPS proc",
    ),
    "222022": ItemEffect(
        item_id="222022",
        name="Glowing Mote",
        defensive_only=True,
        note="Glowing Mote (222022): 250g Arena consumable mote - no DPS contribution",
    ),
    "222141": ItemEffect(
        item_id="222141",
        name="Cappa Juice",
        defensive_only=True,
        note="Cappa Juice (222141): 500g Arena consumable - no DPS contribution",
    ),

    # --- defensive_only: 22xxxx/32xxxx Arena pool ---
    "223002": ItemEffect(
        item_id="223002",
        name="Trailblazer",
        defensive_only=True,
        note="Trailblazer (Arena 223002): same as SR 3002 - Pathfinder proc conditional on dash, not modeled",
    ),
    "223067": ItemEffect(
        item_id="223067",
        name="Kindlegem",
        defensive_only=True,
        note="Kindlegem (Arena 223067): same as SR 3067 - HP + AH component, no DPS contribution",
    ),
    "223069": ItemEffect(
        item_id="223069",
        name="Void Immolation",
        # Phase 4 batch 57 (2026-05-04): promoted. Meraki confirms: "20 (+ 1.5%
        # of your maximum health) true damage every second to enemies within 325
        # units." Distinct from SR Immolate items (3068/6664) which deal MAGICAL
        # damage off bonus HP; Void Immolation deals TRUE damage off max HP.
        # unique_passive_key="immolate" prevents double-ticking if a build
        # includes multiple Immolate items (Riot enforces unique-passive).
        #
        # WHERE THAT CITATION LIVES (2026-08-08, note-only - re-litigated once
        # already): unlike every other Immolate row, Meraki files 223069's
        # Immolate under the row's `active` key and its `passives` list is
        # EMPTY (`[]`). A passives-only probe therefore reads this entry as
        # UNSOURCED and concludes it is an inherited assumption. It is not:
        # 223069 IS present in items_meraki.json at every patch on disk
        # (16.10.1 - 16.15.1, the ONLY Arena Immolate id that is), and
        # `items["223069"]["active"][0]["effects"]` carries the formula above
        # verbatim. Probe `active` as well as `passives` before calling it
        # unsourced.
        #
        # UPTIME IS MODELLED AS EQUAL TO SUNFIRE'S, AND THAT IS WRONG BY 3:5.
        # Meraki/DDragon 16.15.1 both state Void Immolation activates for 5
        # seconds where SR 3068 / 6660 / 6664 activate for 3. PeriodicProc has
        # no window/duration field (see its docstring, limitation 1), so this
        # proc and the SR procs are both modelled at full-rotation uptime.
        # Crediting the longer window needs a schema lift, NOT a scaled
        # bonus_damage here. Meraki also gives 223069 a 150 percent minion
        # multiplier with no monster clause and no minion-execute clause,
        # unlike its SR relatives - also unmodelled and consumer-less; the
        # measured family census lives in the PeriodicProc docstring.
        periodics=(PeriodicProc(
            name="Immolate",
            bonus_damage=lambda c: c.targets_in_rotation * (20.0 + 0.015 * c.caster_max_hp),
            damage_type=TRUE,
            every_n_seconds=1.0,
        ),),
        unique_passive_key="immolate",
        note=(
            "Void Immolation (Arena 223069): Immolate 20 + 1.5% max HP true damage/s "
            "to nearby enemies (MEASURED, not inherited - Meraki files it under the "
            "row's `active` key, `passives` is []; TRUE damage off max HP - distinct "
            "from SR 3068/6664 which deal magical off bonus HP). Its 5-second "
            "activation window is modelled with the same uptime as Sunfire's "
            "3-second window: PeriodicProc has no window/duration field"
        ),
    ),
    "223105": ItemEffect(
        item_id="223105",
        name="Aegis of the Legion",
        defensive_only=True,
        note="Aegis of the Legion (Arena 223105): same as SR 3105 - defensive aura, no self DPS",
    ),
    "223111": ItemEffect(
        item_id="223111",
        name="Mercury's Treads",
        defensive_only=True,
        note="Mercury's Treads (Arena 223111): same as SR 3111 - MR + MS + tenacity, no DPS",
    ),
    "223112": ItemEffect(
        item_id="223112",
        name="Guardian's Orb",
        defensive_only=True,
        note="Guardian's Orb (Arena 223112): same as SR 3112 - lane support component, no DPS proc",
    ),
    "223121": ItemEffect(
        item_id="223121",
        name="Fimbulwinter",
        defensive_only=True,
        # Mirror of SR 3121 Everlasting (opt-in assume_fimbulwinter_shield).
        shield=ItemShield(
            flat=100.0, max_mana_scaling=0.045, damage_type=ANY, default_off=True
        ),
        note="Fimbulwinter (Arena 223121): same as SR 3121 - Everlasting 100 +4.5% max mana generic shield (opt-in), no DPS proc",
    ),
    "223158": ItemEffect(
        item_id="223158",
        name="Ionian Boots of Lucidity",
        defensive_only=True,
        note="Ionian Boots of Lucidity (Arena 223158): same as SR 3158 - MS + AH boots, no DPS",
    ),
    "223172": ItemEffect(
        item_id="223172",
        name="Zephyr",
        defensive_only=True,
        note="Zephyr (Arena 223172): 50% AS + 10% MS + 30 AH; Headwind slow active not modeled as DPS",
    ),
    "223177": ItemEffect(
        item_id="223177",
        name="Guardian's Blade",
        defensive_only=True,
        note="Guardian's Blade (Arena 223177): lane support component - no DPS proc",
    ),
    "223184": ItemEffect(
        item_id="223184",
        name="Guardian's Hammer",
        defensive_only=True,
        note="Guardian's Hammer (Arena 223184): lane support component - no DPS proc",
    ),
    "223193": ItemEffect(
        item_id="223193",
        name="Gargoyle Stoneplate",
        defensive_only=True,
        note="Gargoyle Stoneplate (Arena 223193): same as SR 3193 - Metallicize active shield, no DPS",
    ),
    "222065": ItemEffect(
        item_id="222065",
        name="Shurelya's Battlesong",
        defensive_only=True,
        note="Shurelya's Battlesong (Arena 222065): same as SR 2065 - Inspire MS burst aura, no self DPS",
    ),
    "222051": ItemEffect(
        item_id="222051",
        name="Guardian's Horn",
        defensive_only=True,
        note="Guardian's Horn (Arena 222051): HP + defensive stats component - no DPS proc",
    ),
    "222524": ItemEffect(
        item_id="222524",
        name="Bandlepipes",
        defensive_only=True,
        note="Bandlepipes (222524): support enchanter item (HP + AH + Armor/MR) - no self DPS",
    ),
    "222526": ItemEffect(
        item_id="222526",
        name="Whispering Circlet",
        defensive_only=True,
        note="Whispering Circlet (222526): HP + mana regen + heal/shield power - support, no DPS proc",
    ),
    "222530": ItemEffect(
        item_id="222530",
        name="Diadem of Songs",
        defensive_only=True,
        note="Diadem of Songs (222530): HP + mana (1000) - support/mana item, no DPS proc",
    ),
    "224403": ItemEffect(
        item_id="224403",
        name="The Golden Spatula",
        # Phase 4 batch 57 (2026-05-04): promoted. Meraki confirms "Doing Something"
        # passive: permanently burns enemies within 400 units every second for
        # pp|26 to 43 magic damage (power-progression levels 1->18, slope 1.0/level).
        # Uses targets_in_rotation (AoE-incl-primary idiom).
        periodics=(PeriodicProc(
            name="Doing Something",
            bonus_damage=lambda c: c.targets_in_rotation * (26.0 + 1.0 * (c.level - 1)),
            damage_type=MAGICAL,
            every_n_seconds=1.0,
        ),),
        note=(
            "The Golden Spatula (Arena 224403): Doing Something - burn 26->43 "
            "magic damage/s to nearby enemies (level-scaled pp; Meraki confirmed)"
        ),
    ),
    "322065": ItemEffect(
        item_id="322065",
        name="Shurelya's Battlesong",
        defensive_only=True,
        note="Shurelya's Battlesong (ARAM 322065): same as SR 2065 - Inspire MS burst aura, no self DPS",
    ),
    "322526": ItemEffect(
        item_id="322526",
        name="Whispering Circlet",
        defensive_only=True,
        note="Whispering Circlet (ARAM 322526): HP + mana regen + heal/shield power - support, no DPS proc",
    ),
    "322530": ItemEffect(
        item_id="322530",
        name="Diadem of Songs",
        defensive_only=True,
        note="Diadem of Songs (ARAM 322530): HP + mana - support/mana item, no DPS proc",
    ),
    "323002": ItemEffect(
        item_id="323002",
        name="Trailblazer",
        defensive_only=True,
        note="Trailblazer (ARAM 323002): same as SR 3002 - Pathfinder proc conditional on dash, not modeled",
    ),
    "323070": ItemEffect(
        item_id="323070",
        name="Tear of the Goddess",
        defensive_only=True,
        note="Tear of the Goddess (ARAM 323070): same as SR 3070 - mana component, no DPS; upgrades to Muramana/Archangel's",
    ),
    "323121": ItemEffect(
        item_id="323121",
        name="Fimbulwinter",
        defensive_only=True,
        # Mirror of SR 3121 Everlasting (opt-in assume_fimbulwinter_shield).
        shield=ItemShield(
            flat=100.0, max_mana_scaling=0.045, damage_type=ANY, default_off=True
        ),
        note="Fimbulwinter (ARAM 323121): same as SR 3121 - Everlasting 100 +4.5% max mana generic shield (opt-in), no DPS proc",
    ),

    # -- Phase 4 batch 48 (2026-05-04): Core 1xxx tier-1 components ----------
    # 29 items: 1 proc component, 14 stats-only active, 14 defensive_only

    # --- proc-bearing component ---
    "1043": ItemEffect(
        item_id="1043",
        name="Recurve Bow",
        periodics=(PeriodicProc(
            name="Sting",
            bonus_damage=15.0,
            damage_type=PHYSICAL,
            every_n_attacks=1,
        ),),
        note="Recurve Bow (1043): Sting - 15 bonus physical damage on every attack",
    ),

    # --- stats-only active items ---
    "1018": ItemEffect(item_id="1018", name="Cloak of Agility",
        note="Cloak of Agility (1018): 15% crit - stats only"),
    "1026": ItemEffect(item_id="1026", name="Blasting Wand",
        note="Blasting Wand (1026): 40 AP - stats only"),
    "1036": ItemEffect(item_id="1036", name="Long Sword",
        note="Long Sword (1036): 10 AD - stats only"),
    "1037": ItemEffect(item_id="1037", name="Pickaxe",
        note="Pickaxe (1037): 25 AD - stats only"),
    "1038": ItemEffect(item_id="1038", name="B. F. Sword",
        note="B. F. Sword (1038): 40 AD - stats only"),
    "1042": ItemEffect(item_id="1042", name="Dagger",
        note="Dagger (1042): 15% AS - stats only"),
    "1052": ItemEffect(item_id="1052", name="Amplifying Tome",
        note="Amplifying Tome (1052): 20 AP - stats only"),
    "1053": ItemEffect(item_id="1053", name="Vampiric Scepter",
        note="Vampiric Scepter (1053): 15 AD + lifesteal - stats only"),
    "1055": ItemEffect(item_id="1055", name="Doran's Blade",
        note="Doran's Blade (1055): 8 AD + 80 HP - no DPS proc"),
    "1056": ItemEffect(item_id="1056", name="Doran's Ring",
        note="Doran's Ring (1056): 15 AP + mana - no DPS proc"),
    "1058": ItemEffect(item_id="1058", name="Needlessly Large Rod",
        note="Needlessly Large Rod (1058): 65 AP - stats only"),
    "1082": ItemEffect(item_id="1082", name="Dark Seal",
        note="Dark Seal (1082): 15 AP + kill-stack ramp (Dread unmodeled) - stats only"),
    "1083": ItemEffect(item_id="1083", name="Cull",
        note="Cull (1083): 7 AD; Reap 3 HP on-hit (sustain, not DPS proc)"),
    "1086": ItemEffect(item_id="1086", name="Doran's Bow",
        note="Doran's Bow (1086): 12 AD + AS - no DPS proc"),

    # --- defensive_only components ---
    "1001": ItemEffect(item_id="1001", name="Boots",
        defensive_only=True, note="Boots (1001): 25 flat MS - no DPS contribution"),
    "1004": ItemEffect(item_id="1004", name="Faerie Charm",
        defensive_only=True, note="Faerie Charm (1004): mana regen - no DPS contribution"),
    "1006": ItemEffect(item_id="1006", name="Rejuvenation Bead",
        defensive_only=True, note="Rejuvenation Bead (1006): HP regen - no DPS contribution"),
    "1011": ItemEffect(item_id="1011", name="Giant's Belt",
        defensive_only=True, note="Giant's Belt (1011): 250 HP - no DPS contribution"),
    "1027": ItemEffect(item_id="1027", name="Sapphire Crystal",
        defensive_only=True, note="Sapphire Crystal (1027): 200 mana - no DPS contribution"),
    "1028": ItemEffect(item_id="1028", name="Ruby Crystal",
        defensive_only=True, note="Ruby Crystal (1028): 150 HP - no DPS contribution"),
    "1029": ItemEffect(item_id="1029", name="Cloth Armor",
        defensive_only=True, note="Cloth Armor (1029): 15 Armor - no DPS contribution"),
    "1031": ItemEffect(item_id="1031", name="Chain Vest",
        defensive_only=True, note="Chain Vest (1031): 40 Armor - no DPS contribution"),
    "1033": ItemEffect(item_id="1033", name="Null-Magic Mantle",
        defensive_only=True, note="Null-Magic Mantle (1033): 25 MR - no DPS contribution"),
    "1035": ItemEffect(item_id="1035", name="Emberknife",
        defensive_only=True, note="Emberknife (1035): jungle starter - no DPS proc"),
    "1039": ItemEffect(item_id="1039", name="Hailblade",
        defensive_only=True, note="Hailblade (1039): jungle starter - no DPS proc"),
    "1040": ItemEffect(item_id="1040", name="Obsidian Edge",
        defensive_only=True, note="Obsidian Edge (1040): jungle starter - no DPS proc"),
    "1054": ItemEffect(item_id="1054", name="Doran's Shield",
        defensive_only=True, note="Doran's Shield (1054): HP + regen - no DPS contribution"),
    "1057": ItemEffect(item_id="1057", name="Negatron Cloak",
        defensive_only=True, note="Negatron Cloak (1057): 25 MR - no DPS contribution"),

    # -- Phase 4 batch 49 (2026-05-04): Remaining 3xxx/2xxx + final Arena items --
    # ~37 items: 12 active, 25 defensive_only

    # --- active items with DPS contribution ---
    "3175": ItemEffect(
        item_id="3175",
        name="Spellslinger's Shoes",
        magic_pen_flat=20.0,
        magic_pen_pct=0.08,
        note="Spellslinger's Shoes (3175): 20 flat magic pen + 8% magic pen + 45 MS - both pen layers stack with Sorcerer's/Shadowflame. Flat pen moved 18 -> 20 at DDragon 16.16.1 (RM-190); the percent layer did not move.",
    ),
    "3172": ItemEffect(
        item_id="3172",
        name="Gunmetal Greaves",
        note="Gunmetal Greaves (3172): 40% AS + 45 MS + 5% lifesteal boots - AS contributes to attack-based DPS builds",
    ),
    "3177": ItemEffect(
        item_id="3177",
        name="Guardian's Blade",
        note="Guardian's Blade (3177): 30 AD + 150 HP - lane starter, no proc",
    ),
    "3184": ItemEffect(
        item_id="3184",
        name="Guardian's Hammer",
        note="Guardian's Hammer (3184): 25 AD + 150 HP + 5% lifesteal - lane starter, no proc",
    ),
    "3095": ItemEffect(
        item_id="3095",
        name="Stormrazor",
        note="Stormrazor (3095): 50 AD + 20% AS + 25% crit (deprecated DDragon entry; Stormraider proc not modeled)",
    ),
    "3144": ItemEffect(
        item_id="3144",
        name="Scout's Slingshot",
        note="Scout's Slingshot (3144): 20% AS; Bullseye proc value unspecified in DDragon - stats only",
    ),
    "2508": ItemEffect(
        item_id="2508",
        name="Fated Ashes",
        # Phase 4 batch 51 (2026-05-04): promoted. DDragon confirms:
        # "Inflame: Damaging Abilities deal 15 bonus magic damage over 3s."
        # Modeled as every_n_seconds=3.0 (sustained approximation: 1 ability
        # hit per 3s -> 5 magic/s). Fated Ashes is a caster component so the
        # 3s assumption is realistic for mage rotations. Monster bonus (45 vs
        # champions' 15) not modeled - champion-target numbers pinned.
        periodics=(PeriodicProc(
            name="Inflame",
            bonus_damage=15.0,
            damage_type=MAGICAL,
            every_n_seconds=3.0,
        ),),
        note="Fated Ashes: Inflame 15 magic over 3s (5 magic/s sustained); modeled as 3s periodic proc",
    ),
    "123430": ItemEffect(
        item_id="123430",
        name="Rite of Ruin",
        crit_chance_bonus_flat=0.25,
        note="Rite of Ruin (ARAM 123430): 55 AP + 25% crit + 10 AH + 4% MS; crit_chance_bonus_flat=0.25 for ER Spellblade scaling",
    ),
    "126697": ItemEffect(
        item_id="126697",
        name="Hubris",
        lethality=18.0,
        # DSV2 (1.125.0): ARAM mirror of SR 6697 Eminence takedown AD.
        takedown_bonus_ad_base=15.0,
        takedown_bonus_ad_per_stack=2.0,
        note="Hubris (ARAM 126697): 55 AD + 18 lethality + Eminence takedown AD 15 (+2/stack)",
    ),
    "446693": ItemEffect(
        item_id="446693",
        name="Prowler's Claw",
        lethality=20.0,
        note="Prowler's Claw (Arena 446693): 60 AD + 20 lethality + Sandswipe active not modeled",
    ),
    "221038": ItemEffect(
        item_id="221038",
        name="B. F. Sword",
        note="B. F. Sword (Arena 221038): reduced-cost AD component - no DPS proc",
    ),
    "223006": ItemEffect(
        item_id="223006",
        name="Berserker's Greaves",
        note="Berserker's Greaves (Arena 223006): same as SR 3006 - 25% AS boots; no passive proc",
    ),

    # --- defensive_only boots ---
    "3005": ItemEffect(item_id="3005", name="Ghostcrawlers",
        defensive_only=True, note="Ghostcrawlers (3005): MS boots - no DPS contribution"),
    "3008": ItemEffect(item_id="3008", name="Gluttonous Greaves",
        defensive_only=True, note="Gluttonous Greaves (3008): lifesteal + omni boots - no DPS proc"),
    "3010": ItemEffect(item_id="3010", name="Symbiotic Soles",
        defensive_only=True, note="Symbiotic Soles (3010): MS boots variant - no DPS contribution"),
    "3013": ItemEffect(item_id="3013", name="Synchronized Souls",
        defensive_only=True, note="Synchronized Souls (3013): MS boots variant - no DPS contribution"),
    "3117": ItemEffect(item_id="3117", name="Mobility Boots",
        defensive_only=True, note="Mobility Boots (3117): MS boots - no DPS contribution"),
    "3168": ItemEffect(item_id="3168", name="Immortal Path",
        defensive_only=True, note="Immortal Path (3168): lifesteal + omni boots - no DPS proc"),
    "3170": ItemEffect(item_id="3170", name="Swiftmarch",
        defensive_only=True, note="Swiftmarch (3170): MS boots - no DPS contribution"),
    "3171": ItemEffect(item_id="3171", name="Crimson Lucidity",
        defensive_only=True, note="Crimson Lucidity (3171): AH boots - no DPS contribution"),
    "3173": ItemEffect(item_id="3173", name="Chainlaced Crushers",
        defensive_only=True,
        # R99 (2026-07-10): the uncredited magic SHIELD of Noxian Persistence.
        # Meraki 16.13.1: taking magic damage from champions grants a shield
        # absorbing 100 (L1) -> 200 (L18) + 8% bonus health magic damage for 5s
        # (15s CD). Credited via the default-OFF assume_chainlaced_shield seam -
        # like Kaenic R92 the trigger (taking magic damage, 15s CD) is anti-
        # correlated with the fights where the shield matters, so conservatively
        # opt-in rather than the always-on lifeline pool. Byte-identical OFF.
        shield=ItemShield(
            damage_type=MAGICAL,
            flat=100.0,
            level_lerp_low=1,
            level_lerp_high=18,
            level_lerp_high_value=200.0,
            bonus_hp_scaling=0.08,
            default_off=True,
            note="Chainlaced Crushers Noxian Persistence 100 (L1)->200 (L18) +8% bonus HP magic shield 5s, 15s CD; Meraki 16.13.1",
        ),
        note="Chainlaced Crushers (3173): MR + tenacity boots - no DPS contribution"),
    "3174": ItemEffect(
        item_id="3174",
        name="Armored Advance",
        defensive_only=True,
        # R88 (sibling-carrier of R80 3047): Armored Advance is the tier-3
        # upgrade boot of Plated Steelcaps and carries the IDENTICAL DDragon
        # 16.13.1 "Plating" passive - reduces incoming basic-attack damage by
        # 10%. That plating now earns EHP credit via the physical-denominator
        # item_aa_dr_multiplier (default-OFF assume_item_aa_dr), the SAME
        # item-keyed lane as 3047. The separate "Noxian Endurance" physical-
        # shield passive is intentionally UNMODELED (conditional, out of scope).
        # Still armor boots, no DPS proc.
        basic_attack_damage_reduction=0.10,
        note=(
            "Armored Advance (3174): Plating - reduces incoming basic-attack "
            "damage by 10% (DDragon 16.13.1). Armor boots, no DPS proc; the "
            "Noxian Endurance physical-shield passive is intentionally unmodeled"
        ),
    ),
    "3176": ItemEffect(item_id="3176", name="Forever Forward",
        defensive_only=True, note="Forever Forward (3176): MS boots variant - no DPS contribution"),

    # --- defensive_only components/misc 3xxx ---
    "3012": ItemEffect(item_id="3012", name="Chalice of Blessing",
        defensive_only=True, note="Chalice of Blessing (3012): 200 HP + mana regen - no DPS contribution"),
    "3023": ItemEffect(item_id="3023", name="Lifewell Pendant",
        defensive_only=True, note="Lifewell Pendant (3023): 150 HP + 25 Armor + AH - defensive component"),
    "3066": ItemEffect(item_id="3066", name="Winged Moonplate",
        defensive_only=True, note="Winged Moonplate (3066): 200 HP + 4% MS - no DPS contribution"),
    "3112": ItemEffect(item_id="3112", name="Guardian's Orb",
        defensive_only=True, note="Guardian's Orb (3112): lane support component - no DPS proc"),
    "3114": ItemEffect(item_id="3114", name="Forbidden Idol",
        defensive_only=True, note="Forbidden Idol (3114): mana regen + heal/shield power - no DPS contribution"),

    # --- defensive_only 2xxx ---
    "2065": ItemEffect(item_id="2065", name="Shurelya's Battlesong",
        defensive_only=True, note="Shurelya's Battlesong (2065): Inspire MS burst aura - support, no self DPS"),
    "2524": ItemEffect(item_id="2524", name="Bandlepipes",
        defensive_only=True, note="Bandlepipes (2524): enchanter support item - no self DPS"),
    "2526": ItemEffect(item_id="2526", name="Whispering Circlet",
        defensive_only=True, note="Whispering Circlet (2526): HP + mana regen + heal/shield - no DPS proc"),
    "2530": ItemEffect(item_id="2530", name="Diadem of Songs",
        defensive_only=True, note="Diadem of Songs (2530): HP + mana - no DPS proc"),

    # --- defensive_only Arena remainder ---
    "124011": ItemEffect(item_id="124011", name="Sword of Blossoming Dawn",
        defensive_only=True, note="Sword of Blossoming Dawn (ARAM 124011): 45 AP + 200 HP + heal/shield power - support/enchanter"),
    "223005": ItemEffect(item_id="223005", name="Ghostcrawlers",
        defensive_only=True, note="Ghostcrawlers (Arena 223005): same as SR 3005 - MS boots, no DPS"),
    "223008": ItemEffect(item_id="223008", name="Gluttonous Greaves",
        defensive_only=True, note="Gluttonous Greaves (Arena 223008): lifesteal + omni boots, no DPS proc"),
    "223009": ItemEffect(item_id="223009", name="Boots of Swiftness",
        defensive_only=True, note="Boots of Swiftness (Arena 223009): same as SR 3009 - MS boots, no DPS"),
    "223011": ItemEffect(item_id="223011", name="Chemtech Putrifier",
        defensive_only=True, note="Chemtech Putrifier (Arena 223011): support Grievous Wounds item - no self DPS"),

    # --- batch 51: missing purchasable components (defensive_only) -----------
    # Phase 4 batch 51 (2026-05-04): pure-stat components with no DPS passive.
    # All DDragon descriptions are stat-only (no proc, no passive text).
    "2019": ItemEffect(
        item_id="2019",
        name="Steel Sigil",
        defensive_only=True,
        note="Steel Sigil (2019): 15 AD + 30 Armor component - no passive",
    ),
    "2021": ItemEffect(
        item_id="2021",
        name="Tunneler",
        defensive_only=True,
        note="Tunneler (2021): 15 AD + 250 HP component - no passive",
    ),
    "2022": ItemEffect(
        item_id="2022",
        name="Glowing Mote",
        defensive_only=True,
        note="Glowing Mote (2022): 5 Ability Haste component - no passive",
    ),
    "2420": ItemEffect(
        item_id="2420",
        name="Seeker's Armguard",
        defensive_only=True,
        note=(
            "Seeker's Armguard (2420): 40 AP + 25 Armor; "
            "Time Stop (single-use Stasis active) is self-protective - no DPS"
        ),
    ),
    "2421": ItemEffect(
        item_id="2421",
        name="Shattered Armguard",
        defensive_only=True,
        note=(
            "Shattered Armguard (2421): 40 AP + 25 Armor post-use form; "
            "upgrades to Zhonya's - no DPS passive"
        ),
    ),

    # -- Phase 4 batch 55 (2026-05-04): remaining DDragon purchasable items --
    # Completes DDragon purchasable coverage. All entries are defensive_only -
    # no DPS-relevant passives confirmed from DDragon or Meraki bulk.

    # Doran's Helm - defensive starter (HP + Armor + MR)
    "1120": ItemEffect(item_id="1120", name="Doran's Helm",
        defensive_only=True,
        note="Doran's Helm (1120): 110 HP + 10 Armor + 10 MR - defensive starter, no DPS proc"),

    # Jungle companions - companion procs are PvE/objective-only, not champion DPS
    "1101": ItemEffect(item_id="1101", name="Scorchclaw Pup",
        defensive_only=True, note="Scorchclaw Pup (1101): jungle companion - no champion DPS contribution"),
    "1102": ItemEffect(item_id="1102", name="Gustwalker Hatchling",
        defensive_only=True, note="Gustwalker Hatchling (1102): jungle companion - no champion DPS contribution"),
    "1103": ItemEffect(item_id="1103", name="Mosstomper Seedling",
        defensive_only=True, note="Mosstomper Seedling (1103): jungle companion - no champion DPS contribution"),
    "1105": ItemEffect(item_id="1105", name="Mosstomper Seedling",
        defensive_only=True, note="Mosstomper Seedling (1105): jungle companion - no champion DPS contribution"),
    "1106": ItemEffect(item_id="1106", name="Gustwalker Hatchling",
        defensive_only=True, note="Gustwalker Hatchling (1106): jungle companion - no champion DPS contribution"),
    "1107": ItemEffect(item_id="1107", name="Scorchclaw Pup",
        defensive_only=True, note="Scorchclaw Pup (1107): jungle companion - no champion DPS contribution"),

    # Consumables and utility
    "2003": ItemEffect(item_id="2003", name="Health Potion",
        defensive_only=True, note="Health Potion (2003): consumed heal - no sustained DPS contribution"),
    "2031": ItemEffect(item_id="2031", name="Refillable Potion",
        defensive_only=True, note="Refillable Potion (2031): consumed heal - no sustained DPS contribution"),
    "2055": ItemEffect(item_id="2055", name="Control Ward",
        defensive_only=True, note="Control Ward (2055): vision utility - no DPS contribution"),

    # Guardian starter items (Support)
    "2049": ItemEffect(item_id="2049", name="Guardian's Amulet",
        defensive_only=True, note="Guardian's Amulet (2049): support starter - no DPS proc"),
    "2050": ItemEffect(item_id="2050", name="Guardian's Shroud",
        defensive_only=True, note="Guardian's Shroud (2050): support starter - no DPS proc"),
    "2051": ItemEffect(item_id="2051", name="Guardian's Horn",
        defensive_only=True, note="Guardian's Horn (2051): support starter - no DPS proc"),

    # Elixirs (consumed, temporary buffs)
    "2138": ItemEffect(item_id="2138", name="Elixir of Iron",
        defensive_only=True, note="Elixir of Iron (2138): consumed temporary HP - no sustained DPS"),
    "2139": ItemEffect(item_id="2139", name="Elixir of Sorcery",
        defensive_only=True, note="Elixir of Sorcery (2139): consumed AP + mana regen - no sustained DPS"),
    "2140": ItemEffect(item_id="2140", name="Elixir of Wrath",
        defensive_only=True, note="Elixir of Wrath (2140): consumed AD + lifesteal - no sustained DPS"),

    # Arena / special mode consumables
    "2141": ItemEffect(item_id="2141", name="Cappa Juice",
        defensive_only=True, note="Cappa Juice (2141): Arena consumable - no DPS contribution"),
    "2142": ItemEffect(item_id="2142", name="Juice of Power",
        defensive_only=True, note="Juice of Power (2142): Arena consumable - no DPS contribution"),
    "2143": ItemEffect(item_id="2143", name="Juice of Vitality",
        defensive_only=True, note="Juice of Vitality (2143): Arena consumable - no DPS contribution"),
    "2144": ItemEffect(item_id="2144", name="Juice of Haste",
        defensive_only=True, note="Juice of Haste (2144): Arena consumable - no DPS contribution"),
    "2147": ItemEffect(item_id="2147", name="Augment Level",
        defensive_only=True, note="Augment Level (2147): Arena augment upgrade - no DPS contribution"),

    # Bandle Juice (Bandle City ARAM map) - consumed items giving dynamic stat boosts
    "2161": ItemEffect(item_id="2161", name="Bandle Juice of Power",
        defensive_only=True, note="Bandle Juice of Power (2161): Bandle City ARAM consumed item - no modeled DPS"),
    "2162": ItemEffect(item_id="2162", name="Bandle Juice of Vitality",
        defensive_only=True, note="Bandle Juice of Vitality (2162): Bandle City ARAM consumed item - no modeled DPS"),
    "2163": ItemEffect(item_id="2163", name="Bandle Juice of Haste",
        defensive_only=True, note="Bandle Juice of Haste (2163): Bandle City ARAM consumed item - no modeled DPS"),

    # Trinkets and ward items (0g)
    "3340": ItemEffect(item_id="3340", name="Stealth Ward",
        defensive_only=True, note="Stealth Ward (3340): vision trinket - no DPS contribution"),
    "3363": ItemEffect(item_id="3363", name="Farsight Alteration",
        defensive_only=True, note="Farsight Alteration (3363): vision trinket - no DPS contribution"),
    "3364": ItemEffect(item_id="3364", name="Oracle Lens",
        defensive_only=True, note="Oracle Lens (3364): vision trinket - no DPS contribution"),
    "3599": ItemEffect(item_id="3599", name="Kalista's Black Spear",
        defensive_only=True, note="Kalista's Black Spear (3599): Kalista ally bond - no DPS contribution"),
    "3600": ItemEffect(item_id="3600", name="Kalista's Black Spear",
        defensive_only=True, note="Kalista's Black Spear (3600): Kalista ally bond variant - no DPS contribution"),

    # Support milestone quest items
    "3865": ItemEffect(item_id="3865", name="World Atlas",
        defensive_only=True, note="World Atlas (3865): support quest milestone - no DPS proc"),
    "3869": ItemEffect(item_id="3869", name="Celestial Opposition",
        defensive_only=True, note="Celestial Opposition (3869): support quest milestone - no DPS proc"),
    "3870": ItemEffect(item_id="3870", name="Dream Maker",
        defensive_only=True, note="Dream Maker (3870): support quest milestone - no DPS proc"),
    # Phase 4 batch 61 (2026-05-04): Zaz'Zak's Realmspike - promoted. Meraki confirms
    # Void Explosion: 10 + 15% AP + 3% each target's max HP magic damage per 10s.
    # Ability-triggered proc with 10s item-side CD; modeled via every_n_seconds=10.0
    # (binding-constraint: the item CD is the floor, not the ability cast rate).
    "3871": ItemEffect(
        item_id="3871",
        name="Zaz'Zak's Realmspike",
        periodics=(PeriodicProc(
            name="Void Explosion",
            bonus_damage=lambda c: c.targets_in_rotation * (
                10.0 + 0.15 * c.ap + 0.03 * c.target_max_hp
            ),
            damage_type=MAGICAL,
            every_n_seconds=10.0,
        ),),
        note=(
            "Zaz'Zak's Realmspike: Void Explosion - 10 + 15% AP + 3% each "
            "target's max HP magic damage, 10s CD (Meraki confirmed). AoE burst "
            "scaled by targets_in_rotation; ability-cast gated, modeled at item CD."
        ),
    ),
    "3876": ItemEffect(item_id="3876", name="Solstice Sleigh",
        defensive_only=True, note="Solstice Sleigh (3876): support quest milestone - no DPS proc"),
    # Phase 4 batch 61 (2026-05-04): Bloodsong - promoted. Meraki confirms Spellblade
    # 100% base AD physical (same ratio as Sheen; 1.5s ability-use cadence) + Expose
    # Weakness +5% (ranged) / +8% (melee) increased damage from all sources on champion
    # hit. damage_amp_pct=0.05 models ranged Expose Weakness at ~100% combat uptime
    # (support builds without competing spellblade items). Note: if a higher-priority
    # spellblade (unique_passive_key) overrides this item's proc, the engine still
    # applies the damage_amp - accurate only for solo-Bloodsong builds.
    "3877": ItemEffect(
        item_id="3877",
        name="Bloodsong",
        damage_amp_pct=0.05,
        periodics=(PeriodicProc(
            name="Spellblade",
            bonus_damage=lambda c: 1.00 * c.base_ad,
            damage_type=PHYSICAL,
            every_n_seconds=1.5,
        ),),
        unique_passive_key="spellblade",
        note=(
            "Bloodsong: Spellblade 100% base AD physical every ~1.5s + Expose Weakness "
            "+5% all-source damage (ranged; +8% melee) at ~100% combat uptime. "
            "damage_amp_pct modeled at ranged value; joins spellblade unique-passive family."
        ),
    ),

    # Arena placeholder / selector items
    "6032": ItemEffect(item_id="6032", name="Stat Bonus",
        defensive_only=True, note="Stat Bonus (6032): Arena generic stat purchase - no specific DPS proc"),
    "220000": ItemEffect(item_id="220000", name="Stat Bonus",
        defensive_only=True, note="Stat Bonus (220000): Arena generic stat purchase - no specific DPS proc"),
    "220001": ItemEffect(item_id="220001", name="Legendary Fighter Item",
        defensive_only=True, note="Legendary Fighter Item (220001): Arena random Legendary selector - no fixed DPS effect"),
    "220002": ItemEffect(item_id="220002", name="Legendary Marksman Item",
        defensive_only=True, note="Legendary Marksman Item (220002): Arena random Legendary selector - no fixed DPS effect"),
    "220003": ItemEffect(item_id="220003", name="Legendary Assassin Item",
        defensive_only=True, note="Legendary Assassin Item (220003): Arena random Legendary selector - no fixed DPS effect"),
    "220004": ItemEffect(item_id="220004", name="Legendary Mage Item",
        defensive_only=True, note="Legendary Mage Item (220004): Arena random Legendary selector - no fixed DPS effect"),
    "220005": ItemEffect(item_id="220005", name="Legendary Tank Item",
        defensive_only=True, note="Legendary Tank Item (220005): Arena random Legendary selector - no fixed DPS effect"),
    "220006": ItemEffect(item_id="220006", name="Legendary Support Item",
        defensive_only=True, note="Legendary Support Item (220006): Arena random Legendary selector - no fixed DPS effect"),
    "220007": ItemEffect(item_id="220007", name="Prismatic Item",
        defensive_only=True, note="Prismatic Item (220007): Arena random Prismatic selector - no fixed DPS effect"),

    # Special items
    "663064": ItemEffect(item_id="663064", name="Veigar's Talisman of Ascension",
        defensive_only=True, note="Veigar's Talisman of Ascension (663064): +100% XP bonus; no DPS contribution"),
    "994403": ItemEffect(item_id="994403", name="Golden Spatula",
        defensive_only=True, note="Golden Spatula (994403): cross-mode item; no DPS contribution in SR/ARAM/Arena model"),

    # -- R153 (2026-07-21): flat magic-pen stat-block parity --
    # Same catalog defect class as the R152 lethality slice: DDragon's
    # structured stats block has no flat-magic-pen key, so the magnitude
    # survives only in the description prose. An id with no entry here
    # reads 0.0 at effects.effective_target_mr. 1111 was the only such
    # gap in the 706-item catalog.
    "1111": ItemEffect(
        item_id="1111",
        name="Jarvan I's",
        magic_pen_flat=12.0,
        note=(
            "Jarvan I's (1111): 12 flat magic pen. The value appears ONLY in the "
            "description text (<attention>12</attention> Magic Penetration); the "
            "structured DDragon stats block omits it, carrying just MR/MS/armor/AS. "
            "DS already registered this item's 10 ability haste (_item_ability_haste) "
            "and 30 tenacity (_item_tenacity), so the pen credit restores registration "
            "consistency across all three axes. ARAM-only (maps.12) augment-gated "
            "all-boots prismatic; the Jarvan One all-boots-passives grant is not modeled"
        ),
    ),

}


# ---------------------------------------------------------------------------
# A-04 / RM-99b: Heartsteel damage-half cadence correction (DEFAULT-OFF seam)
# ---------------------------------------------------------------------------
#
# WHAT IS WRONG. The 3084 / 223084 Colossal Consumption procs above carry
# ``every_n_seconds=3.5``, which is NEITHER interval the item's own feed states.
# Meraki ``items["3084"].passives[0].effects`` (the only feed that states a number
# for this item) reads: "generate a stack on them each second, stacking up to 3
# times" and "(30 second cooldown per target)". So the two real intervals are a
# 3-second charge window and a 30-second per-target cooldown. The empowered attack
# is gated by the COOLDOWN, not the charge. ``dps._periodic_proc_dps`` computes
# ``procs = duration / every_n_seconds``, so a single-target rotation is credited
# 30 / 3.5 = 8.5714x the real proc count. MEASURED at shipped build depth
# (build_orders_sr.json 4-to-6 item prefixes, 8 bruiser/tank champions): the
# isolated Heartsteel damage term is exactly 8.5714x too large in every case, and
# it supplies 13% to 32% of total credited auto-attack DPS on those builds.
#
# WHY IT MATTERS BEYOND THE ONE ITEM. R137's ``_item_health_stack`` models the OTHER
# half of the same passive (the permanent-HP-per-proc grant) and derives its proc
# curve from the REAL 30s, then records the disagreement in its docstring as
# deliberate and unresolved. The two halves of one item's model therefore disagree
# about how often it fires. That disagreement - not the raw constant - is the
# invariant ``tests/test_heartsteel_cadence_a04.py`` pins.
#
# WHY DEFAULT-OFF. Correcting the constant is a change to already-shipped damage
# scoring, and it REORDERS live build orders hard: on /rank-bruiser at real depth
# Heartsteel currently reads #1 or #2 for every bruiser measured and drops to #6
# through #43 of a ~135-item pool once corrected. That is an operator call, not an
# agent call, so the corrected value lands here behind a named flag that defaults
# False and returns the live mapping ITSELF when off (identity - byte-identical, no
# copy, no consumer change). Flipping the default is a one-line edit plus a wire in
# ``dps.py`` / the rank routes; nothing is wired yet.
#
# ARENA MIRROR (R161 doctrine B - credit the mirror from its OWN feed). Checked
# first, and the answer is that no feed states a cooldown for 223084: it is absent
# from Meraki entirely, and its own DDragon description renders the cooldown as a
# zeroed template ("Colossal Consumption (0s) per target"). Its description DOES
# carry the literal "per target" token, so the per-target-cooldown STRUCTURE is
# confirmed on the mirror's own data; only the magnitude is unavailable. The 30s
# below is therefore INHERITED and UNSOURCED for 223084 - the same provenance
# ``_item_health_stack`` records for its own 223084 coefficient, and Riot
# demonstrably retuned this mirror on other axes (700 vs 900 Health, 2500g vs
# 3000g). Re-source before any map-30 default-ON flip.

# The real gate on the empowered attack, per the Meraki passive text quoted above.
# Patch-pinned like every other constant in this file; the test parses the feed and
# fails if this drifts from it.
HEARTSTEEL_PER_TARGET_COOLDOWN_S: float = 30.0

# ARENA MIRROR ONLY (operator decision 2026-07-24). The SR entry 3084 now ships
# the corrected 30.0 directly in the table above - it is no longer behind this
# seam, because the SR magnitude is sourced from the Meraki passive text. The
# Arena mirror 223084 stays at the old 3.5 and is corrected only when this seam
# is switched on, because 30s is UNSOURCED on 223084's own feed (R161 doctrine
# B). If 223084's real per-target cooldown is ever sourced, correct the table
# entry and retire this seam rather than flipping its default.
HEARTSTEEL_CADENCE_FIX_IDS: tuple[str, ...] = ("223084",)


def heartsteel_per_target_cooldown_s() -> float:
    """Return the corrected Colossal Consumption cadence in seconds.

    A function rather than a bare constant read so a consumer cannot accidentally
    close over a stale value at import time.
    """
    return HEARTSTEEL_PER_TARGET_COOLDOWN_S


def apply_heartsteel_cadence_fix(
    effects: dict[str, ItemEffect] | None = None,
    *,
    apply_heartsteel_per_target_cadence: bool = False,
) -> dict[str, ItemEffect]:
    """Return item effects with the ARENA Heartsteel mirror's cadence corrected.

    SCOPE NARROWED 2026-07-24 (operator decision). The SR entry 3084 now ships the
    corrected 30s per-target gate directly in :data:`ITEM_EFFECTS`, so it is NOT
    routed through this seam - flipping this flag does not move any SR scoring.
    This seam covers only the Arena mirror 223084, whose 30s would be inherited
    from the SR twin rather than sourced from its own feed (R161 doctrine B).

    ``effects`` defaults to the live :data:`ITEM_EFFECTS`. When
    ``apply_heartsteel_per_target_cadence`` is False (the default) the SAME mapping
    object is returned unchanged - identity, so callers are byte-identical and no
    scoring moves. When True, a shallow copy is returned in which each id in
    :data:`HEARTSTEEL_CADENCE_FIX_IDS` has its seconds-based procs re-timed to
    :func:`heartsteel_per_target_cooldown_s`; every other entry is the same object,
    the damage FORMULA is untouched, and :data:`ITEM_EFFECTS` is never mutated.

    Unregistered or attack-counted procs are left alone, so this is a no-op on any
    build that does not carry the Arena Heartsteel mirror.
    """
    src = ITEM_EFFECTS if effects is None else effects
    if not apply_heartsteel_per_target_cadence:
        return src
    cadence = heartsteel_per_target_cooldown_s()
    patched = dict(src)
    for item_id in HEARTSTEEL_CADENCE_FIX_IDS:
        entry = patched.get(item_id)
        if entry is None or not entry.periodics:
            continue
        procs = tuple(
            dataclasses.replace(p, every_n_seconds=cadence)
            if p.every_n_seconds > 0
            else p
            for p in entry.periodics
        )
        patched[item_id] = dataclasses.replace(entry, periodics=procs)
    return patched
