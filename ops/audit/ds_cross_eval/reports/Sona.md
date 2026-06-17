# Sona DS Cross-Eval Verdict

**SEVERITY: MINOR**
**Scorer: hps | Archetype: enchanter/mage | Anchor: ARAM | Evidence: outcome_all (n=115, wr=53.9%)**

---

## Axis 1: archetype_ok = true

hps is the enchanter scorer axis. Sona is a pure enchanter/mage - kit is heal/shield/aura utility with no meaningful self-EHP or AD-carry identity. The scorer axis is correct. Empirical above-baseline items (Ardent Censer 67.4%, Staff of Flowing Water 61.9%, Redemption 59.3%) are all enchanter support items consistent with hps scoring.

## Axis 2: comp_ok = true

hps/enchanter scorer: comp invariance is EXPECTED behavior. Sona's utility value (heals, shields, auras) is not meaningfully gated by enemy damage type. All 5 comp cells are identical (d_ehp=0.0, d_dps=0.0, comp_blind=true). This is correct for an enchanter - no defect.

## Axis 3: outcome_ok = false (MINOR)

Using ARAM outcome_all (self n=1, too small): baseline wr=53.9%.

Scorer top-8 (ad_squishy representative): Echoes of Helia (rank 1, score 28.1), Ardent Censer (rank 2), Staff of Flowing Water (rank 3), Locket (rank 4), Knight's Vow (rank 5), Redemption (rank 6), Imperial Mandate (rank 7), Mikael's Blessing (rank 8).

Empirical above-baseline items (wr > 53.9%):
- Ardent Censer: wr 67.4% (n=43) -> scorer rank 2 - OK
- Staff of Flowing Water: wr 61.9% (n=42) -> scorer rank 3 - OK
- Redemption: wr 59.3% (n=27) -> scorer rank 6 - OK
- Ionian Boots of Lucidity: wr 56.3% (n=71) -> NOT in scorer pool at all
- Moonstone Renewer: wr 55.6% (n=81, most-purchased item) -> scorer rank 9, outside top-8 cutoff

Key gaps:
1. Moonstone Renewer is the #1 most-purchased ARAM item (n=81) with above-baseline wr (55.6%) but scores rank 9 - outside the top-8 window.
2. Echoes of Helia is scorer rank 1 (score 28.1) but does NOT appear in the ARAM empirical top-10 at all. It appears in SR (rank 1, 54.5% wr, n=22) but ARAM players are not building it with the same frequency.
3. Ionian Boots of Lucidity (56.3% wr, n=71) is entirely absent from the scorer pool (boots exclusion is expected but worth noting as an empirical signal).

The scorer rank-1 item (Echoes of Helia) has no ARAM empirical presence while the empirical #1 (Moonstone Renewer) is rank 9. This is a pool ordering mismatch, not a wrong-axis problem.

## Axis 4: rune_ok = n/a

rune_relevant = false.

---

## Nominated Retune

Investigate why Echoes of Helia outscores Moonstone Renewer 28.1 vs 1.1 in the hps scorer when ARAM empirical data shows the reverse (Moonstone n=81/55.6% vs Echoes absent from top-10). Likely cause: hps scorer weights proc-on-heal mechanics that favor Echoes over Moonstone's ambient sustain passive. Consider a secondary weight for flat sustain volume or ap-synergy to lift Moonstone Renewer into the top-8 for ARAM-anchor champions.

---

## Headline

Sona hps scorer correctly axes enchanter; Moonstone Renewer (#1 ARAM item, 55.6% wr) ranks 9th while scorer-top Echoes of Helia is absent from ARAM empirical top-10.
