# MonkeyKing - DS Scorer Cross-Eval Report
# Verdict: MISMATCH
# Date: 2026-06-16

scorer=hybrid  anchor=ARAM  evidence_tier=outcome_all (n=99, baseline_wr=42.4%)

---

## Axis 1 - archetype_ok: TRUE

Wukong is bruiser/tank, scorer=hybrid (AD axis). Kit is melee AD fighter.
Empirical above-baseline items (ARAM, wr>42.4%): Death's Dance 50.0%, Black Cleaver 48.6%,
Plated Steelcaps 48.1%, Eclipse 47.1%, Caulfield's Warhammer 47.1% - all AD/physical.
AD axis matches kit and what wins. No axis mismatch.

---

## Axis 2 - comp_ok: FALSE (DEFECT)

scorer=hybrid with primary_axis=enemy_damage_type but comp_blind=TRUE.
max_positive_shift=1 when enemy is AP. Hybrid is an EHP scorer and must differentiate
by enemy damage type, but the rank-40 sweep shows near-zero movement.

Comparison ad_squishy vs ap_squishy top-8 (virtually identical):
  #1 Void Immolation  1.6265 vs 1.6171  (shift 0)
  #2 BotRK            1.2722 vs 1.2722  (shift 0)
  #3 Trinity Force    1.0913 vs 1.0913  (shift 0)
  #4 Essence Reaver   0.9727 vs 0.9727  (shift 0)
  #5 Heartsteel       0.9146 vs 0.9146  (shift 0)
  #6 Runaan's         0.8819 vs 0.8819  (shift 0)
  #7 Stormrazor       0.7864 vs 0.7864  (shift 0)
  #8 Dusk and Dawn    0.7472 vs 0.7472  (shift 0)

Top risers when AP have shift=1 only (Yun Tal Wildarrows, Voltaic Cyclosword, etc.).
Iceborn Gauntlet falls -5 rank when AP (expected, armor item), which is the only
meaningful movement, but that is a faller not a meaningful riser.
This is a comp-blind hybrid scorer: does not route MR vs armor recommendations
based on enemy damage type. DEFECT per program rubric.

---

## Axis 3 - outcome_ok: FALSE (pool gap)

Scorer top-8 (bal_squishy cell, the representative squishy baseline):
  #1 Void Immolation  (empirical: ABSENT from top-10)
  #2 BotRK            (empirical: ABSENT from top-10)
  #3 Trinity Force    wr=38.2%  BELOW baseline 42.4%
  #4 Essence Reaver   (empirical: ABSENT)
  #5 Heartsteel       (empirical: ABSENT)
  #6 Runaan's Hurricane (empirical: ABSENT)
  #7 Stormrazor       (empirical: ABSENT)
  #8 Dusk and Dawn    (empirical: ABSENT)

Above-baseline empirical items MISSING from scorer top-8:
  Death's Dance  wr=50.0%  n=42  -> not in scorer top-8
  Black Cleaver  wr=48.6%  n=37  -> not in scorer top-8
  Eclipse        wr=47.1%  n=17  -> appears in tanky cells only (#6 ad_tanky/ap_tanky)

Void Immolation is a 6000g mythic anomaly at rank #1 across all 5 cells; empirically
absent. Trinity Force (empirical wr=38.2%, below baseline) is scorer #3.
Scorer pool does not reflect what wins on Wukong.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false. Not a burst/assassin scorer. Skipped per program contract.

---

## Nominated Retune

1. comp_blind fix (Tier-2): investigate why enemy_damage_type max_shift=1 on hybrid.
   Wukong needs MR items to score higher vs AP comps (e.g. Maw of Malmortius, Mercury's
   Treads) and armor items to score higher vs AD comps. The current EHP calc is not
   differentiating sufficiently.

2. Pool calibration: Death's Dance (50.0% wr) and Black Cleaver (48.6% wr) are the
   strongest above-baseline items and do not appear in scorer top-8. Reduce Void
   Immolation bias (6000g mythic at #1 across all comp cells, empirically absent).
   Eclipse should surface in squishy cells (currently only tanky, shift=7 vs tanky resist).

3. Trinity Force at scorer #3 empirically underperforms (wr=38.2%, below 42.4% baseline);
   consider downweighting vs Death's Dance / Black Cleaver.
