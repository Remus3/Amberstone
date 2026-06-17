# DS Cross-Eval Report: Nilah

**Verdict: MISMATCH**

Scorer top-1 item (BotRK) has 28.6% empirical win rate (baseline 60.0%). Most-played above-baseline staples absent from scorer top-8.

---

## Axis 1 - Archetype OK: true

Primary=carry, secondary=assassin, scorer=dps. Nilah is a melee AD carry (Q reset, passive on-hit LS share with allies, R whirlpool). AD axis for carry is correct. dps scorer for an AA-reliant melee carry is appropriate.

## Axis 2 - Comp OK: true

Scorer=dps. enemy_damage_type responsiveness is comp_blind=true (max_positive_shift=0), but dps scorer does not model incoming damage mitigation so enemy damage type invariance is EXPECTED - not a defect. target_resist responsiveness is working correctly: max_positive_shift=14, top risers vs tanky are Serylda's Grudge (+14), Liandry's Torment (+13), Lord Dominik's Regards (+11). The scorer correctly surfaces armor-pen and %health tools when the enemy is tanky. No comp-blind defect.

## Axis 3 - Outcome OK: false

evidence_tier_ARAM = outcome_self, n=40 (>=8 threshold). Baseline ARAM wr = 60.0%.

Empirical items above baseline (ARAM self):
- The Collector: 61.3% (n=31) - most-played
- Navori Flickerblade: 61.1% (n=18)
- Berserker's Greaves: 68.8% (n=16)
- Cloak of Agility: 71.4% (n=7)
- Immortal Shieldbow: 83.3% (n=6)
- Bloodthirster: 66.7% (n=6)

Scorer top-8 (ad_squishy / bal_squishy - identical ranking):
1. BotRK (3153): empirical wr 28.6% (n=7) - WAY BELOW 60.0 baseline - FAIL
2. Void Immolation (223069): absent from empirical
3. Trinity Force (3078): absent from empirical
4. Essence Reaver (3508): absent from empirical
5. Kraken Slayer (6672): absent from empirical
6. Stormrazor (3097): absent from empirical
7. Heartsteel (3084): absent from empirical
8. Runaan's Hurricane (3085): absent from empirical

BotRK at rank 1 (score 68.9) has 28.6% empirical wr against a 60.0% baseline - a 31.4pp gap. This is a hard empirical loss at the top scorer slot. The Collector (rank 1 empirical by games played, 61.3% wr) and Navori Flickerblade (61.1%) are entirely absent from scorer top-8. Infinity Edge appears at empirical rank 2 (58.6% wr, below baseline) and scorer rank 10 - mildly low but not a primary concern given it is below baseline.

## Axis 4 - Rune OK: n/a

rune_relevant=false.

---

## Nominated Retune

BotRK overscored for Nilah. Nilah's passive gives her a share of ally lifesteal already, reducing marginal LS value from BotRK. Her primary damage pattern is Q-reset combo + crit burst, not sustained on-hit AA chains. The Collector and Navori Flickerblade (crit-synergy with Q reset passive) are the correct scoring anchors. Recommended: apply a champion-specific BotRK DPS discount for Nilah (or audit the on-hit/LS weight that inflates BotRK), and verify that The Collector's passive (execute threshold) and Navori's reset/CDR are captured in the dps scorer for her pattern.
