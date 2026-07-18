# Hwei DS Scorer Cross-Eval

**VERDICT: MINOR**

Scorer: ability | Archetype: mage/enchanter | Anchor: ARAM | Evidence: outcome_all (n=147, baseline wr=49.0)

---

## Axis 1 - archetype_ok: PASS

Mage/enchanter -> ability scorer uses AP axis. Correct. All comp_grid cells surface AP items only (Wooglet's rank 1, Liandry's rank 2, Blackfire Torch rank 3, Rabadon's rank 4, Void Staff rank 5). ARAM empirical above-baseline winners are also AP: Liandry's 53.3, Seraph's Embrace 51.2, Void Staff 54.5, Ionian Boots 55.9. No axis conflict.

## Axis 2 - comp_ok: PASS

Primary axis = target_resist (correct for ability/mage scorer). target_resist.comp_blind = false; max_positive_shift = +7. Top risers vs tanky targets: Abyssal Mask +7, Bloodletter's Curse +4, Cryptbloom +3, Void Staff +1, Liandry's +1. Scorer adjusts build toward MR-shred when facing tanky enemies as expected.

enemy_damage_type.comp_blind = true (max_positive_shift = 0). This is expected for a pure-output ability scorer - the scorer does not model self-survivability vs enemy damage type, only outgoing damage to targets. Not a defect.

Overall responsiveness.comp_blind = false. No EHP/hybrid comp-blind defect.

## Axis 3 - outcome_ok: FAIL (pool gaps + below-baseline ranked item)

Using outcome_all (self n=0). Baseline wr = 49.0.

Scorer top 8 (ad_squishy / bal_squishy cells):
- rank 1 Wooglet's Witchcap (228002): no empirical entry in top-10 list (n too low to appear)
- rank 2 Liandry's Torment (6653): wr 53.3 (n=107) - above baseline, GOOD
- rank 3 Blackfire Torch (2503): wr 41.3 (n=75) - BELOW baseline by 7.7pp, yet scored rank 3
- rank 4 Rabadon's Deathcap (3089): wr 47.6 (n=42) - below baseline
- rank 5 Void Staff (3135): wr 54.5 (n=22) - above baseline, GOOD
- rank 6 Shadowflame (4645): wr 44.8 (n=58) - below baseline
- rank 7 Stormsurge (4646): no empirical entry (low n)
- rank 8 Cryptbloom (3137): no empirical entry (low n)

Above-baseline empirical staples missing from scorer pool:
- Seraph's Embrace (3040): wr 51.2, n=43 - NOT in scorer pool at any rank
- Ionian Boots of Lucidity (3158): wr 55.9, n=34 - NOT in scorer pool at any rank

Blackfire Torch at rank 3 is the sharpest flag: wr 41.3 on 75 games is well below the 49.0 baseline. Its high score likely reflects raw AP amplification math (Blackfire stacks from Q/W cycling) but the empirical record says players lose with it at unusually high rates. Seraph's and Ionian Boots are proven above-baseline winners entirely absent from the scorer pool.

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

1. Add Seraph's Embrace (3040) to ability scorer pool - wr 51.2 on n=43 in ARAM, no scorer representation.
2. Add Ionian Boots of Lucidity (3158) to ability scorer pool - wr 55.9 on n=34, highest wr in empirical set.
3. Investigate Blackfire Torch rank inflation - ranked 3rd by scorer but empirical wr 41.3 (7.7pp below baseline, n=75). Consider a penalty or recalibration of the stacking-AP amplification path for Hwei specifically.
