# Camille - DS Scorer Cross-Eval Report

VERDICT: MISMATCH
Scorer: hybrid | Evidence tier (ARAM): outcome_all (n=48, baseline wr=56.2%) | rune_relevant: false

---

## Axis 1 - archetype_ok: TRUE

Hybrid scorer = AD axis. Camille is an AD melee diver (bruiser/assassin). All
empirical above-baseline items are AD: Trinity Force (wr 61.5%), Mercury's
Treads (62.1%), Sundered Sky (60.9%), Death's Dance (73.7%), Tunneler (66.7%),
Long Sword (66.7%). Scorer top-8 is all AD/physical. Axis alignment is correct.

Pool gap noted (does not flip to false): Death's Dance (73.7% wr, n=19) and
Sundered Sky (60.9%, n=23) are high-wr empirical staples that are absent or
near-absent from the scorer top-8 across all comp cells. Death's Dance does not
appear in any cell's top-8; Sundered Sky reaches rank 12 only in ap_squishy.
Runaan's Hurricane (scorer rank 7, d_dps=43.7) has no empirical support in
ARAM Camille data.

---

## Axis 2 - comp_ok: FALSE (MISMATCH)

Scorer = hybrid. Primary axis = enemy_damage_type. comp_blind = TRUE.
max_positive_shift (enemy_damage_type) = 1 rank. This is effectively zero
movement.

Camille is listed in the COMP-BLIND EHP/hybrid cohort in PROGRAM.md (along
with Aatrox, Ambessa, Gnar, Kled, LeeSin, MonkeyKing, Riven, Udyr, Yasuo).
Inspecting the comp_grid confirms the defect: the top-8 item list is identical
across ad_squishy, bal_squishy, and ap_squishy cells. d_ehp values shift
slightly (e.g. Iceborn Gauntlet d_ehp: 1469.2 vs 1070.1 vs 595.6 across
ad/bal/ap_squishy) but the ranking does not change because the DPS component
dominates the hybrid score and overwhelms the EHP signal.

A hybrid scorer for a bruiser should move toward MR-bearing items (Sterak's
Gage, Spirit Visage, Maw, or MR boots) when enemy team is AP-heavy. It does
not. comp_blind=TRUE on a hybrid/EHP scorer is the canonical MISMATCH condition
per the program rubric.

---

## Axis 3 - outcome_ok: MINOR

Scorer top-8 (bal_squishy): Void Immolation(1), Trinity Force(2), BotRK(3),
Essence Reaver(4), Heartsteel(5), Dusk and Dawn(6), Runaan's Hurricane(7),
Iceborn Gauntlet(8).

Overlap with empirical above-baseline: Trinity Force is rank 2 (wr 61.5%) -
good. Heartsteel is in scorer rank 5 but empirical wr is 41.7% (n=12) - below
baseline, a losing scorer pick. Runaan's Hurricane is scorer rank 7 with zero
empirical support in Camille data. Void Immolation ranks 1 across all cells
(score 1.92) but has no empirical signal in the dataset.

Missing high-wr staples from scorer top-8: Death's Dance (73.7% wr, n=19) -
absent from every cell's top-8. Sundered Sky (60.9%, n=23) - rank 12 in
ap_squishy only, absent from ad_squishy and bal_squishy top-8.

outcome_ok = MINOR (two high-wr staples missing; one below-baseline item in
scorer pool).

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated retune

comp_blind_fix: Increase enemy_damage_type responsiveness weight for the hybrid
scorer so that AP-heavy comps surface MR-bearing items (Spirit Visage, Maw of
Malmortius, Sterak's Gage) higher. The max_positive_shift=1 is insufficient for
a bruiser that must itemize defensively vs AP-burst. Also audit hybrid score
weight balance to promote Death's Dance and Sundered Sky (both survivability +
damage items that score well empirically) into the top-8 ahead of Runaan's
Hurricane and Essence Reaver, which have no empirical support for Camille.
