# DS Cross-Eval: Chogath

**Verdict: MINOR**
Scorer: ehp | Archetype: tank/mage | Evidence: outcome_all (ARAM n=165, wr=50.9%)

---

## Axis 1 - archetype_ok: PASS

Tank primary + mage secondary -> ehp scorer is the correct neutral axis for tanks.
Empirical above-baseline items in ARAM (wr > 50.9%): Thornmail 53.3% (n=45),
Fimbulwinter 52.6% (n=38), Giant's Belt 60.9% (n=23, component). All are
defensive/HP items. No AP/mage items above baseline. EHP axis matches what wins.

## Axis 2 - comp_ok: PASS

EHP scorer must respond to enemy damage type. comp_blind=false confirmed.
Max positive shift = 24 ranks when AP-heavy. Top risers when AP:
Abyssal Mask +24, Hollow Radiance +23, Kaenic Rookern +22, FoN +22, Spirit Visage +21.
Top fallers when AD: Iceborn Gauntlet -28, Randuin's -25, Dead Man's Plate -23.
Responsiveness is meaningful and well-calibrated.

target_resist comp_blind=true with shift=0 is expected for an EHP scorer - target
resistance is a DPS-axis concern, not relevant here. No defect.

## Axis 3 - outcome_ok: FAIL (MINOR pool gap)

Reference cells: ad_squishy and bal_squishy top-8.

ad_squishy top-8: Void Immolation, Randuin's Omen, Warmog's, Heartsteel,
Unending Despair, Dead Man's Plate, Jak'Sho, Sunfire Aegis.

bal_squishy top-8: Void Immolation, Warmog's, Heartsteel, Kaenic Rookern,
Jak'Sho, Randuin's, Force of Nature, Spirit Visage.

Empirical above-baseline items:
- Thornmail 53.3% (n=45): ad_squishy rank #9 - just outside top-8; under-ranked
  for AD-heavy comps given empirical win rate.
- Fimbulwinter 52.6% (n=38): ABSENT from all scorer cells (not in any top-12).
  Clear pool gap - it is the 6th most common item in ARAM data and wins above
  baseline but the scorer never recommends it.
- Giant's Belt 60.9% (n=23): component item; not a DS item candidate, not flagged.

Void Immolation ranks #1 in every cell (score 3893) but has zero empirical
presence in the data. Dominant scorer recommendation with no empirical backing
is worth noting but not a blocking MISMATCH by itself.

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

1. Add Fimbulwinter (id 3121) to the ehp scorer item pool for tank archetypes -
   it is a HP+mana tank item with above-baseline ARAM wr (52.6%, n=38) that the
   scorer never surfaces.
2. Consider a mild boost to Thornmail rank in AD-heavy cell (ad_squishy/ad_tanky)
   to bring it from #9 into the top-8 recommendation window given its empirical
   performance (53.3% wr, n=45).
