# DS Cross-Eval: Lux

VERDICT: MINOR

Scorer: ability | Archetype: mage/enchanter | Anchor: ARAM | Evidence: outcome_self (n=16, wr=50.0)

---

## Axis 1 - archetype_ok: PASS

Mage/enchanter maps to AP axis; ability scorer is the correct scorer for ability-scaling AP damage kits. Empirical self build (n=16) shows only AP items: Rabadon's Deathcap wr 55.6, Shadowflame wr 50.0, Luden's Echo wr 46.2. No AD item appears above baseline. Axis is aligned.

## Axis 2 - comp_ok: PASS

Scorer=ability; primary_axis=target_resist. target_resist is responsive (comp_blind=false): max_positive_shift=+6 ranks. vs tanky comps Bloodletter's Curse rises +6, Cryptbloom +4, Void Staff +2, Liandry's +1. Tanky cells correctly surface Liandry's rank 1 (score 29.3) over Wooglet's rank 1 (41.9 squishy) - logical: Liandry's DoT maximises value vs tanky resisters while Wooglet's raw AP burst is diluted. enemy_damage_type is comp_blind=true (max_positive_shift=0) but this is expected for an ability scorer: self-survivability weighting by enemy damage mix is not the scorer's concern. Not a defect.

## Axis 3 - outcome_ok: PASS (with MINOR pool flag)

Evidence source: outcome_self (n=16 >= 8). Baseline wr=50.0. Above-baseline empirical items: Rabadon's Deathcap (wr 55.6, n=9). Rabadon's is scorer rank 4 in ad_squishy/bal_squishy cells - present in top-8. Good alignment there.

Pool gap: Wooglet's Witchcap is scorer rank 1 (score 41.9 vs Liandry's 28.4, a 47% premium) but has zero appearances in n=16 empirical self games. It is a 6000g ARAM-only item - low appearance rate is plausible for a small sample - but the gap between its scorer dominance and real-game absence is notable. Stormsurge is scorer rank 7 (squishy cell) but empirically wr 45.7 (all, n=94, baseline 49.0) - below baseline in a large sample. Neither is a hard mismatch but both are pool-fit concerns.

No scorer top-8 item is empirically losing (all above-baseline items are either in or above the pool). Malignance (empirically wr 20.0 self / 38.6 all) is correctly absent from scorer top-8.

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Wooglet's Witchcap rank 1 overhang: review whether the 6000g ARAM item gold-efficiency formula inflates its score vs real-game accessibility. If gold-cost normalisation is already applied, no change needed. Stormsurge rank 7 with below-baseline wr in n=94 sample: minor - acceptable given it provides burst + move-speed niche value. Suggested: verify Wooglet's gold-cost factor in ability scorer; if unbounded, cap or penalise items above 5000g.
