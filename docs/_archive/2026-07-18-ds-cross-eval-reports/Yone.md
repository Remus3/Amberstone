# DS Cross-Eval: Yone

**Verdict: MINOR**
Archetype and comp-responsiveness are sound. Two above-baseline empirical ARAM win items (Infinity Edge, Immortal Shieldbow) are absent from the scorer pool across all 12 comp-cell top-12 lists, indicating a pool gap in the hybrid scorer for Yone.

---

## Axis 1 - archetype_ok: true

- Scorer: hybrid (blends AD DPS + EHP).
- Archetype: primary bruiser, secondary assassin. Yone is an AD melee engager who needs both damage output and survivability - hybrid axis fits.
- Empirical check (ARAM self, n=22, baseline 63.6%): above-baseline items are BotRK 75.0%, IE 73.3%, Immortal Shieldbow 70.0% - all AD crit/lifesteal items. No AP wins. AD scorer axis confirmed correct.

---

## Axis 2 - comp_ok: true

- Scorer = hybrid. Hybrid carries an EHP component, which must respond to enemy damage type.
- responsiveness.primary_axis = "enemy_damage_type", comp_blind = false.
- enemy_damage_type.max_positive_shift = 10 (Wit's End rises 10 ranks vs AP comps vs AD comps).
- target_resist.max_positive_shift = 11 (Liandry's Torment rises 11 ranks vs tanky).
- Both axes are comp_blind=false and shift meaningfully. No defect.

---

## Axis 3 - outcome_ok: false (pool gap)

Using ARAM self (n=22 >= 8), baseline wr = 63.6%.

Above-baseline empirical items (self):
| Item | n | wr |
|---|---|---|
| Blade of The Ruined King (3153) | 16 | 75.0% |
| Infinity Edge (3031) | 15 | 73.3% |
| Immortal Shieldbow (6673) | 10 | 70.0% |

Scorer top-8 (ad_squishy / bal_squishy - most favorable cells):
Rank 1 Void Immolation, Rank 2 BotRK, Rank 3 Heartsteel, Rank 4 Trinity Force, Rank 5 Essence Reaver, Rank 6 Stormrazor, Rank 7 Iceborn Gauntlet (or Dusk and Dawn), Rank 8 Dusk and Dawn (or Kraken Slayer).

- BotRK (3153): rank 2 in all squishy cells. Empirically 75.0% wr. Aligned.
- Infinity Edge (3031): NOT present in any comp cell top-12. Empirically 73.3% wr, n=15. MISSING.
- Immortal Shieldbow (6673): NOT present in any comp cell top-12. Empirically 70.0% wr, n=10. MISSING.

Both are core above-baseline Yone win items absent from the entire scorer item pool. This is a pool gap, not a wrong-axis issue.

---

## Axis 4 - rune_ok: n/a

rune_relevant = false.

---

## Nominated Retune

Add Infinity Edge (3031) and Immortal Shieldbow (6673) to the hybrid scorer item pool for Yone. Both are above-baseline ARAM win items (73.3% and 70.0% wr vs 63.6% baseline) absent from scorer top-12 across all five comp cells. Likely cause: IE's value is crit-multiplier synergy (not raw AD or EHP) and Shieldbow's value is its lifesteal + shielding passive - neither maps cleanly to the standard hybrid DPS+EHP formula. Investigate whether IE crit-synergy weighting and Shieldbow passive EHP credit are implemented in the hybrid scorer for this champion.
