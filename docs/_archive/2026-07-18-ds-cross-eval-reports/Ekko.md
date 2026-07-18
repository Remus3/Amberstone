# DS Cross-Eval: Ekko

VERDICT: MINOR

Scorer: ability | Archetype: mage/assassin | Anchor: ARAM | Evidence: outcome_self (n=13, wr=30.8%)

## Axis 1 - archetype_ok: PASS

Ekko is AP mage/assassin. Scorer=ability is AP-axis. All empirical high-wr items are AP
(Hextech Rocketbelt 54.0%, Rabadon's Deathcap 54.1%, Stormsurge 53.7%, Lich Bane 50.0% in all).
Axis alignment is correct.

## Axis 2 - comp_ok: PASS

Ability scorer does not need to respond to enemy damage type; enemy_damage_type comp_blind=true
is expected. target_resist IS responsive: max_positive_shift=5, Bloodletter's Curse +5 rank,
Void Staff +2, Cryptbloom +2 when facing tanky enemies. outer comp_blind=false confirms
scorer moves on resist dimension. No defect.

## Axis 3 - outcome_ok: FAIL (pool gap)

Scorer top-8 (bal_squishy): Liandry's(1), Wooglet's(2), Blackfire Torch(3), Rabadon's(4),
Shadowflame(5), Void Staff(6), Stormsurge(7), Cryptbloom(8).

Absent from scorer pool entirely (not in top-12 of any cell):
- Lich Bane (3100): empirical ARAM all n=86 wr=50.0%, self n=9 wr=33.3% - highest volume item, above both baselines
- Hextech Rocketbelt (3152): empirical ARAM all n=50 wr=54.0%, self n=6 wr=33.3% - above all-baseline

Rabadon's(rank 4), Stormsurge(rank 7), Shadowflame(rank 5) are present and empirically positive -
core pool is not wrong. But two of the most-bought and above-baseline items are fully absent.

## Axis 4 - rune_ok: N/A

rune_relevant=false.

## Nominated retune

Add Lich Bane and Hextech Rocketbelt to ability scorer item pool for Ekko. Both are on-hit/AP
hybrid items that interact with Ekko's passive; their absence likely reflects a scorer
gap in on-hit+AP interaction scoring rather than a champion-specific override.
Verify ability scorer passive-interaction weighting covers proc-on-ability items.
