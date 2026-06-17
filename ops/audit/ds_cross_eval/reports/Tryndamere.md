# DS Cross-Eval: Tryndamere

**Verdict: MINOR**

Scorer: hybrid | Archetype: bruiser/assassin | Anchor: ARAM | Evidence: outcome_all (n=55, baseline wr=49.1%)

---

## Axis 1 - archetype_ok: PASS

Primary bruiser / secondary assassin is a pure AD melee crit kit. Hybrid scorer covers AD
DPS + survivability. Correct axis; no mismatch.

## Axis 2 - comp_ok: PASS

Hybrid has an EHP component so enemy damage-type must shift rankings. comp_blind=false.
Observed shifts confirm movement: Wit's End rises +12 when enemy is AP; Dead Man's Plate
falls -16. Target-resist axis also moves (Liandry's +29, Eclipse +9, Black Cleaver +9 vs
tanky-AP). Responsiveness is working as designed.

## Axis 3 - outcome_ok: FAIL (pool gap)

Scorer top-8 in ad_squishy / bal_squishy vs ARAM all (baseline 49.1%):

| Scorer rank | Item | Empirical wr | n | Note |
|---|---|---|---|---|
| 1 | Void Immolation | absent | 0 | not in empirical pool |
| 2 | Blade of The Ruined King | 39.3% | 28 | BELOW baseline |
| 3 | Runaan's Hurricane | absent | 0 | not in empirical pool |
| 4 | Trinity Force | absent | 0 | not in empirical pool |
| 7 | Heartsteel | 44.1% | 34 | BELOW baseline |
| 8 | Stormrazor | absent | 0 | not in empirical pool |

High-wr empirical staples absent from scorer top-8:

| Item | wr | n |
|---|---|---|
| Titanic Hydra | 63.6% | 11 |
| Berserker's Greaves* | 61.1% | 18 |
| Navori Flickerblade | 58.8% | 17 |
| Mercury's Treads* | 53.8% | 26 |

(*boots; scorer may not pool these - Titanic Hydra and Navori Flickerblade are the
actionable gaps.)

BotRK (scorer rank 2) is the top-played item but wins only 39.3% (10 pp below baseline).
Heartsteel (scorer rank 7) wins 44.1% (5 pp below baseline). Two scorer top-8 items
actively losing in practice. Titanic Hydra at 63.6% and Navori Flickerblade at 58.8%
are high-confidence above-baseline staples that do not appear in the scorer top-8.

## Axis 4 - rune_ok: n/a

rune_relevant=false.

---

## Nominated retune

Investigate why Titanic Hydra (3748) and Navori Flickerblade (6675) score outside top-8
for Tryndamere. Titanic Hydra synergises with his passive HP-scaling / healing; its
absence suggests the hybrid scorer may underweight on-hit HP-ratio effects for this kit.
If the scorer pools boots separately, the Navori gap may be a pool-filter issue rather
than a scoring bug - confirm. BotRK and Heartsteel ranking high while underperforming
empirically is a secondary calibration signal but may reflect ARAM-specific comp matchups
rather than a pure scorer error.
