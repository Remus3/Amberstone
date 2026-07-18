# DS Cross-Eval: Annie

VERDICT: MINOR

## Axis 1 - archetype_ok: PASS

Archetype primary=mage, scorer=ability. Ability scorer is the AP damage axis. Annie is a pure
burst AP mage with zero AD scaling. Scorer axis matches kit and matches empirical: every
above-baseline empirical item (Malignance, Liandry's, Stormsurge, Luden's Echo, Rabadon's,
Rylai's) is AP-oriented. No axis mismatch.

## Axis 2 - comp_ok: MINOR FLAG

Scorer type = ability (damage). enemy_damage_type block reports comp_blind=true,
max_positive_shift=0, top_risers_when_ap=[]. All 5 comp cells show d_ehp=0.0, d_dps=0.0
across every item - the scores are identical in ad_squishy vs ap_squishy vs ad_tanky vs
ap_tanky for each item. The ability scorer is fully blind to whether the enemy team deals
primarily AD or AP. This means Annie gets no nudge toward Banshee's Veil (rank 10, score
8.06) over Zhonya's Hourglass (rank 11, score 8.06 - tied) when facing heavy AP burst, or
vice versa vs AD. For a pure output scorer this is acceptable design but is a data gap for
defensive-item discrimination.

target_resist IS responsive (comp_blind=false, max_positive_shift=5). Against AP-tanky
enemies: Bloodletter's Curse rises +5 ranks, Void Staff +2, Cryptbloom +2, Liandry's +1.
Shadowflame falls -3 (pen item less useful vs MR-stacking targets). This is correct
behavior for a mage facing tanky comps.

Overall comp axis: output scoring is expected comp-invariant on damage type; defensive-item
discrimination is absent. Acceptable for this scorer class - flag as MINOR only (not DEFECT).

## Axis 3 - outcome_ok: MINOR FLAG (pool gap)

Evidence tier ARAM = outcome_all (self n=2, insufficient). Baseline wr = 56.6% (n=129).
Above-baseline empirical items (wr > 56.6%):

  Malignance       n=88  wr=58.0%
  Liandry's        n=61  wr=57.4%
  Rylai's          n=28  wr=57.1%
  Stormsurge       n=33  wr=60.6%
  Luden's Echo     n=31  wr=61.3%
  Rabadon's        n=30  wr=60.0%

Scorer top-8 (bal_squishy): Wooglet's(1), Liandry's(2), Blackfire Torch(3), Rabadon's(4),
Shadowflame(5), Void Staff(6), Stormsurge(7), Cryptbloom(8).

Overlap hits: Liandry's rank 2 (empirical 57.4% - above baseline, good). Rabadon's rank 4
(empirical 60.0% - strong, good). Stormsurge rank 7 (empirical 60.6% - strong, good).

Pool gaps:
- Malignance (highest empirical n=88, wr=58.0%) is absent from the entire scorer top-12
  list. This is the most-built above-baseline item and is invisible to the scorer.
- Luden's Echo (wr=61.3%, n=31, highest wr above baseline) is also absent from scorer top-12.
- Rylai's Crystal Scepter (wr=57.1%, n=28) is absent from scorer top-12.

Shadowflame is scorer rank 5 but empirical wr=55.8%, which is below the 56.6% baseline -
mild empirical underperformance for a highly-ranked item, though n=52 so not definitive.

Wooglet's Witchcap (scorer rank 1, score=34.5) has zero empirical representation in the
data - it is ARAM-exclusive (legitimately) but cannot be validated empirically.

Net: scorer correctly surfaces Liandry's/Rabadon's/Stormsurge but misses the three most
empirically successful items (Malignance, Luden's Echo, Rylai's). Flag as MINOR pool gap.

## Axis 4 - rune_ok: N/A

rune_relevant=false.

## Nominated Retune

Add Malignance, Luden's Echo, and Rylai's Crystal Scepter to Annie's ability scorer item
pool. Malignance is the priority (highest n, above baseline). Review Shadowflame's scorer
weighting vs its below-baseline empirical wr.
