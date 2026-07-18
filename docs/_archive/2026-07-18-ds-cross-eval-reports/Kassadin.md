# Kassadin DS Scorer Cross-Eval

**Verdict: MINOR**
Archetype OK | Comp OK | Outcome FAIL (pool gap) | Rune N/A

---

## Axis 1 - Archetype

- scorer: ability (AP axis)
- primary=mage, secondary=assassin; kit is pure AP (all abilities AP-scaling, passive is magic DR)
- Empirical above-baseline wins (ARAM baseline 44.0%): Seraph's Embrace 54.3%, Lich Bane 66.7%, Sheen 60.0%, Sorcerer's Shoes 51.9% - all AP/mana items
- SR above-baseline (47.6%): Rod of Ages 66.7%, Sorcerer's Shoes 77.8%, Seraph's Embrace 57.1%, Zhonya's 57.1%
- axis = correct

**archetype_ok: true**

---

## Axis 2 - Comp Responsiveness

- scorer = ability; primary_axis = target_resist (correct for mage/ability)
- enemy_damage_type: comp_blind=true, max_positive_shift=0 - expected for AP ability scorer; damage type does not change item axis
- target_resist: comp_blind=false, max_positive_shift=5; Bloodletter's Curse +5, Cryptbloom +3, Void Staff +1 rise vs tanky; Stormsurge -3, Shadowflame -2 fall vs tanky
- penetration items correctly rank up against tanky enemies; burst/proc items correctly fall
- no defect

**comp_ok: true**

---

## Axis 3 - Outcome

Using ARAM outcome_all (self n=2, insufficient; all n=50, baseline wr=44.0%).

Scorer top-8 (ad_squishy / bal_squishy are identical):
  rank1 Wooglet's Witchcap (score 39.9), rank2 Liandry's Torment (31.2),
  rank3 Blackfire Torch (23.0), rank4 Rabadon's Deathcap (15.0),
  rank5 Void Staff (13.8), rank6 Shadowflame (13.8),
  rank7 Stormsurge (11.8), rank8 Luden's Echo (10.3)

Empirical above-baseline items (wr > 44.0%):
  Seraph's Embrace n=35 wr=54.3% - rank NOT in scorer top 8 (absent entirely)
  Sorcerer's Shoes n=27 wr=51.9% - boots, outside item pool scope
  Lich Bane n=9 wr=66.7% - highest empirical wr; NOT in scorer top 8
  Sheen n=10 wr=60.0% - NOT in scorer top 8
  Refillable Potion n=12 wr=58.3% - consumable, not an item
  Mercury's Treads n=6 wr=50.0% - boots

Wooglet's Witchcap (#1 scorer, score 39.9) does not appear in empirical item list at all (too expensive / ARAM pool gap).
Liandry's Torment (#2 scorer) absent from empirical.
Blackfire Torch (#3 scorer) absent from empirical.
Malignance is rank 11 in scorer; empirically wr=41.4% (below baseline) - scorer over-values it relative to outcomes.

Critical misses: Seraph's Embrace (most-played above-baseline item, n=35, 54.3%) and Lich Bane (66.7% wr) are absent from scorer top 8. The ability scorer does not account for Kassadin's mana-scaling synergy (R stacks reduce mana cost; Seraph's + Rod of Ages are core because they enable spam, not pure AP output).

**outcome_ok: false**

---

## Axis 4 - Rune

rune_relevant=false -> n/a

**rune_ok: n/a**

---

## Nominated Retune

Boost Seraph's Embrace and Lich Bane scoring for Kassadin. The ability scorer scores pure-AP burst items (Wooglet's, Liandry's, Blackfire Torch) far above mana-scaling synergy items that empirically win. Kassadin's R-spam loop (mana cost reductions per R cast + Seraph's/Tear mana conversion + Lich Bane proc on R) is not captured. Candidate fix: per-champion mana-synergy weight in ability scorer, or champion-tagged bonus for items with mana->AP conversion that score high on champions with spammable low-CD ultimates.
