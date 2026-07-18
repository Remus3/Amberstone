# DS Cross-Eval Verdict: Akshan

**Verdict: MINOR**
Scorer axis and comp responsiveness are correct. Pool gap: The Collector (highest-sampled above-baseline ARAM item) is absent from scorer top-8.

---

## Axis 1 - Archetype

- Assigned: carry (primary), assassin (secondary), scorer=dps
- Kit: AD marksman/assassin. DPS scorer is the correct AD-carry axis.
- Empirical check (ARAM all, n=106, baseline wr=37.7%): top above-baseline items are BotRK (43.9%), The Collector (41.4%), Mercury's Treads (47.8%), Lord Dominik's Regards (38.9%), Infinity Edge (38.6%). All AD items. No AP staple surfacing above baseline.
- RESULT: archetype_ok=True. No axis mismatch.

---

## Axis 2 - Comp Responsiveness

- Scorer=dps: target_resist responsiveness is the relevant check. Enemy damage type shift is not required for dps scorers (only ehp/hybrid).
- target_resist: comp_blind=false, max_positive_shift=22 (Liandry's Torment +22 vs tanky, Serylda's Grudge +9, Lord Dominik's +7, Mortal Reminder +7, Eclipse +5). Tanky comps correctly promote armor-pen and hybrid items.
- enemy_damage_type: comp_blind=true, max_positive_shift=0. Not a defect for a dps scorer - no ehp component that would need damage-type gating.
- Outer responsiveness: primary_axis=target_resist, comp_blind=false. Scorer is NOT comp-blind overall.
- RESULT: comp_ok=True.

---

## Axis 3 - Outcome Overlap

- Evidence tier ARAM=outcome_all (self n=0). Using ARAM all: n=106, baseline wr=37.7%.
- Items above baseline (empirical winners):
  - Mercury's Treads id=3111, wr=47.8% (n=23) - boots, not in item scorer pool
  - Blade of The Ruined King id=3153, wr=43.9% (n=41) - scorer rank 1 (ad_squishy). ALIGNED.
  - The Collector id=6676, wr=41.4% (n=87) - highest sample, above baseline. ABSENT from scorer top-12 (not listed in ad_squishy or bal_squishy at all).
  - Lord Dominik's Regards id=3036, wr=38.9% (n=36) - scorer rank 12 (ad_tanky), rank not in ad_squishy top-12. Borderline miss.
  - Infinity Edge id=3031, wr=38.6% (n=57) - scorer rank 7 (ad_squishy). ALIGNED.
- Items in scorer top-8 that empirically underperform vs baseline:
  - Kraken Slayer rank 2: empirical wr=37.5% (n=40), just below 37.7% baseline. Minor concern.
  - Runaan's Hurricane rank 3: absent from empirical top-10 entirely (low pick or untracked).
  - Void Immolation rank 4: absent from empirical top-10.
  - Essence Reaver rank 5: absent from empirical top-10.
  - Stormrazor rank 6: absent from empirical top-10.
- PRIMARY FLAG: The Collector (id=6676) is the highest-n above-baseline item (n=87, wr=41.4%) and is completely absent from the scorer top-12 in ad_squishy/bal_squishy. This is a pool gap - the scorer is systematically underweighting it.
- RESULT: outcome_ok=False (pool gap, not a wrong-axis or empirically-losing top build).

---

## Axis 4 - Rune

- rune_relevant=false
- RESULT: rune_ok=n/a

---

## Nominated Retune

Investigate why The Collector (id=6676) scores below top-12 threshold in the dps scorer for Akshan despite being the highest-sample above-baseline ARAM item. Likely the lethality/execute passive is not captured in the dps formula. Lift The Collector into at minimum ad_squishy top-8 for Akshan; verify whether this is a general carry-scorer gap or Akshan-specific.
