# DS Cross-Eval: Mordekaiser

## Verdict: MISMATCH

Scorer top-1 (Liandry's) empirically loses in ARAM self-data; high-wr staple Rylai's absent from scorer pool.

---

## Axis 1 - archetype_ok: TRUE

Primary=mage, scorer=ability. Ability is the AP/mage scoring axis - correct for Mordekaiser's AP-scaling kit (E DoT,
R realm, Q drain). No wrong-axis flag.

---

## Axis 2 - comp_ok: TRUE

Scorer=ability, primary_axis=target_resist. enemy_damage_type is comp_blind=true (max_positive_shift=0, no
risers/fallers). For an ability/mage offensive scorer, not responding to whether enemies deal AD or AP is expected
behavior - Morde cares about enemy MR/armor stacks, not their damage type. target_resist is NOT comp_blind:
max_positive_shift=5; Bloodletter's Curse +5 rank shift, Void Staff +2, Cryptbloom +2 when enemies are AP-tanky.
This is correct behavior for an ability scorer facing tanky vs squishy comps.

---

## Axis 3 - outcome_ok: FALSE

evidence_tier ARAM = outcome_self (n=21, above 8 threshold). Baseline wr = 52.4%.

Above-baseline empirical items (self):
- Riftmaker (id 4633): wr 55.6%, n=18 - ABOVE baseline
- Rylai's Crystal Scepter (id 3116): wr 75.0%, n=12 - well ABOVE baseline
- Mercury's Treads (id 3111): wr 54.5%, n=11 - ABOVE baseline

Scorer top-8 (ad_squishy cell, representative):
1. Liandry's Torment (6653) - score 26.08
2. Wooglet's Witchcap (228002) - score 18.25
3. Blackfire Torch (2503) - score 16.92
4. Rabadon's Deathcap (3089) - score 6.85
5. Shadowflame (4645) - score 6.26
6. Void Staff (3135) - score 6.25
7. Stormsurge (4646) - score 5.36
8. Cryptbloom (3137) - score 4.68

Problems:
1. Liandry's Torment is scorer #1 but empirical wr=42.9% (n=7, BELOW 52.4 baseline). Scorer top
   recommendation empirically loses.
2. Rylai's Crystal Scepter (wr 75.0%, n=12 self) is absent from scorer pool entirely across all 5 comp cells.
   This is the highest-wr ARAM item in the sample and the scorer does not surface it.
3. Riftmaker (top empirical item wr 55.6%, n=18) scores rank 9 in squishy cells - underranked relative to its
   win rate.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Add Rylai's Crystal Scepter to the Mordekaiser ability-scorer item pool (it is an AP+health item with a slow
passive that scores as AP ability value but may be gated out by a missing passive registration). Investigate why
Liandry's Torment scores 26.08 (far above #2 at 18.25) while empirically losing at 42.9% wr - likely the DoT
tick frequency registration inflates its ability score beyond what the champion's actual usage delivers.
Downweight or cap the Liandry's per-tick multiplier for Mordekaiser specifically, or audit the ability-scorer
DoT stacking coefficient.
