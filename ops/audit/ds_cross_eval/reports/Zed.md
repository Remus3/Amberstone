VERDICT: MINOR - Voltaic Cyclosword and The Collector absent from scorer pool despite high empirical WR; axis and comp responsiveness correct.

## Axis 1 - archetype_ok: PASS

Scorer = burst (assassin AD). Kit is pure AD shadow burst. Correct axis.
Empirical above-baseline items (ARAM all baseline 41.3%):
- Eclipse wr 45.1 (n=71) - AD lethality, burst-compatible
- Voltaic Cyclosword wr 45.8 (n=24) - AD lethality, burst-compatible
- Mercury's Treads wr 43.8 (n=32) - boots, not scorer-ranked
- Serylda's Grudge wr 42.1 (n=57) - armor-pen, burst-compatible
- Edge of Night wr 42.1 (n=38) - lethality shield, burst-compatible
SR all baseline 50.0%:
- Voltaic Cyclosword wr 60.7 (n=28) - strongest empirical signal
- Serylda's Grudge wr 57.1 (n=14)
All above-baseline items are AD lethality/armor-pen. Archetype match confirmed.

## Axis 2 - comp_ok: PASS

primary_axis = target_resist. comp_blind = false.
target_resist max_positive_shift = 14 ranks.
Top risers vs tanky: Mortal Reminder (+14), Black Cleaver (+14), Lord Dominik's (+12), BotRK (+10).
Armor-pen items correctly surface vs tanky comps - expected burst scorer behavior.
enemy_damage_type comp_blind = true, but per PROGRAM.md burst scorers test target_resist not enemy damage type; this is by design, not a defect.

## Axis 3 - outcome_ok: MINOR

Evidence tier = outcome_self (ARAM, n=10, wr 20.0% baseline).
Empirical self items vs baseline 20.0%:
- Ionian Boots wr 22.2 (n=9) - barely above
- The Collector wr 25.0 (n=8) - above baseline
- Axiom Arc wr 0.0 (n=5) - BELOW baseline

The Collector (wr 25.0, best self item) does NOT appear in scorer comp_grid top-12 for any cell. Pool gap.
Axiom Arc ranks 5 in scorer squishy - empirically losing (wr 0.0 on n=5 self; 37.9 on n=87 all, below 41.3 baseline). Weak signal but notable.

ARAM all pool (n=155, baseline 41.3%): Voltaic Cyclosword wr 45.8 (n=24) does NOT appear in any comp_grid top-12. Missing staple.
SR all pool (n=48, baseline 50.0%): Voltaic Cyclosword wr 60.7 (n=28) strongest item by far - NOT in any comp_grid cell shown. This is the primary gap.

Scorer top-8 squishy: Umbral Glaive, Essence Reaver, IE, Sundered Sky, Axiom Arc, Youmuu's, Hubris, Bloodthirster.
Eclipse (wr 45.1 ARAM all) appears at rank 9 ad_tanky only - absent from squishy top-8.

Pool gaps: Voltaic Cyclosword (highest SR wr 60.7), The Collector (best self item), Eclipse (above-baseline ARAM all) all missing or low-ranked in squishy scorer output.

## Axis 4 - rune_ok: NOTE

rune_relevant = true. Burst scorer wires self-rune procs (Electrocute is canonical Zed keystone; feeds burst.py).
Self cohort wr = 20.0% on n=10 - extremely low, consistent with ARAM Zed being weak (not a rune wiring fault).
No structural rune-blind flag; wiring is present by scorer design.

## Nominated retune

Investigate why Voltaic Cyclosword and Eclipse rank outside top-8 in squishy cells despite strong empirical WR.
Cyclosword lethality on-hit passive may not be captured in burst item-score weights.
Nomination: audit burst scorer item-effect registry for Voltaic Cyclosword (id 6699) and Eclipse (id 6692) passive weights.
