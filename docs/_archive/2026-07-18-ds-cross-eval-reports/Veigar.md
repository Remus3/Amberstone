# Veigar DS Cross-Eval Report

**Verdict: MINOR**
Scorer: ability | Archetype: mage/assassin | Evidence: outcome_all (ARAM n=220, wr=50.5%)

---

## Axis 1 - archetype_ok: PASS

Mage with secondary assassin -> ability scorer -> AP axis. Correct. All scorer items are pure
AP (Wooglet's r1, Liandry's r2, Rabadon's r4, Void Staff r5, Shadowflame r6). Empirical
above-baseline items are also all AP: Shadowflame 60.3%, Luden's Echo 52.9%, Rod of Ages 52.7%,
Void Staff 51.7%. Kit confirms: Q stacks grant bonus AP (passive), R is pure AP burst. No axis
mismatch.

---

## Axis 2 - comp_ok: PASS

Scorer=ability, primary_axis=target_resist. target_resist IS responsive: max_positive_shift=3.
Top risers vs tanky enemies: Bloodletter's Curse +3, Void Staff +2, Cryptbloom +2, Liandry's +1.
Top fallers: Shadowflame -2, Stormsurge -2 (correct - flat-pen items lose value vs high-resist
targets).

enemy_damage_type sub-field is comp_blind=true (max_positive_shift=0, no risers). For a
mage/ability scorer this is EXPECTED - Veigar's damage output does not change based on whether
enemies deal AD or AP; you don't swap AP items for AD items. The outer responsiveness.comp_blind
is false because target_resist drives differentiation. No defect.

---

## Axis 3 - outcome_ok: MINOR FLAG

Using ARAM outcome_all (n=220, wr=50.5%).

Empirical above-baseline items (wr > 50.5%, reasonable n):
  - Shadowflame (id 4645): n=68, wr=60.3% -> scorer rank 6 [PRESENT, OK]
  - Luden's Echo (id 6655): n=85, wr=52.9% -> NOT in scorer top-8 [MISSING]
  - Rod of Ages (id 6657): n=110, wr=52.7% -> NOT in scorer top-8 [MISSING]
  - Rabadon's Deathcap (id 3089): n=140, wr=51.4% -> scorer rank 4 [PRESENT, OK]
  - Void Staff (id 3135): n=60, wr=51.7% -> scorer rank 5 [PRESENT, OK]

Scorer top-8 (ad_squishy/bal_squishy identical): Wooglet's r1, Liandry's r2, Blackfire Torch r3,
Rabadon's r4, Void Staff r5, Shadowflame r6, Stormsurge r7, Cryptbloom r8.

Stormsurge (r7) and Cryptbloom (r8) appear in scorer top-8 but are absent from empirical list
entirely. Luden's Echo (n=85, wr=52.9%) and Rod of Ages (n=110, wr=52.7%) are high-frequency
above-baseline staples missing from scorer pool. This is a pool gap: mana-stacking/burst-mana
synergy items (Luden's + RoA into Seraph's chain) are an established Veigar build pattern that
the scorer does not surface.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Add Luden's Echo (id 6655) and Rod of Ages (id 6657) to the ability scorer item pool for Veigar.
Both are above-baseline with high empirical frequency (n=85 52.9%, n=110 52.7%). Stormsurge and
Cryptbloom appear overweighted relative to their empirical presence - secondary review warranted
but not blocking.
