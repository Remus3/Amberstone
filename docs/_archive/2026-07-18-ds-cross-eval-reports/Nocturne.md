# Nocturne DS Cross-Eval Report

**Verdict: MINOR**
Scorer axis and comp responsiveness are correct. Empirical above-baseline winners are absent from scorer top-8; scorer over-recommends ADC/crit items.

---

## 1. Archetype OK - PASS

Archetype: bruiser/assassin (source: default). Scorer: hybrid (AD axis).

Nocturne kit is AD-dominant (Q grants bonus AD and deals physical damage; R scales on AD). AD-axis hybrid scorer is correct.

Empirical above-baseline confirmation:
- ARAM baseline wr 44.2% (n=52). Above-baseline items: Ionian Boots 54.5% (n=11), Tear of Goddess 55.6% (n=9), Hubris 46.7% (n=15), Sundered Sky 45.5% (n=11) - all AD items.
- SR baseline wr 42.4% (n=33). Above-baseline items: Stridebreaker 52.0% (n=25), Experimental Hexplate 53.3% (n=15), Black Cleaver 57.1% (n=7), Ionian Boots 60.0% (n=5) - all AD bruiser/diver items.

Axis: AD. Correct.

---

## 2. Comp OK - PASS

Scorer: hybrid. Primary axis: enemy_damage_type. comp_blind: false.

EHP component shifts visibly across cells:
- Void Immolation d_ehp: 4902 (ad_squishy) vs 4135 (ap_squishy) - delta 767 confirming MR component weighed.
- Iceborn Gauntlet: rank 9 in ad_squishy, absent from ap_squishy top 12 (target_resist faller -8 when AP per responsiveness).
- Wit's End rises +11 when AP (top riser in enemy_damage_type).
- Dead Man's Plate falls -10 when AP (top faller).
- Liandry's Torment appears in ad_tanky/ap_tanky (rank 4) as a % HP tool vs tanks, rises +18 in target_resist when AP.

comp_blind=false confirmed. Scorer responds to comp as expected for hybrid.

---

## 3. Outcome OK - FAIL

Using outcome_all ARAM (n=52 >= 8). Baseline wr: 44.2%.

Scorer top-8 (ad_squishy cell): Void Immolation (#1), BotRK (#2), Trinity Force (#3), Heartsteel (#4), Essence Reaver (#5), Runaan's Hurricane (#6), Kraken Slayer (#7), Stormrazor (#8).

Empirical above-baseline items NOT in scorer top-8:
- Sundered Sky (ARAM wr 45.5%, n=11) - absent
- Hubris (ARAM wr 46.7%, n=15) - absent
- Ionian Boots of Lucidity (ARAM wr 54.5%, n=11) - boots, excused
- Tear of the Goddess (ARAM wr 55.6%, n=9) - component, excused
- Stridebreaker (SR wr 52.0%, n=25) - absent
- Experimental Hexplate (SR wr 53.3%, n=15) - absent
- Black Cleaver (SR wr 57.1%, n=7) - absent

Scorer top-8 contains Essence Reaver, Runaan's Hurricane, Kraken Slayer, Stormrazor - marksman/crit items with no above-baseline empirical presence on Nocturne. Stridebreaker (highest-n SR item, 52% wr), Experimental Hexplate, Black Cleaver, Sundered Sky, and Hubris are all proven AD bruiser-diver items that empirically win but are absent from scorer pool top-8.

The scorer is biasing toward ADC on-hit/crit items rather than the bruiser-diver kit items that win in practice.

---

## 4. Rune OK - N/A

rune_relevant: false.

---

## Nominated Retune

Add Stridebreaker, Experimental Hexplate, Black Cleaver, Sundered Sky, Hubris to scorer eligible pool top consideration for Nocturne. Down-weight pure ADC crit/on-hit items (Runaan's Hurricane, Kraken Slayer, Stormrazor, Essence Reaver) which have no above-baseline empirical signal for this bruiser-assassin archetype.
