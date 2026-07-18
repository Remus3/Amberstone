# DS Cross-Eval: Leona

**Verdict: MINOR**

Scorer: ehp | Archetype: tank (primary) / enchanter (secondary) | Anchor: ARAM
Evidence tier ARAM: outcome_all (n=96, baseline wr=59.4%)

---

## Axis 1 - archetype_ok: TRUE

Tank -> EHP scorer is correct. EHP is neutral (no AD/AP axis). Leona kit is
pure frontline CC with no damage scaling. No axis mismatch.

---

## Axis 2 - comp_ok: TRUE

EHP scorer must respond to enemy_damage_type. comp_blind=false, confirmed.
max_positive_shift=24. When enemy is AP-heavy:
- Risers: Abyssal Mask +24, Hollow Radiance +23, Kaenic Rookern +22, Force of Nature +22, Spirit Visage +21
- Fallers: Iceborn Gauntlet -27, Dead Man's Plate -24, Sunfire Aegis -24, Randuin's Omen -21

Grid confirms: ad_squishy has Randuin's Omen at rank 2; ap_squishy replaces it
with Kaenic Rookern (rank 2) and Force of Nature (rank 3). Responsiveness is
meaningful and correct directionally.

target_resist comp_blind=true is expected and correct: Leona deals no
meaningful damage so enemy resistances are irrelevant to her build value.

---

## Axis 3 - outcome_ok: FALSE (pool gaps)

Empirical above-baseline items (ARAM all, baseline 59.4%):
- Mercury's Treads: 67.2% wr (n=64) -- NOT in scorer top-8 any cell
- Thornmail:        66.7% wr (n=33) -- rank 9 in ad_squishy/ad_tanky, misses top-8
- Guardian's Horn:  64.7% wr (n=17) -- absent from scorer output entirely
- Fimbulwinter:     62.5% wr (n=40) -- NOT in scorer top-8 any cell

Scorer top-8 items that underperform empirically:
- Warmog's Armor:    51.9% wr (n=27) -- ranks 2-3 in ad_squishy/bal_squishy, well below baseline
- Heartsteel:        58.7% wr (n=63) -- rank 3-4 in ad_squishy, below baseline
- Jak'Sho, Protean:  50.0% wr (n=16) -- ranks 5-7 in scorer, below baseline

Four above-baseline empirical staples absent or outside top-8. Two scorer-top
items rank poorly in practice. The scorer over-weights raw HP stacking
(Warmog's, Heartsteel) which does not translate to wins, while missing
utility-tank items Fimbulwinter (mana+HP+slow) and Mercury's Treads
(tenacity on a CC-heavy engage tank) that show strong empirical results.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Add Fimbulwinter and Mercury's Treads to Leona scorer item pool (both
above-baseline, high n); add Guardian's Horn investigation (n=17, 64.7%
wr, absent from output suggests it may not be in the candidate pool at
all). Audit pure-HP items (Warmog's, Heartsteel) -- consider a small
anti-stacking penalty or utility-weight uplift so items with CC/utility
passives rank higher relative to raw EHP items that underperform in practice.
