# DS Cross-Eval: Lucian - MINOR

scorer=dps  archetype=carry/assassin  anchor=ARAM  evidence=outcome_self(n=27,wr=40.7%)

## 1. archetype_ok: TRUE
carry/assassin is pure AD. dps scorer = AD axis. Correct axis assignment.

## 2. comp_ok: TRUE
dps scorer primary axis = target_resist (not ehp), so enemy_damage_type comp_blind is
EXPECTED - dps does not need to shift items based on enemy AP/AD share, only on target
armor/MR. responsiveness.target_resist.max_positive_shift=22; top risers when ap:
Liandry's Torment +22, LDR +7, Serylda's +6, Mortal Reminder +6, Eclipse +6.
Target-resist axis is responsive. Overall responsiveness.comp_blind=false. No defect.

## 3. outcome_ok: FALSE (MINOR pool gap)
Scorer top-8 (ad_squishy cell): BotRK(r1,108.6) / Runaan's Hurricane(r2,72.9) /
Kraken Slayer(r3,69.4) / Void Immolation(r4,64.1) / Essence Reaver(r5,62.6) /
Stormrazor(r6,60.0) / Yun Tal Wildarrows(r7,55.1) / Infinity Edge(r8,54.0).

Empirical ARAM self items with wr ABOVE baseline 40.7%:
- Berserker's Greaves (3006): n=17 wr=47.1% - boots, expected exclusion from item pool
- The Collector (6676): n=17 wr=41.2% - NOT in scorer top-12; pool gap
- Essence Reaver (3508): n=12 wr=41.7% - in scorer top-8 (r5); OK

Scorer rank-1 BotRK (3153): n=8 wr=37.5% - BELOW baseline 40.7%. Over-indexed by scorer.
Runaan's Hurricane (3085) and Kraken Slayer (6672): not present in self empirical at all.
Void Immolation (223069, r4): not in empirical; gold=6000 (ARAM Prismatic, expected absence).
Infinity Edge (3031, r8): n=14 wr=35.7% - below baseline; scorer over-rates it for this sample.

The Collector is the clearest pool gap: above-baseline wr (41.2% self, 46.8% all) but absent
from scorer top-12. BotRK over-weighting vs empirical signal is a calibration concern.

## 4. rune_ok: N/A
rune_relevant=false.

## Nominated retune
Add The Collector (6676) to the dps scorer item pool / score it; review BotRK on-hit
weight that may be inflating its score relative to pure-AD crit builds that the empirical
data favors. Essence Reaver alignment is good (scored r5, above-baseline empirically).

severity=MINOR
