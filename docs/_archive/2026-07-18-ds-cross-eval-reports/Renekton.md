# Renekton DS Cross-Eval Verdict

**VERDICT: MISMATCH**

Scorer `hybrid` | Archetype `bruiser/tank` | Anchor `ARAM` | Evidence `outcome_all` (n=77, wr=55.8%)

---

## Axis 1 - archetype_ok: PASS

Hybrid scorer is the correct axis for an AD bruiser. Renekton deals physical damage with no AP scaling worth itemizing. The hybrid scorer balances survivability (ehp) and AD output (dps), matching the kit. Empirical above-baseline items (Sundered Sky 58.2%, Sterak's Gage 60.6%, Death's Dance 59.4%, Black Cleaver 72.7%, Plated Steelcaps 63.2%) are all AD/bruiser items - consistent with the AD-leaning hybrid axis. No axis mismatch.

## Axis 2 - comp_ok: PASS (with pool gap noted)

`comp_blind=false` and `primary_axis=enemy_damage_type`. The scorer does respond to comp: Wit's End rises +12 rank slots vs AP enemies; Liandry's Torment rises +15 on target_resist axis vs tanky AP comps. The tanky cells show visible rank reordering (Liandry's rank 6, Eclipse rank 7 in ad_tanky/ap_tanky). The squishy cells are more static but that is expected - squishy targets don't penalize pure-AD damage. Formally not comp-blind. However, Wit's End (the biggest riser, +12) does not surface in the top-12 displayed cells, suggesting it sits just below the displayed pool horizon. Pool gap flagged but not a comp-blind defect.

## Axis 3 - outcome_ok: FAIL

Baseline ARAM wr = 55.8% (outcome_all, n=77).

Above-baseline empirical staples (wr > 55.8%):
- Sundered Sky: wr=58.2%, n=55 (highest n item)
- Sterak's Gage: wr=60.6%, n=33
- Death's Dance: wr=59.4%, n=32
- Black Cleaver: wr=72.7%, n=11
- Plated Steelcaps: wr=63.2%, n=19

Scorer top-8 (ad_squishy / bal_squishy cells, ranks 1-8):
1. Void Immolation
2. Blade of The Ruined King
3. Trinity Force
4. Essence Reaver
5. Runaan's Hurricane
6. Heartsteel
7. Stormrazor
8. Dusk and Dawn

NONE of the 5 above-baseline empirical staples (Sundered Sky, Sterak's Gage, Death's Dance, Black Cleaver, Plated Steelcaps) appear in the scorer top-8. Meanwhile the scorer surfaces crit/marksman items with no empirical Renekton support: Essence Reaver (rank 4), Runaan's Hurricane (rank 5), Stormrazor (rank 7). These three have zero empirical presence in the outcome_all item list. Void Immolation ranks 1 at score 1.59 driven by massive d_ehp (4506) - plausible for ARAM sustain but not reflected in empirical data. This is a real pool composition mismatch: ADC crit items outranking core bruiser-fighter staples.

## Axis 4 - rune_ok: N/A

`rune_relevant=false`.

---

## Nominated Retune

Bruiser scorer pool for Renekton: add Sundered Sky, Sterak's Gage, Death's Dance, Black Cleaver with appropriate hybrid weights (ehp + AD-synergy). Demote or remove Runaan's Hurricane, Essence Reaver, Stormrazor from Renekton's candidate pool - these are marksman crit items with no bruiser synergy and zero empirical support on this champion.
