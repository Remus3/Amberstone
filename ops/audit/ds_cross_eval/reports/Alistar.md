# DS Cross-Eval: Alistar

**Verdict: MINOR**
Scorer axis and comp responsiveness are correct. Two high-value empirical staples
(Fimbulwinter, Guardian's Horn) are absent from the scorer pool; two scorer top-8
items (Heartsteel, Thornmail) win below the baseline wr.

---

## 1. Archetype OK: true

- archetype=tank (primary), enchanter (secondary); scorer=ehp.
- Tank -> EHP is the correct neutral axis. Alistar is a CC/peel tank support; he
  itemizes for raw tankiness, not damage or healing output.
- Empirical above-baseline items (baseline wr=55.3, outcome_all n=103):
  - Guardian's Horn (wr=68.0, n=25) - highest wr, pure tank sustain
  - Warmog's Armor (wr=57.1, n=28) - HP stacking, classic tank
  Both are fully consistent with an EHP scorer. No carry or AP items appear in the
  above-baseline set. Archetype is aligned.

---

## 2. Comp OK: true

- EHP scorer must respond to enemy_damage_type. comp_blind=false. It does respond:
  - max_positive_shift=29 (Abyssal Mask rises 29 rank positions when enemy is AP)
  - Top risers when AP: Abyssal Mask (+29), Spirit Visage (+23), Force of Nature (+23),
    Hollow Radiance (+22), Kaenic Rookern (+21) - all MR items, correct.
  - Top fallers when AP: Dead Man's Plate (-27), Iceborn Gauntlet (-27),
    Randuin's Omen (-24), Sunfire Aegis (-24) - all armor items, correct.
- target_resist is comp_blind=true with shift=0. This is expected: EHP scorer models
  incoming damage absorbed, not outgoing damage dealt. Alistar does not itemize
  penetration; zero target-resist responsiveness is correct behavior for this scorer.
- Overall: comp responsiveness is healthy and directionally correct.

---

## 3. Outcome OK: false (MINOR pool gaps)

Using outcome_all (n=103 >= 8). Baseline wr=55.3.
Empirical items above baseline: Warmog's Armor (57.1), Guardian's Horn (68.0).

Scorer top-8 ad_squishy:
  #1 Void Immolation, #2 Randuin's Omen, #3 Warmog's Armor, #4 Unending Despair,
  #5 Dead Man's Plate, #6 Heartsteel, #7 Jak'Sho, #8 Thornmail

Scorer top-8 bal_squishy:
  #1 Void Immolation, #2 Warmog's Armor, #3 Jak'Sho, #4 Kaenic Rookern,
  #5 Heartsteel, #6 Randuin's Omen, #7 Force of Nature, #8 Spirit Visage

Gaps and misalignments:
- Fimbulwinter (id=3121): most-built empirical item (n=64, wr=53.1 - near baseline).
  Absent from all 5 scorer cells across all 12 ranks. Not a top-winner but the
  highest-frequency build; its complete absence from the scorer pool is a gap.
- Guardian's Horn (id=2051): highest empirical wr (68.0, n=25). Absent from all
  scorer cells. The scorer is not surfacing the item with the strongest win signal.
- Heartsteel (#6 ad_squishy, #5 bal_squishy): empirical wr=49.1, below baseline.
  Scorer promotes it into top-6/5; it does not win above rate.
- Thornmail (#8 ad_squishy): empirical wr=45.2, below baseline. Scorer includes it
  in top-8 vs AD comps; it does not win above rate for Alistar.

These are pool composition issues (missing staples, two below-baseline items promoted)
rather than a wrong-axis or catastrophic mismatch.

---

## 4. Rune OK: n/a

rune_relevant=false.

---

## Nominated Retune

Add Fimbulwinter (id=3121) and Guardian's Horn (id=2051) to the Alistar EHP item pool
so the scorer can evaluate them. Investigate why Heartsteel and Thornmail score in the
top-8 for Alistar despite below-baseline empirical wr - likely a pure-stat EHP
over-estimation vs Alistar's actual usage pattern (support, not frontline).
