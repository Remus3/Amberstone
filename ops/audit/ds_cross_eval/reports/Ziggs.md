# DS Cross-Eval: Ziggs

**Verdict: MINOR**

Scorer: ability | Archetype: mage/assassin | Anchor: ARAM | Evidence tier: outcome_self (n=11, wr=54.5)

---

## Axis 1 - archetype_ok: PASS

Mage primary -> ability scorer -> AP axis. Correct. All top scorer items are AP (Wooglet's, Liandry's, Blackfire Torch, Rabadon's, Void Staff). Empirical above-baseline items (wr > 54.5 from self): Blackfire Torch 55.6, Refillable Potion 60.0. Both are AP or consumable. No AD items are present in the scorer pool. Axis alignment is correct.

## Axis 2 - comp_ok: PASS (with note)

Primary axis is target_resist. target_resist.comp_blind=false, max_positive_shift=3. Risers vs AP-tanky: Bloodletter's Curse +3, Void Staff +2, Cryptbloom +2, Liandry's +1. Fallers: Shadowflame -2, Stormsurge -2. The scorer responds appropriately to armor-stacking enemies.

enemy_damage_type: max_positive_shift=0, comp_blind=true. For a pure-damage mage scorer, the ability scorer does not model self-EHP adjustments in response to enemy damage type - this is expected behavior for a caster who doesn't itemize defensively based on enemy composition. Acceptable.

Note: all d_ehp and d_dps values are 0.0 across every comp cell and every item. The scorer produces no delta-EHP or delta-DPS signal at all; comp responsiveness is carried entirely by target_resist rank shifts. This is technically correct for the ability scorer archetype but means the comp_grid provides no EHP/DPS guidance.

## Axis 3 - outcome_ok: MINOR FLAG

Reference cell: ad_squishy (squishy typical). Scorer top-8: Wooglet's Witchcap(1), Liandry's Torment(2), Blackfire Torch(3), Rabadon's Deathcap(4), Void Staff(5), Shadowflame(6), Stormsurge(7), Cryptbloom(8).

Empirical self (n=11, baseline wr=54.5):
- Blackfire Torch: wr 55.6 (above baseline) - scorer rank 3. ALIGNED.
- Liandry's Torment: wr 50.0 (below baseline, n=10) - scorer rank 2. FLAG: scorer rates it #2 but it's losing empirically.
- Sorcerer's Shoes: wr 44.4 (below baseline) - not in scorer pool (boots excluded). Expected absence.
- Refillable Potion: wr 60.0 (above baseline) - consumable, correctly absent from scorer.

Wooglet's Witchcap (scorer #1) has zero empirical appearances in self pool - no coverage to validate.

In the all pool (n=157, wr=56.7): Shadowflame has wr 39.3 (n=61), well below 56.7 baseline, yet it sits at scorer rank 6. Seraph's Embrace has wr 62.5 (n=24) and is absent from scorer top-12 entirely - that is a missing high-wr staple.

Flags: Liandry's overranked vs self empirical; Shadowflame in scorer top-8 with poor all-pool wr; Seraph's Embrace (wr 62.5 in all, n=24) missing from scorer entirely.

## Axis 4 - rune_ok: n/a

rune_relevant=false.

---

## Nominated Retune

Audit Seraph's Embrace registration for Ziggs in the ability scorer - it has strong empirical wr (62.5, n=24 in all) but is entirely absent from the scorer pool top-12. Verify whether the mana-stacking passive / AP-from-mana formula is captured. Also review Liandry's weight vs Shadowflame: empirical data suggests Liandry's loses slightly on small self sample but Shadowflame loses badly in the large all pool (39.3, n=61) yet both rank highly. Shadowflame weight reduction vs AP-tanky enemies warranted.
