# DS Cross-Eval: Singed

## Verdict: MINOR

Scorer: ehp | Archetype: tank/mage | Evidence: outcome_all (ARAM n=76, baseline wr=48.7%)

---

## Axis 1 - Archetype OK: PASS

primary=tank, scorer=ehp. Tank is a neutral axis (neither AD nor AP). Singed is a
HP/MR/armor stacking champion with magic-damage poison. EHP scorer is the correct
scorer class for a tank primary. Secondary mage is noted but does not invalidate
the primary scorer choice.

---

## Axis 2 - Comp OK: PASS

comp_blind=false. enemy_damage_type: max_positive_shift=27 (Abyssal Mask +27,
Kaenic Rookern +22, Force of Nature +22, Spirit Visage +21 rise vs AP; Iceborn
Gauntlet -28, Randuin's -25, Dead Man's Plate -24 fall vs AP). Clear rank
reordering across damage-type axis. EHP scorer is doing what it should - shifting
armor items down and MR items up when enemies are AP-heavy.

target_resist comp_blind=true is expected for an EHP scorer (target_resist drives
dps/burst scorers, not survival).

---

## Axis 3 - Outcome OK: FAIL (pool gap)

Evidence base: outcome_all (self n=0). Baseline wr=48.7%.

Above-baseline items (wr > 48.7%):
  - Negatron Cloak   wr=80.0%  n=10  (component - expected exclusion)
  - Dead Man's Plate wr=63.2%  n=19  scorer rank 5 (ad_squishy) - PRESENT, good
  - Winged Moonplate wr=57.1%  n=14  NOT in any scorer cell
  - Rod of Ages      wr=53.8%  n=52  NOT in any scorer cell
  - Boots of Swiftness wr=53.7% n=41 NOT in scorer (boots typically excluded - ok)
  - Liandry's Torment wr=50.0% n=42  NOT in any scorer cell
  - Rylai's Crystal Scepter wr=50.0% n=56  NOT in any scorer cell

The three highest-n items in the empirical dataset are Rylai's (n=56), Rod of Ages
(n=52), and Liandry's (n=42). All are AP mage items. None appear in any scorer
cell. Players are building Singed as AP hybrid, and the scorer pool contains zero
AP items. Rod of Ages (wr=53.8%) is the clearest miss: high n, above baseline,
not in scorer.

Dead Man's Plate is the only scorer top-8 item confirmed above baseline.

The pool is defensible for a pure-tank path, but misses the empirically dominant
AP hybrid path. This is a pool gap, not a wrong-axis call.

---

## Axis 4 - Rune OK: N/A

rune_relevant=false.

---

## Nominated Retune

Add Rylai's Crystal Scepter, Rod of Ages, and Liandry's Torment to the EHP
scorer candidate pool for Singed. These carry AP+HP stats that contribute to
both EHP (HP component) and damage, and are the most-played above-baseline items.
Alternatively, enable the mage secondary scorer to run alongside EHP and take the
union for recommendation. The current pool gap means Singed's most common winning
build path is invisible to the scorer.
