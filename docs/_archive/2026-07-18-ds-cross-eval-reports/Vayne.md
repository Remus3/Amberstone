# Vayne DS Cross-Eval Report

**Verdict: MINOR**

Scorer: dps | Archetype: carry/assassin | Anchor: ARAM | Evidence: outcome_self (n=93)

---

## Axis 1 - archetype_ok: PASS

dps scorer = AD axis. Vayne kit is fully AD/on-hit (Silver Bolts true damage, Tumble, Condemn). Correct axis.

Empirical above-baseline items (self wr > 61.3%): BotRK 63.3%, Guinsoo's 72.9%, Wit's End 73.7%, Berserker's 63.2%, Recurve Bow 70.8%, Trinity Force 62.5% - all AD/on-hit/AS items. Kit and empirical signal both confirm AD dps scorer is right.

---

## Axis 2 - comp_ok: PASS

dps scorer does not model self-EHP, so enemy_damage_type comp_blind=true is EXPECTED (no EHP component to shift). No defect.

target_resist responsiveness is correct: primary_axis=target_resist, comp_blind=false, max_positive_shift=20. Tanky comps lift armor-pen/tank-shred items: Liandry's +20, Serylda's +8, LDR +7, Eclipse +5, Mortal Reminder +4. Appropriate dps-scorer behavior.

---

## Axis 3 - outcome_ok: FAIL (MINOR)

Scorer top-8 (ad_squishy = bal_squishy, identical rankings):
  rank 1 BotRK 109.2, rank 2 Kraken Slayer 72.4, rank 3 Runaan's 71.7, rank 4 Void Immolation 60.2,
  rank 5 Stormrazor 59.1, rank 6 Yun Tal 58.4, rank 7 Essence Reaver 57.4, rank 8 Navori 50.5

Empirical ARAM self (n=93, baseline wr=61.3%):
  Wit's End       n=38  wr=73.7%  -> ABSENT from scorer top-8
  Guinsoo's       n=59  wr=72.9%  -> ABSENT from scorer top-8
  Recurve Bow     n=24  wr=70.8%  -> ABSENT from scorer top-8
  BotRK           n=79  wr=63.3%  -> scorer rank 1 - OK
  Berserker's     n=76  wr=63.2%  -> boots, excluded from scorer pool (expected)
  Trinity Force   n=16  wr=62.5%  -> ABSENT from scorer top-8
  Terminus        n=18  wr=61.1%  -> near-baseline, scorer rank 11

Problem: the three highest-wr empirical items (Wit's End 73.7, Guinsoo's 72.9, Recurve Bow 70.8) are all on-hit AS items and all missing from scorer top-8. The dps scorer is biased toward crit and crit-synergy items (Stormrazor, Yun Tal, Essence Reaver, Navori) which do not appear in the top empirical items.

Additionally: Kraken Slayer is scorer rank 2 (score 72.4) but empirical wr is only 50.0% (n=30), well below baseline. Over-ranked.

---

## Axis 4 - rune_ok: n/a

rune_relevant=false.

---

## Nominated Retune

Boost on-hit AS items in Vayne dps scorer: Guinsoo's Rageblade, Wit's End, and Recurve Bow are empirically top-3 above-baseline items but absent from top-8. The scorer likely lacks a Vayne-specific Silver Bolts on-hit multiplier or AS value pathway. Investigate whether attack_speed weight and on-hit damage components are correctly captured for Vayne's W passive. Revisit Kraken Slayer weight - empirical wr 50.0 does not support rank-2 placement.
