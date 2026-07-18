# Rammus DS Scorer Cross-Eval

**Verdict: MINOR**
Scorer (ehp, tank/neutral axis) is correctly assigned and comp-responsive. Minor pool calibration: Jak'Sho over-ranked vs empirics in balanced comps; Unending Despair under-ranked relative to its 84.6% wr.

---

## 1. Archetype OK: true

Tank (primary) / bruiser (secondary). EHP scorer is the correct neutral-axis scorer for a pure tank. Rammus kit is fully tank-oriented (Spiked Shell passive scales off armor, Defensive Ball Curl armor steroid, Frenzying Taunt). Empirical top items confirm tank itemization: Thornmail (62.5% wr, n=32), Unending Despair (84.6%, n=13), Sunfire Aegis (66.7%, n=12), Warmog's Armor (60.0%, n=10). No axis mismatch.

---

## 2. Comp OK: true

EHP scorer, primary_axis=enemy_damage_type, comp_blind=false. Scorer responds correctly to enemy damage type:
- Top risers when AP: Abyssal Mask (+27 ranks), Kaenic Rookern (+22), Force of Nature (+22), Spirit Visage (+21)
- Top fallers when AP: Iceborn Gauntlet (-28), Dead Man's Plate (-26), Sunfire Aegis (-24), Randuin's Omen (-21)
- max_positive_shift=27 is meaningful responsiveness.

target_resist is comp_blind=true (max_positive_shift=0) - expected for EHP scorer, which measures own survivability not enemy mitigation. Not a defect.

---

## 3. Outcome OK: true (with minor gap)

Using outcome_all (n=36, baseline wr=58.3%) per evidence_tier_ARAM=outcome_all.

Above-baseline empirical items and scorer coverage:
- Thornmail 62.5% (n=32): rank 9 ad_squishy, rank 9 ad_tanky - present in pool, rank is low given high freq+wr
- Mercury's Treads 63.2% (n=19): absent from scorer top-8 - boots structural exclusion, acceptable
- Unending Despair 84.6% (n=13): rank 4 ad_squishy, rank 8 bal_squishy - present but under-ranked in bal_squishy vs its wr
- Sunfire Aegis 66.7% (n=12): rank 8 ad_squishy - present
- Warmog's Armor 60.0% (n=10): rank 3 ad_squishy, rank 2 bal_squishy - well-ranked
- Randuin's Omen 60.0% (n=5): rank 2 ad_squishy - well-ranked

Jak'Sho (rank 4 bal_squishy, rank 7 ad_squishy) has empirical wr 50.0% (below baseline 58.3%, n=14). It is over-ranked relative to Unending Despair (84.6%, rank 8 bal_squishy). This is a calibration gap, not a structural mismatch.

No high-wr staple is fully absent from the scorer pool.

---

## 4. Rune OK: n/a

rune_relevant=false.

---

## Nominated Retune

Down-weight Jak'Sho in balanced/mixed comps (emp wr 50.0% at rank 4 bal_squishy vs baseline 58.3%); up-weight Unending Despair in balanced comps (emp wr 84.6% at rank 8 bal_squishy). Consider also raising Thornmail rank in ad_squishy given highest empirical frequency (n=32, 62.5% wr) vs its rank 9 position.
