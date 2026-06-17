# DS Cross-Eval: Lillia

**Verdict: MINOR**

Scorer: ability | Archetype: mage/bruiser | Anchor: ARAM | Evidence: outcome_all (n=100, wr=41.0)

---

## Axis 1 - Archetype (OK)

Primary archetype=mage, scorer=ability. Ability scorer is the correct AP-axis scorer for a mage.
Kit is pure AP; empirical builds confirm AP items dominate (Liandry's 88 games, Blackfire Torch 55 games).
No axis mismatch.

---

## Axis 2 - Comp Responsiveness (OK)

Scorer=ability; primary_axis=target_resist. Correct: ability scorers respond to target MR/armor (tanky
comps push Bloodletter's +5 ranks, Void Staff +2, Cryptbloom +2).

enemy_damage_type.comp_blind=true (max_positive_shift=0, no risers). This is EXPECTED for an ability
scorer - enemy damage type drives EHP scorer adjustments, not DPS/ability scorers. No defect.

outer comp_blind=false because target_resist does move. Comp responsiveness is working as intended.

---

## Axis 3 - Outcome Alignment (MINOR FLAG)

Used outcome_all (n=100, baseline wr=41.0) per evidence_tier=outcome_all.

Scorer top-8 (ad_squishy/bal_squishy reference cell):
  rank 1 Liandry's Torment (27.1)
  rank 2 Wooglet's Witchcap (24.6)
  rank 3 Blackfire Torch (18.1)
  rank 4 Rabadon's Deathcap (9.3)
  rank 5 Shadowflame (8.2)
  rank 6 Void Staff (8.2)
  rank 7 Stormsurge (7.0)
  rank 8 Cryptbloom (6.1)

Empirical items above 41.0 baseline (completed items only, boots/components excluded):
  Liandry's Torment  n=88 wr=44.3  -> scorer rank 1. ALIGNED.
  Blackfire Torch    n=55 wr=41.8  -> scorer rank 3. ALIGNED (marginal above baseline).
  Cosmic Drive       n=34 wr=44.1  -> NOT in scorer top-8. POOL GAP.
  Riftmaker          n=35 wr=37.1  -> below baseline, scorer rank 11. Acceptable low priority.

Scorer overvalues:
  Rabadon's Deathcap  scorer rank 4 (score 9.3) but empirical wr=18.2 (n=11), well below 41.0 baseline.
  Wooglet's Witchcap  scorer rank 2 (score 24.6) but absent from empirical top-10 entirely.

FLAG: Rabadon's at scorer rank 4 is empirically lossy (18.2 vs 41.0 baseline, -22.8 wr delta).
FLAG: Cosmic Drive (wr=44.1, n=34, above baseline) missing from scorer pool entirely.
Wooglet's absence is noted but n may be too low in this dataset to judge conclusively.

---

## Axis 4 - Rune (N/A)

rune_relevant=false.

---

## Nominated Retune

Demote Rabadon's Deathcap priority in Lillia's ability-scorer pool (empirically lossy at -22.8 wr
below baseline with n=11). Add Cosmic Drive as a scored candidate (wr=44.1, n=34, above baseline,
currently absent from pool).
