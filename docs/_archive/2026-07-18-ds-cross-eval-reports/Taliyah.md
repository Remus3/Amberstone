# DS Cross-Eval: Taliyah

**Verdict: MINOR**

Scorer: ability | Archetype: mage/enchanter | Anchor: ARAM | Evidence: outcome_self (n=32, baseline wr=46.9%)

---

## Axis 1 - archetype_ok: PASS

Taliyah is a pure AP burst/poke mage (Threaded Volley, Seismic Shove, Unraveled Earth).
Mage archetype -> AP axis -> ability scorer. Correct pairing.

Empirical above-baseline items (>46.9%) from outcome_self are all AP items:
- Sorcerer's Shoes 47.8% (n=23)
- Blackfire Torch 47.8% (n=23)
- Rabadon's Deathcap 54.5% (n=11)
- Luden's Echo 71.4% (n=7)
- Blighting Jewel 57.1% (n=7)
- Needlessly Large Rod 60.0% (n=5)

No AD items appear. Axis alignment confirmed.

---

## Axis 2 - comp_ok: PASS (with note)

Scorer type "ability" -> target_resist should respond to tanky comps; enemy_damage_type
invariance is expected for a pure offense scorer.

target_resist.comp_blind = false, max_positive_shift = 6.
Top risers vs tanky: Bloodletter's Curse +6, Void Staff +3, Cryptbloom +2. Sensible.

enemy_damage_type.comp_blind = true, max_positive_shift = 0. The scorer does not shift items
based on whether enemies deal AD or AP. For an ability scorer without EHP weighting (d_ehp=0.0
in every cell), this is expected; Taliyah has no meaningful defensive item interaction keyed on
enemy damage type. Top-level responsiveness.comp_blind = false (target_resist drives it).

No defect. comp_ok = true.

---

## Axis 3 - outcome_ok: FLAG (MINOR)

Scorer top-8 (ad_squishy / bal_squishy cells):
1. Wooglet's Witchcap 60.38
2. Liandry's Torment 34.20
3. Blackfire Torch 25.13
4. Rabadon's Deathcap 22.68
5. Shadowflame 19.49
6. Void Staff 18.98
7. Stormsurge 16.51
8. Cryptbloom 14.27

Problems:

1. Luden's Echo - empirical wr 71.4% (n=7, above baseline 46.9%), but scorer rank #11.
   Outside top-8; not recommended as a priority item despite best empirical wr in the pool.

2. Blighting Jewel - empirical wr 57.1% (n=7), not visible in scorer top-12 at all.
   Missing from scorer pool entirely.

3. Shadowflame - scorer rank #5 but empirical wr 40.0% (n=15), below baseline 46.9%.
   Scorer is over-weighting it relative to win outcomes.

Blackfire Torch (#3 scorer, 47.8% wr) and Rabadon's Deathcap (#4 scorer, 54.5% wr)
are correctly ranked.

---

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Nominated retune

Boost Luden's Echo rank (currently #11; 71.4% empirical wr). Investigate Blighting Jewel
absence from scorer pool. Review Shadowflame over-scoring for Taliyah kit specifically
(flat magic pen favors one-shot burst vs squishy targets; empirical data shows it underperforms).
