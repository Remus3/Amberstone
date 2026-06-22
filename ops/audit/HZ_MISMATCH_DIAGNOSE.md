# HZ laning-combat mismatch diagnosis

generated-at: 2026-06-22T02:30:56Z
schema: hz_mismatch_diagnose/v1
current-engine: 1.149.0
total-records: 17409  genuine-mismatches: 945

WARNING: 6972 of 17409 records were logged under a NON-current engine version; their re-derived cell at the live engine may differ. The buckets below reflect the LOG-TIME precompute output, which is the correct denominator for 'was the precompute too cautious WHEN it spoke'.

## Bucket legend
- bucket 0: (-inf,-0.5]   deep-neg (model-error zone)
- bucket 1: (-0.5,-0.18]  firm back_off
- bucket 2: (-0.18,-0.05] hold zone (calibration zone)
- bucket 3: (-0.05,0]     even dead-zone (neg half)
- bucket 4: (0,+0.10)     even dead-zone (pos half)
- bucket 5: [+0.10,+inf)  favored trade

## Per-class net_swing distribution

| class (pre -> native) | count | median swing | buckets a|b|c|d|e|f | verdict |
|---|---|---|---|---|
| back_off -> hold | 351 | -0.24 | 0|337|14|0|0|0 | MIXED (no dominant bucket; inspect per-pair) |
| hold -> all_in | 151 | -0.02 | 0|0|4|146|1|0 | CALIBRATION (clustered near threshold; _BACK_OFF/_HOLD nudge defensible) |
| back_off -> trade | 138 | -0.30 | 0|101|37|0|0|0 | MODEL-ERROR (enemy-full-combo over-kill; Haiku likely right) |
| even -> trade | 126 | -0.06 | 0|0|105|18|3|0 | CALIBRATION (clustered near threshold; _BACK_OFF/_HOLD nudge defensible) |
| hold -> trade | 91 | +0.06 | 0|0|19|11|61|0 | CALIBRATION (clustered near threshold; _BACK_OFF/_HOLD nudge defensible) |
| even -> hold | 0 | +0.00 | 0|0|0|0|0|0 | no-data |

## Anti-circularity footer

This is a reading of the LOG-TIME net_swing distribution, NOT a flip and NOT a threshold tune. Tuning the precompute cutoffs to chase the agreement metric is circular - the metric is the thing under suspicion.

- CALIBRATION classes justify INVESTIGATING a _BACK_OFF / _HOLD_LOW / _TRADE nudge in core/precomputed_laning_coach.py:79-81 ONLY WITH ground-truth corroboration (rewind-db trade outcomes or a live side-by-side), never to chase this number.
- MODEL-ERROR classes point at the structural sequence_b=_FULL_COMBO assumption (core/laning_scenario_precompute.py:355): the precompute scores the enemy landing their FULL combo, so it over-states incoming damage. A threshold tune cannot fix a structural-input error - the enemy-sequence model itself is the lever.

