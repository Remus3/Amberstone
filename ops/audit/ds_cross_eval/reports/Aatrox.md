# Aatrox DS Scorer Cross-Eval Report

verdict: MISMATCH

scorer: hybrid | archetype: bruiser/tank | anchor: ARAM outcome_all (n=137, wr=45.3)

---

## Axis 1 - archetype_ok: PASS

Hybrid scorer = AD axis. Aatrox is AD melee fighter. Empirical above-baseline
winners (Eclipse wr 54.0, Death's Dance wr 52.8, Sundered Sky wr 51.1, Black
Cleaver SR wr 62.5) are all AD fighter items. No AP-axis conflict. axis=AD is
correct for the kit and for what wins.

## Axis 2 - comp_ok: FAIL (MISMATCH)

Hybrid scorer tests enemy_damage_type responsiveness. comp_blind=true with
max_positive_shift=1 (near-zero). The top-risers when enemy comp is AP are only
rank-1 shifts on Yun Tal, Voltaic, Sundered Sky, Stormrazor, Runaan's. No MR
items surface. The scorer does not materially differentiate its recommendation
between an AD-heavy vs AP-heavy enemy team, which is the primary_axis. This is
the PROGRAM.md explicit DEFECT: a hybrid EHP scorer with comp_blind=true is a
real defect, not a calibration note.

target_resist does move (max_positive_shift=13, Liandry's +13, Mortal Reminder
+9, Lord Dominik's +9), so the DPS branch responds correctly to tanky targets.
The EHP branch is the blind side.

## Axis 3 - outcome_ok: FAIL

Scorer top-8 (bal_squishy context, most representative):
  r1 Void Immolation, r2 Trinity Force, r3 BotRK, r4 Heartsteel,
  r5 Essence Reaver, r6 Dusk and Dawn, r7 Runaan's Hurricane, r8 Iceborn Gauntlet

Empirical items ABOVE baseline wr=45.3 (ARAM):
  Eclipse           r--- squishy cells (absent top-12), wr 54.0 n=50  MISS
  Death's Dance     absent from all top-12 cells entirely, wr 52.8 n=53  MISS
  Sundered Sky      r11 bal_squishy, r11 ad_squishy, wr 51.1 n=94  MISS top-8
  Ruby Crystal      trivial component n=27 wr 55.6 - skip (not a finished item)

Death's Dance is a core Aatrox staple (n=53 ARAM, wr 52.8 > 45.3; n=absent SR
top-10 but likely too few) and is completely absent from the scorer pool across
all 5 comp cells. Sundered Sky (n=94 ARAM wr 51.1, n=13 SR wr 61.5) only
surfaces at rank 11. Eclipse appears in tanky cells (ad_tanky r10, ap_tanky r9)
but is absent from the squishy-comp cells where most play happens.

Runaan's Hurricane at r7 has no EHP contribution (d_ehp=0.0) and is an
atypical Aatrox pick - scorer over-ranking it vs Death's Dance/Eclipse.

## Axis 4 - rune_ok: n/a

rune_relevant=false (hybrid, not burst/assassin).

---

## Nominated retune

1. Add Death's Dance (id 6333) to the hybrid bruiser item pool - it contributes
   AD + armor + damage-reduction passive (heal-interaction for Aatrox self-heal)
   and is empirically winning (wr 52.8 ARAM n=53).
2. Raise Sundered Sky weight or floor in squishy contexts - currently rank 11;
   empirical wr 51.1 ARAM n=94 / wr 61.5 SR n=13.
3. Investigate Eclipse scoring gap in squishy cells - wr 54.0 ARAM n=50 but
   absent from top-12 squishy cells; only ranks in tanky cells.
4. Fix enemy_damage_type comp_blind in the hybrid EHP branch - the EHP sub-score
   should apply MR-item boost when enemy comp is AP-heavy (same as tank scorer
   does). This requires a Tier-2 engine pass.
