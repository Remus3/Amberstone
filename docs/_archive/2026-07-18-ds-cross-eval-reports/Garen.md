# DS Cross-Eval: Garen

VERDICT: MINOR

Scorer: hybrid | Archetype: bruiser/tank | Anchor: ARAM | Evidence: outcome_all (ARAM n=138 wr=43.5%, SR n=40 wr=62.5%)

---

## Axis 1 - archetype_ok: PASS

Bruiser/tank with hybrid scorer = AD axis. Garen is a melee AD bruiser with no AP scaling. AD axis is correct. Empirical above-baseline winners (ARAM >43.5%): Infinity Edge 48.5%, Heartsteel 46.4%, Mercury's Treads 46.3%, Force of Nature 50.0%, Thornmail 59.3%. All are AD-friendly or tank items consistent with an AD-axis scorer. No axis mismatch.

---

## Axis 2 - comp_ok: PASS

Scorer = hybrid; primary_axis = enemy_damage_type; comp_blind = false. The scorer is responsive: Wit's End rises +14 ranks when enemies are AP-heavy; Hollow Radiance +7; Sunfire Aegis falls -6 (armor-based item less valuable vs AP). Max positive shift = 14. Target_resist axis also moves (Black Cleaver +10 vs tanky, Mortal Reminder +9). No comp-blind defect. Comp responsiveness is functioning.

---

## Axis 3 - outcome_ok: FAIL (MINOR - pool gaps + inappropriate item)

Top-8 scorer pool (ad_squishy reference): Void Immolation (rank 1, 6000g mythic), Trinity Force (rank 2, score 1.675), Heartsteel (rank 3, score 1.355), Essence Reaver (rank 4, score 1.295), Dusk and Dawn (rank 5), Iceborn Gauntlet (rank 6), Blade of the Ruined King (rank 7), Dead Man's Plate (rank 8, score 0.968).

Empirical above-baseline items missing from scorer top-8:
- Thornmail (ARAM wr 59.3%, n=27): not in scorer top-8 in any cell
- Force of Nature (ARAM wr 50.0%, n=26): not in scorer top-8 in any cell
- Infinity Edge (ARAM 48.5% n=33, SR 85.7% n=7): not in top-8 (appears rank 12 at best in bal_squishy)
- Stridebreaker (SR wr 62.2% n=37, ARAM wr 41.8% n=98): not in scorer top-8 in any cell
- Mortal Reminder (SR wr 71.4% n=14): not in top-8 (rises +9 via target_resist but still outside top-8)
- Phantom Dancer (SR wr 72.7% n=22): not in scorer pool at all

Inappropriate item: Essence Reaver rank 4 (score 1.295, d_dps 23.6). Garen has no mana resource - Essence Reaver's mana-restore passive is dead value. Its scorer rank is driven by raw AD + CDR stats, not Garen-specific pool filtering.

Dead Man's Plate (rank 8 scorer, SR wr 75.0% n=8) and Heartsteel (rank 3 scorer, ARAM wr 46.4% n=28) are correctly present.

---

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

1. Add Stridebreaker, Thornmail, Force of Nature, and Infinity Edge to Garen scorer-eligible pool - all are high-wr empirical staples absent from top-8.
2. Investigate why Essence Reaver ranks top-4 for a mana-less champion; apply a Garen-specific pool exclusion or a mana-gated item penalty to items whose primary passive requires mana.
3. Severity remains MINOR - no axis mismatch, no comp-blind defect, but the pool gap is broad (5-6 high-wr items absent).
