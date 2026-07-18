# DS Cross-Eval: Ashe

VERDICT: MINOR

Scorer: dps | Archetype: carry (secondary enchanter) | Anchor: ARAM | Evidence: outcome_self (n=18, wr=61.1%)

---

## Axis 1 - archetype_ok: PASS

carry/dps maps to AD-axis scorer. Correct for Ashe (physical ADC, no AP scaling).
Empirical confirms: BotRK 63.6%, Kraken 66.7%, Yun Tal 83.3% all above 61.1% baseline.
AD-item wins are consistent with the dps scorer axis.

## Axis 2 - comp_ok: PASS

Scorer=dps -> target_resist responsiveness expected, enemy_damage_type invariance expected.
- target_resist: primary_axis, comp_blind=false, max_positive_shift=23. Responsive. Liandry's +23, Serylda's +7, LDR +7 vs tanky comps. Correct direction.
- enemy_damage_type: comp_blind=true, max_positive_shift=0. Zero movement across ad/ap enemy comps. Expected for a pure DPS scorer with no EHP term.
All 3 squishy cells produce identical rankings - correct for a DPS scorer that does not factor incoming damage type.

## Axis 3 - outcome_ok: MINOR FLAG

Using outcome_self (n=18 >= 8). Baseline wr = 61.1%.

Scorer top-8 (ad_squishy/bal_squishy):
  Rank 1 BotRK      - self wr 63.6% ABOVE baseline - OK
  Rank 2 Runaan's   - self wr 42.9% BELOW baseline (n=7) - scorer overweights, empirically losing
  Rank 3 Kraken     - self wr 66.7% ABOVE baseline - OK
  Rank 4 Ess Reaver - absent from self empirical
  Rank 5 Stormrazor - absent from self empirical
  Rank 6 Yun Tal    - self wr 83.3% ABOVE baseline - strong
  Rank 7 IE         - self wr 60.0% just below baseline (n=5, borderline)
  Rank 8 Void Imm.  - absent from self empirical

Pool gap: Statikk Shiv (3087) absent from scorer top-8 in all comp cells.
  - self: n=5, wr=60.0% (near baseline)
  - all:  n=68, wr=54.4% above 49.3% all-baseline; 4th most-built item in all-ARAM
Runaan's ranks #2 by scorer but empirically loses in self sample (42.9%). Small n caveat (n=7)
but directional mismatch is notable.

## Axis 4 - rune_ok: n/a

rune_relevant = false.

---

## Nominated Retune

Investigate Statikk Shiv DPS formula coverage - it is the 4th most-built ARAM item for Ashe
(n=68, wr=54.4% vs 49.3% all baseline) but does not appear in scorer top-8 across any comp.
Also review Runaan's Hurricane weight: scorer rank #2 but empirically sub-baseline in self sample.
