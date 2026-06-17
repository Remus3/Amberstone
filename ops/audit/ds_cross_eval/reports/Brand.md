# DS Cross-Eval: Brand

**Verdict: MINOR**
Scorer: ability | Archetype: mage/enchanter | Evidence tier ARAM: outcome_all (n=206, baseline wr=56.3%)

---

## Axis 1 - archetype_ok: PASS

Brand is a pure AP mage (primary mage, secondary enchanter). Scorer = "ability" maps to AP axis. Correct.

Empirical above-baseline items (ARAM all, wr > 56.3%): Liandry's 58.1%, Sorcerer's Shoes 59.1%, Rylai's 62.7%, Malignance 59.2%, Rabadon's 60.0%. All AP items. Scorer top-8 (ad_squishy): Wooglet's #1, Liandry's #2, Blackfire Torch #3, Rabadon's #4, Void Staff #5, Shadowflame #6, Stormsurge #7, Cryptbloom #8. All AP. Axis match confirmed.

---

## Axis 2 - comp_ok: PASS

Scorer primary_axis = target_resist. target_resist shows max_positive_shift=3 with real movers: Bloodletter's Curse +3, Cryptbloom +2, Void Staff +1, Liandry's +1 (squishy -> tanky shift). Scorer adapts to tank-heavy comps correctly.

enemy_damage_type sub-axis is comp_blind=true (max_positive_shift=0, no risers). For an ability/DPS scorer this is expected - Brand's output is pure AP regardless of what enemies deal; the scorer is optimizing outgoing damage, not survivability. The top-level responsiveness.comp_blind=false. No defect here.

---

## Axis 3 - outcome_ok: FAIL (pool gap)

Using outcome_all (self n=3, insufficient). Baseline wr = 56.3%.

Above-baseline empirical items and scorer presence:
| Item | wr | n | Scorer rank (ad_squishy) |
|---|---|---|---|
| Rylai's Crystal Scepter | 62.7% | 118 | ABSENT |
| Malignance | 59.2% | 71 | ABSENT |
| Rabadon's Deathcap | 60.0% | 30 | rank 4 |
| Liandry's Torment | 58.1% | 186 | rank 2 |
| Sorcerer's Shoes | 59.1% | 159 | boots (excluded, OK) |

Rylai's Crystal Scepter (62.7% wr, n=118) is the highest-wr non-boots staple in the dataset and is completely absent from scorer top-8 across all five comp cells. Malignance (59.2%, n=71) is also absent. Both are standard Brand ARAM buys; Rylai's slow enables Liandry's passive proc stacking, which is core to Brand's kit loop.

---

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

Add Rylai's Crystal Scepter and Malignance to the ability scorer item pool for Brand (or investigate why they score below rank 8 - possible AH/ability-frequency weighting mismatch). Rylai's at 62.7% wr with n=118 is the strongest empirical signal in this dataset.
