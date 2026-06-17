# Ryze - DS Scorer Cross-Eval Report

**Verdict: MINOR**
Scorer axis and archetype aligned. Comp responsiveness correct. Empirical staples (Rod of Ages, Seraph's Embrace, Cosmic Drive) missing from scorer top-8.

---

## 1. Archetype

- primary=mage, secondary=assassin, source=default
- Scorer: ability (AP-axis)
- Kit: all AP ability damage (Overload, Flux, Spell Flux). Mana-to-AP passive scaling.
- **archetype_ok: true** - ability scorer is the correct axis for an AP mage.

## 2. Comp Responsiveness

- responsiveness.primary_axis = target_resist (correct for a damage-dealing AP mage)
- enemy_damage_type: comp_blind=true, max_positive_shift=0. Expected for a pure AP damage scorer - does not need to care about enemy damage composition.
- target_resist: comp_blind=false, max_positive_shift=8. Bloodletter's Curse rises +8 ranks vs ap_tanky vs ad_squishy. Cryptbloom +4, Void Staff +2 also rise vs tanky.
- **comp_ok: true** - scorer responds correctly on target_resist axis vs tanky enemies. Comp-blindness on enemy damage type is expected behavior for a mage damage scorer.

## 3. Outcome (Empirical vs Scorer Pool)

Evidence tier: ARAM outcome_all (n=106, baseline wr=55.7%).

Scorer top-8 (ad_squishy/bal_squishy, identical ranking):
1. Wooglet's Witchcap
2. Liandry's Torment
3. Blackfire Torch
4. Rabadon's Deathcap
5. Shadowflame
6. Void Staff
7. Luden's Echo
8. Stormsurge

Empirical items above baseline wr=55.7%:
| Item | n | wr |
|---|---|---|
| Cosmic Drive (4629) | 32 | 68.8% |
| Sorcerer's Shoes (3020) | 62 | 62.9% |
| Rod of Ages (6657) | 96 | 57.3% |
| Seraph's Embrace (3040) | 95 | 56.8% |

None of these appear in the scorer top-8. Rod of Ages (n=96, 57.3%) and Seraph's Embrace (n=95, 56.8%) are Ryze's dominant build staples by sample count AND above baseline wr. Cosmic Drive (n=32, 68.8%) is the highest-wr completed item. All three are absent from scorer top-8.

Items in scorer top-8 that are at or below baseline wr empirically:
- Rabadon's Deathcap: 53.3% (rank 4 scorer, below baseline)
- Void Staff: 52.9% (rank 6 scorer, below baseline)
- Blackfire Torch, Shadowflame, Luden's Echo, Stormsurge: appear too rarely to evaluate or not in empirical top-10

Wooglet's Witchcap (228002) scores rank 1 across all comp cells but has no empirical entry in the top-10 - likely low n/not core Ryze item.

**outcome_ok: false** - Ryze's empirical win staples (Rod of Ages, Seraph's Embrace, Cosmic Drive) are absent from scorer top-8. The scorer favors pure-burst AP items; Ryze wins with mana-scaling AP items which the ability scorer does not weight for this champion.

## 4. Rune

- rune_relevant=false
- **rune_ok: n/a**

---

## Nominated Retune

Add mana-AP scaling credit to ability scorer pool for Ryze: Rod of Ages (6657), Seraph's Embrace (3040), and Cosmic Drive (4629) should score above pure-burst items given Ryze's passive mana-to-AP conversion. These are the empirical win-condition items (n=96/95/32, wr=57.3/56.8/68.8%) but score outside top-8.

Alternatively: champion-specific item eligibility tag on Ryze to boost mana-scaling items in the pool ranking.
