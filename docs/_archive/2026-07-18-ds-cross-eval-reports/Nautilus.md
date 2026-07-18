# DS Cross-Eval: Nautilus

**Verdict: MINOR**

Scorer: ehp | Archetype: tank/enchanter | Anchor: ARAM | Evidence: outcome_all (n=151, wr=51.0)

---

## Axis 1 - Archetype OK: PASS

Tank primary -> ehp scorer is the correct neutral axis. Nautilus is a CC-hard initiator
with no meaningful damage scaling; ehp is the right optimization target. No mismatch.

---

## Axis 2 - Comp OK: PASS

EHP scorer, comp_blind=false. Enemy damage type moves rankings substantially:
- Randuin's Omen: rank 2 (ad_squishy) -> drops out of top-8 (ap_squishy). Shift -21.
- Kaenic Rookern: absent top-8 (ad_squishy) -> rank 2 (ap_squishy). Shift +22.
- Abyssal Mask: rank 9 (ad_squishy) -> rank 9 (ap_squishy) with max_positive_shift=24.
- Dead Man's Plate: rank 6 (ad_squishy) -> absent top-8 (ap_squishy). Shift -24.
- Force of Nature: rank 7 (bal_squishy) -> rank 3 (ap_squishy). Shift +22.

Comp responsiveness is functioning correctly. target_resist comp_blind=true is expected
for a tank scorer with no DPS component.

---

## Axis 3 - Outcome OK: MINOR FLAG

Using outcome_all (n=151, wr=51.0) per evidence_tier directive.

Above-baseline items (wr > 51.0):
- Fimbulwinter  n=76  wr=59.2  -> NOT in any comp_grid top-8
- Thornmail     n=45  wr=62.2  -> rank 9 ad_squishy (just outside top-8); not in ap cells
- Unending Despair n=57 wr=61.4 -> rank 5 ad_squishy, rank 8 bal_squishy (covered)
- Warmog's     n=32  wr=59.4  -> rank 3 ad_squishy, rank 2 bal_squishy (covered)
- Heartsteel   n=102 wr=52.9  -> rank 4 ad_squishy, rank 3 bal_squishy (covered)
- Plated Steelcaps n=41 wr=58.5 -> boots, not in comp_grid (expected exclusion)
- Mercury's Treads n=87 wr=52.9 -> boots, not in comp_grid (expected exclusion)

Key miss: Fimbulwinter (wr 59.2, n=76) does not appear in any cell's top-8.
Fimbulwinter's mana-to-HP passive benefits Nautilus significantly (high mana pool from
base stats and Tear rush). The scorer likely does not model this mana-HP conversion,
causing Fimbulwinter to rank outside the visible window.

Thornmail (wr 62.2 vs AD comps) landing at rank 9 ad_squishy is borderline - the pool
gap is real but not severe.

---

## Axis 4 - Rune OK: N/A

rune_relevant = false.

---

## Nominated Retune

Add Fimbulwinter mana-to-bonus-HP EHP contribution to the tank scorer for Nautilus
(and any other champion with Tear rush tendency). This is a stat-conversion passive
(each 250 mana = 150 bonus HP per Fimbulwinter passive) that flat EHP misses.
Secondary: verify Thornmail AD-facing EHP credit includes grievous wounds damage
reduction value to push it into top-8 vs AD squishies.
