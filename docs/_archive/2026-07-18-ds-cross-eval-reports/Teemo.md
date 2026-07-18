# DS Cross-Eval: Teemo

**Verdict: MINOR**

Scorer: ability | Archetype: mage/carry | Anchor: ARAM | Evidence: outcome_self (ARAM n=11)

---

## Axis 1 - archetype_ok: PASS

Scorer=ability maps to AP axis. Teemo kit is fully AP-scaling (poison mushrooms, Q blind, E poison on-hit all scale AP). Empirical ARAM outcome_self baseline wr=27.3%. Above-baseline empirical items: Liandry's Torment (30.0%), Malignance (33.3%), Sorcerer's Shoes (28.6%). All AP items. Scorer axis is correct.

## Axis 2 - comp_ok: PASS

enemy_damage_type responsiveness: comp_blind=true, max_positive_shift=0. For an ability/mage scorer that measures AP-DPS output (not incoming EHP), invariance to enemy AD/AP mix is expected behavior - not a defect.

target_resist responsiveness: comp_blind=false, max_positive_shift=3. Cryptbloom and Bloodletter's Curse each rise +3 ranks vs tanky targets. Void Staff holds rank 4 across all cells. Ability scorer is correctly differentiating AP-pen value against resist-stacking enemies.

## Axis 3 - outcome_ok: FAIL (MINOR - missing staple)

Scorer top-8 (ad_squishy cell, representative): rank1 Liandry's Torment, rank2 Blackfire Torch, rank3 Wooglet's Witchcap, rank4 Void Staff, rank5 Shadowflame, rank6 Rabadon's Deathcap, rank7 Stormsurge, rank8 Cryptbloom.

Empirical outcome_self (n=11, wr baseline 27.3%) above-baseline items: Liandry's Torment wr=30.0% (rank1 in scorer - OK), Malignance wr=33.3% (ABSENT from scorer pool entirely), Sorcerer's Shoes wr=28.6% (boots, out of scope for item scorer).

Malignance (id 3118) is the highest-wr item in outcome_self (33.3% vs 27.3% baseline) and confirms in outcome_all (wr=44.5% vs 43.0% baseline, n=146). It does not appear in any comp grid cell. This is a scorer pool gap: a confirmed winning staple is invisible to the recommender.

Blackfire Torch (rank2 scorer): wr=40.3% in outcome_all, below the 43.0% baseline. Weak empirical validation for rank2 placement.

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Add Malignance (id 3118) to ability scorer item pool for Teemo. It is the top-performing empirical item (wr 33.3% self / 44.5% all) and is fully absent from the scorer. Investigate why Blackfire Torch scores rank2 but underperforms baseline (wr 40.3% vs 43.0%) - may warrant a pool weight review for low-sample champions.
