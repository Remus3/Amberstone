# Gnar DS Scorer Cross-Eval Report

VERDICT: MISMATCH - comp_blind EHP defect + Heartsteel r4 empirically losing (36% wr vs 56.5% baseline)

evidence_tier: outcome_all (ARAM n=69, baseline wr=56.5%)
scorer: hybrid
archetype: bruiser (primary) / tank (secondary)

---

## Axis 1: archetype_ok = TRUE

Bruiser maps to AD axis. Kit: melee fighter, auto-attack + Q poke, W rage build-up (tank/bruiser stats), R mega-Gnar AoE CC tank. AD axis is correct.

Empirical above-baseline items (wr > 56.5%):
- Trinity Force n=45 wr=57.8% (above baseline)
- Mercury's Treads n=43 wr=58.1%
- Plated Steelcaps n=24 wr=58.3%
- Black Cleaver n=23 wr=65.2%
- Sterak's Gage n=17 wr=58.8%
- Thornmail n=13 wr=61.5%
- Randuin's Omen n=12 wr=75.0%

All are AD or armor/MR tank items. Scorer axis consistent with kit and empirical winners. archetype_ok = TRUE.

---

## Axis 2: comp_ok = FALSE (MISMATCH)

hybrid scorer: enemy_damage_type axis must move. comp_blind=true. max_positive_shift=2 (near-zero movement across all 5 comp cells).

Gnar is explicitly listed in PROGRAM.md COMP-BLIND EHP/hybrid cohort (n=10 prime defect candidates). The comp grid confirms it: scorer rankings are nearly identical across ad_squishy, bal_squishy, ap_squishy, ad_tanky, ap_tanky. Only cosmetic rank shuffles (<=2 positions) for items like Sundered Sky and Kraken Slayer.

Expected behavior for a hybrid scorer: armor-stack items (Sunfire Aegis, Dead Man's Plate, Iceborn Gauntlet) should rise significantly vs AP-heavy comps and fall vs AD-heavy comps. Instead top_fallers_when_ap includes Dead Man's Plate (shift -8) and Iceborn Gauntlet (shift -5), but these shifts are within the top-40 and the top-8 scorer block is barely rearranged (comp_blind=true in the JSON directly confirms the defect).

Nominated retune target: increase enemy_damage_type weight in hybrid scorer dispatch for Gnar or route to ehp scorer (full EHP scoring responds to damage type by construction).

---

## Axis 3: outcome_ok = FALSE (MISMATCH)

Scorer top-8 (ad_squishy used as primary reference):
r1 Void Immolation (score 1.8388)
r2 BotRK (score 1.21)
r3 Trinity Force (score 1.0758)
r4 Heartsteel (score 0.986)
r5 Essence Reaver (score 0.8957)
r6 Iceborn Gauntlet (score 0.7936)
r7 Runaan's Hurricane (score 0.7746)
r8 Stormrazor (score 0.7563)

Empirical cross-check vs above-baseline items:

LOSING in scorer top-8:
- Heartsteel r4: empirical wr=36.0% (n=25), 20.5pp BELOW baseline. Scorer weights it 4th. This is a clear mismatch - Gnar Heartsteel loses far more than average yet scorer ranks it top-4.

MISSING from scorer top-8 despite high empirical wr:
- Black Cleaver wr=65.2% (n=23, +8.7pp above baseline) - not in scorer top-8 for any comp cell.
- Randuin's Omen wr=75.0% (n=12, +18.5pp above baseline) - not in scorer top-8.
- Sterak's Gage wr=58.8% (n=17) - not in scorer top-8.
- Thornmail wr=61.5% (n=13) - not in scorer top-8.

FALSE POSITIVES in scorer top-8 (not in empirical top items at all):
- Void Immolation r1 - absent from empirical top-10 entirely
- Essence Reaver r5 - absent from empirical top-10
- Runaan's Hurricane r7 - absent
- Stormrazor r8 - absent

Trinity Force appears correctly at r3 scorer / r1 empirical (n=45 wr=57.8%).

---

## Axis 4: rune_ok = N/A

rune_relevant=false (hybrid/bruiser, not burst/assassin).

---

## Nominated Retune

1. comp_blind fix (primary): route Gnar hybrid scorer to use enemy_damage_type weighting correctly so armor/MR EHP items shift with comp. Alternatively reclassify to ehp scorer for true comp responsiveness.
2. Heartsteel penalty: Heartsteel's 36% wr on Gnar suggests the D_EHP contribution (1573 in ad_squishy) is overweighted for this champion. Gnar does not efficiently stack Heartsteel. Consider a Gnar-specific Heartsteel cap or reduce D_EHP weight in bruiser scorer.
3. Pool gap (MINOR within MISMATCH): Black Cleaver (65.2% wr), Randuin's Omen (75.0% wr) should surface in scorer top-8. Currently suppressed.
