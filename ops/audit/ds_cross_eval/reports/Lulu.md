# DS Cross-Eval: Lulu

**Verdict: MISMATCH**

Scorer: dps | Archetype: carry/mage (source: user_cs) | Anchor: ARAM | Evidence: outcome_self (n=10, wr=50.0%)

---

## Axis 1 - archetype_ok: FALSE

carry+mage archetype dispatches dps scorer (AD axis). Lulu's kit is AP-based (Q/E/R scale AP); she is an AP mage/enchanter by design. The dps scorer produces an AD item pool: BotRK rank 1, Kraken Slayer rank 3, Essence Reaver rank 4, Stormrazor rank 5, IE rank 7.

Empirical self (n=10) does show AD items winning: BotRK 71.4%, Guinsoo's Rageblade 66.7%, Berserker's Greaves 60.0%. However n=10 is small and the "all" pool (n=125, wr=52.0%) is dominated by enchanter items (Moonstone Renewer, Ionian Boots, Ardent Censer, Staff of Flowing Water 61.1%). The scorer axis (AD/dps) conflicts with both Lulu's AP kit and the broader empirical pool. The carry archetype assignment (user_cs) appears to reflect a niche on-hit ARAM build, not Lulu's canonical role.

## Axis 2 - comp_ok: TRUE

Scorer is dps; dps scorer should respond to target_resist (tanky enemies). target_resist.comp_blind=false, max_positive_shift=19. Top risers vs tanky: Liandry's Torment +19 (rank shift), Serylda's Grudge +13, LDR +10. Responsiveness is present and correct for a dps scorer. enemy_damage_type.comp_blind=true (no damage-type shift) is expected for a dps scorer - no defect here.

## Axis 3 - outcome_ok: FALSE

Using outcome_self (n=10 >= 8). Baseline wr=50.0%. Items above baseline:
- BotRK: wr 71.4%, n=7 -> scorer rank 1 in ad_squishy. ALIGNED.
- Guinsoo's Rageblade: wr 66.7%, n=6 -> NOT present in scorer top-8 or visible in comp_grid. MISSING.
- Berserker's Greaves: wr 60.0%, n=5 -> boots (outside item-pool scope, acceptable).

Guinsoo's Rageblade is the second-highest empirical win-rate item (66.7%) and is absent from the scorer pool top ranks. This is a pool gap - a high-wr staple the scorer cannot recommend.

## Axis 4 - rune_ok: n/a

rune_relevant=false.

---

## Nominated Retune

Re-evaluate archetype assignment: Lulu's canonical kit is AP mage/enchanter; the carry(dps) assignment appears to be a user-cs on-hit ARAM edge case. Two options:

1. If on-hit carry Lulu is intended: add Guinsoo's Rageblade to the dps scorer item pool (it rates 66.7% wr empirically, n=6, and synergizes with BotRK which ranks 1). This fixes the pool gap while keeping the AD scorer.

2. If enchanter/mage Lulu is intended: reclassify archetype to enchanter (or mage), switch scorer to mage or hps/enchanter, which would surface Moonstone Renewer, Staff of Flowing Water, Ardent Censer consistent with the "all" empirical pool (n=125).

Primary recommendation: fix the pool gap first (add Guinsoo's Rageblade under dps scorer for AD on-hit Lulu), then flag for archetype re-classification review given the kit/archetype tension.
