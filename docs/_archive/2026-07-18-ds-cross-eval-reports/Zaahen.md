# DS Cross-Eval: Zaahen

**Verdict: MINOR**

Scorer: hybrid | Archetype: bruiser/assassin | Evidence: ARAM=synthetic, SR=synthetic

---

## Axis 1 - Archetype

OK. Hybrid scorer is the bruiser scorer, an AD-weighted axis. Bruiser+assassin is an AD melee
kit. Scorer axis is correct.

---

## Axis 2 - Comp Responsiveness

OK. Scorer=hybrid (EHP+DPS blend). comp_blind=false on both enemy_damage_type and target_resist.

Enemy damage type: max_positive_shift=13. Wit's End rises +13 when enemy is AP. Dead Man's Plate
falls -12. EHP-weighted items swap as expected when armor is less relevant.

Target resist: max_positive_shift=15. Liandry's Torment rises +15 vs tanky, Lord Dominik's
Regards +11. The anti-tank penetration layer activates correctly.

Grid confirms: BotRK score vs ad_squishy=1.8474, vs ad_tanky=3.1936 (large d_dps uplift because
%hp damage is better vs tanky). Heartsteel d_ehp: ad_squishy=1643, ap_squishy=1398 (armor value
reduced vs AP comp). Shifts are present and meaningful.

---

## Axis 3 - Outcome

MINOR FLAG. Evidence is extremely thin.

Baseline for outcome check: outcome_self n=0 (unusable), outcome_all SR n=6 wr=50.0.
Using outcome_all (n=6 < 8 threshold).

Only empirical item: Trinity Force n=5, wr=40.0 (10 points BELOW baseline 50.0).
Scorer places Trinity Force rank 4 in all squishy comps (score=1.1259) and rank 6 vs tanky.
This is a top-8 scorer recommendation that underperforms in the only empirical data available.

Caveat: n=5 is extremely thin on synthetic evidence. The signal is unreliable but directionally
worth noting. No other above-baseline-wr empirical items exist to cross-check the rest of the
pool.

---

## Axis 4 - Rune

n/a (rune_relevant=false)

---

## Nominated Retune

Monitor Trinity Force rank. Scorer places it rank 4 (score=1.1259, d_dps=41.9 vs squishy),
but the only 5 empirical games show 40% wr vs 50.0 baseline. Sample is too thin for a hard
retune; flag for re-evaluation when n>=20.

---

## Summary

Archetype and scorer axis are correct. Comp responsiveness is working (not comp-blind, shifts
present). The one-item empirical sample has Trinity Force losing at 40% wr vs 50% baseline, but
n=5 on a synthetic evidence champion is insufficient to classify as MISMATCH. No structural
scorer defect identified.
