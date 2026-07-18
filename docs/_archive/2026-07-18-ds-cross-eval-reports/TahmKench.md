# DS Cross-Eval Report: TahmKench

Verdict: MINOR
Scorer: ehp | Archetype: tank/enchanter | Anchor: ARAM
Evidence tier (ARAM): outcome_all (n=99, baseline wr=55.6%)

---

## Axis 1 - archetype_ok: PASS

Tank primary with ehp scorer = neutral axis, correct. Kit is front-line tank/support with no AD/AP skew.
Empirical top items confirm pure tank build: Warmog's Armor (65.4% wr), Plated Steelcaps (70.0%),
Fimbulwinter (62.5%), Thornmail (57.6%), Spirit Visage (58.6%) - no AP or AD damage items.
EHP scorer matches the win condition.

---

## Axis 2 - comp_ok: PASS

Scorer: ehp. comp_blind=false. enemy_damage_type responsive (max_positive_shift=27 ranks).
The ranking shifts across comp cells confirm the scorer responds to damage type:
- vs AD comps: Randuin's Omen rank 2 (score 1893), Iceborn Gauntlet rank 10; armor items dominate.
- vs AP comps: Kaenic Rookern rank 2 (score 1995), Force of Nature rank 3, Spirit Visage rank 5;
  Abyssal Mask enters top 9 (shift +27), Hollow Radiance rank 8.
- Iceborn Gauntlet falls -27 ranks vs AP, Dead Man's Plate falls -24, Randuin's falls -21.
All d_ehp values in the export are 0.0 (delta field appears uncomputed vs a stored baseline),
but the rank-ordering behavior is comp-responsive and correct. No comp-blind defect.
target_resist is comp_blind=true with max_positive_shift=0 - expected for an ehp scorer that does
not compute damage dealt; tank does not need target_resist responsiveness.

---

## Axis 3 - outcome_ok: PASS (minor pool gap)

Scorer top-8 reference comp: ad_squishy (most common threat pattern).
Scorer top-8 ad_squishy: Void Immolation, Randuin's Omen, Warmog's Armor, Unending Despair,
Heartsteel, Dead Man's Plate, Jak'Sho, Sunfire Aegis.

Empirical items above baseline wr (>55.6%):
- Warmog's Armor: 65.4% wr, rank 3 scorer - ALIGNED
- Plated Steelcaps: 70.0% wr, n=20 - absent from scorer (boots excluded from scorer pool, expected)
- Fimbulwinter: 62.5% wr, n=16 - ABSENT from all scorer cells (pool gap)
- Thornmail: 57.6% wr, rank 9 ad_squishy - present, borderline
- Spirit Visage: 58.6% wr, rank 8 bal_squishy / rank 5 ap_squishy - present

Heartsteel (rank 5 scorer, 53.7% empirical wr) is slightly below baseline - not a losing top build
since the gap is small and n=82 may include non-optimal builds.
Fimbulwinter missing from scorer pool is the main gap: 62.5% wr at n=16 suggests real win-rate
signal; its absence means TK players who build it get no scorer recommendation for it.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated retune

Add Fimbulwinter to the TahmKench item pool (or confirm it is blocked by a filter).
62.5% wr at n=16 in ARAM is above baseline and warrants scorer visibility.
No axis or comp-responsiveness change needed.
