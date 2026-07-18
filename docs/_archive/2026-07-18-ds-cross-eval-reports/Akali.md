# DS Cross-Eval: Akali

VERDICT: MINOR

scorer=ability  archetype=mage/assassin  anchor=ARAM  evidence=outcome_all(n=118,wr=36.4%)

---

## Axis 1 - archetype_ok: PASS

ability scorer -> AP axis. Akali kit is AP ability-based. Empirical winners
Shadowflame (wr=43.1%), Rabadon's Deathcap (wr=44.4%), Riftmaker (wr=40.0%)
are all AP items. Scorer and kit align.

---

## Axis 2 - comp_ok: PASS

ability scorer primary_axis=target_resist. target_resist.comp_blind=false,
max_positive_shift=3. Cryptbloom shifts +3, Bloodletter's Curse shifts +3 vs
AP-tanky comps. Responsive as expected for ability scorer.

enemy_damage_type.comp_blind=true with max_positive_shift=0: enemy damage type
does not move item rankings. This is EXPECTED for ability scorers whose value
driver is target resistances not incoming damage type. Not a defect.

---

## Axis 3 - outcome_ok: FAIL (MINOR)

Baseline ARAM wr = 36.4% (outcome_all, n=118).
Items above baseline: Shadowflame 43.1%(n=58), Rabadon's 44.4%(n=27),
Heartsteel 40.6%(n=32), Riftmaker 40.0%(n=35), Sorcerer's Shoes 37.0%(n=73).

Scorer top-8 overlap vs empirical above-baseline:
  rank 1  Liandry's Torment    - NOT in empirical top-10; unvalidated at top spot
  rank 2  Wooglet's Witchcap   - NOT in empirical list
  rank 3  Blackfire Torch      - NOT in empirical list
  rank 4  Void Staff           - NOT in empirical list
  rank 5  Rabadon's Deathcap   - wr=44.4% ABOVE baseline - OVERLAP
  rank 6  Shadowflame          - wr=43.1% ABOVE baseline - OVERLAP
  rank 7  Stormsurge           - wr=30.8% BELOW baseline 36.4% - LOSING
  rank 8  Cryptbloom           - NOT in empirical list

Gaps:
- Stormsurge rank 7 is empirically losing (30.8% vs 36.4% baseline).
- Heartsteel (n=32, wr=40.6%) is entirely absent from scorer pool.
  Heartsteel win rate suggests Akali benefits from tankier hybrid builds not
  captured by the ability scorer pool.
- Liandry's rank 1 is unvalidated vs empirical; Rabadon's (rank 5) and
  Shadowflame (rank 6) are the only validated above-baseline overlaps in top-8.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Penalize Stormsurge in ability scorer pool for Akali: empirically 30.8% wr
(below 36.4% baseline, n=39). Consider adding Heartsteel as a valid pool
candidate to capture the tankier hybrid win condition. Investigate why
Liandry's scores rank 1 but does not appear in empirical top-10.
