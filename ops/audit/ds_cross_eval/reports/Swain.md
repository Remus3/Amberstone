# DS Cross-Eval: Swain

## Verdict: MINOR

Scorer: ability | Archetype: mage/enchanter | Evidence tier (ARAM): outcome_self (n=11, baseline wr=45.5%)

---

## Axis 1 - archetype_ok: TRUE

Mage primary with enchanter secondary maps correctly to the ability scorer (AP axis). Swain
is an AP drain-mage - all high-wr empirical items (Spirit Visage, Sorcerer's Shoes, Rylai's,
Liandry's) are AP or AP-synergy items. No axis mismatch.

---

## Axis 2 - comp_ok: TRUE

Scorer is "ability" (not EHP); the relevant responsiveness axis is target_resist.
- target_resist.comp_blind = false, max_positive_shift = 3. Responsive.
  Top risers vs tanky: Bloodletter's Curse +3, Cryptbloom +2, Void Staff +1, Liandry's +1.
  Top fallers: Shadowflame -2, Stormsurge -2 (correct - these are anti-squishy tools).
- enemy_damage_type.comp_blind = true, max_positive_shift = 0. The ability scorer does not
  shift at all based on enemy AD/AP mix. For an ability scorer this is expected behavior
  (EHP scorers are the ones that must move). Not a DEFECT for this scorer type.

---

## Axis 3 - outcome_ok: FALSE

Using outcome_self (n=11 >= 8). Baseline wr = 45.5%.

Scorer top-8 (ad_squishy cell, reference): Wooglet's Witchcap (rank 1), Liandry's (rank 2),
Blackfire Torch (rank 3), Rabadon's (rank 4), Void Staff (rank 5), Shadowflame (rank 6),
Stormsurge (rank 7), Cryptbloom (rank 8).

Empirical items above baseline (wr > 45.5%):
- Spirit Visage: 80.0% wr (n=5) - ABSENT from scorer top-8
- Sorcerer's Shoes: 60.0% wr (n=5) - boots, acceptable exclusion
- Rylai's Crystal Scepter: 50.0% wr (n=6) - ABSENT from scorer top-8

Empirical items in scorer top-8 that underperform:
- Liandry's Torment: scorer rank 2, empirical wr 33.3% (below 45.5% baseline)
- Wooglet's Witchcap: scorer rank 1, zero empirical appearances in self data

Spirit Visage is Swain's single highest empirical win-rate item at 80% wr and is fully
absent from the scorer's top 8. This is a meaningful pool gap: the ability scorer does not
model healing-amplification value (Spirit Visage's 30% heal amp + MR directly turbocharges
Swain's drain-tank R). Rylai's at 50% wr with n=6 is also a staple absent from the pool.
Liandry's scoring rank 2 while losing at 33.3% wr is a secondary concern (small n, ARAM
variance), but the Spirit Visage + Rylai's absence is a genuine gap.

---

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

Add healing-amplification item weighting to the ability scorer for drain-mage archetypes:
Spirit Visage should surface for champions whose kit contains drain/lifesteal-from-ability
mechanics. Also add slow-uptime synergy weighting to surface Rylai's Crystal Scepter for
champions with multi-hit AP abilities (Swain E+R). Both items are empirically validated
winners and are currently invisible to the scorer.
