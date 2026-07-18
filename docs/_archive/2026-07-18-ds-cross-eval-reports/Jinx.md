# Jinx - DS Scorer Cross-Eval Report

**Verdict: MINOR**
Scorer axis correct (dps/carry/AD-crit-AS), comp responsive. Pool gap: Yun Tal Wildarrows
and The Collector are the two strongest empirical ARAM staples above baseline wr but absent
from scorer top-8. BotRK and Essence Reaver rank high in scorer but have no empirical
above-baseline presence.

Evidence tier: ARAM outcome_self (n=79, baseline wr=64.6%)

---

## Axis 1 - archetype_ok: PASS

- Primary=carry, secondary=bruiser, source=user_cs. Scorer=dps. Correct: Jinx kit is
  pure AD crit/AS (Q AS steroid on rockets/minigun, R crit/AS rocket, no AP scaling).
- Empirical winning builds confirm AD-crit axis: Infinity Edge (wr 66.7%, n=60),
  Runaan's Hurricane (wr 66.7%, n=48), Yun Tal Wildarrows (wr 70.6%, n=34),
  The Collector (wr 77.4%, n=31). All AD-crit items. Archetype assignment correct.

## Axis 2 - comp_ok: PASS

- primary_axis=target_resist, comp_blind=false (outer). This is correct behavior:
  dps scorer tests target_resist axis, not enemy_damage_type (that is EHP territory).
- enemy_damage_type.comp_blind=true is EXPECTED for a dps scorer (no defect).
- target_resist.max_positive_shift=11. Top risers vs tanky comps:
  Serylda's Grudge +11, Liandry's Torment +6, Blackfire Torch +6, Eclipse +5,
  Mortal Reminder +4. Scorer responds to tankiness by promoting armor-pen/% damage.
- Responsiveness is present and directionally correct. PASS.

## Axis 3 - outcome_ok: MINOR

ARAM self above-baseline items (wr > 64.6%, n>=15 for signal):
- Yun Tal Wildarrows: wr 70.6%, n=34 -> NOT in scorer top-8 in any comp cell
- The Collector: wr 77.4%, n=31 -> NOT in scorer top-8 in any comp cell
- Runaan's Hurricane: wr 66.7%, n=48 -> scorer rank 7 (ad_squishy), PRESENT
- Infinity Edge: wr 66.7%, n=60 -> scorer rank 8 (ad_squishy), PRESENT

Scorer top-8 (ad_squishy): Void Immolation (#1, 6000g situational), BotRK (#2),
Essence Reaver (#3), Dusk and Dawn (#4), Stormrazor (#5), Voltaic Cyclosword (#6),
Runaan's Hurricane (#7), Infinity Edge (#8).

- BotRK ranked #2 by scorer; empirical ARAM self shows n=15 wr=66.7% (marginal, at
  baseline). Not a strong empirical winner but not a loser either.
- Essence Reaver at #3 scorer; no appearance in ARAM self top-10. Pool artifact.
- The Collector (wr 77.4%) and Yun Tal Wildarrows (wr 70.6%) - the two highest empirical
  wr items - are both absent from scorer top-8. This is the material gap.

Gap is a pool calibration issue (crit-stacking items likely underweighted vs on-hit
and mana-restore passives that the scorer models). Not a wrong axis; the top scorer
items are at least AD. Severity MINOR.

## Axis 4 - rune_ok: N/A

rune_relevant=false. Jinx is not burst/assassin. Skip.

---

## Nominated Retune

Lift Yun Tal Wildarrows and The Collector scoring weight on the dps carry scorer.
Both are crit-stacking items that synergize with Jinx Q AS and R crit scaling.
The Collector in particular (wr 77.4%, n=31) should be in the scorer top-5.
Investigate whether the scorer models crit-stacking passive synergy or treats
Yun Tal / Collector as generic AD-crit items at base stat value only.
