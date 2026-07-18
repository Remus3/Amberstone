# Udyr - DS Scorer Cross-Eval Report

VERDICT: MISMATCH
scorer=hybrid | archetype=bruiser(tank) | anchor=ARAM outcome_all n=56 wr=42.9%

---

## Axis 1 - archetype_ok: PASS (marginal)

hybrid scorer is AD-leaning; bruiser/tank kit is AD-physical. Axis assignment
is correct for the kit. Minor concern: empirically winning builds skew toward
tank/MR items (Jak'Sho 60.0% n=10, Spirit Visage 62.5% n=8, Fimbulwinter
54.5% n=22) and AP enablers (Sorcerer's Shoes 57.1% n=7, Liandry's 48.6%
n=37) rather than AD-bruiser staples. Scorer top-8 surfaces Trinity Force
(rank 2), Dusk and Dawn (rank 4), Essence Reaver (rank 5) - AD offense items
with weak empirical signal. But bruiser scorer CAN surface these; axis label
is not wrong per rubric. Marked PASS, but pool gap noted under outcome_ok.

---

## Axis 2 - comp_ok: FAIL (MISMATCH)

scorer=hybrid, primary_axis=enemy_damage_type, comp_blind=TRUE.
Per rubric: EHP/hybrid scorer with comp_blind=True = DEFECT candidate.

max_positive_shift=2 (Hollow Radiance +2 rank). Near-zero responsiveness.
The 5 squishy comp cells (ad_squishy / bal_squishy / ap_squishy) show
virtually identical top-8 orderings across AD vs AP enemy compositions:
- ad_squishy rank 1-8: Void Immolation, Trinity Force, Heartsteel, Dusk+Dawn,
  Essence Reaver, Iceborn Gauntlet, Liandry's, Lich Bane (scores identical)
- ap_squishy rank 1-8: same items, same scores
The hybrid scorer is not routing enemy damage type into EHP weighting for
Udyr. A real AP-heavy enemy comp should surface MR items (Spirit Visage,
Jak'Sho, Fimbulwinter) but these do not appear in the top-8 for any comp cell.
This is a confirmed comp-blind EHP defect.

---

## Axis 3 - outcome_ok: FAIL (MISMATCH)

Using outcome_all (ARAM n=56 >= 8). Baseline wr=42.9%.
Above-baseline empirical items (wr > 42.9%):
  Spirit Visage      wr=62.5% n=8  -> absent from scorer top-8 in any cell
  Jak'Sho            wr=60.0% n=10 -> absent from scorer top-8 in any cell
  Sorcerer's Shoes   wr=57.1% n=7  -> absent (boots excluded from scorer)
  Plated Steelcaps   wr=57.1% n=7  -> absent (boots excluded from scorer)
  Fimbulwinter       wr=54.5% n=22 -> absent from scorer top-8 in any cell
  Liandry's Torment  wr=48.6% n=37 -> rank 7 in squishy cells, rank 2 tanky;
                                       present but underweighted vs real usage

Empirically LOSING item in scorer top-8:
  Heartsteel wr=14.3% n=7 -> scorer rank 3 across all squishy cells (score
  2.093). This is a hard empirical loser being surfaced as the third-best
  recommendation. n=7 is below the n>=8 self-threshold but the signal is
  clear: 14.3% wr on n=7 is a strong negative.

Missing high-wr tank staples Fimbulwinter, Jak'Sho, Spirit Visage from scorer
top-8 while Heartsteel (14.3% wr) sits rank 3 = clear outcome misalignment.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false. Non-burst archetype; self-keystone wiring does not apply.

---

## Nominated Retune

1. Investigate why Fimbulwinter (id 3121), Jak'Sho (id 6665), Spirit Visage
   (id 3065) score below rank 8 for Udyr in the hybrid scorer. These are the
   highest-wr ARAM items and carry substantial tank/MR stats fitting bruiser
   secondary=tank profile.
2. Comp-blind root cause: enemy damage type is not feeding into EHP weight
   split for hybrid scorer on Udyr. Verify enemy_ad_share / enemy_ap_share
   is propagating into the hybrid scorer dispatch for this champion.
3. Heartsteel rank-3 overweight: d_ehp contribution (1580 ad_squishy) is
   large but real-world synergy (HP stacking, passive proc rate) not matching.
   Consider a bruiser-specific Heartsteel calibration weight reduction.
