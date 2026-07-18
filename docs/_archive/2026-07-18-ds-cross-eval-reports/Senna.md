# DS Cross-Eval: Senna

VERDICT: MISMATCH

Scorer: dps | Archetype: carry/bruiser | Anchor: ARAM | Evidence: outcome_self (n=30, baseline wr 46.7%)

---

## Axis 1 - archetype_ok: TRUE

DPS scorer = AD axis. Senna is an AD carry whose kit scales hard on attack speed and AD from soul stacks. Empirical above-baseline items in ARAM self are all AD/on-hit: Black Cleaver 61.5% (n=13), Muramana 54.5% (n=11), Berserker's Greaves 53.3% (n=15), Runaan's Hurricane 71.4% (n=7), Guinsoo's Rageblade 85.7% (n=7). AD axis is correct.

---

## Axis 2 - comp_ok: MINOR FLAG

Top-level comp_blind = false and primary_axis = target_resist. Target-resist responsiveness is functional: max_positive_shift = 11 when enemies are tanky, with Liandry's Torment +11, Serylda's Grudge +10, Lord Dominik's Regards +9, Mortal Reminder +8 rising correctly.

However the enemy_damage_type sub-axis has comp_blind = TRUE and max_positive_shift = 0. No items shift based on incoming AD vs AP damage mix. For a damage dealer this is a minor gap: the scorer does not modulate survivability-of-offense (e.g. Sterak's or Maw) based on whether the enemy is AD-heavy. Not a MISMATCH-level defect for a pure DPS axis but worth noting.

---

## Axis 3 - outcome_ok: FALSE (MISMATCH)

Using ARAM self (n=30 >= 8). Baseline = 46.7%.

Scorer top-8 (ad_squishy = bal_squishy for this champion):
  #1 Blade of the Ruined King  score 69.2  empirical wr 44.4%  (BELOW baseline)
  #2 Void Immolation            score 53.0  not in empirical pool
  #3 Kraken Slayer              score 41.4  empirical wr 42.9%  (below baseline)
  #4 Stormrazor                 score 39.1  not in empirical pool
  #5 Essence Reaver             score 35.7  not in empirical pool
  #6 Eclipse                    score 35.3  not in empirical pool
  #7 Voltaic Cyclosword         score 34.5  not in empirical pool
  #8 Infinity Edge              score 33.4  empirical wr 44.4%  (below baseline, all-wr 44.4%)

High-wr empirical items absent from scorer top-8:
  Guinsoo's Rageblade  85.7% wr (n=7)   - NOT in scorer top-8
  Runaan's Hurricane   71.4% wr (n=7)   - NOT in scorer top-8
  Black Cleaver        61.5% wr (n=13)  - NOT in scorer top-8
  Muramana             54.5% wr (n=11)  - NOT in scorer top-8

The scorer's #1 recommendation (BotRK) underperforms baseline. Its %max-HP proc benefit is limited at Senna's soul-stack attack cadence relative to dedicated on-hit or AS/CDR builds. The three highest-wr empirical items are entirely absent from the scored top-8.

---

## Axis 4 - rune_ok: n/a

rune_relevant = false.

---

## Nominated Retune

Promote Muramana, Black Cleaver, Guinsoo's Rageblade, and Runaan's Hurricane into the DPS pool scoring for Senna. These items synergize with her on-hit soul-stack mechanic and dominate above-baseline wr. Penalize or down-weight BotRK for Senna specifically: its %max-HP component does not scale with soul-stack attack speed the way on-hit/AS items do, and it consistently underperforms baseline in self-data.
