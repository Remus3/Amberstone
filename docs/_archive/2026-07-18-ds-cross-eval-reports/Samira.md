# Samira DS Cross-Eval Report

**Verdict: MINOR**

Scorer: dps | Archetype: carry/assassin | Anchor: ARAM | Evidence: outcome_self (n=48, wr=60.4)

---

## Axis 1 - archetype_ok: PASS

carry/assassin with scorer=dps is correct. Samira is an AD melee crit-carry; dps scorer on the AD axis aligns with kit. Empirical above-baseline items (>60.4 wr) are all AD physical: The Collector (62.8), Infinity Edge (61.0), Immortal Shieldbow (62.5), Bloodthirster (64.3), Lord Dominik's Regards (70.0), Mercury's Treads (71.4). No AP items appear in empirical winners. Axis assignment is correct.

## Axis 2 - comp_ok: PASS

scorer=dps -> target_resist responsiveness expected; enemy_damage_type comp-blind is expected (it affects EHP not DPS). responsiveness.target_resist.comp_blind=false, max_positive_shift=10. Liandry's Torment (+10), Serylda's Grudge (+9), Mortal Reminder (+8), Lord Dominik's Regards (+8) rise when targets are tanky - appropriate pen/grievous items. enemy_damage_type.comp_blind=true with max_positive_shift=0 is correct behavior for a dps scorer (enemy damage type does not affect what items maximize Samira's own damage output). No defect.

## Axis 3 - outcome_ok: FAIL

Scorer top-8 in ad_squishy / bal_squishy (primary cells): rank1 Void Immolation (223069), rank2 BotRK (3153), rank3 Essence Reaver (3508), rank4 Stormrazor (3097), rank5 Runaan's Hurricane (3085), rank6 Kraken Slayer (6672), rank7 Voltaic Cyclosword (6699), rank8 Dusk and Dawn (2510).

Empirical items above baseline wr=60.4 (outcome_self n=48):
- The Collector (6676): n=43, wr=62.8 - ABSENT from scorer top-12 in squishy cells
- Infinity Edge (3031): n=41, wr=61.0 - rank 9 (outside top-8)
- Immortal Shieldbow (6673): n=24, wr=62.5 - ABSENT from scorer top-12 in squishy cells
- Bloodthirster (3072): n=14, wr=64.3 - ABSENT from scorer top-12 in squishy cells
- Lord Dominik's Regards (3036): n=10, wr=70.0 - rank 12 in tanky cells only; absent from squishy top-12

The Collector is the single highest-n empirical item (n=43) and is a confirmed above-baseline winner (62.8 > 60.4) yet does not appear anywhere in the scorer's top-12 for squishy cells. It appears only in target_resist.top_fallers_when_ap (shift -3), which is why it drops out of tanky-cell recommendations - but in the squishy primary cells it should surface and does not. Immortal Shieldbow (n=24, wr=62.5) and Bloodthirster (n=14, wr=64.3) are both empirically above baseline and absent from top-12.

This is a pool gap: the scorer's DPS math does not rank The Collector, Immortal Shieldbow, or Bloodthirster highly enough for Samira's kit despite empirical evidence of their value.

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Investigate why The Collector (6676), Immortal Shieldbow (6673), and Bloodthirster (3072) score low for Samira in the dps scorer squishy cells. The Collector's on-kill execute and crit interaction and Immortal Shieldbow's shield-on-crit passive may not be captured by the current dps math. Bloodthirster's lifesteal is substantial for a sustained-damage carry. Recommended: audit dps scorer passive credit for these three items against Samira's kit (execute mechanics, lifesteal, shieldbow proc).
