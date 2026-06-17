# DS Cross-Eval: Naafiri

VERDICT: MINOR

scorer=burst | archetype=assassin (secondary=bruiser) | anchor=ARAM | evidence=outcome_all

---

## Axis 1 - archetype_ok: PASS

Burst scorer is the correct AD axis for an assassin. Naafiri's kit is pure physical
damage (P pack synergy, Q dash-stab, E lunge, R all-in). Empirical high-wr items in
SR are all AD: Profane Hydra 77.8% wr (n=9), Black Cleaver 85.7% wr (n=7), Serylda's
Grudge 75.0% wr (n=8). No AP item appears in any empirical list. Axis is correct.

---

## Axis 2 - comp_ok: PASS

Scorer=burst; the relevant responsiveness axis is target_resist (armor-pen items rise
vs tanky enemies). target_resist.comp_blind=false, max_positive_shift=+15. Correct
items rise: Mortal Reminder +15, Black Cleaver +15, Serylda's Grudge +10, Lord
Dominik's Regards +10. The burst scorer does not model self-EHP, so
enemy_damage_type.comp_blind=true (max_positive_shift=0, no risers/fallers) is
expected behavior - not a defect for a pure damage scorer. comp_ok=true.

---

## Axis 3 - outcome_ok: MINOR FLAG

Evidence: ARAM outcome_all (n=54, baseline wr=42.6%). Scorer top-8 in ad_squishy /
bal_squishy cells:
  Rank 1: Blade of the Ruined King (3153)
  Rank 2: Infinity Edge (3031)
  Rank 3: Umbral Glaive (3179)
  Rank 4: Essence Reaver (3508)
  Rank 5: Eclipse (6692)
  Rank 6: Bloodthirster (3072)
  Rank 7: Sundered Sky (6610)
  Rank 8: Axiom Arc (6696)

Empirical items above baseline (42.6%):
  Serylda's Grudge: wr=50.0% (n=20) - NOT in top-8 squishy scorer cell
  Long Sword: wr=50.0% (n=10) - starter item, ignore
  The Collector: wr=45.8% (n=24) - scorer rank 12 in squishy (low)
  Hubris: wr=42.9% (n=28) - scorer rank 10 in squishy (borderline, acceptable)

Scorer top-8 items with below-baseline empirical wr:
  Eclipse: scorer rank 5 in all squishy cells, empirical wr=35.1% (n=37) vs baseline
  42.6% - underperforming by ~7.5 pp at meaningful sample size.

BotRK is scorer rank 1 but does not appear in the empirical top-10 at all (n likely
near zero or untested), which weakens rank-1 confidence.

Serylda's Grudge (50.0% wr) is the top-performing above-baseline item and appears
only at rank 3 in ad_tanky/ap_tanky cells but is missing from the squishy-cell top-8.
In ARAM the enemy comp is mixed; Serylda's being absent from squishy top-8 means the
scorer underweights it when enemies are not heavy-armor.

---

## Axis 4 - rune_ok: true

rune_relevant=true. No rune data to contradict. Accepted.

---

## Nominated Retune

1. Reduce Eclipse scoring weight for burst scorer vs squishy targets. Empirical wr=35.1%
   (n=37) is ~7.5 pp below the 42.6% baseline at high sample size.
2. Raise Serylda's Grudge in the burst squishy-cell pool. It is the highest above-
   baseline empirical item (50.0%, n=20) but absent from squishy-cell top-8; its
   armor-pen passive has value even vs squishy targets (flat arpen component).
3. Consider raising The Collector from rank 12 (wr=45.8%, n=24 above baseline, largest
   empirical sample of any above-baseline item).
