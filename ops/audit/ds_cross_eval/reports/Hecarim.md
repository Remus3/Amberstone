# Hecarim DS Scorer Cross-Eval

## Verdict: MINOR

---

## 1. Archetype

- Primary: bruiser, Secondary: tank, Scorer: hybrid
- Hybrid scorer blends AD and AP contributions - correct for a bruiser/tank champion.
- Hecarim kit is AD physical with heal on W; played as bruiser or bruiser-carry.
- Empirical above-baseline winners (ARAM baseline 45.2, n=42): Eclipse 72.7, Ionian Boots
  66.7, Spirit Visage 57.1, Plated Steelcaps 57.1, Muramana 52.2. All are AD-leaning or
  hybrid items consistent with hybrid scorer axis.
- PASS: archetype_ok = true

---

## 2. Comp Responsiveness

- Scorer = hybrid; primary_axis = enemy_damage_type; comp_blind = false.
- enemy_damage_type max_positive_shift = +6 (Wit's End rises 6 ranks when enemy is AP).
- target_resist max_positive_shift = +13 (Liandry's rises 13 ranks vs tanky enemies;
  Black Cleaver +10, Eclipse +10).
- Both axes respond meaningfully. No comp-blind defect.
- PASS: comp_ok = true

---

## 3. Outcome Alignment

Evidence tier: ARAM outcome_all (self n=2, too small; all n=42, wr=45.2 baseline).

Scorer top-8 (ad_squishy / bal_squishy cells, ranks 1-8):
  1 Void Immolation   score 1.78
  2 Blade of the Ruined King   score 1.29
  3 Trinity Force   score 1.24
  4 Heartsteel   score 1.01
  5 Runaan's Hurricane   score 0.99
  6 Essence Reaver   score 0.99
  7 Dusk and Dawn   score 0.86
  8 Stormrazor   score 0.83

Empirical above-baseline items (wr > 45.2):
  Eclipse 6692   n=11   wr=72.7   -> scorer rank: ad_tanky #9, ap_tanky #9; NOT in squishy top-8
  Ionian Boots 3158   n=6    wr=66.7   -> boots, not scored as items
  Spirit Visage 3065  n=14   wr=57.1   -> absent from all scorer cells top-12
  Plated Steelcaps 3047  n=7  wr=57.1  -> boots, not scored
  Muramana 3042   n=23   wr=52.2   -> absent from all scorer cells top-12

Mismatches:
  - Eclipse (72.7 wr, n=11) is only rank 9 in tanky cells; not in squishy top-8 despite
    being the strongest empirical performer.
  - Spirit Visage (57.1 wr, n=14) absent from top-12 in all cells.
  - Muramana (52.2 wr, n=23, highest n) absent from top-12 in all cells.
  - Runaan's Hurricane (#5), Essence Reaver (#6), Stormrazor (#8) in scorer top-8 are pure
    marksman attack-speed or crit items; zero empirical above-baseline backing for Hecarim.

FAIL: outcome_ok = false

---

## 4. Rune Relevance

rune_relevant = false -> n/a

---

## Nominated Retune

Suppress pure marksman attack-speed/crit items (Runaan's Hurricane 3085, Essence Reaver
3508, Stormrazor 3097, Yun Tal Wildarrows 3032) from Hecarim's scorer-eligible pool.
Add Eclipse 6692, Spirit Visage 3065, and Muramana 3042 to the scored item pool so
empirically strong picks surface in top-8 recommendations.
