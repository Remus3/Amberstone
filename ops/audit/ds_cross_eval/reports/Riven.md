# Riven - DS scorer cross-eval report
verdict: MISMATCH

scorer: hybrid | anchor: ARAM outcome_self (n=19, baseline wr=42.1%)

---

## 1. archetype_ok: TRUE

primary=bruiser, secondary=assassin. Hybrid scorer is the correct axis for a
melee AD fighter with both sustained damage and survivability demand. Empirical
above-baseline ARAM-self items (wr>42.1): Eclipse 66.7% (n=9), Sundered Sky
50.0% (n=10), Mercury's Treads 50.0% (n=8) - all AD-aligned. No AP-axis items
in winning pool. Archetype call is correct.

---

## 2. comp_ok: FALSE (MISMATCH)

Riven is flagged in the pre-seeded COMP-BLIND EHP/hybrid cohort. Confirmed:
- responsiveness.primary_axis = "enemy_damage_type"
- responsiveness.enemy_damage_type.comp_blind = TRUE
- max_positive_shift = 1 (trivial; top risers when AP all shift by only 1 rank)

The hybrid scorer EHP sub-component should move meaningfully when enemy damage
type flips AD->AP (physical-resist vs magic-resist weighting). Shift of 1 rank
across 40-deep pool is effectively zero responsiveness. Dead Man's Plate falls
10 when AP (correct direction) but the NET effect on the top-8 recommendation
is comp_blind=True. An EHP/hybrid scorer that cannot distinguish AD-heavy vs
AP-heavy enemy comps is a real defect for a champion whose MR vs armor itemization
matters in team-fights.

---

## 3. outcome_ok: FALSE (MISMATCH)

Scorer top-8 (bal_squishy, representative): Void Immolation (#1, score 1.64),
BotRK (#2, 1.58), Trinity Force (#3, 1.18), Essence Reaver (#4, 1.11),
Runaan's Hurricane (#5, 1.02), Heartsteel (#6, 0.97), Stormrazor (#7, 0.94),
Kraken Slayer (#8, 0.92).

Cross-check vs ARAM-self empirical (n=19, outcome_self tier):
- Eclipse (wr 66.7%, n=9) -> scorer rank 10 in squishy cells (score 0.824).
  Highest empirical win-correlated item is buried below rank 8. FAIL.
- Sundered Sky (wr 50.0%, n=10) -> NOT present in any comp_grid top-12.
  A Riven staple with above-baseline wr is completely absent from the
  scored pool. FAIL.
- Mercury's Treads (wr 50.0%, n=8) -> boots; not an item slot scored by DS.
  Expected absence; not a flag.
- Death's Dance (wr 42.9%, n=7) -> below baseline 42.1% marginally, n<8; skip.

Runaan's Hurricane at rank 5 (score 1.02) is a ranged-AA item; it has no
meaningful on-Riven application. Its scorer rank reflects a pure stat/gold
efficiency calculation that ignores champion-specific item eligibility.

Top-2 scorer items (Void Immolation, BotRK) have zero empirical presence in
the ARAM-self sample. The scorer pool is not aligned with what wins on Riven.

---

## 4. rune_ok: N/A

rune_relevant = false. Riven is not in the burst/assassin rune cohort.

---

## Nominated retune

1. Elevate Eclipse in hybrid scorer weight: it is the highest-wr Riven item
   (66.7%) but ranks 10th. Likely underweighted on the EHP sub-component
   (Eclipse's shield proc gives real EHP but may not be registered in the
   hybrid EHP term).
2. Add Sundered Sky to the scored item pool: wr 50.0% above-baseline staple
   absent from top-12. If missing from item registry entirely, that is a
   coverage gap.
3. Fix comp_blind EHP sub-component responsiveness: max_positive_shift=1 is
   negligible. The hybrid scorer must shift armor-stacking items vs MR-stacking
   items by enemy damage type. This is a systemic bruiser-cohort issue (10
   champs flagged comp-blind per PROGRAM.md).
4. Demote or eligibility-gate Runaan's Hurricane: rank 5 on a melee champion
   with no multi-target AA mechanic is a scorer artifact, not a real recommendation.
