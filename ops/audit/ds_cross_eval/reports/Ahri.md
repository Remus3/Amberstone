# DS Cross-Eval: Ahri

**Verdict: MISMATCH**

Scorer: ability | Archetype: mage/assassin (AP) | Anchor: ARAM | Evidence: outcome_self (n=61, wr=54.1%)

---

## Axis 1 - archetype_ok: PASS

Primary archetype = mage, secondary = assassin. Scorer = ability. Mage/assassin maps to AP axis;
ability scorer is correct for AP skill-shot champions. Empirical confirms: all above-baseline items
(Rabadon's 65.6%, Stormsurge 78.6%, Luden's Echo 58.3%) are AP. No AD items above baseline. Axis aligned.

## Axis 2 - comp_ok: PASS

Ability scorer primary responsiveness axis = target_resist. responsiveness.target_resist.comp_blind = false;
max_positive_shift = 6. Bloodletter's Curse +6, Void Staff +2, Cryptbloom +2, Liandry's +1 when
enemies are tanky/AP. Scorer adapts meaningfully vs armored/MR targets as expected for an ability scorer.

Note: enemy_damage_type.comp_blind = true (no shift). For an ability scorer this sub-axis is not
primary; target_resist responsiveness is what matters. Not flagged at this tier.

## Axis 3 - outcome_ok: FAIL

Top-8 scorer items (ad_squishy/bal_squishy, identical rankings) vs empirical self (n=61, baseline 54.1%):

| Scorer Rank | Item | Empirical WR | Status |
|-------------|------|-------------|--------|
| 1 | Wooglet's Witchcap (228002) | absent from top-10 | FLAG: rank 1, zero empirical signal |
| 2 | Liandry's Torment | 40.0% (n=15) | FLAG: 14pp BELOW baseline |
| 3 | Blackfire Torch | 52.4% (n=21) | borderline below |
| 4 | Rabadon's Deathcap | 65.6% (n=32) | above baseline, OK |
| 5 | Shadowflame | 54.5% (n=33) | marginal above |
| 6 | Void Staff | n/a in self top-10 | weak signal |
| 7 | Stormsurge | 78.6% (n=14) | strong above baseline, OK |
| 8 | Cryptbloom | absent from self top-10 | weak signal |

Missing staple: Luden's Echo scorer rank 12, but empirical self wr 58.3% (n=36) - 4pp above baseline.
Strong real-world item buried at the bottom of the scorer pool.

Critical defects: Wooglet's Witchcap at rank 1 with no empirical support in a 61-game sample.
Liandry's Torment at rank 2 with 40.0% empirical wr - worst-performing frequently-built item.

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

Demote Wooglet's Witchcap (rank 1, empirically absent) and Liandry's Torment (rank 2, wr 40.0%)
in the ability scorer for Ahri. Promote Luden's Echo (empirical self wr 58.3%, scorer rank 12)
into the top-5. Investigate the scorer formula weighting that elevates the 6000g Wooglet's to rank 1
while a high-n high-wr item like Luden's Echo scores rank 12. Likely cause: the ability scorer
rewards total AP scaling without discounting burn/DoT synergy (which disfavors Ahri's burst-and-dash
pattern vs Liandry's ramp profile) and does not have Wooglet's empirical availability gated by mode.
