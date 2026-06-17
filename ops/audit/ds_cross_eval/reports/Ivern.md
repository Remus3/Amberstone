# DS Cross-Eval: Ivern

**VERDICT: MINOR**

Archetype enchanter/mage, scorer hps. Axis is correct and kit-aligned. Comp
invariance is expected and present. Outcome has one significant defect: Imperial
Mandate sits at scorer rank 7 with a 28.6% win rate (18pp below the 46.8%
baseline) and is empirically the lowest-performing item in the top-10 empirical
list. Moonstone Renewer is the most-played item (n=34, wr 47.1%) yet scores at
rank 9, outside the top-8 pool. No rune signal (rune_relevant=false).

---

## Axis 1 - archetype_ok: PASS

Scorer hps is the correct axis for enchanter. Ivern's kit (R shield bubble,
Daisy, bramblezone heals) is heal/shield-centric. Empirical above-baseline items
(Redemption 55.6%, Moonstone Renewer 47.1%) are all enchanter support items, not
AP damage items. No AP carry build wins above baseline. Axis is aligned.

## Axis 2 - comp_ok: PASS

Scorer is hps/enchanter. Comp invariance is expected: hps scoring does not depend
on enemy damage type or target resistances. All 5 comp cells (ad_squishy,
bal_squishy, ap_squishy, ad_tanky, ap_tanky) are identical with d_ehp=0,
d_dps=0, and every score unchanged across comps. comp_blind=true is CORRECT
behavior here, not a defect.

## Axis 3 - outcome_ok: FAIL

Evidence tier ARAM: outcome_all (n=47, baseline wr=46.8%).

Scorer top-8: Echoes of Helia(r1), Ardent Censer(r2,wr 45.5 below baseline),
Staff of Flowing Water(r3,wr 46.7 near baseline), Locket of the Iron Solari(r4,
not in empirical top-10), Knight's Vow(r5, not in empirical top-10), Redemption
(r6, wr 55.6 ABOVE baseline - good), Imperial Mandate(r7, wr 28.6 FAR BELOW
baseline - DEFECT), Mikael's Blessing(r8, not in empirical top-10).

Defects:
- Imperial Mandate (id 4005) is scorer rank 7 but empirically 28.6% wr, 18pp
  below the 46.8% baseline. This item is actively losing in player hands yet the
  scorer endorses it as a top-7 recommendation.
- Moonstone Renewer (id 6617) is the most popular Ivern item (n=34) with wr 47.1%
  (above baseline) but scores at rank 9, outside the top-8 pool.

High-wr items outside scorer top-8:
- Redemption (wr 55.6%, scorer r6) - present, good.
- Fiendish Codex (id 3108, wr 50.0%, n=8) - absent from scorer pool entirely.
  Mage component, hps scorer correctly deprioritizes it for an enchanter, but it
  is an above-baseline item worth noting.
- Malignance (id 3118, wr 66.7%, n=9) - absent from scorer pool. Mage item with
  high wr; small sample but notable. hps scorer not expected to surface this; not
  a scorer defect but suggests some Ivern players are running AP damage builds
  with above-baseline success.

Primary flag: Imperial Mandate rank 7 at 28.6% wr is a scorer-endorsed losing
item. Moonstone Renewer rank 9 with the highest play frequency should be in the
top-8.

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Demote Imperial Mandate below rank 9 in the hps scorer pool for enchanter Ivern.
Promote Moonstone Renewer into the top-8 (currently rank 9, score 0.87 vs
Imperial Mandate score 8.27 - the gap suggests the hps scorer underweights the
flat-periodic AoE heal pattern and overweights the on-cast damage-amplification
passive of Imperial Mandate which provides zero healing value for Ivern).
Investigate whether the hps scorer's Imperial Mandate weight is correct for other
enchanters or is a universal overweight.
