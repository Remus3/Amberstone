# KogMaw DS Cross-Eval Report

**VERDICT: MISMATCH**

Scorer: ability (AP axis). Archetype: primary=mage, secondary=carry.
Evidence tier: ARAM=outcome_self (n=9).

---

## Axis 1 - archetype_ok: FALSE

Scorer=ability maps to the AP axis. KogMaw has a hybrid kit (W grants on-hit AP scaling, R is global AP),
but empirically winning builds are on-hit/carry, not AP caster.

ARAM self baseline wr: 44.4% (n=9). Items above baseline in self:
- Berserker's Greaves (n=8, wr=50.0%)

ARAM all baseline wr: 42.6% (n=148). Items above baseline in all:
- Terminus (n=33, wr=51.5%)
- Wit's End (n=35, wr=51.4%)
- Berserker's Greaves (n=91, wr=46.2%)

All three winners are on-hit/AD carry items. The mage/ability axis is wrong vs what empirically wins.

---

## Axis 2 - comp_ok: TRUE

Scorer=ability. Expected: target_resist moves vs tanky (AP penetration items rise), enemy_damage_type
should be comp_blind (ability scorers don't weight d_ehp by incoming damage type).

Observed:
- enemy_damage_type.comp_blind=true, max_positive_shift=0 - CORRECT for ability scorer
- target_resist.comp_blind=false, max_positive_shift=5
  - Bloodletter's Curse +5 rank shift (rank 7 ad_tanky vs rank 12 ad_squishy)
  - Void Staff +2, Cryptbloom +2 vs tanky

Target_resist responsiveness is present and correct for an AP ability scorer.
comp_ok=true (conditional on the scorer being correct - which it is not, see axis 1).

---

## Axis 3 - outcome_ok: FALSE

Evidence tier = outcome_self (n=9 >= 8). Scorer top-8 items (ad_squishy/bal_squishy cells):
1. Liandry's Torment (score 25.90)
2. Wooglet's Witchcap (21.24)
3. Blackfire Torch (17.02)
4. Rabadon's Deathcap (7.98)
5. Shadowflame (7.28)
6. Void Staff (7.26)
7. Stormsurge (6.23)
8. Cryptbloom (5.44)

Self empirical items: Berserker's Greaves, BotRK, Guinsoo's Rageblade.
- None of the scorer top-8 appear in self empirical items at all.
- Liandry's Torment (rank 1) appears in outcome_all at wr=37.1% vs 42.6% baseline - actively losing.
- Wit's End (51.4%), Terminus (51.5%), and Berserker's Greaves (50.0%) - all empirically winning -
  are entirely absent from scorer top-8.

Complete pool miss: scorer recommends AP caster items, players win with on-hit items.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Switch archetype primary to "carry" (secondary keep "mage" or drop), scorer to "carry" or "dps".
This would surface on-hit items (Wit's End, Terminus, BotRK, Guinsoo's, Berserker's Greaves)
that empirically win instead of AP caster items that empirically lose.
The W on-hit AP scaling is real but secondary to the on-hit carry pattern in practice.
