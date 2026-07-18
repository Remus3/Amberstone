# DS Cross-Eval: Jhin

Severity: MINOR
Scorer: dps | Archetype: carry/mage | Anchor: ARAM | Evidence: outcome_self (n=33, baseline wr 54.5)

## Axis 1 - archetype_ok: PASS

carry primary, dps scorer. Correct axis: carry/bruiser/assassin = AD. Jhin is an AD marksman.
Empirical above-baseline items (ARAM self, wr > 54.5): The Collector 56.7 (n=30), Rapid Firecannon
60.9 (n=23), Boots of Swiftness 55.0 (n=20), Axiom Arc 57.1 (n=7), Ionian Boots 60.0 (n=5).
All are AD physical items. Axis is correct.

## Axis 2 - comp_ok: PASS

dps scorer -> target_resist responsiveness expected, enemy damage type invariance expected.
target_resist.comp_blind = false, max_positive_shift = 18 (Liandry's Torment +18, Serylda's +12).
Rankings shift squishy vs tanky as expected: Essence Reaver drops rank 3->4, Liandry's Torment
enters at rank 5 vs tanky (not in squishy top-8). Appropriate target-resist sensitivity.
enemy_damage_type.comp_blind = true is expected for a pure dps scorer (incoming type irrelevant).
d_ehp and d_dps show 0.0 across all cells - likely a display artifact of how dps scorer
reports totals vs deltas, not a functional failure since rank order IS shifting.

## Axis 3 - outcome_ok: FAIL (pool gap)

Scorer top-8 (ad_squishy): BoRK (1), Void Immolation (2), Essence Reaver (3), Runaan's Hurricane (4),
Stormrazor (5), Infinity Edge (6), Eclipse (7), Kraken Slayer (8).

Above-baseline empirical staples missing from top-8:
- Rapid Firecannon: 60.9% wr (n=23) - Jhin's signature item, ABSENT from scorer top-8.
  RFC extends AA range on Jhin's 4th shot, a core mechanic not captured by generic dps math.
- The Collector: 56.7% wr (n=30) - most-built above-baseline item, scorer ranks it #11 in ad_squishy.
- Axiom Arc: 57.1% wr (n=7) - scorer rank not in top-8 for squishy cells.

BoRK (rank 1 scorer) has no empirical presence in the top items at all - likely overscored.
Infinity Edge (rank 6 scorer) is 54.2% wr empirically, just barely above baseline.
Void Immolation (rank 2 scorer) has no empirical entry - small/zero empirical representation.

## Axis 4 - rune_ok: N/A

rune_relevant = false.

## Nominated Retune

Jhin RFC-Collector lift: add Jhin-specific item affinity weights for Rapid Firecannon (RFC)
and The Collector in the dps scorer pool. RFC's value comes from the 4th-shot range extension
mechanic (not raw dps), so it needs a champion-specific passive bonus. The Collector's execute
passive undervalues in generic dps math vs its empirical win rate.
Also investigate BoRK overscoring: rank 1 scorer but absent from empirical high-wr items.
