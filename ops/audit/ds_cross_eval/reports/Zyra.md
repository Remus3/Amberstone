# DS Cross-Eval: Zyra

**Verdict: MINOR**
Archetype and scorer axis are correct. Comp responsiveness on target_resist is functional. Pool gap: two high-win-rate empirical staples (Oblivion Orb 64.3% wr, Malignance 62.5% wr) are absent from scorer top-8, both below rank 12 or not surfaced at all.

---

## Axis 1 - archetype_ok: true

Zyra archetype primary=mage, secondary=enchanter. Scorer=ability. Mage/enchanter maps to AP axis; ability scorer is the correct choice. Empirical ARAM all (n=120, baseline wr=51.7%) shows exclusively AP items at the top of purchase frequency: Liandry's (n=109), Rylai's (n=79), Blackfire Torch (n=75). No AD items appear in the top-10. Archetype and scorer axis are aligned.

---

## Axis 2 - comp_ok: true

Scorer=ability (mage DPS). Primary axis per responsiveness field = target_resist. Enemy damage type sub-axis: comp_blind=true, max_positive_shift=0, no risers. This is expected for ability scorer - Zyra's item selection is not driven by what type of damage the enemy deals; she builds the same AP DPS kit regardless. The target_resist axis is NOT blind (comp_blind=false at that level). Max positive shift = 5 rank positions. Bloodletter's Curse shifts +5 ranks (rank 7 in ad_squishy, rank 2 in ad_tanky/ap_tanky by net movement), Void Staff +2, Cryptbloom +2 vs tanky enemies. Penetration items correctly rise vs tanky comps. Ability scorer comp_ok for its axis.

---

## Axis 3 - outcome_ok: false

evidence_tier ARAM = outcome_all (self n=3, too small). Use all: n=120, baseline wr=51.7%.

Empirical items above baseline:
- Oblivion Orb (id 3916): wr 64.3%, n=28 - NOT in scorer top-8 across any comp cell
- Malignance (id 3118): wr 62.5%, n=24 - NOT in scorer top-8 across any comp cell
- Ionian Boots of Lucidity (id 3158): wr 60.0%, n=20 - boots, scorer exclusion expected
- Rabadon's Deathcap (id 3089): wr 58.8%, n=17 - scorer rank 4 (squishy cells), PRESENT
- Liandry's Torment (id 6653): wr 51.4%, n=109 - scorer rank 1, present (marginally below baseline)

Scorer top-8 squishy (ad_squishy / bal_squishy, identical): Liandry's(1), Wooglet's(2), Blackfire Torch(3), Rabadon's(4), Shadowflame(5), Void Staff(6), Stormsurge(7), Cryptbloom(8).

Oblivion Orb (GW component, not a completed item but significant purchase) and Malignance (ultimate-haste, high-sample high-wr) are both absent. These are the two strongest above-baseline empirical signals. Pool gap confirmed. outcome_ok=false.

---

## Axis 4 - rune_ok: n/a

rune_relevant=false.

---

## Nominated Retune

Check ability scorer valuation path for Oblivion Orb (id 3916, grievous wounds) and Malignance (id 3118, ultimate-haste). Both have high empirical win rate (64.3% and 62.5% respectively in ARAM, n>=24) but do not surface in scorer top-8. Likely missing because ability scorer weights AP/damage throughput and neither item maximizes raw AP output - Oblivion Orb is a component/GW tool, Malignance trades raw damage for CDR on ult. Consider adding a utility bonus for GW + ult-haste items on mage champions where empirical signal is strong, or validate that the scorer's stat weights structurally under-value these.
