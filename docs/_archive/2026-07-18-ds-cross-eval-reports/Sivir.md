# DS Cross-Eval: Sivir

**Verdict: MINOR**

Scorer: dps | Archetype: carry (AD) | Anchor: ARAM | Evidence tier ARAM: outcome_self (n=16)

---

## Axis 1 - archetype_ok: PASS

dps scorer = AD axis. Sivir is an AD marksman; kit is AA-focused physical damage. Axis correct.

Empirical check (outcome_self, baseline wr=37.5): above-baseline items are IE (wr 50.0, n=10),
Navori Flickerblade (wr 40.0, n=10), The Collector (wr 50.0, n=6). IE is scorer rank 8 in
ad_squishy/bal_squishy - present. Navori is scorer rank 10 - just outside top-8 but in pool.
BotRK is scorer rank 1 and empirically strong (all-data wr 61.5, n=26). No axis mismatch.

---

## Axis 2 - comp_ok: PASS

dps scorer primary axis = target_resist (comp_blind=false, max shift +22 via Liandry's Torment
and armor-pen items). Correct: dps scorer should respond to tank comps.

enemy_damage_type: comp_blind=true, max_positive_shift=0. Expected for a pure AD physical
champion - Sivir does not swap to AP items regardless of enemy damage type, so zero shift is
correct behavior, not a defect.

---

## Axis 3 - outcome_ok: PASS (minor gap)

Scorer top-8 (ad_squishy = bal_squishy, identical rankings):
  Rank 1 BotRK (score 105.4), Rank 2 Hurricane (68.9), Rank 3 Kraken Slayer (68.4),
  Rank 4 Void Immolation (56.8), Rank 5 Stormrazor (56.5), Rank 6 Essence Reaver (56.2),
  Rank 7 Yun Tal Wildarrows (54.6), Rank 8 Infinity Edge (50.6).

Above-baseline empirical items (self, baseline 37.5):
  - IE (wr 50.0) -> scorer rank 8. Present. OK.
  - Navori Flickerblade (wr 40.0) -> scorer rank 10. Barely outside top-8.
  - The Collector (wr 50.0, n=6) -> absent from scorer pool in all comp cells. Pool gap.

No scorer-top item is empirically losing. BotRK at rank 1 is empirically strong.
The Collector is the main pool gap - above baseline wr in self data, absent from scorer pool.
Minor, not a MISMATCH (small n=6 in self; all-data Collector wr=39.2 is below all-data baseline
44.2, so the gap is noisy rather than clearly structural).

---

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

Add The Collector (id 6676) to the dps scorer item pool for Sivir so it appears in comp-cell
rankings. Verify Statikk Shiv (id 3087, empirically n=9 self but wr 22.2 - below baseline)
is intentionally absent (its low empirical wr supports exclusion or low weighting).
