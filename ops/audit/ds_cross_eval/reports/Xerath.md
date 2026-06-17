# DS Cross-Eval: Xerath

**Verdict: MINOR**

Scorer: ability | Archetype: mage/enchanter | Anchor: ARAM (outcome_all, n=169, baseline wr=48.5)

---

## Axis 1 - archetype_ok: PASS

Primary archetype mage -> scorer=ability -> AP axis. Correct mapping for a pure-AP poke/siege kit.
Empirical items above baseline (48.5 wr): Luden's Echo 50.8 (n=128), Needlessly Large Rod 58.3 (n=48).
Both are AP items. No AD items appear above baseline. Axis is aligned.

## Axis 2 - comp_ok: PASS

Primary_axis=target_resist, comp_blind=false on that axis.
Vs tanky comps: Bloodletter's Curse +3 ranks, Void Staff +2, Cryptbloom +2 - all pen items rising correctly.
Shadowflame -2, Stormsurge -2 - flat-pen burst items correctly falling vs tanks.
Max shift=3 is modest but directionally sound for an ability scorer.

enemy_damage_type.comp_blind=true (max_positive_shift=0) - ability/mage scorers do not gate on
enemy damage mix for EHP, so this is expected behavior, not a defect.

## Axis 3 - outcome_ok: FAIL

Scorer top-8 (ad_squishy/bal_squishy): Wooglet's Witchcap #1 (59.2), Liandry's #2 (33.4),
Blackfire Torch #3 (23.9), Rabadon's #4 (22.2), Void Staff #5 (21.4), Shadowflame #6 (21.2),
Stormsurge #7 (18.2), Cryptbloom #8 (16.0).

Empirical winners above baseline (48.5):
- Luden's Echo: wr=50.8, n=128 - ONLY significant above-baseline empirical item.
  Luden's does NOT appear anywhere in scorer top-12. Major pool gap.

Empirically losing items promoted by scorer:
- Stormsurge rank #7 (score 18.2): empirical wr=30.4 (n=23), 18 points below baseline. Losing hard.
- Rabadon's Deathcap rank #4 (score 22.2): empirical wr=41.2, below baseline.
- Shadowflame rank #6 (score 21.2): empirical wr=44.0, below baseline.

Wooglet's Witchcap rank #1 has no empirical occurrences in the data (ARAM-specific item, rightly 0 n).
Its dominance at #1 is a scorer artifact that crowds out practical items.

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Add Luden's Echo to the ability scorer item pool (currently absent from top-12 despite n=128, wr=50.8).
Demote or cap Stormsurge in the ability scorer for sustained-poke mages - it is a burst-conduit item
with no synergy for Xerath's damage pattern (wr=30.4 is hard empirical evidence).
