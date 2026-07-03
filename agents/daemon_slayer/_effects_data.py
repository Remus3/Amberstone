"""Static per-item ItemEffect registry for Daemon Slayer (ITEM_EFFECTS).

Split out of effects.py (s246, behavior-preserving): this is the
patch-pinned multi-thousand-line data table. effects.py keeps the
logic functions and re-exports ITEM_EFFECTS from here. Patch-pinned
per data/daemon_slayer/current.txt - refresh on patch bump (the
extractor manifest is the trigger), exactly as before the split.
"""

from __future__ import annotations

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
        note="Lord Dominik's Regards: 35% armor pen (physical) + Giant Slayer up to 15% damage scaling with target_bonus_hp (capped at 1500)",
    ),
    "3033": ItemEffect(
        item_id="3033",
        name="Mortal Reminder",
        armor_pen_pct=0.30,
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
    # No unique_passive_key - the % pen layer sums across items in current
    # League (LDR + Serylda would stack to 70% pen if a build carried both;
    # the build-legality "only one of these archetypes" decision is
    # ranker-owned, not effect-layer).
    "6694": ItemEffect(
        item_id="6694",
        name="Serylda's Grudge",
        armor_pen_pct=0.35,
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
        note="Serpent's Fang: anti-shield; situational, not DPS-modeled",
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
        note="Frozen Heart: AS-slow aura + armor; no DPS contribution",
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
        # armor+MR per stack, level pp 1;11;14) stay caster-side and
        # OUT of scope - no item-keyed resist-grant path exists
        # (_passive_resist_overrides.py is champion-keyed only); FUTURE.
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
            "30% magic pen (BC full-stack convention); Light caster-side "
            "resists not modeled"
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
            # HP-on-damage permanent stack (8% of damage as max HP) is not
            # modeled - that's stat-side, not proc-side.
            bonus_damage=lambda c: 70.0 + 0.06 * c.caster_max_hp,
            damage_type=PHYSICAL,
            every_n_seconds=3.5,
        ),),
        note=(
            "Heartsteel: Colossal Consumption flat 70 + 6% caster max HP "
            "physical every ~3.5s in combat"
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
        note="Guardian Angel: revive after lethal damage; no DPS contribution",
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
        note="Stridebreaker: Cleave ~40% AD physical to other enemies in 350 radius (melee, scales with rotation targets)",
    ),
    # Phase 4 batch 24 (2026-05-04): Profane Hydra (6698) added to
    # ITEM_EFFECTS as a new entry (was stats-only via item aggregation
    # prior - assassin-tagged Tiamat upgrade). Per Meraki bulk, Cleave
    # deals "40% AD (melee) / 20% AD (ranged) physical damage to other
    # enemies in a 350 radius centered around the target" on every
    # damaging basic on-hit. Same shape and per-rotation isolation as
    # Stridebreaker / Ravenous; coefficient pinned at 40% (melee value)
    # to match Stridebreaker's call. Heretical Cleave active (~80% AD
    # AoE) stays not-modeled - Meraki bulk has its cooldown null and
    # actives-without-CD-pin are deferred per the s77/s78 hand-off rule.
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
        note="Profane Hydra: Cleave ~40% AD physical to other enemies in 350 radius (melee, scales with rotation targets)",
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
        # to lift Lich Bane / Nashor's Tooth proc damage. The omnivamp
        # at full Void Corruption stacks is intentionally not modeled
        # (DPS engine doesn't track healing).
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
        note="Void Staff: 40% magic pen (magical)",
    ),
    "3137": ItemEffect(
        item_id="3137",
        name="Cryptbloom",
        magic_pen_pct=0.30,
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
            # Melee: 35% total AD physical to nearby enemies only (no
            # damage to primary target - that already lands via the basic
            # attack). With targets_in_rotation=1.0 the cleave hits 0 enemies
            # and contributes zero, exactly the historic single-target shape.
            # Ranged variant 21% under-counted - same call as Titanic.
            bonus_damage=lambda c: max(0.0, c.targets_in_rotation - 1.0)
                * 0.35 * (c.base_ad + c.bonus_ad),
            damage_type=PHYSICAL,
            every_n_attacks=1,
        ),),
        # Iter 3 (2026-05-19): hydra_cleave family - see Stridebreaker.
        unique_passive_key="hydra_cleave",
        note="Ravenous Hydra: Cleave ~35% AD physical to nearby enemies (melee, scales with rotation targets)",
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
        # Lifeline shield (350 + max-mana% shield at <30% HP) is non-DPS;
        # tagged ``unique_passive_key="lifeline"`` so collect_effects
        # dedups against Shieldbow / Sterak's / Maw / Phantom Dancer
        # (which uses Spectral Waltz, NOT lifeline - see batch 12). The
        # Awe walk lives in engine.py and bypasses collect_effects, so
        # the AP contribution survives any lifeline dedup.
        bonus_ap_pct_bonus_mp=0.02,
        unique_passive_key="lifeline",
        note=(
            "Seraph's Embrace: Awe +2% bonus mana as AP + Lifeline "
            "(low-HP mana shield, deduped - no DPS contribution from "
            "the shield piece)"
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
        # Approach. Everfrost passive: first ability hit in combat freezes
        # target briefly. CC utility, ability-bound - not a per-auto DPS proc.
        note="Fimbulwinter: Awe (8% max mana as HP) + Everfrost CC on first ability hit (ability-bound utility); no DPS contribution",
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
        note=(
            "Overlord's Bloodmail: Tyranny 2.5% bonus HP as bonus AD "
            "(engine resolves at stat-build time via item_totals[hp_flat]). "
            "Retribution missing-HP-scaled AD not modeled (combat ramp)"
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
            "Horizon Focus: Hypershot 15% damage amp requires range 600+ and ability "
            "hit (range conditional + ability-cast schema gap); no sustained DPS contribution"
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
    # Unending Despair (2502): Agony - 3% caster bonus HP magic damage every 4s.
    # Meraki: 3% bonus HP to self and nearest ally as magic. Using self-damage value only
    # (the ally component is utility). Caster-bonus-HP-scaled proc via caster_bonus_hp.
    "2502": ItemEffect(
        item_id="2502",
        name="Unending Despair",
        periodics=(
            PeriodicProc(
                name="Agony",
                every_n_seconds=4.0,
                bonus_damage=lambda c: 0.03 * c.caster_bonus_hp,
                damage_type=MAGICAL,
            ),
        ),
        note=(
            "Unending Despair: Agony 3% caster bonus HP magic damage every 4s "
            "(proc AoE to enemy; ally self-heal component utility-only; "
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
        defensive_only=True,
        note=(
            "Sword of the Divine: Pact of the Blade conditional 100% crit guarantee "
            "on ability (ability-cast schema gap); stat block AS bonus only"
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
    # Navori Flickerblade (6672): Bring It Down - every 3rd basic attack deals bonus
    # physical damage on-hit, scaling 120->168 (ranged) over levels 1->13.
    # Quicken (CDR on crit) is utility-only.
    "6675": ItemEffect(
        item_id="6675",
        name="Navori Flickerblade",
        periodics=(
            PeriodicProc(
                name="Bring It Down",
                every_n_attacks=3,
                bonus_damage=lambda c: min(168.0, 120.0 + 4.0 * (c.level - 1)),
                damage_type=PHYSICAL,
            ),
        ),
        note=(
            "Navori Flickerblade: Bring It Down 120->168 bonus physical every 3rd attack "
            "(ranged scaling 120 + 4 x (level-1), capped at 168 at level 13+; "
            "Quicken CDR-on-crit utility-only)"
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
        note=(
            "Goredrinker: Thirsting Slash is an active ability (no passive DPS proc); "
            "Resolve 8% omnivamp is lifesteal (utility); no DPS contribution"
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
    # by 7%, stacks 5 times = 35% max reduction. Same layer as Black Cleaver's
    # armor_reduction_pct (applied before % pen). Modeled at full stacks per sustained-
    # DPS convention. Fervor 20 MS utility-only.
    "228005": ItemEffect(
        item_id="228005",
        name="Obsidian Cleaver",
        armor_reduction_pct=0.35,
        note=(
            "Obsidian Cleaver: Carve 7% armor reduction per stack x 5 stacks = 35% max "
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
            "Protoplasm Harness: Lifeline - triggered shield when dropping below 30% HP, "
            "then heals max HP over 5s + size/MS/tenacity boost. "
            "Joins lifeline unique-passive family (Immortal Shieldbow, Sterak's, Maw, Seraph's). "
            "Shield/sustain mechanic, no DPS"
        ),
    ),
    "3143": ItemEffect(
        item_id="3143",
        name="Randuin's Omen",
        defensive_only=True,
        note=(
            "Randuin's Omen: Resilience 30% reduced crit damage taken + Humility "
            "active 70% AoE slow - damage mitigation + CC active, no DPS contribution"
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
    # dynamic and not modelable in static sustained-DPS; deferred.
    "447111": ItemEffect(
        item_id="447111",
        name="Overlord's Bloodmail",
        bonus_ad_pct_bonus_hp=0.03,
        note=(
            "Overlord's Bloodmail (Arena 447111): Tyranny 3% bonus HP -> bonus AD "
            "(Arena variant; SR 2501 has 2.5%). "
            "Retribution up-to-17.5% AD based on missing HP deferred (dynamic)"
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
        note=(
            "Duskblade of Draktharr (446691 Arena): Nightstalker - ability damage amp "
            "based on target missing HP; ability-cast schema gap; deferred. "
            "Different mechanism from SR 6691 (which just carries lethality)"
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
        # Phase 4 batch 54 (2026-05-04): promoted. Glory grants 5 AP per kill
        # stack (max 25 stacks = 125 AP); DDragon's FlatMagicDamageMod only
        # carries the base 20 AP. Engine pins at full 25 stacks (same
        # sustained-peak convention as BC armor-reduction at full stacks /
        # Riftmaker at full ramp). AP-scaling procs (Lich Bane, Nashor's) and
        # Rabadon's amplification both see the stacked total via compute_dps.
        bonus_ap_stacked=125.0,
        note=(
            "Mejai's Soulstealer: Glory +125 stacked AP (25 stacks x 5 AP; "
            "full-stacks pin - same sustained-peak convention as Black Cleaver)"
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
        note=(
            "Plated Steelcaps: Plating - reduces incoming damage from Attacks by 10%. "
            "Incoming damage reduction, no DPS proc"
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
        note="Stridebreaker (Arena 226631): same as SR 6631 - Cleave 40% AD to other enemies",
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
        takedown_eruption_base=60.0,
        takedown_eruption_bonus_hp_ratio=0.04,
        note=(
            "Hollow Radiance (Arena 226664): same as SR 6664 - Immolate "
            "15+1% bonus HP per second (Meraki 16.10.1); Desolate "
            "champion-takedown eruption modeled R70 on assume_takedown "
            "(400% Immolate = 60 + 4% bonus HP magic within 500); 200% "
            "non-champion kill eruption unmodeled"
        ),
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
        armor_pen_pct=0.35,
        note="Serylda's Grudge (Arena 226694): same as SR 6694 - 35% armor penetration",
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
        periodics=(PeriodicProc(
            name="Cleave",
            bonus_damage=lambda c: max(0.0, c.targets_in_rotation - 1.0)
                * 0.40 * (c.base_ad + c.bonus_ad),
            damage_type=PHYSICAL,
            every_n_attacks=1,
        ),),
        unique_passive_key="hydra_cleave",
        note="Profane Hydra (Arena 226698): same as SR 6698 - Cleave 40% AD to other enemies",
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
        lethality=10.0,
        note="Voltaic Cyclosword (Arena 226699): same as SR 6699 - Energized 100 flat bonus physical, 10 lethality",
    ),
    "226701": ItemEffect(
        item_id="226701",
        name="Opportunity",
        lethality=18.0,
        note="Opportunity (Arena 226701): same as SR 6701 - 18 lethality",
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
        note="Goredrinker (Arena 226630): Thirsting Slash active heal - sustain only, no DPS contribution",
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
        lethality=10.0,
        # DSV2 (1.125.0): Arena mirror of SR 6676 Death execute finisher.
        execute_max_hp_pct=0.05,
        note="The Collector (Arena 226676): mirrors SR 6676 - 50 AD + 10 Lethality + 25% Crit; "
             "Death execute below 5% HP valued as a kill-state finisher under assume_takedown; "
             "Taxes (25g) is out-of-combat. lethality=10.0 feeds the rotation.",
    ),
    "226695": ItemEffect(
        item_id="226695",
        name="Serpent's Fang",
        defensive_only=True,
        note="Serpent's Fang (Arena 226695): Shield Reaver anti-shield - utility, no DPS contribution",
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
            name="Agony",
            every_n_seconds=4.0,
            bonus_damage=lambda c: 0.03 * c.caster_bonus_hp,
            damage_type=MAGICAL,
        ),),
        note="Unending Despair (Arena 222502): same as SR 2502 - Agony 3% caster bonus HP magic every 4s",
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
        note="Kaenic Rookern (Arena 222504): Nullmagic Mantle magic-damage shield; no DPS contribution",
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
        note="Protoplasm Harness (Arena 222525): Lifeline shield; joins lifeline unique-passive family",
    ),

    # -- 224xxx Arena mirrors (base 4xxx) ----------------------------------

    "224004": ItemEffect(
        item_id="224004",
        name="Spectral Cutlass",
        lethality=15.0,
        note="Spectral Cutlass (Arena 224004): same as SR 4004 - 15 lethality (level-scaled flat pen)",
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
        note="Horizon Focus (Arena 224628): Hypershot slowed/immobilized amp - ability-trigger; deferred",
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
        magic_pen_flat=15.0,
        note="Shadowflame (Arena 224645): same as SR 4645 - Cinderbloom 15 flat magic pen",
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
        magic_pen_flat=12.0,
        note="Sorcerer's Shoes (Arena 223020): same as SR 3020 - 12 flat magic pen",
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
        note="Mortal Reminder (Arena 223033): same as SR 3033 - Last Whisper 30% armor pen",
    ),
    "223036": ItemEffect(
        item_id="223036",
        name="Lord Dominik's Regards",
        armor_pen_pct=0.35,
        target_bonus_hp_amp_max_pct=0.15,
        target_bonus_hp_amp_cap=1500.0,
        note="Lord Dominik's (Arena 223036): same as SR 3036 - 35% armor pen + Giant Slayer up to 15% at 1500 bonus HP",
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
        note="Sunfire Aegis (Arena 223068): same as SR 3068 - Immolate 20+1% bonus HP magic/s (Meraki 16.10.1), immolate-key",
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
            bonus_damage=lambda c: max(0.0, c.targets_in_rotation - 1.0)
                * 0.35 * (c.base_ad + c.bonus_ad),
            damage_type=PHYSICAL,
            every_n_attacks=1,
        ),),
        unique_passive_key="hydra_cleave",
        note="Ravenous Hydra (Arena 223074): same as SR 3074 - Cleave 35% AD to other enemies",
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
        note="Void Staff (Arena 223135): same as SR 3135 - Void Leech 40% magic pen",
    ),
    "223137": ItemEffect(
        item_id="223137",
        name="Cryptbloom",
        magic_pen_pct=0.30,
        note="Cryptbloom (Arena 223137): same as SR 3137 - Draining Venom 30% magic pen",
    ),
    "223142": ItemEffect(
        item_id="223142",
        name="Youmuu's Ghostblade",
        lethality=18.0,
        note="Youmuu's Ghostblade (Arena 223142): same as SR 3142 - 18 lethality",
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
        armor_pen_pct=0.30,
        magic_pen_pct=0.30,
        note="Terminus (Arena 223302): same as SR 3302 - Shadow 30 magic on-hit + Juxtaposition Dark 3-stack steady-state 30% armor+magic pen (BC full-stack convention); Light caster-side resists not modeled",
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
        lethality=15.0,
        note="Edge of Night (Arena 223814): same as SR 3814 - 15 lethality",
    ),

    # -- 25 defensive_only 223xxx mirrors ---------------------------------

    "223026": ItemEffect(
        item_id="223026",
        name="Guardian Angel",
        defensive_only=True,
        note="Guardian Angel (Arena 223026): Rebirth passive revive - no DPS contribution",
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
        note="Plated Steelcaps (Arena 223047): Plating 10% incoming attack damage reduction; no DPS proc",
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
        note="Malignance ARAM mirror (223118) Hatefog: (180+15%AP) magic per ult zone hit",
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
        note="Randuin's Omen (Arena 223143): Humility crit-damage reduction + active slow - defensive, no DPS",
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
            bonus_damage=lambda c: max(0.0, c.targets_in_rotation - 1.0)
                * 0.50 * (c.base_ad + c.bonus_ad),
            damage_type=PHYSICAL,
            every_n_attacks=1,
        ),),
        note="Tiamat (3077): Cleave 50% total AD to nearby - zero in single-target, scales with targets_in_rotation",
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
    "3131": ItemEffect(
        item_id="3131",
        name="Sword of the Divine",
        lethality=18.0,
        periodics=(PeriodicProc(
            name="Divine Judgment",
            bonus_damage=lambda c: 0.75 * (c.base_ad + c.bonus_ad),
            damage_type=PHYSICAL,
            every_n_seconds=15.0,
        ),),
        note="Sword of the Divine (3131): 18 leth + Divine Judgment guaranteed-crit bonus (~75% AD extra) every 15s",
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
        note="Bami's Cinder (Arena 226660): same as SR 6660 - Immolate flat 15 magic/s (Meraki 16.10.1); shares immolate-key",
    ),
    "226691": ItemEffect(
        item_id="226691",
        name="Duskblade of Draktharr",
        lethality=18.0,
        note="Duskblade of Draktharr (Arena 226691): same as SR 6691 - 18 lethality",
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
        note="Seraph's Embrace (Arena 223040): same as SR 3040 - Awe 2% bonus mana as AP + Shurelya lifeline shield",
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
        note="Seraph's Embrace (ARAM 323040): same as SR 3040 - Awe 2% bonus mana as AP + lifeline shield",
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
        periodics=(PeriodicProc(
            name="Immolate",
            bonus_damage=lambda c: c.targets_in_rotation * (20.0 + 0.015 * c.caster_max_hp),
            damage_type=TRUE,
            every_n_seconds=1.0,
        ),),
        unique_passive_key="immolate",
        note=(
            "Void Immolation (Arena 223069): Immolate 20 + 1.5% max HP true damage/s "
            "to nearby enemies (Meraki confirmed; TRUE damage off max HP - distinct "
            "from SR 3068/6664 which deal magical off bonus HP)"
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
        note="Fimbulwinter (Arena 223121): same as SR 3121 - shield passive on ability near enemies, no DPS proc",
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
        note="Shurelya's Battlesong (ARAM 222065): same as SR 2065 - Inspire MS burst aura, no self DPS",
    ),
    "222051": ItemEffect(
        item_id="222051",
        name="Guardian's Horn",
        defensive_only=True,
        note="Guardian's Horn (ARAM 222051): HP + defensive stats component - no DPS proc",
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
        note="Fimbulwinter (ARAM 323121): same as SR 3121 - shield passive, no DPS proc",
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
        magic_pen_flat=18.0,
        magic_pen_pct=0.08,
        note="Spellslinger's Shoes (3175): 18 flat magic pen + 8% magic pen + 45 MS - both pen layers stack with Sorcerer's/Shadowflame",
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
        defensive_only=True, note="Chainlaced Crushers (3173): MR + tenacity boots - no DPS contribution"),
    "3174": ItemEffect(item_id="3174", name="Armored Advance",
        defensive_only=True, note="Armored Advance (3174): Armor boots - no DPS contribution"),
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

}
