# DS Cross-Eval: Mel

**Verdict: MINOR**

Scorer: ability | Archetype: mage/enchanter | Anchor: ARAM | Evidence: outcome_self (n=9, wr 55.6%)

## Axis 1 - archetype_ok: true

Scorer=ability is the AP axis. Correct for a mage/enchanter kit. Empirical top items
(Liandry's Torment, Blackfire Torch, Cosmic Drive) are all AP items. No AD scorer
contamination. Axis matches kit and empirical winners.

## Axis 2 - comp_ok: true

Scorer primary_axis=target_resist. responsiveness.target_resist.comp_blind=false,
max_positive_shift=6. Comp grid confirms tanky enemy shifts rankings: Liandry's rises
to rank 1 (31.11) vs squishy rank 2 (29.19); Wooglet's drops to rank 2 (18.20) vs
squishy rank 1 (30.33). Bloodletter's Curse shifts +6 into tanky cells.

enemy_damage_type.comp_blind=true with max_positive_shift=0. This is EXPECTED for
ability/mage scorer - incoming damage type does not drive AP item selection. Not a defect.

## Axis 3 - outcome_ok: true (with MINOR pool gaps)

Scorer top-8 (ad_squishy/bal_squishy reference cells):
1. Wooglet's Witchcap  2. Liandry's Torment  3. Blackfire Torch
4. Rabadon's Deathcap  5. Shadowflame  6. Void Staff  7. Stormsurge  8. Cryptbloom

Empirical ARAM self (n=9 >= 8, baseline 55.6%):
- Blackfire Torch: wr 100.0% (n=5) - rank 3 in scorer. Aligned.
- Liandry's Torment: wr 55.6% (n=9) - rank 2 in scorer. Aligned (at baseline).

Empirical ARAM all (n=130, baseline 50.8%) - above-baseline items:
- Seraph's Embrace: 58.3% (n=24) - NOT in scorer top-12. Pool gap.
- Blackfire Torch: 57.7% (n=52) - rank 3. Good.
- Ionian Boots of Lucidity: 56.5% (n=23) - boots, expected absence.
- Cosmic Drive: 54.5% (n=33) - NOT in scorer top-12. Pool gap.
- Liandry's Torment: 53.8% (n=91) - rank 2. Good.

Core scorer picks (Liandry's, Blackfire Torch) appear above baseline. Seraph's Embrace
(58.3%, n=24) and Cosmic Drive (54.5%, n=33) are empirically above baseline but absent
from scorer pool entirely. This is a MINOR pool gap.

Below-baseline scorer items in top-8: Wooglet's has no direct empirical sample in top
items, Rabadon's wr 46.0% (n=50) below baseline in outcome_all - minor concern.
Shadowflame wr 43.0% (n=79) below baseline but rank 5 scorer - mild overrank.

## Axis 4 - rune_ok: n/a

rune_relevant=false.

## Nominated Retune

Add Seraph's Embrace and Cosmic Drive to ability scorer item pool for Mel. Both are
above-baseline empirically (58.3% and 54.5% respectively with meaningful n). Verify
whether their absence is an explicit exclusion or a coverage miss. Shadowflame at rank 5
(empirical 43.0%, n=79) may be mildly overranked; cross-check scorer weight for low-MR
squish vs penetration path.
