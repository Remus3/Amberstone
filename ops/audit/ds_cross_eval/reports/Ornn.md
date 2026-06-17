# DS Cross-Eval: Ornn

**Verdict: MINOR**

Scorer: ehp | Archetype: tank/bruiser | Anchor: ARAM | Evidence: outcome_all (n=70, wr=51.4%)

---

## Axis 1 - archetype_ok: PASS

Tank (primary) + bruiser (secondary) -> ehp scorer is neutral-axis (correct for tank).
Ornn kit = frontline initiator, no meaningful damage identity. Axis match confirmed.

---

## Axis 2 - comp_ok: PASS

EHP scorer must respond to enemy damage type. responsiveness.comp_blind = false.
max_positive_shift = 27 ranks (Abyssal Mask +27 when enemy AP).

Top risers vs AP comp: Abyssal Mask+27, Hollow Radiance+24, Spirit Visage+22,
Kaenic Rookern+22, Force of Nature+22.
Top fallers vs AP: Iceborn Gauntlet -27, Dead Man's Plate -26, Sunfire Aegis -24.

Strong bidirectional responsiveness. EHP scorer pivoting AD<->AP resists correctly.
target_resist comp_blind=true but expected: tank resist items do not depend on what enemies build.

---

## Axis 3 - outcome_ok: PASS (minor gap)

Using outcome_all ARAM (n=70 >= 8). Baseline wr = 51.4%.
Scorer top-8 reference cell: ad_squishy (standard squishy lane).

Top-8 scorer vs empirical above-baseline items:

| Item           | Scorer rank (ad_sq) | Empirical wr | n  | Status         |
|----------------|--------------------:|-------------:|---:|----------------|
| Heartsteel     | 6                   | 56.5%        | 46 | MATCH          |
| Warmog's Armor | 3                   | 58.8%        | 34 | MATCH          |
| Unending Despair| 4                  | 57.7%        | 26 | MATCH          |
| Jak'Sho        | 7                   | 66.7%        | 18 | MATCH          |
| Thornmail      | 9                   | 61.1%        | 18 | NEAR-MISS (r9) |
| Mercury's Treads| not in scorer      | 55.6%        | 45 | BOOTS - structural exclusion, expected |
| Fimbulwinter   | not in scorer       | 50.0%        | 22 | at baseline, not above |

4/4 high-wr non-boot empirical staples land in scorer top-8.
Thornmail (wr 61.1%, n=18) sits at rank 9 in ad_squishy - just outside the top-8 window.
Mercury's Treads (wr 55.6%, n=45) is absent from scorer cells; expected structural exclusion (boots).

Minor gap: Thornmail one rank outside top-8 in AD-heavy comps.

---

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

Shift Thornmail from rank 9 to top-8 in AD-heavy comps (wr 61.1%, n=18 empirically).
Low urgency - one rank gap, not a misalignment.

---

## Summary

Ornn ehp scorer is well-calibrated. Archetype axis correct, comp responsiveness strong (27-rank
swing on damage type), and 4 of 4 high-wr empirical staples land in scorer top-8. Only issue is
Thornmail sitting at rank 9 (one outside the window) despite 61.1% empirical wr. Severity: MINOR.
