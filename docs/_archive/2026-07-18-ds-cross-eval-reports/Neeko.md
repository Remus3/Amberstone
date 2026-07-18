# Neeko - DS Scorer Cross-Eval Report

**Verdict: MINOR**
Scorer: ability | Archetype: mage/enchanter | Anchor: ARAM | Evidence: outcome_all (n=141, baseline wr=44.7%)

---

## Axis 1 - archetype_ok: TRUE

Scorer = ability. Neeko is a pure AP mage; all damage is AP-scaling. Mage/ability axis is correct.
No AD empirical builds above baseline to challenge this.

---

## Axis 2 - comp_ok: TRUE

Scorer = ability. Expected behavior: target_resist responsive (AP-pen vs tanky), enemy_damage_type blind.

- responsiveness.primary_axis = "target_resist" (correct for ability scorer)
- target_resist.comp_blind = false; max_positive_shift = +3
  - Bloodletter's Curse +3, Cryptbloom +2, Void Staff +1, Liandry's +1 when vs tanky
- enemy_damage_type.comp_blind = true; max_positive_shift = 0
  - This is EXPECTED for ability scorer - EHP delta is irrelevant when scorer doesn't model survivability
  - responsiveness.comp_blind (outer) = false -> scorer IS responsive overall

No defect. comp_ok = true.

---

## Axis 3 - outcome_ok: FALSE (MINOR pool gap)

Empirical source: ARAM outcome_all (n=141, baseline wr=44.7%).
Above-baseline items (wr > 44.7%):
  - Shadowflame (n=64, wr=53.1%) - scorer rank 6 ad_squishy/bal_squishy -> PRESENT, good
  - Stormsurge (n=47, wr=51.1%) - scorer rank 7 -> PRESENT, good
  - Sorcerer's Shoes (n=109, wr=46.8%) - boots, scorer does not rank boots, expected absence
  - Refillable Potion (n=25, wr=52.0%) - consumable, not in item scorer scope

Scorer top-8 (ad_squishy / bal_squishy):
  rank1 Wooglet's Witchcap (6000g) - NOT in empirical top-10 at all (0 tracked rows)
  rank2 Liandry's Torment (3000g) - NOT in empirical top-10 at all
  rank3 Blackfire Torch (2800g) - NOT in empirical top-10
  rank4 Rabadon's Deathcap (n=31, wr=45.2%) - marginal above baseline, present
  rank5 Void Staff (not in empirical top-10)
  rank6 Shadowflame (n=64, wr=53.1%) - above baseline, aligned
  rank7 Stormsurge (n=47, wr=51.1%) - above baseline, aligned

Missing from scorer top-8 but high empirical frequency:
  - Luden's Echo (n=62, wr=43.5% - below baseline, not a winning gap)
  - Malignance (n=65, wr=40.0% - below baseline)
  - Hextech Rocketbelt (n=28, wr=42.9% - below baseline)

Assessment: The scorer's top items (Wooglet's #1, Liandry's #2) have zero empirical presence in
rewind data. Wooglet's is a 6000g ARAM-only item; Liandry's is a standard mage pick that should
appear. Their absence from the top-10 suggests either small n effects or scorer over-ranking
expensive/niche items. The true above-baseline empirical winners (Shadowflame, Stormsurge) are
present at rank 6-7, which is correct directionally but ranked below items with no empirical
support. Pool gap is MINOR (no winning item actively absent; Luden's Echo below baseline).

outcome_ok = false (MINOR: Wooglet's/Liandry's scorer-top-2 have zero empirical presence;
ranked above empirical above-baseline winners Shadowflame and Stormsurge)

---

## Axis 4 - rune_ok: n/a

rune_relevant = false.

---

## Nominated Retune

Investigate Wooglet's Witchcap and Liandry's Torment scorer weighting vs gold cost: both rank in
top-2 but have zero ARAM empirical presence (n=141 sample). Consider whether the ability scorer's
AP ratio / gold-efficiency formula overvalues these relative to actual purchase frequency.
Luden's Echo does not need addition (below baseline wr=43.5%); no urgent item pool add required.

Nominated retune: "review Wooglet's Witchcap + Liandry's scorer rank vs zero empirical presence; ability scorer may over-weight AP-ratio burst items at high gold cost in ARAM"
