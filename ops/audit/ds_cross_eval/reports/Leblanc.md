# DS Cross-Eval: Leblanc

**Verdict: MINOR**
Scorer axis aligned; pool gap - Luden's Echo (empirical #1 by frequency) absent from scorer, Rabadon's at scorer rank 4 loses empirically in ARAM self.

---

## Archetype

- Primary: mage / Secondary: assassin / Scorer: ability (AP axis) - correct.
- Kit is pure AP burst/chain-spell; ability scorer maps directly.
- Empirical ARAM self (n=29, baseline 41.4 wr): above-baseline items are Shadowflame (52.9 wr, scorer rank 5), Stormsurge (50.0 wr, scorer rank 7), Sheen (66.7 wr, n=6 small), Ionian Boots of Lucidity (60.0 wr, n=5 boots).
- All above-baseline full items are AP damage items. No AD or bruiser staple outperforms baseline.
- **archetype_ok: true**

---

## Comp Responsiveness

- Scorer primary_axis = target_resist. Max positive shift +5 (Bloodletter's Curse +5, Void Staff +2, Cryptbloom +2, Liandry's +1 when facing AP-tanky). Shadowflame falls -3, Stormsurge -2 vs AP-tanky. This is correct behavior: magic-pen items rise vs tanky, flat-pen items fall.
- enemy_damage_type: comp_blind = true (max_positive_shift = 0, no risers/fallers). This is expected for ability scorer - it is a pure damage-output scorer with no EHP component, so enemy damage type does not shift item rankings. Not a defect.
- Overall comp_blind at responsiveness level = false (target_resist moves).
- **comp_ok: true**

---

## Outcome Alignment

- evidence_tier ARAM = outcome_self, n=29 >= 8. Use self. Baseline wr = 41.4.
- Scorer top-8 (squishy cells reference): Wooglet's Witchcap (#1, 33.6), Liandry's Torment (#2, 32.4), Blackfire Torch (#3, 21.8), Rabadon's Deathcap (#4, 12.6), Shadowflame (#5, 11.5), Void Staff (#6, 11.5), Stormsurge (#7, 9.9), Cryptbloom (#8, 8.6).

Issues:
1. **Luden's Echo** - empirical #1 by frequency (n=25, wr=40.0 - near baseline, not above). Absent from scorer pool entirely. This is the most-purchased item and the scorer has no opinion on it; a pool gap.
2. **Rabadon's Deathcap** - scorer rank #4 (high priority), empirical wr=31.6 (well below 41.4 baseline, n=19). Empirically a losing item in self data; the scorer overvalues it for a burst-assassin mage profile.
3. **Void Staff** - scorer rank #6, empirical wr=0.0 (n=6, very small sample - low confidence; caution on over-weighting).
4. **Sheen** - empirical wr=66.7 (n=6, small), absent from scorer. Interesting for LB reset-weaving but low n.

- Shadowflame (52.9 wr) and Stormsurge (50.0 wr) are above baseline and appear at scorer ranks 5 and 7 - aligned.
- Primary gap: Rabadon's overranked (scorer #4, empirical 31.6 wr); Luden's absent.
- **outcome_ok: false** (MINOR - pool gap and one overranked item vs empirical)

---

## Rune

- rune_relevant: false
- **rune_ok: n/a**

---

## Nominated Retune

Add Luden's Echo to ability scorer item pool for burst-mage profiles; investigate downweighting Rabadon's Deathcap for assassin-mage archetypes (empirical wr 31.6 vs 41.4 baseline in ARAM self, n=19).
