# DS Cross-Eval: Rengar

**VERDICT: MINOR**
Scorer axis correct (burst/AD). Pool is contaminated - Wooglet's Witchcap sits at scorer rank 2 with zero empirical backing, and Profane Hydra (the canonical Rengar reset item) is absent from the top-12 entirely.

---

## 1. Archetype OK - PASS

Primary assassin, secondary bruiser. Scorer = burst. Burst is AD-aligned, which matches Rengar's
physical burst kit (empowered Q, R leap-assassinate) and empirical evidence:

- SR empirical (outcome_all n=35, wr=51.4): Youmuu's Ghostblade wr=71.4 (n=7), Edge of Night
  wr=66.7 (n=12), Profane Hydra wr=62.5 (n=16), Tiamat wr=66.7 (n=6) - all AD lethality.
- ARAM empirical (outcome_all n=50, wr=38.0): Sundered Sky wr=54.5 (n=11), Serrated Dirk
  wr=50.0 (n=8), Profane Hydra wr=42.9 (n=21) - all AD physical.

No AP items appear in any empirical list. Burst scorer axis = correct.

---

## 2. Comp OK - PASS (with note)

Scorer primary_axis = "target_resist". comp_blind (overall) = false. target_resist.max_positive_shift = 18.

Top risers vs tanky enemy: Black Cleaver +18, Terminus +12, Serylda's Grudge +11, Mortal Reminder +7,
Lord Dominik's Regards +7. This is correct behavior - burst scorer should prioritize armor-pen when
targets are tanky.

enemy_damage_type.comp_blind = true (max_positive_shift = 0). For a burst scorer the enemy damage
type dimension is expected to be secondary or irrelevant - Rengar deals physical damage regardless of
what the enemy deals. Comp-blindness on the incoming-damage axis is not a defect for this archetype.

Note: all three squishy cells (ad_squishy, bal_squishy, ap_squishy) produce identical rankings. This
means the scorer does not adjust Rengar's items based on whether enemies deal AP or AD. Acceptable
for a burst/physical-damage scorer where own damage type does not shift item selection.

---

## 3. Outcome OK - FAIL

Using outcome_all ARAM (n=50, baseline wr=38.0%). Above-baseline items vs scorer top-8:

Scorer top-8 (ad_squishy): BotRK(#1), Wooglet's Witchcap(#2), Essence Reaver(#3), Sundered Sky(#4),
Infinity Edge(#5), Trinity Force(#6), Eclipse(#7), Kraken Slayer(#8).

Empirical above-baseline cross-check:
- Profane Hydra: wr=42.9 (n=21, ARAM), wr=62.5 (n=16, SR) - NOT in scorer top-12. Critical miss.
  Profane Hydra is Rengar's signature item - its on-kill reset directly synergizes with Rengar's
  empowered ability stacking. The burst scorer should reward it highly but it is completely absent.
- Wooglet's Witchcap: scorer rank 2 (score=252.0) - zero appearances in ARAM or SR empirical items.
  It is a mixed-stat item (AD+AP+armor cloak). Its score at rank 2 suggests the scorer is heavily
  weighting its raw stats rather than burst-pattern fit. With no empirical wins, it is over-ranked.
- Sundered Sky: scorer rank 4, ARAM wr=54.5 (n=11). This overlap is correct.
- Infinity Edge: scorer rank 5, ARAM wr=33.3 (n=9) - below baseline. Scorer over-ranks it.
- The Collector: scorer rank 11 (ad_squishy), ARAM wr=40.7 (n=27) - above baseline, decent sample,
  but outside the top-8 window. Minor ordering gap.

Conclusion: Profane Hydra absent from top-12 despite being Rengar's highest-n SR item and third-best
ARAM item. Wooglet's at #2 with no empirical support. outcome_ok = false.

---

## 4. Rune OK - true

rune_relevant = true. Scored as rune_ok = true.

---

## Nominated Retune

Two-part fix:
1. Audit why Profane Hydra scores below rank 12 for Rengar burst scorer. Its on-kill Hydra passive
   resets on champion kill, which directly amplifies Rengar's multi-target burst loop. Check whether
   the burst scorer's item-passive registry is missing this Profane Hydra interaction.
2. Audit Wooglet's Witchcap rank-2 position. The item's hybrid AD+AP+armor stats may be boosting its
   raw-stat score without any empirical backing. Consider adding a burst-scorer penalty for AP-ratio
   items on AD-archetype champions, or verify the passive scoring is correct for this item.
