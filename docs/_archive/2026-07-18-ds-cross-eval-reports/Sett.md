# DS Cross-Eval: Sett
Date: 2026-06-16
Scorer: hybrid | Archetype: bruiser/tank | Anchor: ARAM | Evidence: outcome_all (n=133, wr=61.7%)

## Verdict: MINOR

---

## Axis 1 - archetype_ok: PASS

Scorer is hybrid (AD+EHP blend). Sett kit is AD melee brawler with a passive that rewards HP (Grit scales with max HP). Hybrid is the correct axis.

Empirical ARAM confirms AD/bruiser-first pattern: Heartsteel (64.3% wr), Overlord's Bloodmail (67.6%), Warmog's (67.4%), Sterak's Gage (67.5%), Titanic Hydra (64.3%) all above the 61.7% baseline. All HP/bruiser items, consistent with hybrid weighting both EHP and AD damage.

---

## Axis 2 - comp_ok: PASS

comp_blind=false, primary_axis=enemy_damage_type, max_positive_shift=5.

Hybrid carries an EHP component so enemy damage type MUST shift rankings - and it does:
- Wit's End rises +5 ranks when AP-heavy.
- Hollow Radiance rises +3 when AP-heavy.
- Dead Man's Plate falls -2 when AP-heavy (correct: armor less valuable vs AP).

Tanky cells also show meaningful movement: in ad_tanky vs ad_squishy, BotRK moves from rank 7 to rank 2, Liandry's from rank 9 to rank 3 (percent-health damage against tanky targets). The scorer is responsive. No defect.

---

## Axis 3 - outcome_ok: FAIL

Reference cell: ad_squishy top-8: Void Immolation (r1), Trinity Force (r2), Heartsteel (r3), Dusk and Dawn (r4), Essence Reaver (r5), Iceborn Gauntlet (r6), BotRK (r7), Stormrazor (r8).

Empirical items above baseline wr (61.7%):
- Heartsteel 64.3% (n=84) - scorer rank 3. PRESENT. OK.
- Overlord's Bloodmail 67.6% (n=68) - NOT IN scorer top-12. MISS.
- Warmog's Armor 67.4% (n=43) - NOT IN scorer top-12. MISS.
- Sterak's Gage 67.5% (n=40) - NOT IN scorer top-12. MISS.
- Ruby Crystal 71.4% (n=35) - component, not a final item judgment.
- Titanic Hydra 64.3% (n=28) - NOT IN scorer top-12. MISS.

Scorer top-8 problems:
- Essence Reaver (r5): d_ehp=0.0 - pure DPS, zero EHP contribution. Sett's kit does not proc Essence Reaver's CDR synergy optimally. Not an above-baseline empirical item.
- Stormrazor (r8): d_ehp=0.0 - pure DPS. Absent from empirical data.
- Dusk and Dawn (r4): present in scorer but absent from empirical top-10.
- Trinity Force (r2): some synergy via Spellblade, but absent from empirical top-10.

The HP-stacking identity (Bloodmail + Warmog + Sterak + Titanic Hydra) is wholly absent from the scored pool. These four items collectively represent Sett's highest empirical win-rate cluster. The scorer is over-weighting DPS items and under-weighting HP-percent-max items that feed Sett's Grit passive.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Ensure Overlord's Bloodmail, Warmog's Armor, Sterak's Gage, and Titanic Hydra enter the hybrid scorer's evaluated pool for Sett. The likely cause is insufficient weight on HP-flat / HP-percent-max EHP contributions relative to raw AD+DPS in the hybrid formula for high-base-HP champions. Cross-check whether the scorer's EHP delta for these items is being computed (d_ehp values are nonzero for Heartsteel which IS present, so the HP path works in principle - Bloodmail/Warmog/Sterak/Titanic may be simply absent from the candidate set at item-generation time for this archetype).
