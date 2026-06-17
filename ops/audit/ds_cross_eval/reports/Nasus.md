# DS Cross-Eval: Nasus - MINOR

**Scorer:** hybrid | **Archetype:** bruiser/tank | **Evidence:** outcome_all ARAM (n=79, baseline wr=54.4%)

---

## Axis 1 - archetype_ok: PASS

Hybrid scorer is AD-axis (EHP+DPS blend). Nasus damage is AD-scaled (Q auto/Siphoning Strike, R armor/health). AD axis is correct for bruiser. No axis mismatch.

## Axis 2 - comp_ok: PASS

Hybrid EHP portion must respond to enemy damage type. comp_blind=false confirmed. When enemy is AP:
- Hollow Radiance rises +8 ranks (MR item, expected)
- Dead Man's Plate falls -4 ranks (armor item, expected)
- max_positive_shift=8

Enemy damage type responsiveness is working. target_resist also moves (max +9, Eclipse/Liandry rise when target is tanky). comp_ok=true.

## Axis 3 - outcome_ok: FAIL (MINOR)

Scorer top-8 in ad_squishy cell vs empirical wr > baseline (54.4%):

| Scorer rank | Item | Empirical wr | Note |
|---|---|---|---|
| 1 | Void Immolation (223069) | absent from data | no empirical signal |
| 2 | Trinity Force (3078) | 50.0% (n=52) | BELOW baseline |
| 3 | Heartsteel (3084) | absent | no signal |
| 4 | Essence Reaver (3508) | absent | no signal |
| 5 | Dusk and Dawn (2510) | absent | no signal |
| 6 | Iceborn Gauntlet (6662) | 90.0% (n=10) | above baseline |
| 7 | Blade of the Ruined King (3153) | absent | no signal |
| 8 | Dead Man's Plate (3742) | absent | no signal |

Empirical above-baseline items absent from scorer top-8:
- Force of Nature (4401): wr 64.7%, n=17 - not in top-8 any cell
- Thornmail (3075): wr 59.3%, n=27 - not in top-8 any cell
- Frozen Heart (3110): wr 55.9%, n=34 - not in top-8 any cell
- Spirit Visage (3065): wr 55.3%, n=47 - not in top-8 any cell
- Sundered Sky (6610): wr 57.1%, n=14 - rank 11 ad_squishy (misses top-8)

Trinity Force (rank 2 scorer) scores below baseline wr 50.0% vs 54.4%. Pure-AD items (Essence Reaver rank 4, BotRK rank 7) have no empirical support. DPS weight in hybrid scorer is overdone relative to what wins empirically. Tank staples with strong wr (Spirit Visage n=47, Frozen Heart n=34, Thornmail n=27, Force of Nature n=17) are all blocked out of top-8 by the DPS component.

## Axis 4 - rune_ok: n/a

rune_relevant=false.

---

## Verdict: MINOR

Archetype axis and comp responsiveness are correct. The pool gap is material: 4 empirically-winning tank items with n>=17 and wr above baseline are absent from the scorer top-8 in all comp cells. Trinity Force at rank 2 underperforms baseline. DPS weight in hybrid is slightly overdone for a bruiser/secondary=tank champion.

## Nominated Retune

Reduce DPS weight in hybrid scorer when archetype secondary=tank so tank-stat items (Spirit Visage, Frozen Heart, Thornmail, Force of Nature) score into top-8; Sundered Sky (wr 57.1%, n=14) already at rank 11, would likely enter top-8 with a modest DPS weight trim.
