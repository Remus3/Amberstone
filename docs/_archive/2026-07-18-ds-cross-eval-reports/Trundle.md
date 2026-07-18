# DS Cross-Eval Report: Trundle

**Verdict: MINOR**
Archetype and comp responsiveness are correctly calibrated. Pool is contaminated by ADC crit items ranking inside the scorer top-8 with zero empirical presence on Trundle.

---

## Axis 1 - archetype_ok: TRUE

Archetype bruiser/tank uses the hybrid scorer (AD-oriented: dps + ehp blend). This is correct for Trundle's kit - he is a melee auto-attacker who scales off AD and converts resists via Subjugate. The hybrid scorer's AD bias is appropriate.

Empirical validation (ARAM outcome_all, n=64, baseline wr=51.6%):
- Trinity Force n=22 wr=59.1% -> scorer rank 3 (ad_squishy). Aligned.
- Heartsteel n=18 wr=55.6% -> scorer rank 6. Aligned.
- BoRK n=26 wr=53.8% -> scorer rank 2. Aligned.

All three above-baseline staples land in scorer top-8. No wrong-axis issue.

---

## Axis 2 - comp_ok: TRUE

Scorer=hybrid. Primary axis is enemy_damage_type, comp_blind=false.

EHP shifts across comp cells as expected:
- Void Immolation d_ehp: 4230.9 (ad_squishy) -> 3595.8 (ap_squishy), delta -635.
- Iceborn Gauntlet d_ehp: 1382.9 (ad_squishy) -> 545.2 (ap_squishy), delta -837.
- Dead Man's Plate falls -6 ranks when enemy is AP (correct: armor EHP less valuable vs AP).
- Wit's End rises +5 ranks when enemy is AP (correct: MR bonus).

target_resist max_positive_shift=15 (Liandry's +15 vs tanky). DPS axis responds to target armor.

No comp-blind defect. Responsiveness is working.

---

## Axis 3 - outcome_ok: FALSE

ARAM self n=6 < 8, using outcome_all (n=64, baseline wr=51.6%).

Scorer top-8 (ad_squishy cell):
1. Void Immolation (score 1.763, d_ehp 4230, d_dps 62.8)
2. Blade of The Ruined King (score 1.317, wr empirical 53.8%) - ABOVE BASELINE
3. Trinity Force (score 1.295, wr empirical 59.1%) - ABOVE BASELINE
4. Essence Reaver (score 1.051, d_ehp 0) - NOT in empirical data
5. Runaan's Hurricane (score 1.049, d_ehp 0) - NOT in empirical data
6. Heartsteel (score 1.015, wr empirical 55.6%) - ABOVE BASELINE
7. Dusk and Dawn (score 0.905) - not in empirical top-10
8. Stormrazor (score 0.861, d_ehp 0) - NOT in empirical data

Problem: Essence Reaver (#4), Runaan's Hurricane (#5), and Stormrazor (#8) are pure ADC crit items. All three have d_ehp=0 (no tank contribution). None appear in the 64-game empirical sample at all. They rank ahead of or alongside Heartsteel, which actually wins at 55.6% wr.

Iceborn Gauntlet ranks #9 but empirical wr=33.3% (n=9) - a losing item in practice. Scorer over-ranks it slightly but it is not inside top-8.

The bruiser DPS weight is pulling in ADC items that Trundle never successfully builds. Pool contamination. outcome_ok=false.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

bruiser-hybrid DPS gate: require d_ehp > 0 OR explicit bruiser-archetype whitelist to qualify for top-8 in the hybrid scorer. Items with d_ehp=0 in the hybrid scorer should require a minimum empirical n floor before ranking above core bruiser items. Specifically flag Essence Reaver, Runaan's Hurricane, and Stormrazor as low-plausibility entries on Trundle and downweight their DPS contribution in the hybrid score.
