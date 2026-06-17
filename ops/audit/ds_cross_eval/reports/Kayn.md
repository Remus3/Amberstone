# DS Cross-Eval: Kayn

**Verdict: MINOR**

Scorer: hybrid | Archetype: bruiser/assassin | Evidence tier ARAM: outcome_all (n=72, baseline wr=45.8%)

---

## Axis 1 - archetype_ok: PASS

Kayn primary=bruiser, secondary=assassin. Scorer=hybrid is AD-family. Kit is dual-form (Rhaast bruiser, Shadow Assassin). AD scorer axis is correct. Empirical above-baseline items (Muramana 50.0%, Hubris 54.5%, Black Cleaver 52.6%, Axiom Arc 61.5%, Spirit Visage 54.5%) are all AD/fighter - consistent with hybrid AD scorer.

## Axis 2 - comp_ok: PASS

Scorer=hybrid has an EHP component -> enemy_damage_type must shift. comp_blind=false, max_positive_shift=18 (Hollow Radiance +18 when AP). Scorer is responsive. target_resist also moves (max_positive_shift=11, Liandry's +11 vs tanky AP). No comp-blind defect.

## Axis 3 - outcome_ok: FAIL

Using ARAM all (n=72 >= 8). Baseline wr=45.8%.

Above-baseline empirical items (ARAM all):
- Axiom Arc (6696): n=13, wr=61.5% - NOT in scorer top-8 (any cell)
- Hubris (126697): n=22, wr=54.5% - NOT in scorer top-8
- Spirit Visage (3065): n=11, wr=54.5% - NOT in scorer top-8
- Black Cleaver (3071): n=19, wr=52.6% - NOT in scorer top-8
- Muramana (3042): n=24, wr=50.0% - NOT in scorer top-8

Scorer top-8 (ad_squishy/bal_squishy): Void Immolation, Trinity Force, BotRK, Heartsteel, Essence Reaver, Iceborn Gauntlet, Dusk and Dawn, Runaan's Hurricane. Of these, Trinity Force and BotRK appear in empirical data but with modest representation and no above-baseline wr. Essence Reaver, Iceborn Gauntlet, Dusk and Dawn, Runaan's Hurricane do not appear in the empirical top-10 at all.

The actual high-wr staples (Axiom Arc, Hubris, Black Cleaver, Muramana) are all outside scorer top-8. This is a meaningful pool gap.

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Boost Hubris (126697), Axiom Arc (6696), Black Cleaver (3071), Muramana (3042) in hybrid DPS component scoring for Kayn. These items show strong empirical wr (50-61.5%) but rank outside top-8 in all comp cells. Inspect whether ability-haste/lethality/mana values are underweighted in the DPS sub-score for this champion profile.
