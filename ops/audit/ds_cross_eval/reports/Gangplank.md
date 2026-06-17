# DS Cross-Eval: Gangplank

**Verdict: MINOR**
Scorer axis aligned (hybrid/AD). Pool gap: Infinity Edge absent from top-8 despite strong empirical backing. Void Immolation holds rank 1 with no empirical presence.

---

## 1. Archetype OK: true

Archetype bruiser/tank, scorer hybrid (AD-axis blend of EHP + DPS).
Gangplank deals physical damage via Parrrley, barrel, and crit autos - AD axis is correct.

Empirical top items all AD/crit: Trinity Force (wr 71.4%, n=63), Infinity Edge (wr 69.4%, n=62), The Collector (wr 63.8%, n=80). No AP items charting. Hybrid scorer axis matches kit and empirical signal.

---

## 2. Comp OK: true

Scorer = hybrid (EHP + DPS). Primary axis = enemy_damage_type, comp_blind = false.

EHP sub-axis does respond to enemy damage type:
- Sunfire Aegis falls -14 vs AP enemies (armor-EHP item correctly penalized vs magic)
- Dead Man's Plate falls -4
- Iceborn Gauntlet falls -3

Wit's End rises +16 (MR item rewarded vs AP). Four other items shift +1.
target_resist also moves: Liandry's +12, Eclipse +9, Lord Dom +8, Black Cleaver +5 vs tanky.

Responsiveness is present on both sub-axes. Not comp_blind. No DEFECT.
Note: Wit's End shift of +16 is the lone large mover on damage_type axis; remaining shifts are small (+1 range). Responsiveness exists but is thin outside Wit's End.

---

## 3. Outcome OK: false

Baseline ARAM wr (outcome_all, n=105): 64.8%.

Above-baseline empirical items (wr > 64.8%):
- Cloak of Agility: wr 83.3%, n=24
- Trinity Force: wr 71.4%, n=63
- Infinity Edge: wr 69.4%, n=62
- Ionian Boots of Lucidity: wr 65.6%, n=64

Scorer top-8 (ad_squishy cell):
1. Void Immolation (score 1.741) - ABSENT from empirical items entirely
2. Trinity Force (score 1.096) - present, wr 71.4% - ALIGNED
3. Blade of The Ruined King (score 1.066) - not in empirical top
4. Heartsteel (score 0.955) - not in empirical top
5. Essence Reaver (score 0.892) - wr 54.8%, BELOW baseline
6. Iceborn Gauntlet (score 0.802) - not in empirical top
7. Runaan's Hurricane (score 0.801) - not in empirical top
8. Dusk and Dawn (score 0.780) - not in empirical top

Gap 1: Infinity Edge (wr 69.4%, n=62) is missing from scorer top-8. This is a high-confidence staple item that empirically wins above baseline but scorer does not surface it.

Gap 2: Void Immolation holds rank 1 (score 1.741) yet does not appear in any empirical item list across 105 ARAM games. This suggests it may not be a real buildable item in this context, or it is too rare to evaluate. Rank 1 with zero empirical presence is a red flag for scorer calibration.

Gap 3: Heartsteel rank 4 has no empirical representation. Runaan's Hurricane rank 7 has no empirical representation. Neither is inherently wrong but both dilute the pool of empirically-validated recommendations.

---

## 4. Rune OK: n/a

rune_relevant = false.

---

## Nominated Retune

Add Infinity Edge to Gangplank scorer item pool - it is the highest-confidence missing staple (wr 69.4%, n=62, above 64.8% baseline). Investigate Void Immolation rank-1 status: confirm whether it is a legitimately buildable item for Gangplank in ARAM and whether its DPS formula is correctly modeled; if not purchasable or extremely rare, it should not dominate rank 1.
