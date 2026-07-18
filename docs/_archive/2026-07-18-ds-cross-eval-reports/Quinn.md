# Quinn DS Scorer Cross-Eval Report

**Verdict: MINOR**
Scorer: dps | Archetype: carry/assassin | Evidence tier ARAM: outcome_self (n=82, baseline wr 50.0)

---

## Axis 1 - archetype_ok: PASS

carry/assassin are AD archetypes; dps scorer = AD axis. Quinn is a pure AD marksman/skirmisher - axis matches kit.

Empirical above-baseline items (ARAM self, wr > 50.0): Phantom Dancer 64.3, Lord Dominik's 61.5,
B.F. Sword 58.3, Berserker's Greaves 54.4, Statikk Shiv 54.3, Collector 52.5, IE 51.8. All AD items.
No AP-item overperformance. Archetype assignment correct.

---

## Axis 2 - comp_ok: PASS

Scorer = dps; primary_axis = target_resist. enemy_damage_type is comp_blind (max_positive_shift=0,
top_risers_when_ap=[]) but that is EXPECTED for a dps scorer - Quinn's outgoing damage efficiency
is independent of what damage type enemies deal. Comp-blindness on the enemy_damage_type sub-axis
is not a defect here.

target_resist.comp_blind = false, max_positive_shift = 21. Top risers when tanky:
Liandry's Torment +21, Serylda's Grudge +8, Mortal Reminder +7, Lord Dominik's +7, Eclipse +5.

Comp grid confirms responsiveness: Runaan's drops from rank 2 (score 75.8 vs squishy) to rank 4
(score 43.3 vs tanky); Kraken drops from rank 3 (74.4) to rank 5 (42.5). Appropriate anti-tank
items rise. comp_ok = true.

---

## Axis 3 - outcome_ok: FAIL (MINOR)

Using ARAM self (n=82 >= 8). Baseline wr = 50.0.

Scorer top-8 (ad_squishy baseline):
  rank 1 BotRK (id 3153)
  rank 2 Runaan's Hurricane (id 3085)
  rank 3 Kraken Slayer (id 6672)
  rank 4 Void Immolation (id 223069)
  rank 5 Essence Reaver (id 3508)
  rank 6 Stormrazor (id 3097)
  rank 7 Infinity Edge (id 3031)
  rank 8 Eclipse (id 6692)

Issues:
- BotRK is scorer rank 1 but empirically loses: wr=43.8 (n=16), BELOW baseline 50.0. Overvalued.
- Runaan's Hurricane (rank 2) - absent from empirical top-10 entirely.
- Kraken Slayer (rank 3) - absent from empirical top-10 entirely.
- Eclipse (rank 8) - absent from empirical top-10 entirely.
- IE (rank 7) - empirically wr=51.8, above baseline. OK.

High-wr empirical staples missing from scorer top-8:
- The Collector: wr=52.5, n=61 (most-played item) - scorer rank NOT in top 8 (absent).
- Statikk Shiv: wr=54.3, n=35 - absent from scorer entirely.
- Phantom Dancer: wr=64.3, n=14 - absent from scorer entirely.
- Lord Dominik's: wr=61.5, n=13 - scorer rank 11 (ad_tanky) but outside top-8 in squishy baseline.

The scorer overweights on-hit / multi-target DPS items (BotRK, Runaan's, Kraken) that do not
convert to wins on Quinn. Collector, Statikk Shiv, and Phantom Dancer - her empirically winning
crit/burst-crit items - are absent or ranked low.

---

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

Investigate why BotRK scores 118.9 on Quinn (rank 1, likely on-hit/attack-speed DPS model fitting
Quinn's rapid AA pattern) when empirical wr=43.8. Check whether Collector, Statikk Shiv, and
Phantom Dancer are being considered in the dps scorer item pool for Quinn at all, and why they
rank outside the top 8 vs squishy comps. A crit-path weight correction or item-pool inclusion
fix is indicated. Severity is MINOR (not a wrong axis, pool calibration issue).
