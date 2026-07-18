# DS Cross-Eval: Darius

**Verdict: MINOR**

Scorer: hybrid | Archetype: bruiser/tank | Anchor: ARAM | Evidence: outcome_self (n=13, wr=69.2%)

---

## Axis 1 - archetype_ok: PASS

Darius is bruiser/tank with AD-scaling bleed (passive), W heal, E armor shred, R true-damage execute.
Hybrid scorer is correct for bruiser: it blends EHP and DPS sub-scores on an AD axis. No AP scaling.
Empirical confirms AD-bruiser builds dominate (Trinity Force, Stridebreaker, Sterak's Gage, Sundered Sky).
Archetype assignment and scorer axis are aligned.

## Axis 2 - comp_ok: PASS

Scorer = hybrid (has EHP component), so enemy_damage_type MUST move. comp_blind = false.
- enemy_damage_type: max_positive_shift = 13 (Wit's End rises +13 when AP). Responsive.
- target_resist: max_positive_shift = 18 (Liandry's Torment +18, Black Cleaver +12, LDR +9 when tanky). Responsive.
Both axes shift appropriately. No comp-blind defect.

## Axis 3 - outcome_ok: MINOR FLAG

Baseline wr = 69.2% (outcome_self, n=13).
Items above baseline:
  - Stridebreaker (id=6631, n=8, wr=75.0%) -- ABOVE baseline, high-n staple

Scorer top-8 (ad_squishy / bal_squishy):
  Rank 1  Void Immolation    (1.4635)
  Rank 2  BotRK              (1.2454)
  Rank 3  Trinity Force      (1.1185)
  Rank 4  Runaan's Hurricane (1.0058) -- d_ehp=0, marksman AA item, zero relevance to Darius
  Rank 5  Essence Reaver     (0.9808) -- d_ehp=0, crit-mana marksman item, irrelevant to Darius
  Rank 6  Heartsteel         (0.8426)
  Rank 7  Stormrazor         (0.7746)
  Rank 8  Dusk and Dawn      (0.7650)

Stridebreaker (the sole above-baseline empirical staple, n=8) is absent from the scorer top-8 entirely.
Runaan's Hurricane and Essence Reaver rank #4 and #5 with d_ehp=0 -- pure-DPS marksman items that
are not Darius builds. The hybrid scorer's DPS sub-score is lifting irrelevant AA-scaling items.

Pool gap: Stridebreaker missing. Scorer noise: marksman DPS items inflating ranks 4-5.

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

1. Add Stridebreaker to the Darius bruiser/hybrid scorer item pool or verify it is not being filtered.
2. Apply a melee-champion filter or bruiser-role weight to suppress pure-AA items (Runaan's Hurricane,
   Essence Reaver) that carry d_ehp=0 and are empirically absent from Darius builds.
