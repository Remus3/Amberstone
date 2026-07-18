# DS Cross-Eval: Olaf

**Verdict: MINOR**

Scorer: hybrid | Archetype: bruiser/tank | Evidence: outcome_self (ARAM n=18, wr=50.0%)

---

## Axis 1 - archetype_ok: true

Olaf primary=bruiser, secondary=tank. Bruiser maps to AD axis; hybrid scorer is the correct
AD-axis scorer. No mismatch.

Empirical confirmation: above-baseline items (ARAM self baseline 50.0%) are all AD bruiser items:
- Experimental Hexplate: n=8, wr=62.5%
- Stridebreaker: n=8, wr=62.5%
- Sundered Sky: n=5, wr=60.0%

Kit is melee AD sustained-damage bruiser. Hybrid scorer axis is appropriate.

---

## Axis 2 - comp_ok: true

Scorer=hybrid. primary_axis=enemy_damage_type, comp_blind=false (confirmed in responsiveness).

The scorer responds to enemy damage type:
- Wit's End rises +11 ranks when enemy is AP (MR item becomes high value).
- Dead Man's Plate falls -18 ranks when enemy is AP (armor item less useful vs AP enemies).
- Void Immolation d_ehp shifts: 4484.5 (ad_squishy) -> 3843.3 (ap_squishy), modest reduction
  as MR from Void Immolation loses some EHP value vs AD-heavy enemy.

target_resist also moves: Liandry's Torment rises +30 when enemy is AP/tanky (magic-pen value
spikes). Black Cleaver +12, Lord Dominik's +11 vs AD tanky.

Responsiveness is real and directionally correct. comp_blind=false. comp_ok=true.

---

## Axis 3 - outcome_ok: false

ARAM self n=18 >= 8, so outcome_self is used. Baseline wr=50.0%.

Above-baseline empirical staples:
- Experimental Hexplate (id 3073): wr=62.5%, n=8 - ABSENT from scorer top-8 in all comp cells
- Stridebreaker (id 6631): wr=62.5%, n=8 - ABSENT from scorer top-8 in all comp cells
- Sundered Sky (id 6610): wr=60.0%, n=5 - ABSENT from scorer top-8 in all comp cells

Scorer top-8 in ad_squishy / bal_squishy:
1 Blade of The Ruined King (1.2197)
2 Void Immolation (1.2041)
3 Runaan's Hurricane (1.0212)
4 Trinity Force (0.8791)
5 Kraken Slayer (0.7712)
6 Essence Reaver (0.7655)
7 Stormrazor (0.6777)
8 Yun Tal Wildarrows (0.6448)

Runaan's Hurricane, Kraken Slayer, Essence Reaver, Stormrazor, Yun Tal Wildarrows are ADC
crit items - none appear in the empirical winning-item list for Olaf. The three empirically
winning bruiser items (Stridebreaker, Experimental Hexplate, Sundered Sky) do not appear in
scorer top-8 under any comp cell.

Pool gap: scorer over-weights pure DPS crit items; bruiser utility items that actually win
are ranked outside the top 8.

---

## Axis 4 - rune_ok: n/a

rune_relevant=false.

---

## Nominated Retune

Boost Stridebreaker (id 6631), Experimental Hexplate (id 3073), and Sundered Sky (id 6610)
in the hybrid scorer pool for Olaf. The scorer is over-weighting pure AD DPS (crit/ADC items)
relative to bruiser utility items that carry a meaningful win-rate premium. Consider a bruiser
item tag weight in the hybrid scorer, or champion-level pool override for these three items.
