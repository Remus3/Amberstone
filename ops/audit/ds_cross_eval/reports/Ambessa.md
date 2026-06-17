# Ambessa DS Scorer Cross-Eval Report

VERDICT: MISMATCH

Scorer: hybrid | Archetype: bruiser/assassin | Anchor: ARAM outcome_self (n=9, wr=33.3%) | SR: outcome_all (n=48, wr=39.6%)

---

## Axis 1 - archetype_ok: TRUE

Hybrid scorer maps to AD axis. Ambessa is an AD melee bruiser/assassin. Empirical
confirms: ARAM all top items by wr are Black Cleaver (n=14, wr=71.4%), Sundered Sky
(n=16, wr=68.8%), Sterak's Gage (n=12, wr=50.0%) - all AD/physical. SR all: Eclipse
(n=26, wr=50.0%), Spear of Shojin (n=26, wr=50.0%), Doran's Blade (n=12, wr=66.7%).
AD axis is correct for the kit and for what wins empirically. No flag.

---

## Axis 2 - comp_ok: FALSE (DEFECT - MISMATCH)

Hybrid scorer primary_axis=enemy_damage_type -> MUST move with enemy composition.
responsiveness.comp_blind=TRUE. enemy_damage_type.max_positive_shift=1 (trivial).
Top risers when AP shift by only 1 rank: Umbral Glaive +1, The Collector +1, Terminus +1,
Sterak's Gage +1, Statikk Shiv +1. This is effectively zero movement.

Void Immolation holds rank 1 across ALL five comp cells (ad_squishy score=1.272,
ap_squishy score=1.263, ad_tanky score=1.724[BotRK displaces to rank 2 on tanky]).
BotRK holds rank 1-2 across all cells. The scorer does not distinguish AD-heavy vs
AP-heavy enemy comps for Ambessa. The hybrid EHP sub-component should weight armor
vs MR differentially based on enemy damage split, but it does not do so here.

This is the prime COMP-BLIND EHP/hybrid DEFECT identified in the pre-seeded cohort.

---

## Axis 3 - outcome_ok: FALSE (MINOR - missing high-wr staples)

Evidence tier: outcome_self (ARAM self n=9, wr=33.3% baseline). Self items:
Eclipse n=8 wr=25.0% (below baseline), Mercury's Treads n=5 wr=20.0% (below baseline).
No self items beat baseline; pool too sparse to flag scorer losses directly.

Falling back to ARAM all (n=73, wr=46.6% baseline) for staple check:
- Black Cleaver (n=14, wr=71.4%): NOT in any scorer top-12 cell. High-wr staple absent.
- Sundered Sky (n=16, wr=68.8%): NOT in any scorer top-12 cell. High-wr staple absent.
- Sterak's Gage (n=12, wr=50.0%): NOT in scorer top-12 (Heartsteel at rank 7 instead).

Scorer top-8 ad_squishy includes Runaan's Hurricane (rank 3, d_dps=76.0) and
Essence Reaver (rank 5, d_dps=69.5) - these do not appear in empirical high-wr items.
Infinity Edge rank 8 (d_dps=64.9) also absent from empirical top items.

The scorer overweights marksman-style carry items (Runaan's, Essence Reaver, IE) that
Ambessa does not build or win with empirically, while underweighting bruiser staples
Sundered Sky, Black Cleaver, and Sterak's Gage.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false. Ambessa is not a burst/assassin primary scorer path. No rune
surface in DS scorer.

---

## Nominated Retune

1. PRIMARY - comp sensitivity: enable enemy_damage_type shift weight in hybrid scorer
   for bruiser archetype. Ambessa needs armor vs MR split to respond to AP-heavy vs
   AD-heavy enemy comps. The EHP sub-component should shift item rankings by ~5-8
   ranks when enemy damage type flips (per the target_resist axis which does move:
   Lord Dominik's +11, Mortal Reminder +9, Black Cleaver +9 when vs tanky).

2. SECONDARY - pool calibration: Black Cleaver (71.4% wr) and Sundered Sky (68.8% wr)
   are empirically dominant but absent from scorer top-12. Sterak's Gage (50.0% wr)
   should displace Heartsteel (rank 7) or at minimum rank higher. Investigate whether
   Ambessa's bruiser scorer weights are over-indexing the carry/DPS sub-score vs
   the hybrid EHP sub-score that would surface tank-buster and defensive items.
