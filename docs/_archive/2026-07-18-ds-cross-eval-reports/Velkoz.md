# Velkoz DS Cross-Eval Verdict

**Severity: MINOR**
**Scorer: ability | Archetype: mage/enchanter**
**Evidence tier ARAM: outcome_self (n=16, baseline wr=62.5%)**

Luden's Echo (wr 66.7% self, 63.1% all) absent from scorer pool; add to ability pool.

---

## Axis 1 - archetype_ok: TRUE

Mage primary -> ability scorer is the correct AP-axis scorer. Empirical top items
are all AP mage items: Liandry's Torment rank 1 (wr 61.5%), Shadowflame rank 3
(wr 70.0%), Blackfire Torch rank 3 (wr 66.7%), Luden's Echo (wr 66.7%). Scorer
axis matches kit and empirical winners. No flag.

## Axis 2 - comp_ok: TRUE

Scorer=ability has no EHP component (all d_ehp=0.0 across every comp cell).
enemy_damage_type is fully comp_blind (max_positive_shift=0, no risers) - this is
EXPECTED for a pure-damage AP scorer that builds no defensive items.
target_resist sub-axis IS responsive: max shift=3 vs tanky; Bloodletter's Curse
+3, Cryptbloom +2, Void Staff +1 when vs AP-tanky. Primary axis is correctly
target_resist. Comp sensitivity is appropriate for the scorer type. No flag.

## Axis 3 - outcome_ok: FALSE (MINOR pool gap)

Use outcome_self (n=16 >= 8). Baseline wr=62.5%.

Above-baseline items in empirical self:
  Sorcerer's Shoes     wr 66.7%  (boot - not in item pool, expected absent)
  Shadowflame          wr 70.0%  (id 4645) -> scorer rank 6 ad_squishy - COVERED
  Luden's Echo         wr 66.7%  (id 6655) -> NOT in scorer top-12 any cell - MISSING
  Blackfire Torch      wr 66.7%  (id 2503) -> scorer rank 3 - COVERED

Luden's Echo is a high-wr staple (self wr=66.7%, all wr=63.1%, n=65 in all) that
is absent from the scorer recommendation pool entirely. Every other above-baseline
item is either covered or a boot. Minor pool gap; no empirically-losing top build.

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Add Luden's Echo (id 6655) to the ability scorer item pool for Velkoz (or verify
it is not filtered out by a pool gate that should be relaxed for poke mages).
