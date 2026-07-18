# DS Cross-Eval: DrMundo

**Verdict: MINOR**
Scorer: ehp | Archetype: tank/bruiser | Evidence tier (ARAM): outcome_self (n=8, wr=50.0)

---

## Axis 1 - archetype_ok: PASS

Tank archetype -> ehp scorer is neutral (correct axis; tank is neither AD nor AP). Empirical ARAM self (n=8, baseline 50.0): Heartsteel wr=57.1 above baseline. Empirical all (n=103, baseline 46.6): Unending Despair wr=56.8, Thornmail wr=51.5 above baseline - both are tank staples. No axis mismatch.

## Axis 2 - comp_ok: PASS

Scorer is ehp/tank -> enemy_damage_type must move. responsiveness.enemy_damage_type.comp_blind=false, max_positive_shift=27 ranks. AD-heavy comp: Randuin's Omen rank 2, Iceborn Gauntlet rank 10, Dead Man's Plate rank 5. AP-heavy comp: Kaenic Rookern rank 2 (up 22), Force of Nature rank 3 (up 22), Abyssal Mask rank 9 (up 27), Spirit Visage rank 5 (up 21), with Iceborn Gauntlet falling 28 ranks and Dead Man's Plate falling 26. Comp responsiveness is healthy. NOTE: all d_ehp fields are 0.0 across every comp cell - the delta display is not populated for this champion; this is a calibration/display gap but does not affect scorer responsiveness.

## Axis 3 - outcome_ok: MINOR FLAG

Using outcome_self (n=8 >= threshold). Baseline wr=50.0. Above-baseline empirical items: Heartsteel wr=57.1. In scorer top-8 (ad_squishy/bal_squishy):

- Void Immolation rank 1 score 4113 vs rank 2 Randuin's 1867 - 2.2x gap, no empirical presence at all.
- Heartsteel rank 6 (ad_squishy) / rank 5 (bal_squishy) - present and above baseline, good.
- Warmog's Armor rank 3 - present in empirical all wr=46.6 (at all-baseline, not above self-baseline).
- Unending Despair rank 4 (ad_squishy) - empirical all wr=56.8 (well above all-baseline), good.
- Thornmail empirical all wr=51.5 (above all-baseline 46.6) but scorer rank 9 in ad_squishy, rank 12 not present in bal_squishy top-8 - under-ranked vs empirical signal.
- Randuin's Omen scorer rank 2 (ad_squishy) / rank 6 (bal_squishy) - not in empirical top items despite high score.

Void Immolation dominance (rank 1, 2.2x next item) with zero empirical presence is the primary flag. Thornmail's above-baseline wr vs its scorer rank 9 placement is a secondary miss.

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated retune

Void Immolation score deflation: the 4113 rank-1 score (vs 1867 rank-2) with no empirical presence suggests the item's EHP contribution is being over-weighted relative to gold cost or that its unique mechanic scores outside what real builds capture. Recommend capping Void Immolation's effective EHP multiplier or adding a gold-efficiency normalisation pass. Additionally, review Thornmail's armor contribution to the EHP scorer - it ranks 9 in ad_squishy despite above-baseline empirical wr=51.5 and Grievous Wounds value vs AD comps.
