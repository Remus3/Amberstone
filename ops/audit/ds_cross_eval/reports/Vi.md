# Vi - DS Scorer Cross-Eval Report

**Verdict: MISMATCH**

Scorer: hybrid | Archetype: bruiser/assassin | Anchor: ARAM | Evidence tier ARAM: outcome_self (n=19)

---

## Axis 1 - archetype_ok: TRUE

Hybrid scorer is AD-oriented. Vi is a melee AD diver/bruiser (Q/E/R all physical, W on-hit).
Hybrid axis is directionally correct. No axis mismatch.

---

## Axis 2 - comp_ok: TRUE

Hybrid has an EHP component. Scorer primary_axis = enemy_damage_type, comp_blind = false.

EHP scores shift with comp as expected:
- Void Immolation d_ehp: 4584.5 (ad_squishy) -> 3928.4 (ap_squishy)
- Heartsteel d_ehp: 1655.0 (ad_squishy) -> 1463.0 (ap_squishy)
- Tanky comps flip BotRK to rank 1 (score 2.31 vs 1.34 in squishy)

Responsiveness max_positive_shift = 13 (Wit's End rises 13 ranks when AP comp).
Dead Man's Plate falls 13 ranks when AP comp. Comp sensitivity is working.

---

## Axis 3 - outcome_ok: FALSE

Using outcome_self (n=19 >= 8). ARAM baseline wr = 42.1%.

Scorer top-8 (ad_squishy): Void Immolation (#1, score 1.51), BotRK (#2, 1.34),
Trinity Force (#3, 0.95), Runaan's Hurricane (#4, 0.90), Essence Reaver (#5, 0.84),
Kraken Slayer (#6, 0.82), Heartsteel (#7, 0.82), Stormrazor (#8, 0.76).

Empirical self top items:
- Sundered Sky: n=13, wr=30.8%
- The Collector: n=9, wr=33.3%
- Mercury's Treads: n=8, wr=12.5%
- Eclipse: n=7, wr=42.9%
- Death's Dance: n=5, wr=60.0%

Overlap between scorer top-8 and empirical self top-5: ZERO.

High-wr staple missing from scorer top-8:
- Death's Dance wr=60.0% - absent from scorer output entirely (not in top-12 for any cell)
- Eclipse wr=42.9% - appears at rank 10 in ad_squishy (score 0.654), not top-8

Scorer top items empirically absent:
- Void Immolation (#1): never seen in empirical data
- Runaan's Hurricane (#4): marksman multi-target item, empirically absent from Vi data
- Essence Reaver (#5): ADC mana/crit item, empirically absent
- Kraken Slayer (#6): ADC anti-tank item, empirically absent
- Stormrazor (#8): ADC crit setup item, empirically absent

The scorer is surfacing a full ADC/marksman item stack for a diver/bruiser champion.
Death's Dance - the single best-performing staple at 60% wr - is not in the scorer output.

---

## Axis 4 - rune_ok: n/a

rune_relevant = false.

---

## Nominated Retune

Pool restriction: exclude pure ADC/crit/marksman items (Runaan's Hurricane, Essence Reaver,
Kraken Slayer, Stormrazor) from Vi's eligible item set, or add archetype-gating in the hybrid
scorer to filter items incompatible with melee divers (no ranged-required passives, no
multi-target bounce passives that only hit ranged AA).

Pool promotion: Death's Dance (60% wr empirical, 0% scorer presence) and Sundered Sky
(most-built empirical item) should appear in Vi's scorer top-8. Black Cleaver and Sterak's
Gage are empirically present in SR data (50% and 66.7% wr respectively) and should be
accessible in the scorer pool.

Root cause likely: hybrid DPS subcomponent over-weights raw attack-speed / on-hit synergy
that scores well on paper for Vi's high base AD but that Vi does not build in practice
because she is a dive/CC initiator, not a sustained auto-attack DPS champion.
