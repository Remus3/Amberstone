# Fizz DS Scorer Cross-Eval

**Verdict: MINOR**
Archetype and comp responsiveness are correct. Pool ordering has a meaningful gap: Luden's Echo
is rank 11 in the scorer but empirically one of the top performers (wr 58.3%, n=36, ARAM
baseline 46.7%). Stormsurge is rank 7 in the scorer but empirically below baseline (40.5 wr).

---

## Axis 1 - archetype_ok: true

scorer = ability (AP axis). Fizz primary=mage, secondary=assassin. All abilities scale AP (Q E R
full AP, W on-hit AP). Empirical above-baseline ARAM items are all AP: Luden's Echo 58.3 wr,
Needlessly Large Rod 58.3 wr, Shadowflame 54.1 wr. Ability scorer on AP axis is correct.

## Axis 2 - comp_ok: true

scorer = ability. Primary responsiveness axis = target_resist (not enemy_damage_type).
enemy_damage_type.comp_blind = true (max_positive_shift = 0, no risers). For an ability/mage
scorer the ehp branch is not active, so zero enemy-damage-type sensitivity is expected - not a
defect.
target_resist.comp_blind = false. max_positive_shift = 7 (Bloodletter's Curse +7 when vs tanky,
Cryptbloom +4, Void Staff +2). The scorer correctly steers toward MR-shred vs tanky comps.
No comp-blind defect on the relevant axis.

## Axis 3 - outcome_ok: false (MINOR - pool ordering gap)

Using outcome_all (ARAM, n=107, baseline wr 46.7%). Above-baseline empirical items:
- Shadowflame: wr 54.1% (n=37) - scorer rank 5 in ad_squishy/bal_squishy. OK.
- Luden's Echo: wr 58.3% (n=36) - scorer rank 11. UNDERRANKED. This is a top-3 empirical
  performer sitting outside the scorer top-8.
- Needlessly Large Rod: wr 58.3% (n=24) - not in scorer pool (component item, expected absence).

Scorer overrates:
- Stormsurge: scorer rank 7 (score 6.70 vs baseline), empirical wr 40.5% (n=37) - well below
  baseline. Stormsurge's proc pattern may not align with Fizz's ability burst window.
- Zhonya's Hourglass: scorer rank 9 / 8 (tie), empirical wr 35.5% (n=31) - significantly
  below baseline.

Net: Luden's Echo should rank in top-5 for Fizz ability scorer; Stormsurge should drop below rank
10. No above-baseline empirical staple is absent from the pool entirely, but rank ordering is
materially off.

## Axis 4 - rune_ok: n/a

rune_relevant = false.

---

## Nominated Retune

Boost Luden's Echo ability-scorer weight for Fizz (empirical rank ~2 ARAM, scorer rank 11).
Reduce Stormsurge weight for Fizz (scorer rank 7, empirical wr 40.5% well below 46.7% baseline).
Consider downgrading Zhonya's Hourglass weight (scorer rank 9, empirical wr 35.5%).
