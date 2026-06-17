# DS Cross-Eval Report: Warwick

**Verdict: MINOR**
Scorer axis and comp responsiveness are correct. Item pool has ADC-crit contamination and
is missing key empirical bruiser staples (Sundered Sky, Spirit Visage, Titanic Hydra).

---

## 1. Archetype OK - PASS

- Archetype: bruiser/tank (source: default)
- Scorer: hybrid (AD axis for bruiser)
- Warwick kit is physical: Q heal/damage, E fear on pounce, R suppression - all AD-scaling.
- Empirical above-baseline (baseline wr=58.0 ARAM n=50) items are AD/bruiser/tank:
  Sundered Sky (62.1%), BotRK (60.7%), Spirit Visage (60.0%), Heartsteel (60.0%),
  Titanic Hydra (75.0%), Ravenous Hydra (83.3%).
- Hybrid AD axis correctly models a physical bruiser. No axis mismatch.

---

## 2. Comp OK - PASS (with note)

- Scorer: hybrid - has both EHP and DPS components. EHP component MUST respond to
  enemy_damage_type; DPS component should respond to target_resist.
- comp_blind = false for both axes. Responsiveness confirmed live:
  - enemy_damage_type max_positive_shift = 9 (Wit's End rises 9 ranks vs AP comp)
  - Dead Man's Plate falls 11 ranks vs AP comp (physical-resist item correctly deprioritized)
  - target_resist max_positive_shift = 19 (Liandry's Torment rises 19 ranks vs tanky)
- Liandry's Torment rising 19 ranks vs tanky is a minor anomaly for an AD bruiser - the DPS
  component is crediting %HP AP damage vs tanky enemies. Not a defect (hybrid has no AP gate)
  but is unexpected and may inflate AP items in tanky comps. Flagged for awareness.
- Overall: scorer is comp-responsive on the primary axis. PASS.

---

## 3. Outcome OK - MINOR DEFECT

Evidence tier: outcome_all (ARAM n=50, baseline wr=58.0). n<8 for self (n=4).

Scorer top-8 (ad_squishy / bal_squishy cells used for overlap check):
  R1 Void Immolation (score 1.64), R2 BotRK (1.39), R3 Trinity Force (1.05),
  R4 Runaan's Hurricane (0.95), R5 Heartsteel (0.90), R6 Essence Reaver (0.90),
  R7 Kraken Slayer (0.87), R8 Stormrazor (0.82)

Empirical above-baseline items and scorer presence:
  - Sundered Sky     n=29 wr=62.1% -> ABSENT from top-12 scorer
  - BotRK            n=28 wr=60.7% -> rank 2 - PRESENT
  - Spirit Visage    n=25 wr=60.0% -> ABSENT from top-12 scorer
  - Heartsteel       n=10 wr=60.0% -> rank 5 - PRESENT
  - Titanic Hydra    n=8  wr=75.0% -> ABSENT from top-12 scorer
  - Plated Steelcaps n=6  wr=66.7% -> boots, expected absent
  - Ravenous Hydra   n=6  wr=83.3% -> ABSENT (small n, high wr)

Scorer top-8 items with zero empirical appearances:
  - Runaan's Hurricane (rank 4): pure ADC attack-speed item, never seen on WW empirically
  - Essence Reaver   (rank 6): crit mana ADC item, no WW empirical presence
  - Kraken Slayer    (rank 7): crit ADC anti-tank, no WW empirical presence
  - Stormrazor       (rank 8): crit ADC on-hit, no WW empirical presence
  - Void Immolation  (rank 1): ranks #1 with d_ehp=4483 but 0 empirical appearances

Summary: 4 of top-8 scorer items are pure ADC-crit/marksman items with zero empirical
backing on Warwick. The three highest-n above-baseline staples (Sundered Sky n=29, Spirit
Visage n=25, Titanic Hydra n=8) are completely absent from the scorer top-12. This is a
pool contamination issue - the hybrid DPS component scores crit-synergy items high without
a bruiser-archetype gate, and Void Immolation's EHP delta inflates a rarely-purchased item.

---

## 4. Rune OK - N/A

rune_relevant = false

---

## Nominated Retune

Apply bruiser-archetype pool filter in hybrid scorer: gate out items with crit_scaling=true
or items primarily designed for marksman archetype (Runaan's Hurricane, Essence Reaver,
Kraken Slayer, Stormrazor, Infinity Edge) when archetype=bruiser. Investigate why Sundered
Sky (n=29 wr=62.1%) scores outside top-12 - likely missing Sundered Sky passive EHP credit
or lifesteal interaction. Verify Titanic Hydra and Ravenous Hydra passive d_dps computation
for WW (HP-scaling cleave should score well for a high-HP bruiser). Consider whether
Void Immolation's EHP contribution should be discounted by purchase-frequency prior for
empirical calibration.
