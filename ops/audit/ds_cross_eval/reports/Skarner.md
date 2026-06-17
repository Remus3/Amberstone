# DS Cross-Eval: Skarner

**Verdict: MINOR**

archetype=tank/bruiser, scorer=ehp, anchor_mode=ARAM, evidence_tier_aram=outcome_all (n=54, baseline wr=42.6%)

---

## Axis 1: archetype_ok = true

tank primary, secondary bruiser. ehp scorer is the correct neutral-axis scorer for a tank (armor+mr survivability, no AD/AP damage bias). Kit is a CC-and-suppress engage tank - pure durability optimization is appropriate. Empirical top items (Heartsteel, Warmog's, Unending Despair) are all tank survivability staples, consistent with the scorer axis.

## Axis 2: comp_ok = true

ehp scorer with enemy_damage_type as primary_axis. comp_blind=false, max_positive_shift=27 ranks. The scorer correctly differentiates:
- vs AD-heavy comp: Randuin's Omen rises to rank 2 (ad_squishy), Dead Man's Plate rank 5, Frozen Heart rank 12
- vs AP-heavy comp: Kaenic Rookern rises to rank 2 (ap_squishy/ap_tanky), Force of Nature rank 3, Spirit Visage rank 4, Abyssal Mask rises 27 ranks

target_resist.comp_blind=true is expected - Skarner does not build DPS items so target resistance is irrelevant for the ehp scorer.

Note: all d_ehp and d_dps fields are 0.0 across all cells. This is a data-population concern (delta values not written to the grid output) but does not affect rank ordering or comp responsiveness, which is confirmed functional via the responsiveness block.

## Axis 3: outcome_ok = false (MINOR pool gap)

Using outcome_all (self n=0). Baseline wr = 42.6%.

Above-baseline empirical items (wr > 42.6%):
- Heartsteel 48.6% (n=35) -> scorer rank 6 ad_squishy, rank 5 bal_squishy - present in top-8, OK
- Warmog's Armor 50.0% (n=12) -> scorer rank 3 ad_squishy, rank 2 bal_squishy - present, OK
- Unending Despair 45.0% (n=20) -> scorer rank 4 ad_squishy - present, rank 9 bal_squishy (marginal miss)
- Thornmail 46.2% (n=13) -> scorer rank 9 ad_squishy, rank not in bal_squishy top-8 - misses top-8 cutoff despite above-baseline wr
- Spirit Visage 42.9% (n=14) -> barely above baseline; scorer rank 8 bal_squishy, rank 4 ap_squishy - present in AP scenario

Below-baseline items (Mercury's Treads 35.5%, Fimbulwinter 36.7%, Guardian's Horn 30.8%) are correctly absent from scorer top-8.

Negatron Cloak (55.6% wr, n=9) and Plated Steelcaps (50.0%, n=12) are components/boots - expected to be absent from full-item scorer pool.

Fimbulwinter (id 3121, 36.7% wr) is not in scorer top-8, which is correct given it underperforms.

Gap: Thornmail (46.2%, rank 9 ad_squishy) just outside top-8 cutoff. Minor pool depth issue - not a structural mismatch.

## Axis 4: rune_ok = n/a

rune_relevant=false.

---

## Nominated Retune

none

---

## Summary

Skarner's ehp scorer is correctly aligned to the tank archetype and responds well to enemy damage type (27-rank swings on armor vs MR items). Empirical wins match scorer recommendations for primary staples (Heartsteel, Warmog's, Unending Despair). Only gap is Thornmail (46.2% wr, above baseline) landing at rank 9 in ad_squishy, one position outside the top-8 window. The d_ehp/d_dps=0.0 grid issue should be investigated separately as a data-export concern, not a scorer logic defect.
