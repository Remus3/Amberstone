# Kled DS scorer cross-eval report

VERDICT: MISMATCH
scorer=hybrid archetype=bruiser/tank evidence=outcome_all(ARAM n=25 wr=40.0%)

## Axis 1 - archetype_ok: PASS

hybrid scorer is AD-weighted, correct for Kled (melee AD fighter, no AP scaling).
Empirical above-baseline builds (>40.0% baseline): Heartsteel 44.4%(n=9),
Sterak's Gage 44.4%(n=9), Plated Steelcaps 42.9%(n=7). All AD/tank items.
No AP builds winning above baseline. Axis alignment is correct.

## Axis 2 - comp_ok: FAIL (DEFECT)

scorer=hybrid; primary_axis=enemy_damage_type; comp_blind=true.
enemy_damage_type.max_positive_shift=0, top_risers_when_ap=[].
A hybrid EHP scorer MUST shift item rankings when the enemy team is heavy AP
(magic-resist items should rise). Zero positive shift means the scorer is
completely blind to enemy damage type despite claiming it as primary_axis.
top_fallers_when_ap are only -1 shift items (Atma's Reckoning, Dusk and Dawn,
Overlord's Bloodmail, Sterak's Gage, Stormrazor) - trivial movement.
Per program rubric: comp_blind=true on an EHP/hybrid scorer = DEFECT -> MISMATCH.

target_resist axis does move correctly (max_positive_shift=13, Lord Dominik's
Regards +13, Mortal Reminder +11 when vs tanky) - DPS subcomponent is responsive.

## Axis 3 - outcome_ok: MINOR

Empirical above-baseline items (ARAM, outcome_all):
- Heartsteel 44.4% (n=9): scorer rank 9 in ad_squishy/bal_squishy - present but
  below top-8 cutoff. Minor gap.
- Sterak's Gage 44.4% (n=9): NOT present in scorer top-12 in any comp cell.
  A bruiser staple with proven above-baseline wr is missing from the ranked pool.
  Pool gap flagged.
- Plated Steelcaps 42.9% (n=7): boots not expected in scorer pool (items pool
  typically excludes boots by design), tolerated.

Scorer top-8 (ad_squishy): Void Immolation(1,score=1.17), BotRK(2,1.08),
Runaan's Hurricane(3,0.73), Kraken Slayer(4,0.62), Immortal Shieldbow(5,0.61),
Trinity Force(6,0.61), Hullbreaker(7,0.59), IE(8,0.59). These are ADC-crit/on-hit
items. Empirically the Kled population in rewind_history.db leans bruiser
(Heartsteel, Sterak's, Titanic Hydra 40.0% n=15, Black Cleaver 40.0% n=5).
Titanic Hydra is also absent from scorer top-12.

Outcome partial gap - bruiser-tank staples (Sterak's, Titanic Hydra) not surfaced
while ADC items dominate top-8. Not losing (no above-baseline item at rank 1-8
that loses empirically), but missing staples -> MINOR flag on top of comp MISMATCH.

## Axis 4 - rune_ok: N/A

rune_relevant=false (hybrid/bruiser, not burst/assassin).

## Nominated retune

1. (Primary, Tier-2) Fix hybrid scorer enemy_damage_type responsiveness: EHP
   sub-weight must shift when enemy_ap_share increases. Current comp_blind=true
   on primary_axis is the core defect shared with the COMP-BLIND EHP/hybrid
   cohort (Aatrox, Ambessa, Camille, Gnar, LeeSin, MonkeyKing, Riven, Udyr,
   Yasuo per PROGRAM.md pre-seeded list).
2. (Secondary, Tier-1) Pool gap: add Sterak's Gage and Titanic Hydra to hybrid
   scorer item consideration if currently excluded; both appear above-baseline
   in Kled ARAM data.
