# DS Cross-Eval: Maokai

**Verdict: MINOR**
Scorer=ehp, archetype=tank(neutral). Archetype and scorer axis are aligned. Comp responsiveness is working. Two pool issues: Heartsteel is over-ranked vs its empirical losing record; Fimbulwinter (high-volume staple) is absent from the scored pool.

---

## Axis 1 - archetype_ok: PASS

Tank primary, secondary enchanter. Scorer=ehp. Tank is damage-type neutral - ehp is the correct scorer axis. Kit matches: Maokai is a frontline CC tank whose value is soaking damage, not dealing it. No axis mismatch.

---

## Axis 2 - comp_ok: PASS

Scorer=ehp with primary_axis=enemy_damage_type, comp_blind=false.

The responsiveness data confirms movement:
- Abyssal Mask rises +27 ranks when enemy is AP (ap_squishy rank 9 -> ad_squishy rank outside top-12).
- Dead Man's Plate falls -26 ranks when enemy is AP.
- Iceborn Gauntlet falls -28 ranks when enemy is AP.
- Randuin's Omen falls -23 ranks when enemy is AP.
- Kaenic Rookern rises to rank 2 in ap_squishy/ap_tanky vs absent in ad cells.

The scorer is correctly steering armor-stacking vs MR-stacking based on enemy damage type. comp_blind=false is correctly reported.

Note: d_ehp=0.0 for every item in every cell. This appears to be a display-layer zero rather than a scorer signal defect, since the rank shifts above prove the scorer is differentiating. Worth confirming whether the d_ehp column is populated correctly in the comp grid pipeline.

target_resist: comp_blind=true, max_positive_shift=0. Expected for an ehp scorer - enemy resistances do not affect the tank's own EHP, so this axis is correctly invariant.

---

## Axis 3 - outcome_ok: MINOR FLAG

Using evidence_tier ARAM = outcome_all (self n=2, all n=102, baseline wr=48.0).

Scorer top-8 ad_squishy: Void Immolation, Randuin's Omen, Warmog's Armor, Unending Despair, Dead Man's Plate, Heartsteel, Jak'Sho, Sunfire Aegis.
Scorer top-8 bal_squishy: Void Immolation, Warmog's Armor, Jak'Sho, Kaenic Rookern, Heartsteel, Randuin's Omen, Force of Nature, Spirit Visage.

Empirical items above baseline (>48.0 wr):
- Unending Despair: n=38, wr=52.6 -> IN scorer top-8 (ad_squishy rank 4). Aligned.
- Warmog's Armor: n=15, wr=60.0 -> IN scorer top-8 (ad_squishy rank 3, bal_squishy rank 2). Aligned.
- Liandry's Torment: n=25, wr=52.0 -> NOT in scorer pool at all. Liandry's is an AP damage item; its absence from an ehp scorer is expected but it represents a real empirical win path the scorer cannot surface.

Empirical items in scorer top-8 that are LOSING:
- Heartsteel: scorer rank 6 (ad_squishy), rank 5 (bal_squishy). Empirical n=50, wr=44.0 - 4 points below baseline. High sample size, consistent losing record. Scorer is over-ranking Heartsteel.

Staple gap:
- Fimbulwinter: n=56 (2nd most-built item), wr=50.0 (at baseline). Absent from scorer top-12 in any comp cell. As a mana-to-health + slow item it has clear EHP value for Maokai. Its absence is notable given the build frequency.

Void Immolation is rank 1 by a large margin (score 4085 vs rank-2 ~1864) in all comp cells. Score gap of ~2x is an outlier worth inspecting - may reflect a large passive EHP bonus baked into the item that is disproportionate vs other items at similar gold cost.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Investigate Heartsteel over-ranking: empirical wr=44.0 (n=50) vs baseline 48.0 while scorer places it rank 5-6 in both squishy comps. Consider whether Heartsteel's stacking EHP model inflates its score for champions where the stacking is slow to come online (tanks in ARAM fights start without stacks). Add Fimbulwinter to the ehp item pool - its mana-to-HP conversion (passive) and the shield from Frozen Heart adjacency make it a legitimate EHP contributor that the scorer is missing.
