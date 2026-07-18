# DS Cross-Eval: Karma

**Verdict: MINOR**
Scorer: ability | Archetype: mage/enchanter | Evidence: ARAM outcome_all (n=182, baseline wr=48.9)

---

## Axis 1 - archetype_ok: PASS

Archetype primary=mage, secondary=enchanter. Mage/enchanter maps to AP axis; ability scorer is correct.
Empirical above-baseline items (wr > 48.9): Ionian Boots 55.2, Liandry's 54.3, Rabadon's 52.7,
Refillable Potion 51.4. These are all AP items. Scorer axis aligns with what wins empirically.

---

## Axis 2 - comp_ok: PASS (marginal)

Scorer=ability; primary_axis=target_resist. Ability scorer comp-blindness on enemy_damage_type is
expected (AP ability math does not gate on enemy AD/AP mix). target_resist DOES move: Cryptbloom +2,
Bloodletter's +2, Void Staff +1 when target is AP-tanky vs squishy. However max_positive_shift=2
(weak signal). Acceptable for this scorer type; no EHP/hybrid defect present.

---

## Axis 3 - outcome_ok: FAIL

Scorer top-8 (ad_squishy): Liandry's #1, Wooglet's #2, Blackfire Torch #3, Rabadon's #4,
Void Staff #5, Shadowflame #6, Stormsurge #7, Cryptbloom #8.

Problems:
- Malignance (empirical rank 1, n=128, wr=49.2) is absent from scorer top-8 entirely. It is the
  highest-frequency Karma item by a large margin and sits above baseline wr. This is a pool gap.
- Stormsurge (scorer rank 7) has empirical wr=45.5 vs baseline 48.9 - it is a losing item but
  sits in the top half of the scorer recommendation pool.
- Wooglet's Witchcap (scorer rank 2, gold=6000) has zero empirical presence in top-10 items.
  This is not necessarily wrong (small-n phenomenon) but compounds the Malignance gap.
- Liandry's #1 (wr=54.3) and Rabadon's #4 (wr=52.7) align well.

Net: Malignance gap + Stormsurge below-baseline in top-8 = outcome_ok FAIL.

---

## Axis 4 - rune_ok: n/a

rune_relevant=false.

---

## Nominated Retune

Investigate why Malignance scores outside top-8 for Karma in the ability scorer.
Malignance grants ultimate haste which amplifies Karma's mantra (R) uptime - if the
ability scorer does not model ultimate haste or R-frequency bonus, Malignance will be
systematically undervalued. Additionally consider whether Stormsurge's burst-nuke
profile matches Karma's poke/sustained pattern; if not, a profile-gating penalty
for burst-only items on sustained-ability kits would suppress Stormsurge and lift
Malignance.

Nominated retune: "audit Malignance ult-haste scoring path for ability scorer; add sustained-vs-burst
profile gate to suppress Stormsurge on non-burst mage kits"
