# DS Cross-Eval: Zac

**Verdict: MINOR**
Scorer (ehp/tank/neutral) is well-aligned. One below-baseline empirical item (Sunfire Aegis) sits in
the scorer top-8; no axis mismatch. Comp responsiveness is healthy.

---

## Axis 1 - archetype_ok: TRUE

Zac is primary=tank, secondary=bruiser. Tank maps to neutral axis; ehp scorer is correct.
Empirical above-baseline items (ARAM all, baseline 44.9%, n=78) are all tank/HP items:
- Unending Despair 60.0% wr (n=30) - scorer rank 4 ad_squishy / rank 4 ad_tanky
- Warmog's Armor 55.0% wr (n=20) - scorer rank 3 ad_squishy / rank 2 bal_squishy
- Mercury's Treads 47.5% wr (n=40) - boots, not in item grid; no scorer penalty
- Heartsteel 46.9% wr (n=49) - scorer rank 6 ad_squishy / rank 5 bal_squishy

No AD carry or AP carry items appear empirically. Axis = correct.

---

## Axis 2 - comp_ok: TRUE

ehp scorer must respond to enemy_damage_type. comp_blind=false; max_positive_shift=+29 ranks.
Top risers vs AP enemy:
- Abyssal Mask +29 ranks (ad_squishy rank 13 -> ap_squishy rank 7 equivalent)
- Spirit Visage +23, Force of Nature +23, Kaenic Rookern +21, Hollow Radiance +20

Top fallers vs AP enemy:
- Iceborn Gauntlet -28, Dead Man's Plate -26, Sunfire Aegis -24, Randuin's Omen -22

Armor-heavy items fall and MR items rise as expected. Responsiveness is correct and meaningful.

target_resist is comp_blind=true (shift=0) which is expected for an ehp tank scorer - Zac
does not scale off enemy resistances for survival.

---

## Axis 3 - outcome_ok: MINOR FLAG

Using ARAM outcome_all (n=78, baseline 44.9%). Scorer top-8 overlap vs ad_squishy + bal_squishy:

Above-baseline empirical items that ARE in scorer top-8:
- Unending Despair 60.0% -> scorer rank 4 ad_squishy. OK.
- Warmog's Armor 55.0% -> scorer rank 3 ad_squishy / rank 2 bal_squishy. OK.
- Heartsteel 46.9% -> scorer rank 6 ad_squishy / rank 5 bal_squishy. OK.

MINOR FLAG: Sunfire Aegis
- Empirical ARAM wr: 38.5% (n=26), well below 44.9% baseline
- Scorer rank: 8 ad_squishy (score 1632.8), rank 12 bal_squishy (score 1198.2)
- Sunfire in the ad_squishy top-8 despite being one of the worst-performing items empirically
- Likely caused by raw armor+HP EHP contribution; the passive AoE dmg/engage utility is not
  captured, but the negative wr signal suggests it underperforms vs its stat bulk in practice

No above-baseline empirical staple is missing from the scorer pool.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Reduce Sunfire Aegis weight for Zac specifically, or add a small empirical-penalty modifier
for items with wr significantly below champion baseline when n >= 20. This would push Sunfire
out of top-8 in favor of stronger-performing tank items.

Alternatively, no code change needed if Sunfire is expected to drop naturally once the
comp_grid reflects balanced enemy compositions in real games (it already falls to rank 12
in bal_squishy). Flag as calibration note only; no hard retune required.

Nominated retune: "Apply empirical-underperform penalty to Sunfire Aegis for Zac
(38.5% wr vs 44.9% baseline, n=26) to push it below scorer top-8 in ad_squishy cell."
