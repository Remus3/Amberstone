# Rell DS Cross-Eval Report

**Verdict: MINOR**

scorer=ehp | archetype=tank/enchanter | anchor=ARAM | evidence=outcome_all (n=53, baseline wr=39.6%)

---

## Axis 1 - archetype_ok: TRUE

Tank = neutral scorer axis. EHP is correct for Rell's frontline engage/peel kit (high base resists, no meaningful damage output). Archetype source=default is appropriate. No axis mismatch.

---

## Axis 2 - comp_ok: TRUE

primary_axis=enemy_damage_type, comp_blind=false, max_positive_shift=27.

EHP scorer responds correctly to enemy damage mix:
- When enemy=AP: Abyssal Mask +27, Spirit Visage +23, Force of Nature +23, Kaenic Rookern +21, Hollow Radiance +20 rise.
- When enemy=AD: Iceborn Gauntlet +27, Dead Man's Plate +26, Sunfire Aegis +24, Randuin's Omen +21 rise.

target_resist is comp_blind=true, shift=0 - expected for a tank EHP scorer; Rell does not deal enough damage for target-resist differentiation to matter. No defect.

---

## Axis 3 - outcome_ok: FALSE (MINOR pool gap)

Baseline wr = 39.6% (outcome_all, n=53). Items empirically above baseline:
- Heartsteel 51.9% (n=27) - scorer rank 6 (ad_squishy), rank 5 (bal_squishy). ALIGNED.
- Fimbulwinter 40.9% (n=22) - NOT in any scorer cell top-12. POOL GAP.
- Unending Despair 40.0% (n=20) - barely above; scorer rank 4 (ad_squishy). Marginal.

Scorer-top items empirically underperforming:
- Warmog's Armor: scorer r3 (ad_squishy), empirical wr 23.1% (n=13). Well below baseline.
- Jak'Sho, The Protean: scorer r7 (ad_squishy) / r3 (bal_squishy), empirical wr 21.4% (n=14). Well below baseline.
- Kaenic Rookern: scorer r4 (bal_squishy) / r2 (ap_squishy), empirical wr 25.0% (n=12). Below baseline.
- Randuin's Omen: scorer r2 (ad_squishy), empirical wr 35.3% (n=17). Below baseline.

Fimbulwinter (Rell staple, HP+mana+slow aura, n=22, wr 40.9%) is absent from all scorer cells. This is the primary pool gap. Several high-ranked scorer items also lose consistently in practice, suggesting the raw-stat EHP model over-rewards HP-stacking without accounting for Rell's reliance on ability-haste and mana (Fimbulwinter's actual value).

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Add Fimbulwinter (3121) to Rell's scorer item pool. Rell has a mana-gated kit (Ferromancy spells cost mana; Attract and Repel has a long CD). Fimbulwinter's mana-to-HP passive grants effective bulk that the raw-stat EHP model misses when the item is absent from the pool entirely. Consider a small ability-haste weight for Rell specifically given her CD-dependent engage loop, or at minimum ensure Fimbulwinter is eligible for scoring so comp shifts can surface it.
