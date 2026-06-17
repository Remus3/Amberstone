# DS Cross-Eval: Braum

VERDICT: MINOR

Scorer: ehp | Archetype: tank/enchanter | Anchor: ARAM | Evidence: outcome_all (n=98, wr=53.1)

---

## Axis 1 - archetype_ok: PASS

Tank primary, enchanter secondary. EHP scorer is neutral-axis (correct for tank).
Braum kit is pure CC/protect with no scaling AD or AP damage output.
No axis mismatch.

---

## Axis 2 - comp_ok: PASS

EHP scorer is NOT comp_blind (enemy_damage_type.comp_blind = false, max_positive_shift = 27).
AD-heavy cell: Randuin's Omen #2 (score 2029), Dead Man's Plate #5 (1658), Iceborn Gauntlet #10 (1453).
AP-heavy cell: Kaenic Rookern rises to #2 (2141), Force of Nature #3 (1666), Spirit Visage #4 (1571),
Abyssal Mask rises +27 ranks.
Target_resist is comp_blind = true with max_positive_shift = 0 - expected for EHP (target resist
affects outgoing DPS, not incoming EHP, so invariance is correct here).
Comp responsiveness is working as intended.

---

## Axis 3 - outcome_ok: FAIL (pool gap + scoring anomaly)

Baseline: ARAM outcome_all, n=98, wr=53.1. Using all empirical items (self n=1 insufficient).

Above-baseline empirical items:
- Mercury's Treads: wr=62.3 (n=53) - absent from scorer pool (boots exclusion, acceptable)
- Giant's Belt: wr=63.2 (n=19) - component item, not a completion candidate, acceptable absence
- Heartsteel: wr=58.9 (n=56) - scorer ranks #6 ad_squishy, #5 bal_squishy - present, OK

Pool gap (in scorer top-8, missing from empirical top-10 OR scoring anomalously):
- Void Immolation: scorer #1 ALL cells, score 4455 vs next item at ~2029 (2.2x gap).
  Zero empirical games in 98-game ARAM sample. Score magnitude looks like a scoring artifact.
  6000g item at #1 by a factor of 2 with no empirical support is a red flag.
- Fimbulwinter (id 3121): empirical n=52 (second-most built item), wr=51.9 (near-baseline).
  Completely absent from scorer pool across all 5 cells. Missing staple.
- Warmog's Armor: scorer #3 ad_squishy (score 1817), but empirical wr=42.9 (n=28), well below
  baseline 53.1. Scorer over-ranks it vs empirical outcomes.
- Thornmail: scorer #9 ad_squishy, empirical wr=44.8 (n=29), below baseline.
- Unending Despair: scorer #4 ad_squishy, empirical wr=50.0, below baseline.

Summary: Void Immolation scoring anomaly (2x gap, zero empirical presence) + Fimbulwinter staple
entirely absent from pool are the primary flags. Warmog/Thornmail/Unending Despair over-ranking
are secondary.

---

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

1. Investigate Void Immolation scoring: 4455 vs 2029 next item suggests a multiplier or passive
   double-count artifact. Reduce or cap if artifact confirmed.
2. Add Fimbulwinter (id 3121) to Braum scorer pool - it is the second-most-built item (n=52)
   and is entirely absent from all 5 comp cells.
