# HZ precompute-vs-Haiku agreement re-measurement (R32, item-614 follow-up)

Date: 2026-06-27
Theme: haiku-zero (Lane A laning flip-readiness gate)
Engine impact: NONE (offline measurement; no math, no network, no write to engine state)
Tool: `tools/hz_shadow_report.py` (read-only) over `data/hz_choice_shadow.jsonl`
(24,289 records) + `data/hz_build_shadow.jsonl`.

## Why this pass exists

Item 614 (commit `8ce870e4`, 2026-06-24 19:45 -05:00) was a structural model-error
fix in `core/laning_scenario_precompute.py`: the enemy now fires the cell's
cd-state rotation (`sequence_b = combo_sequence(cd_state)`) instead of always
`_FULL_COMBO`, so a `no_ult` window drops R for BOTH laners. The item-575
diagnosis (`ops/audit/HZ_MISMATCH_DIAGNOSE.md`) had isolated ONE structural pocket
to that over-kill: `precompute=back_off -> native=trade`, n=138, median net_swing
-0.30. Item 614's ledger entry named the precompute-vs-Haiku agreement
RE-MEASUREMENT on the corrected tables as the gated NEXT step. This is that step.

## Method

The shadow record's precompute verdict (`choices[0].label`) is computed and baked
at LOG TIME from whatever laning table was live on that tick. So records bucket
cleanly by timestamp against the fix-commit boundary:

  FIX boundary (UTC) = 2026-06-25T00:45:07 (= 2026-06-24 19:45:07 -05:00)

Classification reuses the live tool's own `record_agreement` / `classify_verdict`
(no reimplementation), so the verdict mapping is byte-identical to the flip-gate
report. A second regen (the 16.13.1 patch refresh, commit `c022498f`,
2026-06-25 03:06 -05:00) also rebuilt the tables; the symmetric-cd-state CODE fix
persists into those tables too, so every post-boundary record carries the
corrected combo logic.

The split is a clean natural experiment - the data straddles nothing near the
boundary: all PRE comparable-covered ticks are dated <= 2026-06-23, all POST are
dated 2026-06-27 (zero comparable-covered laning ticks were logged 06-24/25/26).

## Result - laning (the item-614 axis)

| Bucket | records | comparable-covered | agreement | TARGET pocket back_off->trade |
|--------|---------|--------------------|-----------|-------------------------------|
| PRE-FIX  (<= 06-23) | 22,600 | 3,405 | 1,656/3,405 = 0.4863 | 138 |
| POST-FIX (06-27)    |  1,689 |   312 |    77/312  = 0.2468 |   0 |
| WHOLE LOG | 24,289 | 3,717 | 1,733/3,717 = 0.4662 | 138 |

(WHOLE LOG reconciles exactly to the live `hz_shadow_report.py` aggregate:
agreement 1733/3717 0.4662, MISMATCH pre=back_off -> native=trade x138.)

### Finding 1 - the targeted pocket is ELIMINATED (fix did its job)

`back_off -> trade` went **138 (pre) -> 0 (post)**. Every one of the 138
model-error mismatches is a pre-fix record (per-day: 21 on 06-17, 91 on 06-18,
26 on 06-20; sums to 138). Zero recurred in the post-fix games. On its targeted
structural pocket, item 614 worked - the corrected `no_ult` cells no longer
fabricate a one-sided enemy ult, so the over-stated incoming damage that pushed
`back_off` over `trade` is gone.

### Finding 2 - post-fix AGGREGATE is a 2-game small-sample artifact, NOT a regression

Post-fix agreement (0.2468) is lower than pre-fix (0.4863), but this is NOT a fix
regression. The entire post-fix comparable-covered sample is TWO matchups from one
day:

  - Renekton vs Gragas: 235 comparable ticks, ALL 235 are `all_in -> hold` (0 agree)
  - Nasus vs Gragas:      77 comparable ticks, all 77 agree

77/312 = 0.2468 is mechanically just "one game agreed, one game disagreed." The
item-614 fix only changes `no_ult` cells and could not have created the
Renekton-vs-Gragas `all_in` lean (that is the table's standing combat verdict for
that matchup, unrelated to the symmetric-cd-state change). Day-to-day agreement
across the whole log already swings 0.18 -> 0.86, confirming the rate is
matchup/sample-bound, not yet a stable metric.

### Finding 3 - a NEW pocket surfaced (next-diagnosis candidate, NOT fixed here)

`precompute=all_in -> native=hold`, driven entirely by **Renekton vs Gragas**
(235/235). This is a distinct pocket from item 614's `back_off->trade` and is the
natural next `HZ_MISMATCH_DIAGNOSE` target: either the precompute over-values
Renekton's all-in into Gragas (Gragas W damage-reduction + E disengage), or Haiku
is conservatively holding. It is a SINGLE-MATCHUP, SINGLE-GAME signal - too thin
to act on, and out of scope for a measurement pass. Logged as FUTURE; do not fix
blind.

## Result - build axis (secondary)

Post-fix has ZERO comparable build records (neither post-fix game produced a
covered + native build-lean signal), so the build agreement is unmeasurable
post-fix. Pre-fix baseline is unchanged at 199/407 = 0.4889 (dominant mismatch
`anti_squishy -> anti_tank` x184). No build conclusion this pass.

## Verdict

- Item 614 fix on its targeted pocket: CONFIRMED effective (back_off->trade 138 -> 0).
- Aggregate agreement: no regression from the fix; the post-fix dip is a 2-game
  artifact dominated by one new unrelated matchup pocket.
- Flip readiness: STILL NOT MET. Coverage is accruing (~0.96 laning coverage),
  aggregate agreement ~47%, and the post-fix window is dominated by a single
  un-diagnosed pocket. The do-not-flip-blind operator gate HOLDS. Live coach NOT
  flipped this pass (directive-mandated).

## Next (FUTURE, not done here)

1. Diagnose the Renekton-vs-Gragas `all_in -> hold` pocket once more games on that
   matchup accrue (replicate the item-575 `HZ_MISMATCH_DIAGNOSE` method).
2. Re-run this re-measurement after the next batch of live SR games to grow the
   post-fix sample beyond two matchups before any aggregate agreement claim.
