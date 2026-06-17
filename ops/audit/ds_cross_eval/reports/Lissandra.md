# DS Cross-Eval: Lissandra

## Verdict: MINOR

Scorer: ability | Archetype: mage/assassin | Anchor: ARAM | Evidence: outcome_all (n=109, wr=56.9)

---

## Axis 1: archetype_ok = true

Scorer axis is AP (ability scorer). Lissandra is a pure AP mage with no AA-scaling kit. Correct.

Empirical above-baseline items (wr > 56.9): Shadowflame 63.6, Rabadon's 63.0, Malignance 59.3,
Sorcerer's Shoes 58.8, Liandry's 57.5. All AP items. No AD items appear at above-baseline wr.
Axis assignment is sound.

---

## Axis 2: comp_ok = false (MINOR)

Primary responsiveness axis is target_resist (comp_blind=false, max_positive_shift=5).
Risers vs tanky: Bloodletter's Curse +5, Void Staff +2, Cryptbloom +2, Liandry's +1. This is correct.

The enemy_damage_type sub-axis is fully blind (comp_blind=true, max_positive_shift=0, no risers or
fallers). For an ability/mage scorer the target_resist axis is the dominant signal, so this is not
a hard DEFECT. However AP vs AD enemy comp makes zero difference to recommendations, which means
Shadowflame (best vs squishy/glass AD) and Void Staff/Cryptbloom (best vs AP-heavy tanks) get no
dynamic rerank relative to the enemy damage mix. Flagged MINOR, not MISMATCH, because target_resist
does respond and the scorer type is ability not ehp.

All d_ehp values are 0.0 across every comp cell (scorer does not model survivability side), which
is expected for a pure ability scorer but means comp_blind on the ehp dimension is structural.

---

## Axis 3: outcome_ok = false (MINOR - Malignance gap + Blackfire Torch overrank)

Scorer top-8 (ad_squishy cell): Wooglet's Witchcap #1 (27.9), Liandry's #2 (27.7),
Blackfire Torch #3 (18.6), Rabadon's #4 (10.5), Shadowflame #5 (9.3), Void Staff #6 (9.2),
Stormsurge #7 (8.0), Cryptbloom #8 (6.9).

Empirical cross-check vs baseline 56.9:
- Liandry's #2: wr 57.5 (above baseline) - OK
- Rabadon's #4: wr 63.0 (above baseline, strongly) - OK
- Shadowflame #5: wr 63.6 (above baseline, strongly) - OK
- Blackfire Torch #3: wr 52.4 (BELOW baseline 56.9, n=21) - overranked at #3 in scorer
- Wooglet's Witchcap #1: absent from empirical top-10 (6000g, rarely completed in real games) -
  gold-gated, not a reliability signal per se
- Stormsurge: absent from empirical items - small pool gap
- Cryptbloom: absent from empirical items - small pool gap

KEY MISS: Malignance (id 3118) is the second-most-played item at 54 games, wr 59.3 (above
baseline). It does not appear in scorer top-8 in any cell; it is not visible in the comp_grid
output at all. This is a meaningful pool gap - Malignance is a high-frequency staple with a
winning wr and the scorer is not surfacing it.

Zhonya's Hourglass: scorer #10, empirical wr 51.9 (below baseline). Mild overvaluation in scorer.

---

## Axis 4: rune_ok = n/a

rune_relevant = false.

---

## Nominated Retune

Add Malignance (id 3118) to the ability scorer item pool for Lissandra. Malignance is the
second-most-played item (n=54, wr=59.3) and is absent from scorer rankings entirely.
Separately, investigate Blackfire Torch scorer rank #3 vs empirical wr 52.4 (below baseline).
