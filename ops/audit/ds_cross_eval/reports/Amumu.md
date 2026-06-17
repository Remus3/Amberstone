# DS Cross-Eval: Amumu
verdict: MINOR
scorer: ehp | archetype: tank (secondary: enchanter) | anchor: ARAM | evidence: outcome_all (n=113, wr=50.4)

---

## Axis 1 - archetype_ok: true

tank = neutral scorer axis; ehp is the correct scorer for a pure initiator/HP-stacker kit.
No AD or AP identity conflicts. Source = default, consistent with role.

---

## Axis 2 - comp_ok: true

EHP scorer must respond to enemy_damage_type. It does:
- comp_blind = false
- max_positive_shift = 27 (Abyssal Mask), Kaenic Rookern +22, Force of Nature +22
- fallers when AP: Iceborn Gauntlet -28, Dead Man's Plate -26, Sunfire Aegis -24

target_resist is comp_blind (shift=0, no risers) which is expected: Amumu is the tank being
targeted, not a damage dealer; resist-stacking EHP is correct, target-resist irrelevant.

---

## Axis 3 - outcome_ok: false

ARAM self n=7 (<8), using outcome_all (n=113, wr=50.4).

Above-baseline empirical items (wr > 50.4):
  Fimbulwinter     id 3121  n=58  wr=55.2  -- highest volume above-baseline item
  Plated Steelcaps id 3047  n=22  wr=68.2  -- boot, likely scorer-excluded by design
  Liandry's Torment id 6653 n=15  wr=60.0  -- AP niche, above baseline

Scorer top-8 (ad_squishy, primary squishy cell):
  rank 1 Void Immolation, rank 2 Randuin's Omen, rank 3 Warmog's Armor,
  rank 4 Unending Despair, rank 5 Dead Man's Plate, rank 6 Heartsteel,
  rank 7 Jak'Sho, rank 8 Sunfire Aegis

FLAGS:
  - Fimbulwinter (n=58, wr=55.2) is ABSENT from all 5 comp cells entirely.
    It is the single highest-volume above-baseline item for Amumu in ARAM.
    Missing from scorer pool = pool gap.
  - Sunfire Aegis ranks 8th in scorer (ad_squishy, bal_squishy) but empirical
    wr=49.1 (below baseline 50.4, n=55). Over-ranked vs outcome.
  - Liandry's Torment appears in ap_squishy/ap_tanky cells only (rank 9 ap_squishy),
    but empirically wr=60.0 (n=15). Weak scorer presence relative to win rate.

---

## Axis 4 - rune_ok: n/a

rune_relevant = false.

---

## Nominated retune

1. Add Fimbulwinter to the tank EHP item pool so it can compete in scorer ranking.
   It is Amumu's most-played above-baseline item (n=58, wr=55.2) and is currently
   invisible to the scorer.
2. Audit Sunfire Aegis weighting in the tank EHP scorer: empirical wr=49.1 (n=55,
   below 50.4 baseline) suggests it is over-valued relative to outcome.
