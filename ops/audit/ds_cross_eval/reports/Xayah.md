# Xayah DS Cross-Eval Report

**Verdict: MISMATCH**
BotRK is scorer rank-1 but wins only 25.0% in empirical self (baseline 55.8%); Statikk Shiv (66.7% wr, n=15) and The Collector (64.3% wr, n=14) are top empirical winners absent from scorer top-8.

---

## Axis 1 - archetype_ok: TRUE

archetype.primary=carry, scorer=dps. Carry is AD-oriented; dps scorer is the correct axis for a sustained-AA crit ADC like Xayah. Empirical winners are all AD crit/attack-speed items (Navori Flickerblade 60.0%, Infinity Edge 57.7%, Statikk Shiv 66.7%, The Collector 64.3%). No axis mismatch.

---

## Axis 2 - comp_ok: TRUE

scorer=dps -> primary_axis=target_resist. responsiveness.target_resist.comp_blind=false, max_positive_shift=22. Top risers vs tanky: Liandry's Torment +22, Serylda's Grudge +8, Lord Dominik's Regards +6. The scorer correctly promotes armor-pen items when facing tanky comps. responsiveness.enemy_damage_type.comp_blind=true with max_positive_shift=0: a pure dps scorer is not expected to shift on enemy damage type (no EHP component), so this is expected behavior. comp_ok=true.

---

## Axis 3 - outcome_ok: FALSE

evidence_tier.ARAM=outcome_self, n=52 (>=8), baseline wr=55.8%.

Above-baseline empirical self items:
- Statikk Shiv: 66.7% (n=15) -- absent from scorer top-8
- The Collector: 64.3% (n=14) -- absent from scorer top-8
- Berserker's Greaves: 61.9% (n=42) -- boots, not in item pool
- Navori Flickerblade: 60.0% (n=35) -- scorer rank 10 in ad_squishy
- Infinity Edge: 57.7% (n=26) -- scorer rank 6, OK
- Yun Tal Wildarrows: 56.2% (n=16) -- scorer rank 7, OK
- Phantom Dancer: 55.6% (n=9) -- not in scorer top-8

Scorer top-8 (ad_squishy):
1. Blade of The Ruined King (score 130.4) -- empirical wr 25.0% (n=16), far below 55.8% baseline. MISMATCH.
2. Runaan's Hurricane (92.4) -- n<8 in empirical self, inconclusive but empirical all shows 39.0% wr (below all-baseline 47.2%).
3. Kraken Slayer (82.6) -- empirical wr 50.0% (n=8), below baseline.
4. Essence Reaver (72.7) -- not in empirical self top-10.
5. Stormrazor (69.3) -- not in empirical self top-10.
6. Infinity Edge (66.7) -- above baseline 57.7%, aligned.
7. Yun Tal Wildarrows (65.9) -- above baseline 56.2%, aligned.
8. Void Immolation (65.1) -- ARAM-specific legendar, low n, not assessable.

BotRK at rank 1 with 25.0% empirical wr is a clear scorer over-weighting. Xayah's feather-proc kit does not benefit from BotRK's %hp on-hit as much as crit builds do. Statikk Shiv (Xayah Q multi-hits trigger AoE chain) and The Collector (feather burst executes) are the empirical top performers but absent from scorer top-8.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Reduce BotRK scoring weight for Xayah's kit (feather-proc mechanics do not amplify BotRK %hp proc; Xayah is not an AA-spammer in the BotRK mold). Add Statikk Shiv to the scorer pool with credit for Q multi-hit AoE chain interaction. Add The Collector to the scorer pool; crit synergy with feather-burst execute is empirically validated. Navori Flickerblade should rise from rank 10 toward top-5 given 60.0% empirical wr.
