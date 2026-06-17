# DS Cross-Eval: KSante

**Verdict: MINOR**

Scorer: ehp | Archetype: tank/bruiser | Anchor: ARAM | Evidence: outcome_all (n=57, wr=45.6)

---

## Axis 1 - archetype_ok: PASS

Tank primary, bruiser secondary. EHP scorer = neutral axis (correct for a frontline tank that
scales into both armor and MR). No off-axis (AD crit / AP damage) items win empirically. Kit
confirmed: K'Sante is a pure-durability frontliner - ehp is the right lens.

---

## Axis 2 - comp_ok: PASS

Scorer = ehp. EHP must respond to enemy damage type. comp_blind = false.
max_positive_shift = 29 ranks when enemy comp shifts AD -> AP.

Top risers when AP: Abyssal Mask +29, Spirit Visage +23, Force of Nature +23, Kaenic Rookern +21,
Hollow Radiance +20. Top fallers: Iceborn Gauntlet -28, Dead Man's Plate -26, Sunfire Aegis -25,
Randuin's Omen -24.

Shift is large and directionally correct (MR items rise, armor items fall). No comp-blind defect.

Note: target_resist axis is comp_blind with shift=0, but that is expected - ehp scorer primary axis
is enemy damage type, not target resist. Not a defect.

---

## Axis 3 - outcome_ok: MINOR FLAG

Using outcome_all (self n=3, too small). ARAM baseline wr = 45.6.

Above-baseline empirical items (wr > 45.6):
- Unending Despair: wr 57.9, n=19 -> scorer rank ad_squishy #4. ALIGNED.
- Thornmail: wr 57.1, n=14 -> scorer rank ad_squishy #9. Just outside top-8.
- Jak'Sho: wr 56.5, n=23 -> scorer rank ad_squishy #7. ALIGNED.
- Negatron Cloak: wr 54.5, n=11 -> not in top-12 scorer pool at all. Missing staple.
- Plated Steelcaps: wr 50.0, n=12 -> not in scorer top-12 (boots slot, tolerable).
- Iceborn Gauntlet: wr 47.5, n=40 (most-purchased) -> scorer rank ad_squishy #10. Marginally above
  baseline, pool placement at #10 is acceptable.

FLAG: Heartsteel sits at scorer rank #6 (ad_squishy score 1658, bal_squishy rank #5) but its
empirical wr is 31.2 (n=16) - 14 points below baseline. A top-6 scorer recommendation that loses
empirically this badly is a pool quality issue.

FLAG: Negatron Cloak (wr 54.5, n=11) absent from scorer top-12 in any cell. As an above-baseline
winning component it warrants inspection.

Thornmail at scorer #9 (just outside top-8) but wr 57.1 is a minor miss, not a hard defect.

---

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

Investigate Heartsteel EHP contribution vs actual game impact for K'Sante specifically. The item
inflates raw EHP (large HP stacks) but K'Sante's form-swap mechanics may make raw HP less efficient
in practice than the scorer weights. Consider a K'Sante-specific Heartsteel penalty or capping its
score weight. Also verify Negatron Cloak inclusion logic - it outperforms most top-12 items
empirically but is absent from scorer pools.
