# DS Cross-Eval: Zilean

## Verdict: MISMATCH

Archetype enchanter/mage, scorer hps. Empirical ARAM builds winning above baseline
(52.8 wr, n=125 outcome_all) are pure AP damage: Luden's Echo 57.5wr/80n,
Rabadon's Deathcap 61.8wr/34n, Shadowflame 65.5wr/29n, Stormsurge 56.7wr/30n.
hps scorer maps to the wrong primary axis.

---

## Axis 1: archetype_ok - FAIL

hps scorer is enchanter-axis. Zilean's primary archetype is enchanter, but secondary
is mage, and the empirical data is unambiguous: every above-baseline item in ARAM
is AP damage (Luden's, Rabadon's, Shadowflame, Stormsurge). Enchanter scorer
nominates Echoes of Helia (rank 1), Ardent Censer (rank 2), Staff of Flowing Water
(rank 3), Locket (rank 4), Knight's Vow (rank 5) - none appear anywhere in the
empirical top-10. Zilean's kit (time bombs, slow, revive) is not attack-speed-buff
dependent, so Ardent Censer / Echoes proc value is weak. hps fits a heal-heavy
enchanter like Soraka or Sona, not a damage-oriented AP utility mage. Scorer axis
should be mage (AP DPS / ability scorer).

## Axis 2: comp_ok - PASS

Scorer is hps (enchanter). For this archetype, comp invariance is expected behavior:
hps items provide heal/shield utility regardless of enemy damage mix. comp_blind=true
is correct. Both enemy_damage_type and target_resist responsiveness show
max_positive_shift=0 and empty risers - consistent with an enchanter scorer that does
not branch on enemy comp. No defect.

## Axis 3: outcome_ok - FAIL

Top-8 scorer items (identical across all 5 comp cells):
  rank 1: Echoes of Helia 27.1
  rank 2: Ardent Censer 15.7
  rank 3: Staff of Flowing Water 12.6
  rank 4: Locket of the Iron Solari 11.3
  rank 5: Knight's Vow 10.0
  rank 6: Redemption 8.5
  rank 7: Imperial Mandate 7.0
  rank 8: Mikael's Blessing 3.9

Empirical above-baseline items (wr > 52.8 baseline, n=125 ARAM outcome_all):
  Luden's Echo: wr 57.5, n=80
  Rabadon's Deathcap: wr 61.8, n=34
  Stormsurge: wr 56.7, n=30
  Shadowflame: wr 65.5, n=29
  Refillable Potion: wr 61.9, n=21

Zero overlap between scorer top-8 and empirical above-baseline items. Shadowflame
at 65.5wr and Rabadon's at 61.8wr are completely absent from scorer pool. Echoes
of Helia (rank 1 scorer) does not appear in empirical top-10 at all.

## Axis 4: rune_ok - n/a

rune_relevant=false.

---

## Nominated Retune

Rearchetype Zilean from enchanter (primary) to mage (primary), enchanter (secondary).
Switch scorer from hps to mage (AP ability/DPS scorer). This will surface Luden's Echo,
Shadowflame, Rabadon's Deathcap, Stormsurge as high-scoring recommendations, matching
the empirical above-baseline builds. Verify the secondary enchanter weighting does not
pull hps items back into top slots.
