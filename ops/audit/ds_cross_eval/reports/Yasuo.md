# Yasuo DS Scorer Cross-Eval

VERDICT: MISMATCH

scorer=hybrid anchor=ARAM evidence_tier=outcome_self (n=12)
baseline_wr=33.3% (self ARAM) / 42.0% (all ARAM) / 56.2% (all SR)

---

## Axis 1: archetype_ok - MINOR concern

Scorer=hybrid (AD axis). Yasuo is crit-scaler melee; AD axis correct.
Hybrid scorer ranks BotRK #2 (good, wr=50.0% n=6) and Trinity Force #3.
BUT Infinity Edge (SR wr=71.4% n=14, strongest SR signal) does not appear
in ad_squishy or bal_squishy top-12. It surfaces only at ap_squishy rank 12.
Immortal Shieldbow (ARAM wr=42.9% n=7, above baseline) absent from all
top-12 scorer cells. Heartsteel #4 has no empirical above-baseline support.
Crit items (IE, ISB) underweighted relative to empirical outcomes.

archetype_ok=true (axis correct) with MINOR pool gap flag.

---

## Axis 2: comp_ok - MISMATCH (DEFECT)

Scorer=hybrid, primary_axis=enemy_damage_type, comp_blind=TRUE.
Per rubric: EHP/hybrid scorer with comp_blind=True is a defect candidate.

Evidence from cells:
- ad_squishy rank 1: Void Immolation score=1.8002
- ap_tanky rank 1: Void Immolation score=2.6122
- ap_squishy rank 1: Void Immolation score=1.7805

Same item tops all 5 cells. Max positive shift on enemy damage type = only 2 ranks.
Top risers when AP: Voltaic Cyclosword +2, Sundered Sky +2, IE +2 - trivial movement.
The hybrid scorer does not differentiate item recommendations by enemy damage type
for Yasuo. A Yasuo player should build differently vs full-AP vs full-AD but scorer
outputs near-identical pools.

comp_ok=false (comp_blind EHP/hybrid defect confirmed).

---

## Axis 3: outcome_ok - MINOR

Evidence tier: outcome_self (ARAM self n=12, baseline_wr=33.3%).
Above-baseline empirical (self ARAM): BotRK 50.0% (n=6), ISB 42.9% (n=7).

Scorer ad_squishy top-8: Void Immolation, BotRK, Trinity Force, Heartsteel,
Essence Reaver, Runaan's Hurricane, Stormrazor, Iceborn Gauntlet.

BotRK at rank 2 - aligned. But:
- Immortal Shieldbow (wr=42.9%, above baseline) absent from all scorer top-12 cells.
- IE (SR wr=71.4% n=14, top signal) absent from ad_squishy/bal_squishy top-12.
- Heartsteel rank 4 (d_ehp=1579, low d_dps=41) has zero empirical above-baseline.
- Essence Reaver rank 5 not in empirical above-baseline pool.

High-wr crit staples (ISB, IE) missing from scorer pool = MINOR pool gap.

outcome_ok=false (MINOR: ISB absent, IE buried, Heartsteel overweighted).

---

## Axis 4: rune_ok - n/a

rune_relevant=false. Yasuo is not burst/assassin scorer. No rune wiring assessed.

---

## Nominated retune

1. Investigate hybrid scorer EHP branch: enemy damage type should shift
   Yasuo item recommendations more than 2 ranks. The comp_blind=True flag
   means the scorer's EHP arm does not react to damage type input for this
   champion - check hybrid weight split and whether the dps arm dominates
   completely, leaving the EHP branch inert.
2. Add Immortal Shieldbow to Yasuo scorer pool (absent from all top-12 cells
   despite being an above-baseline empirical winner with n=7).
3. Audit why Infinity Edge ranks only at ap_squishy rank 12 and not in
   ad_squishy/bal_squishy - crit-synergy weight may be calibrated too low
   for the hybrid scorer on crit-scaling champions.
