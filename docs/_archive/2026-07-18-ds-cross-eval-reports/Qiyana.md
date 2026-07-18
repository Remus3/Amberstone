# DS Cross-Eval: Qiyana

**Verdict: MINOR**
Scorer: burst | Archetype: assassin (primary) / mage (secondary) | Evidence: outcome_all (ARAM n=59 wr=37.3)

---

## Axis 1 - archetype_ok: PASS

Archetype primary=assassin -> burst scorer on AD axis. Correct.
Empirical items above ARAM baseline (37.3): The Collector 47.2, Caulfield's 44.4, Hubris 40.0,
Ionian Boots 38.9, Long Sword 38.9. All are AD lethality / component items.
Scorer top-8 (ad_squishy): Umbral Glaive, Essence Reaver, Sundered Sky, IE, Axiom Arc,
Youmuu's, Hubris, Trinity Force. Entirely AD lethality. Axis aligned.

## Axis 2 - comp_ok: PASS

Scorer=burst -> target_resist should move vs tanky; enemy damage type need not.
responsiveness.primary_axis = target_resist, max_positive_shift = 14, comp_blind=false.
Mortal Reminder +14, Black Cleaver +14, LDR +10 when facing tanky. Correct behavior.
enemy_damage_type.comp_blind=true: all 3 squishy cells are identical, both tanky cells are
identical. Burst scorer does not track enemy AP/AD split - expected for AD assassin.
No EHP scorer comp-blind defect.

## Axis 3 - outcome_ok: FAIL (MINOR)

ARAM baseline wr = 37.3 (n=59, outcome_all).
Items above baseline:
  The Collector (id 6676): wr 47.2, n=36 -- ABSENT from scorer top-12 (ad_squishy or bal_squishy)
  Hubris (id 126697): wr 40.0, n=30 -- rank 7 ad_squishy. OK.
  Ionian Boots (id 3158): wr 38.9, n=36 -- boots, not in item pool. expected.
  Long Sword (id 1036): wr 38.9, n=18 -- component, not in item pool. expected.
  Caulfield's Warhammer (id 3133): wr 44.4, n=9 -- component, not in item pool. expected.

The Collector is the single highest-wr completed item at 47.2 with the highest sample count (n=36)
among completed items. It does not appear anywhere in the 12-item scorer list for any squishy cell.
For SR: Profane Hydra wr 56.2 (n=16) does not appear in ARAM top-8. These are pool gaps, not
wrong-axis failures.

## Axis 4 - rune_ok: PASS

rune_relevant=true. Scorer uses rune data. No defect.

---

## Nominated Retune

Investigate why The Collector (id 6676) scores below rank 12 for Qiyana burst scorer.
The Collector provides lethality + execute passive (executes below 5% HP), which aligns
directly with burst assassin burst-kill fantasy. Expected near rank 3-5 behind Umbral Glaive.
Check that execute-threshold passive is registered in burst scorer item-effect pool.
