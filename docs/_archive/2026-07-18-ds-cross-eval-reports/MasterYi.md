# DS Cross-Eval: MasterYi

**Verdict: MINOR**
Scorer axis and comp responsiveness are correct. Pool gap: The Collector and Guinsoo's Rageblade are absent from scorer top-8 despite being empirically top-performing items in ARAM.

---

## Axis 1 - Archetype

archetype_ok: TRUE

Primary=bruiser, secondary=assassin, scorer=hybrid (AD-axis). MasterYi is a pure AD melee on-hit/crit carry. Kit (Alpha Strike + on-hit passive) is entirely AD-dependent. Bruiser label is defensible for a melee skirmisher that runs Heartsteel in some builds. The hybrid scorer correctly operates on the AD axis. Empirical confirms AD itemization wins: Berserker's Greaves 80.0% wr (n=15), The Collector 76.9% (n=13), Infinity Edge 100% (n=6), Guinsoo's Rageblade 63.3% wr all-ARAM (n=30). All are AD/on-hit items. No AP build signal anywhere. Axis is correct.

---

## Axis 2 - Comp Responsiveness

comp_ok: TRUE

Scorer=hybrid. primary_axis=enemy_damage_type, comp_blind=false. Verified: d_ehp values shift meaningfully across comp cells. Heartsteel d_ehp: ad_squishy=1578.4, ap_squishy=1390.6 (difference 188). Void Immolation d_ehp: ad_squishy=4348.3, ap_squishy=3721.1 (difference 627). Rankings shift in tanky cells - BotRK rises to rank 1 (score 2.1785) from rank 2 in squishy cells (score 1.2773), driven by %hp damage value vs tanky targets. Enemy damage type responsiveness max_positive_shift=11 (Wit's End shifts +11 in AP comps). target_resist max_positive_shift=29 (Liandry's Torment shifts +29 in ap_tanky). Scorer is not comp-blind; it responds appropriately to both damage-type and target-resist dimensions.

---

## Axis 3 - Outcome Overlap

outcome_ok: FALSE (pool gap)

Using outcome_self (n=19 >= 8). ARAM self baseline wr=68.4%.

Scorer top-8 (ad_squishy): Void Immolation, BotRK, Runaan's Hurricane, Trinity Force, Kraken Slayer, Heartsteel, Essence Reaver, Stormrazor.

Empirical items above 68.4% baseline:
- Berserker's Greaves: 80.0% wr, n=15
- The Collector: 76.9% wr, n=13
- Infinity Edge: 100% wr, n=6 (small n)
- BotRK: 58.3% wr (BELOW baseline - in scorer but underperforming)

Pool gaps:
1. The Collector (id 6676): strongest consistent signal (76.9% wr, n=13 ARAM self; 57.9% SR all n=19 above 51.6% baseline). Absent from all scorer comp cells entirely. This is the primary miss.
2. Guinsoo's Rageblade (id 3124): 63.3% wr ARAM all (n=30, well above 55.2% all baseline), 57.9% SR all (n=19, above 51.6% baseline). Also absent from scorer pool.
3. BotRK is in scorer rank 2 but ARAM self wr is 58.3% (below 68.4% baseline). Not flagged as losing badly, but the scorer overweights it relative to empirical outcomes.
4. Kraken Slayer in scorer rank 5 but ARAM all wr=38.9% (n=18, well below 55.2%) - consistently underperforming.

The scorer top-8 includes two items that empirically underperform (BotRK below self baseline, Kraken Slayer far below all baseline) while missing two that outperform (Collector, Guinsoo). This is a pool gap, not a wrong-axis issue.

---

## Axis 4 - Rune

rune_ok: n/a (rune_relevant=false)

---

## Nominated Retune

Add The Collector (6676) and Guinsoo's Rageblade (3124) to MasterYi's hybrid scorer item pool. Both show strong above-baseline wr signals across ARAM self and ARAM all cohorts. Consider deprioritizing Kraken Slayer (ARAM all wr 38.9%, n=18) in the pool or reviewing its interaction with the hybrid dps component for Yi specifically.
