# DS Cross-Eval: Kindred

Verdict: MINOR

---

## Axis 1 - archetype_ok: PASS

Scorer: dps (AD axis). Archetype: carry/bruiser.
Kindred is an AD marksman jungler with AA-based on-hit kit. AD-axis dps scorer
is correct for kit. Empirical above-baseline items (ARAM self, baseline 63.9%):
- Yun Tal Wildarrows: 85.7% wr (n=14) - crit
- Cloak of Agility: 75.0% wr (n=8) - crit component
- Infinity Edge: 73.3% wr (n=15) - crit
- Berserker's Greaves: 66.7% wr (n=30) - AS/AD

All above-baseline empirical items are AD/crit. Axis match confirmed.

---

## Axis 2 - comp_ok: PASS

Scorer is dps. Primary axis is target_resist (comp_blind=false).
target_resist.max_positive_shift=22: Liandry's Torment rises +22 ranks in
tanky enemy comps, Serylda's Grudge +8, Lord Dominik's +6. Meaningful
target-resist responsiveness confirmed for a dps scorer.

enemy_damage_type is comp_blind=true (max_positive_shift=0). For a dps scorer
this is expected - damage-type EHP adaptation is an EHP-scorer concern, not
dps. No defect here.

---

## Axis 3 - outcome_ok: FAIL (MINOR)

Evidence source: ARAM self (n=36 >= 8). Baseline wr=63.9%.

Scorer top-8 (ad_squishy / bal_squishy cells) vs empirical:

| Rank | Item                | Emp WR  | Above baseline? |
|------|---------------------|---------|-----------------|
| 1    | Blade of The Ruined King | 58.8% | NO (-5.1pp)  |
| 2    | Runaan's Hurricane  | 57.1%   | NO (-6.8pp)     |
| 3    | Kraken Slayer       | 54.5%   | NO (-9.4pp)     |
| 4    | Essence Reaver      | n/a     | absent          |
| 5    | Void Immolation     | n/a     | absent          |
| 6    | Stormrazor          | n/a     | absent          |
| 7    | Infinity Edge       | 73.3%   | YES (+9.4pp)    |
| 8    | Yun Tal Wildarrows  | 85.7%   | YES (+21.8pp)   |

Ranks 1-3 all underperform empirical baseline. Yun Tal Wildarrows (85.7% wr,
n=14) is the strongest empirical performer but sits at only rank 8 in the
scorer. Runaan's Hurricane is over-weighted (rank 2) vs its 57.1% empirical
outcome. Essence Reaver, Stormrazor, Void Immolation have no empirical
representation in the sample.

This is a calibration gap, not a wrong-axis defect. Severity: MINOR.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated retune

Reduce weight on Runaan's Hurricane in the Kindred dps scorer configuration
(rank 2 -> closer to 5-6 range, empirical 57.1% wr is below-baseline).
Elevate Yun Tal Wildarrows toward rank 4-5 to reflect empirical 85.7% wr
(n=14). Review Essence Reaver and Stormrazor - no empirical data, may be pool
padding over confirmed winners.
