# DS Cross-Eval: Jax

**Verdict: MINOR**
Scorer axis and comp responsiveness are correct, but two high-wr empirical staples
(Spear of Shojin 60.7% wr n=28, Death's Dance 68.0% wr n=25) are absent from scorer
top-8, indicating an item-pool gap in the hybrid scorer for Jax.

---

## 1. archetype_ok: TRUE

- Archetype: bruiser/tank, scorer: hybrid.
- Hybrid scorer is the bruiser/AD scorer. Jax is an auto-attack bruiser (passive
  stacks AD on each attack, E Counter-Strike scales AD, R divine ascent is on-hit
  stacking). AD axis is correct.
- Empirical (outcome_all used; outcome_self n=8 at threshold but only 2 items
  reported, both at or below 25.0% self-baseline; outcome_all n=102, baseline 49.0%):
  above-baseline items are Sundered Sky 53.4%, Mercury's Treads 53.7%, Spear of
  Shojin 60.7%, Death's Dance 68.0%, Plated Steelcaps 52.2%. All are AD or
  AD-adjacent (no AP items above baseline). Axis confirmed correct.

## 2. comp_ok: TRUE

- Scorer: hybrid. primary_axis = enemy_damage_type, comp_blind = false.
- EHP component shifts with enemy damage type: Void Immolation d_ehp drops from
  4468.8 (ad_squishy) to 3826.3 (ap_squishy) as expected (MR-heavy item scores
  lower vs AD enemies). max_positive_shift = 18 (Wit's End rises 18 ranks when
  enemy is AP-heavy). Dead Man's Plate falls 13 ranks when AP (armor-MR flip
  correct).
- target_resist axis also responsive: max_positive_shift 26 (Liandry's Torment +26
  vs tanky enemies). Eclipse +12, Mortal Reminder +9.
- No comp-blind defect. comp_ok = true.

## 3. outcome_ok: FALSE (MINOR pool gap)

Evidence base: outcome_all (n=102, baseline wr 49.0%) used because outcome_self
items list is thin (only 2 items despite n=8).

Scorer top-8 (ad_squishy / bal_squishy):
  #1 Void Immolation, #2 Blade of the Ruined King, #3 Runaan's Hurricane,
  #4 Trinity Force, #5 Essence Reaver, #6 Heartsteel, #7 Kraken Slayer,
  #8 Stormrazor.

Empirical above-baseline staples NOT in scorer top-8:
  - Spear of Shojin: n=28, wr=60.7% (empirical rank ~4) - absent from scorer list
  - Death's Dance: n=25, wr=68.0% (empirical rank ~5, highest wr of all) - absent
  - Sundered Sky: n=73, wr=53.4% (empirical rank ~2) - absent from scorer top-8

Scorer top-8 items that appear in empirical data but under-perform relative to
baseline:
  - BotRK: wr=43.5% (below 49.0% baseline, n=23) - scorer rank #2 is too high
  - Trinity Force: wr=48.9% (below baseline, n=88) - scorer rank #4, marginal

The gap is real: Death's Dance and Spear of Shojin are Jax's two highest-confidence
above-baseline items but do not appear in scorer top-8. Both provide AD + ability
haste, which feeds Jax's ability-enhanced auto cadence. The scorer likely undervalues
AH-to-ability-frequency translation for Jax's kit, or these items' d_dps contribution
is being suppressed relative to pure-DPS items.

## 4. rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

Investigate why Spear of Shojin and Death's Dance score outside top-8 for Jax hybrid
scorer. Both are confirmed AD/bruiser staples with high empirical wr. Likely causes:
(a) AH-to-DPS frequency multiplier not wired for Jax's kit, (b) Death's Dance DR
component not captured in d_ehp for hybrid scorer, or (c) item pool cutoff excludes
them before scoring. Fix: raise Spear of Shojin and Death's Dance into scorer
consideration pool and verify they land top-8 after calibration. Also audit BotRK
rank-2 which is overcredited (empirical wr 43.5%, below baseline).
