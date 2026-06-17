# DS Cross-Eval: Caitlyn

**Verdict: MINOR**

Scorer: dps | Archetype: carry(primary) / bruiser(secondary) | Anchor: ARAM
Evidence tier (ARAM): outcome_self (n=42, baseline wr=47.6)

---

## Axis 1 - archetype_ok: PASS

carry + dps = AD axis. Correct for Caitlyn (physical auto/trap scaling). Empirical above-baseline items are all AD physical (Berserker's Greaves 51.6, The Collector 52.2, Lord Dominik's Regards 54.5, Bloodthirster 60.0). Axis match confirmed.

## Axis 2 - comp_ok: PASS

dps scorer -> target_resist must move vs tanky; enemy_damage_type comp_blind is expected for dps (not EHP). responsiveness.primary_axis = target_resist, comp_blind=false. max_positive_shift = +16 (Liandry's Torment +16, Serylda's Grudge +9, Eclipse +7 when targets tanky). Comp adaptation on the correct axis. No defect.

Note: enemy_damage_type.comp_blind=true with shift=0 is benign for a dps scorer - damage type affects the player's survivability axis (ehp), not dps output.

## Axis 3 - outcome_ok: FAIL (MINOR)

Scorer top-8 (ad_squishy): BotRK(1, 81.9), Runaan's Hurricane(2, 61.3), Void Immolation(3, 61.3), Essence Reaver(4, 56.7), Kraken Slayer(5, 52.4), Stormrazor(6, 49.7), Yun Tal Wildarrows(7, 42.5), Infinity Edge(8, 41.9).

Empirical above-baseline (wr > 47.6, self n>=5):
- Berserker's Greaves: wr=51.6, n=31 - NOT in scorer top-8
- The Collector: wr=52.2, n=23 - NOT in scorer top-8
- Lord Dominik's Regards: wr=54.5, n=11 - NOT in scorer top-8
- Bloodthirster: wr=60.0, n=5 - NOT in scorer top-8

BotRK is scorer rank 1 (81.9) but empirically wr=47.2 (n=36) - at or below baseline. Scorer over-weights BotRK relative to actual winrate.

Pool gaps: The Collector (n=23, wr=52.2) and Lord Dominik's Regards (n=11, wr=54.5) are consistent above-baseline winners absent from the scorer top-8. Yun Tal Wildarrows appears scorer rank 7 but wr=35.0 in self (below baseline by 12.6pp, n=20) - scorer is recommending a consistently losing build path.

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Boost The Collector and Lord Dominik's Regards in the DPS scorer pool for Caitlyn. Investigate BotRK rank-1 dominance (81.9 score vs 47.2 empirical wr) - likely over-weighted percent-health passive. Penalize Yun Tal Wildarrows - scorer rank 7 but wr=35.0 in self (n=20).
