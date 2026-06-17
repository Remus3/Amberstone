# DS Cross-Eval: Varus

**Verdict: MINOR**
Scorer axis and comp responsiveness are correct. Pool gap: high-wr empirical staples
(Muramana 71.4%, The Collector 50.0%, Wit's End 50.0%) are absent from scorer top-8.

---

## 1. Archetype

- Scorer: dps (AD axis). Archetype: carry/secondary mage.
- Varus is an AD ranged carry. Physical auto-attack damage dominates; W stacks deal
  physical+magic but AD itemization is empirically correct.
- Empirical ARAM self (n=20, baseline 45.0%): above-baseline items are Muramana 71.4%
  (n=7), The Collector 50.0% (n=10), Wit's End 50.0% (n=6).
- All above-baseline items are AD/hybrid items consistent with AD axis.
- **archetype_ok: true**

## 2. Comp Responsiveness

- Scorer = dps. Enemy damage type blindness (comp_blind=true, max_positive_shift=0) is
  expected for a dps scorer - enemy damage type does not drive AD item selection.
- target_resist.comp_blind = false; max_positive_shift = 23 (Liandry's +23, Mortal
  Reminder +8, Serylda's +7, Lord Dominik's +7, Eclipse +5). Scorer correctly shifts
  toward penetration items when enemy team is tanky.
- Overall responsiveness.comp_blind = false.
- **comp_ok: true**

## 3. Outcome Overlap

Using outcome_self (n=20 >= 8). Baseline wr = 45.0%.

Above-baseline empirical items (ARAM self):
- Muramana: 71.4% wr (n=7)
- The Collector: 50.0% wr (n=10)
- Wit's End: 50.0% wr (n=6)

Scorer top-8 in ad_squishy cell:
  1. Blade of The Ruined King (93.8)
  2. Runaan's Hurricane (65.9)
  3. Kraken Slayer (60.1)
  4. Essence Reaver (52.5)
  5. Stormrazor (50.5)
  6. Void Immolation (49.0)
  7. Yun Tal Wildarrows (48.2)
  8. Infinity Edge (47.0)

None of the three above-baseline empirical winners appear in scorer top-8. Muramana
(highest wr at 71.4%) is completely absent. The Collector does not appear until ad_tanky
cell rank 12 area. Wit's End is not scored in the squishy cells at all.

**outcome_ok: false** - Muramana missing from scorer pool entirely; Collector and Wit's
End also above baseline and absent.

## 4. Rune

rune_relevant = false.
**rune_ok: n/a**

---

## Nominated Retune

Add Muramana to Varus dps scorer item pool. Verify The Collector and Wit's End are
evaluated and surfaced when their passives qualify. Muramana's mana-scaling and on-hit
hybrid damage are likely unmodeled in the current dps scorer formulation.
