# DS Cross-Eval: Fiddlesticks

verdict: MINOR
scorer: ability
archetype: mage/enchanter
evidence_tier_aram: outcome_all (n=128, baseline wr=46.1%)

## Axis 1 - archetype_ok: TRUE

Scorer=ability is AP-axis. Fiddlesticks kit is full AP (drain, fear, bouncing bats, ult all scale AP).
Empirical above-baseline items are all AP: Rabadon's (55.0%), Zhonya's (48.1%), Liandry's (48.4%).
AP axis correct, no mismatch.

## Axis 2 - comp_ok: TRUE

Ability scorer primary_axis=target_resist, comp_blind=false (top level). Target resist responds:
Abyssal Mask +5, Cryptbloom +3, Bloodletter's Curse +3 when vs tanky AP - MR-shred items rise
correctly as targets get more MR.

enemy_damage_type.comp_blind=true with max_positive_shift=0. This is expected: ability scorer
outputs pure AP damage and has no EHP component, so enemy AD/AP split does not influence
recommendations. Not a defect.

## Axis 3 - outcome_ok: FALSE

Scorer top-8 (ad_squishy = bal_squishy, identical): Liandry's(r1), Wooglet's(r2), Blackfire Torch(r3),
Void Staff(r4), Shadowflame(r5), Rabadon's(r6), Stormsurge(r7), Cryptbloom(r8).

Empirical items above 46.1% baseline (outcome_all n=128):
  Liandry's   48.4%  r1 in scorer  - aligned
  Zhonya's    48.1%  r12 in scorer - present but deprioritized (MINOR gap)
  Rabadon's   55.0%  r6 in scorer  - aligned

Critical gap: Malignance (id 3118) is the most-purchased item in the sample (n=107, 84% pick rate,
wr=45.8%). It is ABSENT from the scorer top-12 entirely. Even below baseline wr, a near-universal
staple not appearing anywhere in the pool is a pool coverage gap. Fiddlesticks' passive (Dread on
R cooldown) ties directly to ult haste, making Malignance the highest-synergy item - its absence
from the scorer pool is the nominated retune target.

Zhonya's (48.1% wr, above baseline, n=77) landing at r12 is a secondary pool gap.

## Axis 4 - rune_ok: N/A

rune_relevant=false.

## Nominated Retune

Add Malignance (id 3118) to ability scorer item pool; verify Malignance surfaces in top-8 across
squishy comp cells. Also investigate why Zhonya's scores only r12 despite above-baseline empirical wr.

## Summary

Archetype and comp behavior are correct. Pool gap: Malignance (most-purchased Fiddlesticks item,
n=107 out of 128 games) is completely absent from scorer output; Zhonya's ranks 12th despite
above-baseline win rate. Both are scorer pool/scoring-weight issues, not axis mismatches.
Severity: MINOR.
