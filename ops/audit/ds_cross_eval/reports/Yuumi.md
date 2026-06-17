# Yuumi DS Cross-Eval Report

**Verdict: MINOR**
Scorer (hps / enchanter) axis is correct. Comp invariance is expected and present.
Pool gap: Moonstone Renewer is empirically the top ARAM item (n=73, wr 58.9 vs baseline 56.9)
but scores rank 9 (score 0.5752) - nearly zero vs rank-1 Echoes of Helia at 27.35.
Dawncore (n=28, wr 57.1) and Tear of the Goddess (n=28, wr 60.7) are absent from scorer pool.

---

## Axis 1: archetype_ok - PASS

Scorer: hps. Archetype: enchanter (primary), mage (secondary).
hps is the correct scorer axis for an enchanter. Yuumi kit is purely heal/shield.
Empirical top ARAM items by wr: Ardent Censer (59.3, scorer rank 2) and
Staff of Flowing Water (58.3, scorer rank 3) are both correctly high-ranked.
No axis mismatch.

## Axis 2: comp_ok - PASS

scorer = hps (enchanter). Enchanter heal/shield output is inherently independent of
enemy damage type and target resistances. comp_blind=true is the expected and correct
behavior for this scorer. All 5 comp cells (ad_squishy / bal_squishy / ap_squishy /
ad_tanky / ap_tanky) produce identical rankings, which is expected for hps.
No defect here.

## Axis 3: outcome_ok - MINOR FLAG

Evidence: ARAM outcome_all (n=116, baseline wr 56.9).
Above-baseline empirical items (wr > 56.9):
  - Moonstone Renewer:    n=73,  wr 58.9  -> scorer rank 9, score 0.5752 (NEARLY ZERO)
  - Ardent Censer:        n=59,  wr 59.3  -> scorer rank 2  (OK)
  - Mikael's Blessing:    n=31,  wr 58.1  -> scorer rank 8  (OK)
  - Dawncore:             n=28,  wr 57.1  -> ABSENT from scorer pool
  - Tear of the Goddess:  n=28,  wr 60.7  -> ABSENT from scorer pool
  - Staff of Flowing Water: n=24, wr 58.3 -> scorer rank 3  (OK)

Moonstone Renewer is the most-played item in Yuumi's ARAM pool (n=73) and is
above baseline wr (58.9 vs 56.9), but the hps scorer gives it near-zero weight (0.5752).
Echoes of Helia scores rank 1 (27.35) yet does not appear in empirical top-10 at all,
suggesting the scorer over-rewards Echoes while severely under-rewarding Moonstone.
Dawncore and Tear of the Goddess are above baseline and entirely absent.

Pool gap = MINOR (not a losing top build - Moonstone is not in scorer top-8, but items
that ARE in the top-8 are not empirically underperforming; the real issue is what is
missing and what is over-elevated).

## Axis 4: rune_ok - n/a

rune_relevant = false.

---

## Nominated Retune

Boost Moonstone Renewer weight in hps scorer (currently near-zero at rank 9; highest
empirical volume item with above-baseline wr). Add Dawncore and Tear of the Goddess to
hps item pool. Investigate why Echoes of Helia scores 27.35 but has no empirical presence
in top-10 (possibly inflated by a passive haste/heal formula not translating to actual wr).
