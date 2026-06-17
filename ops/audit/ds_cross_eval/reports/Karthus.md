# Karthus DS Cross-Eval Report

**Verdict: MINOR**
Scorer axis correct. Comp responsiveness OK. Malignance missing from scorer pool; Shadowflame and Stormsurge over-ranked vs empirical.

---

## 1. Archetype / Scorer Axis

primary=mage, secondary=assassin, scorer=ability (AP axis). Correct.
Karthus deals pure AP magic damage (Q, E passive, R). All empirical above-baseline items are AP:
- Blackfire Torch: 70.0% wr (n=10, ARAM self, baseline 56.2%)
- Sorcerer's Shoes: 63.6% wr (n=11)
- Malignance: 62.5% wr (n=8)
- Rabadon's Deathcap: 60.0% wr (n=10)

Scorer top-2 (Wooglet's Witchcap rank 1, Liandry's rank 2) are AP. No axis mismatch.

**archetype_ok: true**

---

## 2. Comp Responsiveness

scorer=ability -> primary_axis=target_resist. Expected: target_resist moves, enemy_damage_type blind.

enemy_damage_type: max_positive_shift=0, comp_blind=true. Correct - Karthus deals damage not
survives it; the ability scorer does not adapt to enemy AD/AP share. No defect.

target_resist: max_positive_shift=3 (Bloodletter's Curse +3, Void Staff +2, Cryptbloom +2 vs tanky).
Scores shift appropriately when enemies are AP-tanky (MR targets). comp_blind=false at top level.

**comp_ok: true**

---

## 3. Outcome Overlap (ARAM outcome_self, n=16 >= 8)

Baseline wr: 56.2%.

Empirical above-baseline items (ARAM self):
- Blackfire Torch: 70.0% (n=10)
- Sorcerer's Shoes: 63.6% (n=11) [boots, separate slot]
- Malignance: 62.5% (n=8)
- Rabadon's Deathcap: 60.0% (n=10)

Scorer top-8 (bal_squishy): Wooglet's(1), Liandry's(2), Blackfire Torch(3), Rabadon's(4),
Void Staff(5), Shadowflame(6), Stormsurge(7), Cryptbloom(8).

Overlap hits:
- Blackfire Torch: scorer rank 3, empirical 70.0% - GOOD
- Rabadon's Deathcap: scorer rank 4, empirical 60.0% - GOOD

Pool gap:
- Malignance (62.5% wr, n=8; 60.5% all n=76) is absent from scorer top-8. Malignance grants
  ult haste - a direct Karthus R amplifier - and is a primary staple by frequency. Missing.

Over-ranked items (in top-8 but below baseline empirically):
- Shadowflame: scorer rank 6, ARAM self wr 50.0% (n=12, below baseline 56.2%)
- Stormsurge: scorer rank 7, ARAM self wr not listed (below threshold). Falls -2 vs tanky.

**outcome_ok: false**

---

## 4. Rune Relevance

rune_relevant=false -> n/a.

**rune_ok: n/a**

---

## Nominated Retune

Promote Malignance into scorer pool (ult-haste passive is a direct Karthus R DPS multiplier;
62.5% wr self, 60.5% all, n=76 all). Demote Shadowflame and Stormsurge - both underperform
empirically for Karthus (50.0% and unlisted wr vs 56.2% baseline) and Stormsurge falls 2 ranks
vs tanky comps where Bloodletter's/Void Staff are stronger. Shadowflame is a burst-amp item less
suited to Karthus's sustained AoE profile.
