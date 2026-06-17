# Talon DS Scorer Cross-Eval

**Verdict: MISMATCH**

Scorer top items (Essence Reaver #1, Trinity Force #2) are absent from empirical data;
Eclipse (#10 scorer, wr 46.7%) and Edge of Night (absent scorer top-8, wr 38.5%)
are the empirical winners. Pool gap is severe.

---

## Axis 1 - archetype_ok: PASS

Archetype = assassin(primary) / mage(secondary), scorer = burst.
Burst scorer is AD-oriented - correct for Talon whose kit deals physical
damage (bleed, Q/E/R). AD axis matches kit and the empirical above-baseline
items are all AD lethality items (Eclipse 46.7%, Serylda's 38.1%,
Edge of Night 38.5%). No axis mismatch.

## Axis 2 - comp_ok: PASS

Scorer = burst (pure-damage, not EHP). Expected behavior:
- enemy_damage_type: comp_blind expected for non-EHP scorer. Confirmed:
  max_positive_shift=0, top_risers=[]. Correct.
- target_resist: SHOULD move for a damage scorer vs tanky comps. Confirmed:
  max_positive_shift=15; top risers Black Cleaver +15, Mortal Reminder +10,
  Lord Dominik's +9, Serylda's Grudge +8. Responsive.
Overall comp_blind=false at top level. Comp axis is working correctly.

## Axis 3 - outcome_ok: FAIL

Evidence tier: outcome_all, n=59, baseline wr=32.2%.

Scorer top-8 (ad_squishy / bal_squishy):
  #1 Essence Reaver   - NOT in empirical top-10 at all
  #2 Trinity Force    - NOT in empirical top-10 at all
  #3 Infinity Edge    - NOT in empirical top-10 at all
  #4 BotRK            - NOT in empirical top-10 at all
  #5 Umbral Glaive    - empirical wr 32.3% (below/at baseline - boots only)
  #6 Bloodthirster    - NOT in empirical top-10 at all
  #7 Axiom Arc        - empirical wr 32.6% (barely above baseline, n=43)
  #8 Youmuu's Ghostblade - empirical wr 32.1% (below baseline)

Above-baseline empirical items (wr > 32.2%):
  Eclipse         wr 46.7%  (n=15)  - scorer rank 10, OUTSIDE top-8
  Edge of Night   wr 38.5%  (n=13)  - NOT in scorer top-8 at all
  Serylda's Grudge wr 38.1% (n=21)  - scorer rank 11, OUTSIDE top-8
  Axiom Arc       wr 32.6%  (n=43)  - scorer rank 7, in top-8 (marginal)
  Hubris          wr 33.3%  (n=33)  - scorer rank 9, just outside top-8

Critical gaps:
- The Collector (wr 31.7%, n=41) - completely absent from scorer pool
- Eclipse is the highest-wr item (46.7%) but ranks only #10 in scorer
- Essence Reaver #1 scorer has zero empirical representation

## Axis 4 - rune_ok: PASS

rune_relevant=true. No contradicting evidence in data. Rune signals present.

---

## Nominated Retune

burst scorer item weights for Talon need re-calibration:
1. Boost Eclipse weight - empirical wr 46.7% (n=15) but scorer rank 10;
   should be top-5 in all squishy comps.
2. Add Edge of Night to scorer pool top-8 - wr 38.5% (n=13), currently absent.
3. Boost Serylda's Grudge - wr 38.1% (n=21) but scorer rank 11.
4. Investigate and reduce Essence Reaver / Trinity Force / Infinity Edge /
   BotRK weights - all rank in top-4 but have zero empirical representation.
5. Add The Collector to scorer pool - n=41 appearances, currently unranked.
