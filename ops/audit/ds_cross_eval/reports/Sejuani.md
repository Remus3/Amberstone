# Sejuani DS Scorer Cross-Eval

**Verdict: MINOR**

Scorer: ehp | Archetype: tank (secondary bruiser) | Anchor: ARAM | Evidence: outcome_self (n=12, wr=50.0%)

---

## Axis 1 - archetype_ok: PASS

tank scorer is neutral (neither AD nor AP axis). Sejuani is primary tank / secondary bruiser.
Empirical above-baseline items (self, >50% wr): Heartsteel 57.1%, Warmog's 66.7%, Plated Steelcaps 60.0%.
All are pure tank/bruiser items. Scorer axis matches what wins. No mismatch.

---

## Axis 2 - comp_ok: PASS

ehp scorer requires enemy_damage_type responsiveness. comp_blind=false. max_positive_shift=27 ranks.
- AP risers: Abyssal Mask +27, Hollow Radiance +24, Spirit Visage +22, Kaenic Rookern +22, FoN +22.
- AP fallers: Iceborn Gauntlet -28, Dead Man's Plate -26, Sunfire Aegis -24, Randuin's Omen -23.
ad_squishy vs ap_squishy top-8 are substantially different pools (armor items vs MR items). Responsiveness is healthy.
target_resist comp_blind=true with shift=0 - expected for a tank EHP scorer (no DPS axis). No defect.

---

## Axis 3 - outcome_ok: MINOR FLAG

Using ARAM self (n=12 >= 8). Baseline wr=50.0%.
Above-baseline empirical items: Heartsteel 57.1%, Warmog's 66.7%, Plated Steelcaps 60.0%.

Scorer top-8 check (ad_squishy | bal_squishy):
- Warmog's Armor: ad_squishy rank 3, bal_squishy rank 2. Present and winning (66.7%).
- Heartsteel: ad_squishy rank 6, bal_squishy rank 5. Present and winning (57.1%).
- Plated Steelcaps: boots, absent from item pool (expected, not a defect).

ARAM all (n=59) shows Fimbulwinter (n=23, wr=56.5%) is completely absent from all comp_grid cells
(not in ad_squishy, bal_squishy, ap_squishy, ad_tanky, or ap_tanky at any rank). This is a pool gap -
Fimbulwinter is the 4th most common item and above the all-sample baseline of 54.2%. Also Thornmail
(wr=59.1%, n=22) only appears in ad_squishy/ad_tanky rank 9; absent from bal_squishy top-8 despite
being a strong win-rate item. Kaenic Rookern (wr=81.8%, n=11) appears in bal_squishy rank 4 and
ap_squishy/ap_tanky rank 2 but missing from ad_squishy entirely.

Top scorer items (Void Immolation rank 1 all cells, score 3800-4527) have no empirical n in self data
at all - Void Immolation does not appear in the ARAM self item list. This warrants attention but
self sample is thin (n=12); not flagging as MISMATCH.

Primary flag: Fimbulwinter absent from scorer pool entirely despite being a high-frequency above-baseline
empirical item.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Add Fimbulwinter (3121) to Sejuani's scored item pool. It is absent from all comp_grid cells despite
n=23, wr=56.5% empirically in ARAM. Investigate whether the mana-to-HP conversion on Fimbulwinter is
being scored - Sejuani has no meaningful mana scaling so it may be scored as near-zero and buried below
the display threshold.
