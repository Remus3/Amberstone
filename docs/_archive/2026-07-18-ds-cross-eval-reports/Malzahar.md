# Malzahar DS Cross-Eval Report

Verdict: MINOR
Scorer: ability (AP axis)
Evidence tier (ARAM): outcome_all (n=172, baseline wr=52.3)

---

## Axis 1 - archetype_ok: PASS

Primary archetype mage, secondary assassin. Scorer = ability (AP axis). Correct: Malzahar
is a pure AP mage (DoT + voidling damage from Q/W/E/R, all AP-scaling). Empirical ARAM
winners confirm AP builds: Liandry's (wr 52.9), Blackfire Torch (53.1), Rylai's (53.4),
Shadowflame (52.0). No AD build anywhere near baseline. Axis is right.

---

## Axis 2 - comp_ok: PASS

Scorer = ability (mage/AP category). Rule: target_resist should move vs tanky.
responsiveness.primary_axis = "target_resist"; target_resist.comp_blind = false;
max_positive_shift = 7. Bloodletter's Curse shifts +7 vs AP-tanky, Void Staff +2,
Cryptbloom +2. The scorer responds correctly to target tankiness.

enemy_damage_type.comp_blind = true, max_positive_shift = 0. This is expected for a
pure-ability/DPS scorer - d_ehp = 0.0 across all comp_grid cells, so the scorer does not
model Malzahar's survivability vs enemy damage type. That is correct behavior for a mage
dealing damage; no EHP defect here.

Top-level comp_blind = false (target_resist axis fires). No DEFECT.

---

## Axis 3 - outcome_ok: FAIL

Using outcome_all (self n=0). ARAM baseline wr = 52.3. Items above baseline:
  Sorcerer's Shoes  wr 53.6 (n=140) - boots, scorer exclusion acceptable
  Rylai's Crystal Scepter  wr 53.4 (n=88) - NOT in scorer top-12, pool gap
  Blackfire Torch  wr 53.1 (n=113) - scorer rank 3, winning, OK
  Liandry's Torment  wr 52.9 (n=155) - scorer rank 2, winning, OK

Scorer top-8 (ad_squishy / bal_squishy cells used as reference):
  rank 1 Wooglet's Witchcap (score 29.2) - absent from empirical top-10
  rank 2 Liandry's Torment  (score 26.7) - empirical wr 52.9, above baseline, OK
  rank 3 Blackfire Torch    (score 18.2) - empirical wr 53.1, above baseline, OK
  rank 4 Rabadon's Deathcap (score 10.98) - empirical wr 36.7 (n=30), -15.6pp vs baseline. LOSING.
  rank 5 Shadowflame        (score 9.67) - empirical wr 52.0, marginally below baseline
  rank 6 Void Staff         (score 9.52) - not in empirical top list with usable wr
  rank 7 Stormsurge         (score 8.23) - not in empirical top list
  rank 8 Cryptbloom         (score 7.15) - not in empirical top list

Two issues:
1. Rabadon's Deathcap is scorer rank 4 but wr 36.7 (n=30) - well below baseline. The
   stat-amp formula in the ability scorer likely over-rewards pure AP amplifiers without
   discounting opportunity cost vs cheaper items that also provide utility (Rylai's slow,
   Blackfire HP/burn).
2. Rylai's Crystal Scepter (wr 53.4, n=88, strongest sample in top-10) is entirely absent
   from scorer top-12. Rylai's provides AP + HP + slow; the ability scorer likely misses
   the HP component or does not model the synergy bonus (slow enables more W/E ticks).

---

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

Two-part fix:
1. Audit Rabadon's Deathcap scoring in the ability scorer for AP mages - the pure-amp
   multiplier bonus likely overflows for champions where raw AP ceiling rarely translates
   to wins (Malzahar's damage is DoT/voidling, not burst, so amp value is lower than
   burst mages). Consider a DoT-mage sub-path or a diminishing-returns cap on AP-amp
   bonuses past a threshold.
2. Add Rylai's Crystal Scepter to the ability-scorer item pool for Malzahar (and AP DoT
   mages in general). Rylai's HP + slow directly extends DoT windows and voidling uptime;
   its absence from top-12 is a pool-coverage miss.
