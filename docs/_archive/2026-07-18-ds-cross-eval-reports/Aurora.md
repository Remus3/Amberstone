# Aurora DS Scorer Cross-Eval

**Verdict: MINOR**
scorer=ability | archetype=mage/assassin | anchor=ARAM | evidence=outcome_self (n=17, wr=35.3)

---

## Axis 1 - archetype_ok: PASS

Aurora is a mage/assassin (AP kit, ability-damage primary). The "ability" scorer is the correct AP-axis scorer. No mismatch.

---

## Axis 2 - comp_ok: PASS

scorer=ability -> primary_axis=target_resist. This is correct behavior: ability scorer responds to tanky vs squishy targets, not to enemy damage type.

target_resist: max_positive_shift=5 (Bloodletter's Curse +5, Void Staff +2, Cryptbloom +2, Liandry's Torment +1 when AP target). Movement is present and directionally correct.

enemy_damage_type: comp_blind=true at the sub-block level (max_positive_shift=0, no risers/fallers). This is expected for the ability scorer - it does not consume enemy AD/AP share. Not a defect; the ability scorer is designed this way.

All 5 comp cells confirm: squishy tier cells (ad_squishy/bal_squishy/ap_squishy) are identical; tanky tier cells (ad_tanky/ap_tanky) are identical. No damage-type differentiation - consistent with scorer design.

---

## Axis 3 - outcome_ok: MINOR FLAG

Using outcome_self (n=17 >= 8). Baseline wr=35.3.

Items above baseline wr in empirical (outcome_self, ARAM):
- Sorcerer's Shoes: wr 50.0 (n=10) - shoes, not scored
- Liandry's Torment: wr 50.0 (n=10) - SCORER rank2 GOOD
- Malignance: wr 40.0 (n=10) - ABSENT from scorer top-8 GAP
- Luden's Echo: wr 42.9 (n=7) - ABSENT from scorer top-8 GAP
- Shadowflame: wr 37.5 (n=8) - SCORER rank5, marginally above baseline

Scorer top-8 (ad_squishy/bal_squishy):
rank1 Wooglet's Witchcap (score 34.78) - ZERO empirical appearances in self or all ARAM
rank2 Liandry's Torment (score 30.2) - empirically strong (wr 50.0) ALIGNED
rank3 Blackfire Torch (score 20.58) - zero appearances in self
rank4 Rabadon's Deathcap (score 13.06) - wr 42.9 in outcome_all but absent in self
rank5 Shadowflame (score 11.83) - wr 37.5 in self, marginal
rank6 Void Staff (score 11.77) - wr 26.7 in outcome_all, below baseline
rank7 Stormsurge (score 10.11) - not in ARAM empirical
rank8 Cryptbloom (score 8.82) - not in ARAM empirical

Issues:
1. Malignance (n=10, wr=40.0) and Luden's Echo (n=7, wr=42.9) are both above-baseline empirical staples entirely absent from scorer top-8.
2. Wooglet's Witchcap sits rank1 (score 34.78) with zero ARAM empirical presence - overvalued by scorer.
3. Void Staff is rank6 but has wr 26.7 in outcome_all (well below 44.9 all baseline) - empirically weak.

---

## Axis 4 - rune_ok: n/a

rune_relevant=false.

---

## Nominated Retune

Investigate why Malignance and Luden's Echo score below rank-8 threshold. Both are active-haste or cooldown-accelerating AP items with above-baseline empirical wr. Check ability-haste / CDR weighting in the ability scorer for these two items. Separately, audit Wooglet's Witchcap scoring at 34.78 vs 0 empirical appearances - likely an ARAM-item gold-value or passive-formula overcount.
