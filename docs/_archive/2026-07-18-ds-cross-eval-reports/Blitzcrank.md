# DS Cross-Eval: Blitzcrank

**Verdict: MINOR**

Scorer: ehp | Archetype: tank (secondary: enchanter) | Anchor: ARAM
Evidence tier (ARAM): outcome_self (n=11, wr=36.4%) | SR: outcome_all

---

## Axis 1 - archetype_ok: PASS

Tank archetype -> ehp scorer -> neutral axis. Correct. Blitzcrank kit is a hook/CC/shield support with
no meaningful AD or AP scaling on core items. EHP is the right optimization target for this role.

## Axis 2 - comp_ok: PASS

scorer = ehp, primary_axis = enemy_damage_type, comp_blind = false.
Max positive shift = 27 ranks (Abyssal Mask +27 when AP).
Top risers when AP: Abyssal Mask +27, Hollow Radiance +24, Spirit Visage +22, Kaenic Rookern +22, Force of Nature +22.
Top fallers when AP: Iceborn Gauntlet -27, Dead Man's Plate -25, Sunfire Aegis -24, Randuin's Omen -21.
Grid cells confirm: ap_squishy/ap_tanky push MR items to top-3 (Kaenic Rookern #2, Force of Nature #3);
ad_squishy/ad_tanky push armor items up (Randuin's Omen #2, Dead Man's Plate #5).
EHP scorer behaving correctly. target_resist is comp_blind but irrelevant for tank ehp scorer
(does not need to shift based on enemy resistance - no dps component).

## Axis 3 - outcome_ok: FAIL (pool gap)

Used outcome_self (n=11 >= 8). Baseline wr = 36.4%.
Above-baseline empirical items:
  - Fimbulwinter (3121): n=8, wr=50.0% (self) / 53.2% (all, n=111) - ABSENT from all scorer cells
  - Mercury's Treads (3111): n=8, wr=37.5% (self) / 54.8% (all, n=93) - boots, not main item slot
  - Warmog's Armor (3083): wr=52.9% (all) - scorer rank 3 in ad_squishy, rank 2 in bal_squishy - OK
  - Thornmail (3075): wr=50.0% (all) - scorer rank 9 in ad_squishy - minor gap
  - Frozen Heart (3110): wr=55.9% (all, n=34) - not in scorer top-8 in any cell (armor+mana item for mana-stacking Blitzcrank) - secondary gap

Fimbulwinter is the highest-wr empirical item and most validated (n=111 all, 53.2% wr; 50.0% self).
It does not appear in ANY scorer cell. This is a real pool gap: mana-to-health + shield passive makes
Fimbulwinter a natural Blitzcrank pick but the ehp scorer does not model it.
Frozen Heart (55.9% wr, n=34) similarly absent from top-8; Blitzcrank's passive and mana pool make
mana-scaling items uniquely valuable but scorer does not capture this.

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

Add Fimbulwinter (3121) and Frozen Heart (3110) to ehp scorer item pool for Blitzcrank.
Fimbulwinter: empirical ARAM wr=53.2% (n=111) / self 50.0% (n=8) - absent from all comp cells.
Frozen Heart: empirical ARAM wr=55.9% (n=34) - absent from scorer top-8.
Both items have mana synergy with Blitzcrank passive (mana -> shield scaling on Overdrive/passive)
that the current ehp scorer does not capture. This is a scorer pool gap, not an axis error.
