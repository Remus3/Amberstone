# DS Cross-Eval: Rumble

**VERDICT: MINOR**

Scorer: ability | Archetype: mage/bruiser | Evidence tier (ARAM): outcome_all (n=80, baseline wr=46.2)

---

## Axis 1 - archetype_ok: PASS

Scorer=ability is the AP-axis scorer. Rumble is a pure AP mage (Flamespitter/Scrap Shield/Electro-Harpoon/The Equalizer are all AP-scaling). Correct axis.

Empirical cross-check (outcome_all, self n=3 < 8): items above baseline wr 46.2 include Liandry's (r2 scorer, wr 47.2), Shadowflame (r6 scorer, wr 54.8), Rabadon's (r4 scorer, wr 50.0). All above-baseline empirical staples appear in scorer pool. No axis mismatch.

---

## Axis 2 - comp_ok: PASS

Scorer=ability -> primary responsiveness axis is target_resist. responsiveness.target_resist.comp_blind=false, max_positive_shift=5. Abyssal Mask +5, Cryptbloom +3, Bloodletter's Curse +3 vs tanky enemies. Scorer responds correctly to target resist composition.

responsiveness.enemy_damage_type.comp_blind=true with max_positive_shift=0. This is EXPECTED for a pure offensive ability scorer - enemy damage type does not affect AP item recommendations. No EHP axis is active here. Not a defect.

---

## Axis 3 - outcome_ok: FAIL (pool gap)

Scorer top-8 (bal_squishy) vs empirical wr (baseline 46.2):

| Rank | Item | Empirical wr | Empirical n | Status |
|------|------|-------------|-------------|--------|
| 1 | Wooglet's Witchcap | not in top 10 | - | unverified |
| 2 | Liandry's Torment | 47.2 | 72 | OK (above baseline) |
| 3 | Blackfire Torch | not in top 10 | - | unverified |
| 4 | Rabadon's Deathcap | 50.0 | 24 | OK (above baseline) |
| 5 | Void Staff | 42.9 | 14 | below baseline |
| 6 | Shadowflame | 54.8 | 42 | OK (highest wr item) |
| 7 | Stormsurge | not in top 10 | - | unverified |
| 8 | Cryptbloom | not in top 10 | - | unverified |

Pool gaps and underperformers:
- Malignance (id 3118): empirical wr 48.1, n=27 (above baseline) - ABSENT from scorer top 12 entirely. High-wr staple missing.
- Riftmaker (r9 scorer): empirical wr 35.3 (n=17) - 11 points below baseline, still in pool.
- Zhonya's Hourglass (r12 scorer): empirical wr 36.8 (n=19) - 9 points below baseline, still in pool.
- Void Staff (r5): wr 42.9, marginally below baseline.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Add Malignance (id 3118) to ability scorer item pool for Rumble - wr 48.1, n=27 in ARAM, currently absent.
Consider down-weighting Riftmaker (wr 35.3) and Stormsurge (no empirical signal) relative to Shadowflame (wr 54.8) which is underranked at r6 vs r1-r3 burst items.
