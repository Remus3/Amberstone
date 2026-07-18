# Vex DS Cross-Eval Report

**Verdict: MINOR**

Scorer: ability | Archetype: mage/assassin | Anchor: ARAM | Evidence: outcome_all (n=105, wr=41.9%)

---

## Axis 1 - archetype_ok: PASS

Mage maps to AP axis; ability scorer is correct for an AP burst/poke kit. All scorer top items are AP
(Liandry's #1, Wooglet's #2, Blackfire Torch #3, Rabadon's #4, Void Staff #5, Shadowflame #6).
Empirical builds are uniformly AP (Luden's n=78, Shadowflame n=72, Stormsurge n=49, Rabadon's n=39).
Axis is aligned.

---

## Axis 2 - comp_ok: PASS

Scorer=ability -> target_resist should respond to tanky comps; enemy_damage_type comp-blindness is expected.

target_resist.comp_blind=false. max_positive_shift=3. vs tanky: Cryptbloom rises +3 ranks, Bloodletter's +2,
Void Staff +1. Rabadon's drops -2, Shadowflame -2, Stormsurge -2 vs tanky (less flat-burst value vs armor/MR).
Liandry's rises from score 27.64 (squishy) to 29.50 (tanky) - correct DoT scaling.

enemy_damage_type.comp_blind=true: expected for ability scorer (no self-EHP term). Not a defect.

---

## Axis 3 - outcome_ok: FAIL (pool gap)

Baseline wr=41.9% (n=105). No build item beats baseline; top empirical items by wr: Refillable Potion
45.0% (n=20, consumable), Luden's Echo 41.0% (n=78), Shadowflame 38.9% (n=72).

Pool mismatch:
- Luden's Echo is empirical #1 by usage (n=78, wr=41.0%) but is ABSENT from scorer top-12 in every
  comp cell. A staple in 74% of sampled games with no scorer representation is a gap.
- Liandry's Torment is scorer #1 (score=27.64 squishy, 29.50 tanky) but has ZERO empirical appearances
  in the top-10 item list (not even listed). Wooglet's (#2, score=25.24) and Blackfire Torch (#3,
  score=18.17) are also empirically absent.
- Shadowflame overlaps at scorer #6 (score=9.21) and empirical n=72 wr=38.9% - partial alignment.
- Void Staff scorer #5 appears empirically at n=14 wr=28.6% (low wr).

The scorer elevates Liandry's/Wooglet's/Blackfire Torch to the top 3 spots but empirical players
almost never buy them on Vex. Luden's being the #1 played item with zero scorer presence is the
primary gap.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Add Luden's Echo to the ability scorer item pool for Vex (currently absent from all comp cells).
Investigate why Liandry's Torment scores 27.64 as scorer #1 but has zero empirical plays in ARAM -
likely an AH/passive interaction weight inflating it for Vex specifically vs actual usage patterns.
Consider a Vex-specific item weight or capping Liandry's score relative to burst-oriented AP items.
