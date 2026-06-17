# DS Cross-Eval: Belveth

VERDICT: MINOR

Scorer: hybrid | Archetype: bruiser/tank | Anchor: ARAM | Evidence: outcome_all (n=47, wr=31.9%)

---

## Axis 1 - archetype_ok: PASS

Archetype bruiser/tank with scorer hybrid (AD EHP + AD DPS blend) is correct.
Belveth kit is attack-speed on-hit with void-form and MR/armor scaling passive.
All empirical above-baseline-wr items are AD physical or on-hit:
- ARAM: Death's Dance 52.9% (n=17), Titanic Hydra 57.1% (n=7), Heartsteel 42.9% (n=7)
- SR: Guinsoo's Rageblade 57.1% (n=21), Stridebreaker 71.4% (n=14), Plated Steelcaps 69.2% (n=13)
AD hybrid axis is confirmed by empirical data.

---

## Axis 2 - comp_ok: PASS

Scorer is hybrid (contains EHP component), so enemy_damage_type MUST respond.
comp_blind=false; max_positive_shift=8 (Wit's End +8 rank when AP enemy).
target_resist max_positive_shift=18 (Liandry's +18 rank when tanky enemies).
Scorer does differentiate: tanky cells elevate Liandry's (rank 3, score 1.23) vs
squishy cells where it drops out of top-12 entirely. EHP d_ehp numbers shift
meaningfully across cells (Heartsteel d_ehp: 1671 ad_squishy vs 1465 ap_squishy).

Pool note: Liandry's Torment reaching rank 3 vs tanky enemies is a marginal concern
(it is an AP burn item, not an AD item for Belveth) but this is target_resist
responsiveness working as designed - not a comp-blindness defect.

---

## Axis 3 - outcome_ok: FAIL (MINOR)

Scorer top-8 in ad_squishy (primary squishy cell):
  r1 Void Immolation, r2 BotRK (score 1.60), r3 Trinity Force, r4 Heartsteel,
  r5 Kraken Slayer (score 1.00), r6 Essence Reaver, r7 Stormrazor, r8 Runaan's Hurricane

ARAM empirical vs scorer overlap:
  BotRK (r2): wr 27.6% - BELOW baseline 31.9%. Scorer over-ranks.
  Kraken Slayer (r5): wr 25.9% - BELOW baseline 31.9%. Scorer over-ranks.
  Heartsteel (r4): wr 42.9% - above baseline. OK.

High-wr empirical staples absent from scorer top-8:
  Death's Dance: wr 52.9% ARAM (n=17) - not in any cell top-12. MISSING.
  Titanic Hydra: wr 57.1% ARAM (n=7) - not in any cell top-12. MISSING.
  Guinsoo's Rageblade: wr 57.1% SR (n=21) - not in any cell top-12. MISSING.

BotRK and Kraken Slayer score high on raw DPS math but underperform in actual ARAM
outcomes. Death's Dance and Titanic Hydra are the top ARAM winners yet are invisible
to the scorer. Pool gap = MINOR (axis correct, some winners present, but key staples
absent and two over-ranked losers).

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Investigate Death's Dance and Titanic Hydra score suppression (likely missing
bruiser-specific passive modeling or survivability-weighted scoring path). Add both
to priority pool. Audit BotRK and Kraken Slayer scoring weight in ARAM context -
on-hit value degrades in short fights; consider comp-length or fight-duration
penalty. Liandry's pool inclusion vs tanky enemies is acceptable but should be
flagged as an AP-item-on-AD-champ edge case for future calibration.
