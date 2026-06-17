# Evelynn DS Cross-Eval Report

**Verdict: MINOR**
Archetype/axis correct. Comp responsive on target_resist. Pool gap: Lich Bane (empirical wr 57.1, n=14) absent from scorer top-12; Luden's Echo underranked (scorer rank 12, empirical wr 62.5, n=8).

---

## 1. Archetype

- archetype: primary=mage, secondary=assassin
- scorer: ability (AP axis)
- Evelynn deals 100% magic damage across all abilities (W charm, Q, E, R). AP axis is correct.
- Empirical ARAM baseline wr: 52.8 (n=36, outcome_all).
- Above-baseline empirical items: Stormsurge 58.8, Luden's Echo 62.5, Lich Bane 57.1, Shadowflame 55.6, Tear of the Goddess 71.4 (n=7, small).
- All above-baseline items are AP items. Archetype alignment confirmed.

**archetype_ok: true**

---

## 2. Comp Responsiveness

- scorer primary_axis: target_resist (not enemy_damage_type).
- responsiveness.comp_blind: false (scorer IS responsive overall).
- enemy_damage_type sub-block: comp_blind=true (max_positive_shift=0, no risers or fallers).
  - This is expected for a pure ability/DPS scorer: item ranks do not shift based on whether enemies deal AD or AP because self-survival (EHP) is not modeled. Evelynn does not build EHP items. No defect here.
- target_resist block: comp_blind=false, max_positive_shift=7.
  - Top risers vs tanky: Bloodletter's Curse +7 (rank 7->not-ranked in squishy), Void Staff +3 (rank 6->rank 3), Cryptbloom +2 (rank 8->rank 6).
  - Top fallers vs tanky: Shadowflame -3, Stormsurge -2, Banshee's Veil -1, Blackfire Torch -1, Lich Bane -1.
  - Scorer correctly promotes penetration items vs tanky and demotes burst-oriented items. Sensible behavior.

**comp_ok: true**

---

## 3. Outcome

Evidence tier ARAM = outcome_all (self n=1, all n=36). Using outcome_all.
Baseline wr: 52.8.

Scorer top-8 (ad_squishy / bal_squishy cells, identical):
1. Wooglet's Witchcap (score 93.8) - no empirical data in items list
2. Liandry's Torment (score 42.7) - not in empirical items
3. Rabadon's Deathcap (score 35.2) - empirical wr 50.0 (below baseline)
4. Blackfire Torch (score 32.5) - not in empirical items
5. Shadowflame (score 31.1) - empirical wr 55.6 (above baseline, n=18) - ALIGNED
6. Void Staff (score 30.7) - empirical wr 42.9 (below baseline)
7. Stormsurge (score 26.5) - empirical wr 58.8 (above baseline, n=17) - ALIGNED
8. Cryptbloom (score 23.0) - not in empirical items

Above-baseline empirical items NOT in scorer top-8:
- Lich Bane: empirical wr 57.1 (n=14) - NOT in scorer top-12 at all; appears only as a top-faller (-1 shift vs tanky). This is the primary gap.
- Luden's Echo: empirical wr 62.5 (n=8) - scorer rank 12 only (score 20.8). Underranked.

Scorer top-8 items absent from or below-baseline in empirical:
- Rabadon's Deathcap rank 3: wr 50.0 (below 52.8 baseline).
- Void Staff rank 6: wr 42.9 (well below baseline).
- Wooglet's Witchcap rank 1: no empirical data to confirm.

The Lich Bane gap is notable: a high-n, above-baseline item is completely absent from the scorer pool top-12 while a low-wr item (Void Staff 42.9) sits at rank 6. Luden's Echo at rank 12 despite wr 62.5 is a secondary gap. Not a catastrophic mismatch (Shadowflame + Stormsurge are both aligned), but the pool misses two of the top empirical winners.

**outcome_ok: false**

---

## 4. Rune Relevance

rune_relevant: false

**rune_ok: n/a**

---

## Nominated Retune

Promote Lich Bane into Evelynn ability-scorer top-8 pool; it is the highest-n above-baseline ARAM item (wr 57.1, n=14) but ranks outside top-12. Investigate why it falls as a faller in scorer vs tanky targets (-1 shift) and whether its ranking correctly accounts for Evelynn's passive on-hit magic damage amplification on Q. Also promote Luden's Echo weighting (currently rank 12, empirical wr 62.5).
