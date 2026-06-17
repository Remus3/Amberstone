# DS Cross-Eval: Nidalee

**Verdict: MINOR**

Scorer: ability (AP axis). Archetype: mage/assassin. Anchor: ARAM.
Evidence tier ARAM: outcome_self (n=28, baseline wr=32.1%).

---

## Axis 1 - archetype_ok: TRUE

Mage/assassin -> ability scorer = AP axis. Correct. Nidalee's entire damage kit
scales AP (spear, Aspect of the Cougar takedown/pounce). Scorer top-8 in
ad_squishy/bal_squishy are all AP items: Wooglet's Witchcap #1, Liandry's #2,
Blackfire Torch #3, Rabadon's #4, Void Staff #5, Shadowflame #6, Hextech
Gunblade #7, Stormsurge #8. Empirically above-baseline items (ARAM self) are
also all AP: Stormsurge 40.0%, Sorcerer's Shoes 36.4%, Needlessly Large Rod
36.4%, Shadowflame 35.3%, Luden's Echo 33.3% (all > 32.1% baseline). Axis
alignment is solid.

---

## Axis 2 - comp_ok: TRUE

Ability scorer - target_resist responsiveness is expected; enemy_damage_type
comp-blindness is expected (ability scorer does not model damage taken type).
responsiveness.primary_axis="target_resist", comp_blind=false. Max positive
shift +8 (Bloodletter's Curse +8, Cryptbloom +6, Void Staff +2, Liandry +1)
confirms the scorer correctly up-weights MR-pen/MR-shred vs tanky comps.
enemy_damage_type comp_blind=true is not a defect here - ability scorers are
not EHP scorers and are not expected to shift on incoming damage type.

---

## Axis 3 - outcome_ok: FALSE (pool gap)

Using outcome_self (n=28 >= 8). Baseline wr=32.1%.

Above-baseline empirical items (ARAM self):
- Luden's Echo: n=27, wr=33.3% - MOST PLAYED, above baseline
- Sorcerer's Shoes: n=22, wr=36.4%
- Shadowflame: n=17, wr=35.3%
- Needlessly Large Rod: n=11, wr=36.4%
- Stormsurge: n=10, wr=40.0%
- Luden's Echo: present

Scorer top-8 (ad_squishy): Wooglet's Witchcap, Liandry's, Blackfire Torch,
Rabadon's, Void Staff, Shadowflame, Hextech Gunblade, Stormsurge.

MISS: Luden's Echo (n=27, wr=33.3%) is the highest-n empirical item and
above baseline, but is ABSENT from scorer top-12 entirely. The community
core-first item on Nidalee is not in the scorer pool at all.

Secondary note: Wooglet's Witchcap is scorer #1 but has zero empirical
presence (not in self or all top-10 list), suggesting scorer over-weights it
relative to actual play patterns.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Add Luden's Echo to the ability scorer item pool for Nidalee. It is the
most-played item (n=27 in self, n=176 in all) and above baseline wr in both
cohorts (33.3% self, 43.2% all). Its absence from the scorer top-12 is a
clear pool gap. If Wooglet's Witchcap's #1 score is driven by generic AP
power-amp without game-presence weighting, a calibration pass on that item's
weight for Nidalee (or ability scorers broadly) may also be warranted.
