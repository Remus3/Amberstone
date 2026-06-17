# Pantheon DS Cross-Eval Verdict

**Severity: MINOR**
Scorer: hybrid | Archetype: bruiser/assassin | Anchor: ARAM | Evidence: outcome_all (n=131, wr=51.9%)

---

## Axis 1 - Archetype OK: true

Scorer=hybrid is the correct axis for a physical-damage bruiser/diver. Empirical
above-baseline items are all AD/physical: Black Cleaver (61.3% wr, n=31),
Death's Dance (57.8%, n=45), Spear of Shojin (55.0%, n=40), The Collector (54.5%,
n=44), Mercury's Treads (55.3%, n=85). No AP items appear. Axis is aligned.

---

## Axis 2 - Comp OK: true

Scorer=hybrid carries an EHP component (d_ehp nonzero on most items).
comp_blind=false; enemy_damage_type max_positive_shift=17 (Hollow Radiance rises
17 ranks vs AP enemy comp). Iceborn Gauntlet falls 2 ranks (armor less valuable vs
AP), Dead Man's Plate falls 6. The scorer meaningfully reprices armor-bearing items
against AP-heavy comps. No defect here.

target_resist also responds: Liandry's Torment rises +11 ranks vs tanky targets,
Eclipse +8, Black Cleaver +7. Both axes are active; comp_blind=false on both. Passes.

---

## Axis 3 - Outcome OK: false

Using outcome_all (n=131, wr=51.9% baseline). Above-baseline empirical items:
  - Black Cleaver     61.3% wr  n=31  (absent from scorer top-8)
  - Death's Dance     57.8% wr  n=45  (absent from scorer top-8)
  - Spear of Shojin   55.0% wr  n=40  (absent from scorer top-8)
  - Mercury's Treads  55.3% wr  n=85  (boots - exempt from item pool comparison)
  - The Collector     54.5% wr  n=44  (absent from scorer top-8)
  - Long Sword        55.0% wr  n=20  (component - exempt)
  - Hubris            52.6% wr  n=19  (marginally above baseline)

Scorer top-8 (ad_squishy cell):
  #1 Void Immolation (6000g, 0 empirical presence)
  #2 Trinity Force   (0 empirical presence)
  #3 Blade of the Ruined King (0 empirical presence)
  #4 Heartsteel      (0 empirical presence)
  #5 Essence Reaver  (0 empirical presence)
  #6 Iceborn Gauntlet (0 empirical presence)
  #7 Dusk and Dawn   (0 empirical presence)
  #8 Stormrazor      (0 empirical presence)

Every scorer top-8 item has zero empirical representation. The three highest-wr
staples (Black Cleaver, Death's Dance, Spear of Shojin) are absent from the top-8.
Void Immolation dominates at rank 1 with score 1.89 (vs Trinity Force 1.12) largely
because its 6000g price inflates the d_ehp term (4495 ehp) in the hybrid scorer.

This is a pool gap, not a wrong-axis MISMATCH: the items are AD/physical throughout,
but the hybrid scorer's relative weighting over-rewards high-EHP items (Void
Immolation, Heartsteel) and AA-proc items (BoRK, Trinity, Stormrazor) rather than
the ability-rotation + armor-shred items that empirically win.

---

## Axis 4 - Rune OK: n/a

rune_relevant=false.

---

## Nominated Retune

Reduce hybrid EHP term dominance for Void Immolation (6000g item; d_ehp 4495 at
rank 1 by large margin inflates score to 1.89 vs next item 1.12). Lift ability-haste
+ shred-pen items: Black Cleaver (target_resist shift +7 confirms scorer sees it but
ranks it low in baseline AD-squishy comp), Death's Dance (defensive-AD; hybrid EHP
should capture its DR but it scores below 8), Spear of Shojin (ability-haste; not
reflected in hybrid scoring at all). Consider a cost-normalized per-gold DPS floor
to avoid 6000g items commanding rank 1 vs 3000g alternatives.
