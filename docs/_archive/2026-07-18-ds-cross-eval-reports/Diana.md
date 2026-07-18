# Diana DS Scorer Cross-Eval

Verdict: MINOR

## Axis 1 - archetype_ok: TRUE

Primary=mage, secondary=bruiser, scorer=ability. Diana is a pure AP burst/dive kit (Q arc
damage, R moonfall AP scaling, E AP shield). Ability scorer is the correct AP axis. The
secondary bruiser archetype is consistent with Diana building tank-AP hybrids. No axis mismatch.

## Axis 2 - comp_ok: TRUE

Scorer primary_axis=target_resist. responsiveness.comp_blind=false at the outer level.

- enemy_damage_type: comp_blind=TRUE (max_positive_shift=0, no risers). All d_ehp=0.0 across
  all five comp cells (ad_squishy/bal_squishy/ap_squishy/ad_tanky/ap_tanky). This is expected
  for an ability scorer - it does not weight EHP, so enemy damage-type invariance is correct.

- target_resist: comp_blind=FALSE (max_positive_shift=5). Bloodletter's Curse rises +5 ranks
  vs AP-tanky; Void Staff +2; Cryptbloom +2. Shadowflame falls -3 vs AP-tanky (armor pen item
  loses value vs MR stacking). The scorer responds correctly to tanky enemies.

No defect.

## Axis 3 - outcome_ok: FALSE

Using outcome_self (n=39 >= 8). Diana ARAM baseline wr=53.8%.

Above-baseline empirical items:
  Heartsteel      76.9% (n=13) - rank absent from scorer pool
  Unending Despair 68.8% (n=16) - rank absent from scorer pool
  Stormsurge       62.5% (n=8)  - scorer rank 7 (ad_squishy) - correctly surfaced

Scorer top-8 (ad_squishy cell, representative):
  rank 1  Liandry's Torment    emp wr 50.0% (below baseline 53.8%)
  rank 2  Wooglet's Witchcap   not in empirical top-10
  rank 3  Blackfire Torch      not in empirical top-10
  rank 4  Rabadon's Deathcap   not in empirical top-10
  rank 5  Shadowflame          emp wr 52.9% (below baseline)
  rank 6  Void Staff           not in empirical top-10
  rank 7  Stormsurge           emp wr 62.5% (above baseline - correct)
  rank 8  Cryptbloom           not in empirical top-10

Pool gap: Heartsteel (76.9%) and Unending Despair (68.8%) are the two highest-wr empirical
staples and both are absent from the ability scorer pool entirely. The scorer over-weights
pure AP items (Wooglet's, Blackfire Torch, Rabadon's) that have no empirical representation.
Luden's Echo (emp wr 42.9%) and Hextech Rocketbelt (emp wr 43.8%) are also missing; both
underperform baseline, so their absence is acceptable. The critical miss is the bruiser items
(Heartsteel, Unending Despair) that Diana players build for survivability in dive patterns.

Liandry's ranks 1 but posts only 50.0% wr (below baseline), making it an over-promoted item.

## Axis 4 - rune_ok: n/a

rune_relevant=false.

## Nominated Retune

Add Heartsteel and Unending Despair to the ability scorer item pool for Diana (or exclude
bruiser-eligible items from pool suppression). Recalibrate Liandry's score weight - it is
ranked #1 but underperforms the champ baseline by 3.8 pp. Consider giving Stormsurge more
weight (62.5% wr, currently rank 7).
