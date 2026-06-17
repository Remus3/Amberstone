# DS Cross-Eval: Renata

**Verdict: MINOR**
Scorer=hps, archetype=enchanter/mage. Axis and comp invariance are correct.
Two above-baseline empirical items (Seraph's Embrace, Fimbulwinter) missing from scorer pool.
Echoes of Helia is scorer rank 1 but has zero empirical entries in outcome_all.

---

## Axis 1 - archetype_ok: TRUE

- primary=enchanter, secondary=mage, scorer=hps.
- HPS axis is the correct scorer for enchanter: heal/shield utility, AP-neutral.
- Kit match: Renata W is a revive/shield, E is a slow+shield, passive stacks heals on allies.
- No axis mismatch.

## Axis 2 - comp_ok: TRUE (invariance expected)

- HPS scorer for enchanter -> comp invariance is EXPECTED behavior, not a defect.
- Confirmed: all 5 comp cells (ad_squishy/bal_squishy/ap_squishy/ad_tanky/ap_tanky) show
  identical scores. Echoes of Helia=27.1676, Ardent Censer=15.7967, Staff of Flowing Water=12.6196
  across every cell. d_ehp=0 and d_dps=0 everywhere.
- responsiveness.comp_blind=true for both enemy_damage_type and target_resist axes,
  max_positive_shift=0 for both.
- This is correct. An enchanter HPS scorer should not shift on enemy damage type or target resist.
- comp_ok=true.

## Axis 3 - outcome_ok: FALSE (pool gap, MINOR)

Evidence: outcome_all (n=109, baseline wr=53.2).

Above-baseline empirical items (wr > 53.2):
- Imperial Mandate 4005: wr 57.7 -> scorer rank 7, PRESENT
- Redemption 3107: wr 55.9 -> scorer rank 6, PRESENT
- Seraph's Embrace 3040: wr 61.3 -> NOT in scorer pool (absent entirely)
- Locket of the Iron Solari 3190: wr 65.2 -> scorer rank 4, PRESENT
- Ardent Censer 3504: wr 64.7 -> scorer rank 2, PRESENT
- Fimbulwinter 3121: wr 55.0 -> NOT in scorer pool (absent entirely)

Missing items:
- Seraph's Embrace (3040): 61.3% wr, n=31 - mana-scaling AP item; fits Renata secondary mage.
  Not in HPS pool at all.
- Fimbulwinter (3121): 55.0% wr, n=20 - mana/shield item; synergizes with enchanter shielding.
  Not in HPS pool at all.

Scorer rank 1 concern:
- Echoes of Helia (6620): scorer rank 1 (score 27.1676) but zero empirical entries in outcome_all
  top-10. This may reflect a sample gap or patch rotation, but the absence is notable.

Scorer items that ARE winning empirically: Ardent Censer (64.7%), Locket (65.2%), Redemption (55.9%),
Imperial Mandate (57.7%). Core enchanter pool is validated.

Gap is pool-coverage only (2 missing above-baseline items), not a wrong-direction recommendation.
Severity stays MINOR.

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Add Seraph's Embrace (3040) and Fimbulwinter (3121) to the Renata HPS item pool.
Both are empirically above baseline in ARAM (61.3% / 55.0% wr) and fit Renata's mana-scaling
secondary mage archetype. Investigate Echoes of Helia empirical absence vs its rank-1 scorer
position - may be a sample gap that resolves with more data, or a scoring overweight to re-check.
