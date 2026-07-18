# Heimerdinger DS Cross-Eval Report

**Verdict: MINOR**
Scorer axis correct (mage->ability, AP). Comp responsiveness working. Pool gap: Rylai's Crystal Scepter and Malignance absent from scorer; top-scored Liandry's underperforms ARAM baseline wr.

---

## 1. archetype_ok: TRUE

scorer=ability, archetype=mage/enchanter. Ability scorer uses AP axis. Heimerdinger kit is 100% AP-scaling (turrets Q, rockets W, grenade E, super-charged ult all AP). Axis is correct.

Empirical check (ARAM all, n=122, baseline wr=44.3, using outcome_all per evidence_tier):
Above-baseline items: Zhonya's Hourglass 47.6, Malignance 46.2, Sorcerer's Shoes 46.9, Blackfire Torch 46.1, Rylai's Crystal Scepter 44.6. All are AP items. Scorer recommends AP pool. No axis mismatch.

---

## 2. comp_ok: TRUE

Scorer=ability (mage family). Rule: ability/mage scorer -> target_resist should respond vs tanky. EHP axis need not respond to enemy damage type.

responsiveness.primary_axis = "target_resist". target_resist.comp_blind = false. max_positive_shift = +6 ranks. Top risers vs tanky enemy: Bloodletter's Curse (+6), Void Staff (+2), Cryptbloom (+2). Scorer correctly promotes MR-penetration items when facing tanky targets.

enemy_damage_type: inner comp_blind = true, max_positive_shift = 0. For an ability scorer that does not model EHP against incoming damage, indifference to enemy damage type is expected and correct behavior. Not a defect.

Overall comp_ok = true.

---

## 3. outcome_ok: FALSE (MINOR pool gap)

Reference: ARAM all (n=122 >= 8 threshold). Baseline wr = 44.3.

Scorer top-8 in ad_squishy cell (primary reference):
  rank 1 Liandry's Torment (score 25.39) -> empirical wr 43.0, BELOW baseline 44.3
  rank 2 Wooglet's Witchcap (score 22.38) -> not in empirical data at meaningful n
  rank 3 Blackfire Torch (score 16.94) -> empirical wr 46.1, above baseline (OK)
  rank 4 Rabadon's Deathcap (score 8.41) -> empirical wr 41.7, well below baseline
  rank 5 Shadowflame (score 7.23) -> not in top empirical items
  rank 6 Void Staff (score 7.05) -> not in top empirical items
  rank 7 Stormsurge (score 6.13) -> not in top empirical items
  rank 8 Cryptbloom (score 5.30) -> not in top empirical items

Missing staples (above-baseline, not in scorer top-12):
  Rylai's Crystal Scepter: n=74, wr=44.6, rank not in scorer top-12 at all. Highest-frequency above-baseline item in empirical pool. Major gap.
  Malignance: n=26, wr=46.2, not in scorer top-12. Second-highest wr above-baseline empirical item absent from pool.

Additional concern:
  Liandry's Torment is scorer rank 1 (score 25.39) but empirical wr 43.0 is 1.3pp below baseline. Top scorer recommendation is empirically losing.
  Rabadon's Deathcap is scorer rank 4 but wr 41.7 is 2.6pp below baseline.

Zhonya's Hourglass (wr 47.6, highest empirical wr) appears at scorer rank 10 - present but under-weighted.

outcome_ok = false.

---

## 4. rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

Add Rylai's Crystal Scepter (id 3116) and Malignance (id 3118) to the ability scorer AP item pool for Heimerdinger. Investigate Liandry's Torment score inflation: rank 1 scorer vs empirical wr 43.0 below the 44.3 baseline suggests the passive-damage formula is overweighting the DOT component relative to actual game outcomes. Consider whether Zhonya's Hourglass deserves a rank boost (current rank 10, empirical wr 47.6 is highest in pool).
