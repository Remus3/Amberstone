# DS Cross-Eval: Illaoi

**Verdict: MINOR**

Scorer: hybrid | Archetype: bruiser/tank | Evidence tier ARAM: outcome_all (n=79, baseline wr=40.5%)

---

## Axis 1 - archetype_ok: PASS

Hybrid scorer is AD-axis (carry/bruiser/assassin). Illaoi is primary bruiser / secondary tank. Kit is physical: tentacles + E/W/R all deal physical/AD damage. AD-axis is correct.

Empirical check (ARAM all, n=79, baseline 40.5%): above-baseline items are Plated Steelcaps (47.8%, n=23) and Black Cleaver (41.7%, n=12). Both are AD/tank items consistent with AD-axis bruiser. No AP-axis signal in empirical winners. PASS.

---

## Axis 2 - comp_ok: PASS

Hybrid scorer is EHP+DPS blend. Primary axis = enemy_damage_type. comp_blind = false.

Enemy damage type does shift rankings: max_positive_shift=6 (Hollow Radiance rises 6 spots in ap_squishy vs ad_squishy). Sunfire Aegis falls 4 spots vs AP comps. MR items rise vs AP enemies, armor items fall - correct EHP behavior for a hybrid scorer. comp_blind is explicitly false. PASS.

---

## Axis 3 - outcome_ok: FAIL (MINOR)

Reference cell: ad_squishy top-8: Void Immolation #1, Trinity Force #2, Heartsteel #3, Essence Reaver #4, Iceborn Gauntlet #5, Dusk and Dawn #6, Blade of the Ruined King #7, Dead Man's Plate #8.

Above-baseline empirical items (ARAM all, wr > 40.5%):
- Plated Steelcaps: wr=47.8%, n=23 - NOT in scorer top-8 in any cell
- Black Cleaver: wr=41.7%, n=12 - NOT in scorer top-8 (appears only as a "faller" in responsiveness data, absent from grid top-8)

Scorer top items vs empirical wr:
- Trinity Force #2: wr not in empirical top
- Essence Reaver #4: not in empirical list at all (0 appearances in ARAM sample)
- Dusk and Dawn #6: not in empirical list
- BotRK #7: not in empirical list

The two empirically strongest items (Steelcaps at +7.3pp above baseline, Black Cleaver at +1.2pp) are absent from the scorer pool entirely. The scorer over-ranks damage items (Essence Reaver, Dusk and Dawn, BotRK) that do not appear in empirical builds. This is a pool gap, not a catastrophic mismatch - the items are plausible on paper but not what winning builds actually use.

FAIL - MINOR pool gap.

---

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

Add Plated Steelcaps and Black Cleaver to Illaoi's item pool. Investigate why Essence Reaver and Dusk and Dawn rank so highly (zero empirical appearances in 79-game sample); consider a pool eligibility gate or downweight for items with zero empirical usage on a champion.
