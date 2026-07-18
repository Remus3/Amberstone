# DS Cross-Eval: Shyvana

## Verdict: MISMATCH

Scorer: hybrid | Archetype: bruiser/tank | Anchor: ARAM | Evidence: outcome_all (n=45, baseline wr=62.2%)

---

## Axis 1: archetype_ok = FALSE

Hybrid scorer sits on the AD axis (EHP+DPS blend weighted for physical damage dealing).
Shyvana's kit is AP-scaling: E (Flame Breath) and empowered R form deal magic damage.

Empirical ARAM (outcome_all, n=45):
- Spear of Shojin: wr 69.2% (rank 5 by freq) - AP item, above baseline
- Riftmaker: wr 66.7% (rank 6) - AP item, above baseline
- Liandry's Torment: wr 62.5% (rank 2) - AP item, above baseline
- Needlessly Large Rod: wr 62.5% (rank 7)
- Sorcerer's Shoes: wr 60.7% (rank 1 by freq, n=28)

Every item at or above the 62.2% baseline is AP-oriented. No AD item clears baseline.
The scorer axis contradicts both kit and what wins empirically.

---

## Axis 2: comp_ok = TRUE

Hybrid scorer has an EHP component; enemy_damage_type must shift the pool.
comp_blind=false confirmed. Max positive shift = 9 (Wit's End rises 9 ranks vs AP comp).
Dead Man's Plate falls -14 ranks vs AP comp (as expected for armor-centric item vs AP).
target_resist also responds: Liandry's rises +18 vs tanky target, Mortal Reminder +11.
Structural responsiveness is working correctly for a hybrid scorer.

---

## Axis 3: outcome_ok = FALSE

Scorer top-8 (ad_squishy / bal_squishy cells):
  1. Void Immolation  2. Blade of The Ruined King  3. Trinity Force  4. Heartsteel
  5. Runaan's Hurricane  6. Essence Reaver  7. Kraken Slayer  8. Stormrazor

None of these appear in the empirical above-baseline pool. Conversely:
- Liandry's Torment (wr 62.5%) appears only at rank 4 in the tanky cells (ad_tanky/ap_tanky),
  absent from squishy cells entirely.
- Spear of Shojin (wr 69.2%) does not appear in any comp_grid top-12.
- Riftmaker (wr 66.7%) does not appear in any comp_grid top-12.

The scorer is recommending an AD marksman-style pool while the champion wins with AP bruiser/mage items.

---

## Axis 4: rune_ok = n/a

rune_relevant=false.

---

## Nominated Retune

Switch Shyvana from hybrid to mage scorer (or ability scorer if available).
Her R-empowered form is the damage amplifier and scales with AP; Liandry's, Riftmaker,
Spear of Shojin, and Sorcerer's Shoes are her empirically validated win-rate leaders.
An AP-axis scorer would surface these items in the squishy cells where she actually fights.

Retune: assign scorer = mage (AP-axis, ability-damage weighted)
