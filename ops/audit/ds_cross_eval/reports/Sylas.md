# DS Cross-Eval: Sylas

**VERDICT: MINOR**

Scorer: ability | Archetype: mage/assassin | Evidence tier (ARAM): outcome_all (n=137)

---

## Axis 1 - archetype_ok: PASS

Sylas is AP mage/assassin. Ability scorer uses AP axis. Kit alignment is strong: Q/W/E/R all scale AP, empowered AA scales AP, W sustain scales AP. Mage -> AP scorer is correct.

Empirical above-baseline (ARAM all, baseline 54.7%): Riftmaker 59.6%, Spirit Visage 61.3%, Shadowflame 62.1%, Lich Bane 63.6%, Hextech Rocketbelt 68.4%. All AP items. Axis confirmed correct.

## Axis 2 - comp_ok: PASS

Scorer = ability. Primary axis = target_resist (correct for mage damage dealer). target_resist.comp_blind = false; max_positive_shift = 3. Bloodletter's Curse rises +3 ranks vs tanky, Cryptbloom +2, Void Staff +1. Responsiveness is present and sensible.

enemy_damage_type.comp_blind = true (max_positive_shift=0, no risers). This is EXPECTED for an ability scorer - enemy damage type does not affect the AP-damage output scoring axis. No defect.

## Axis 3 - outcome_ok: FAIL (pool gap)

Scorer top-8 (ad_squishy): Liandry's #1 (29.4), Wooglet's #2 (22.6), Blackfire Torch #3 (19.1), Rabadon's #4 (8.5), Void Staff #5 (8.1), Shadowflame #6 (8.1), Stormsurge #7 (6.9), Cryptbloom #8 (6.1).

Empirical above-baseline winners NOT in scorer top-8:
- Hextech Rocketbelt: wr 68.4% (n=19) - absent from all comp cells top-12
- Lich Bane: wr 63.6% (n=22) - absent from all comp cells top-12
- Spirit Visage: wr 61.3% (n=31) - absent from all comp cells top-12

Scorer top-3 items (Liandry's, Wooglet's, Blackfire Torch) have zero empirical representation in the outcome_all list. Riftmaker is scorer rank 9 at ad_squishy, empirically 59.6% (above baseline).

Shadowflame is correctly in both scorer top-8 (#6) and empirical winners (62.1%) - one good overlap.

Three strong empirical winners are missing from the scorer pool entirely. Over-ranking of Liandry's/Wooglet's/Blackfire Torch not supported by outcomes.

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

Investigate why Hextech Rocketbelt (68.4% wr, n=19), Lich Bane (63.6%, n=22), and Spirit Visage (61.3%, n=31) score outside the ability scorer's top-12 for Sylas. If the ability scorer lacks passive-on-hit handling for Rocketbelt/Lich Bane or sustain-amplifier handling for Spirit Visage, add those effects. Liandry's/Wooglet's/Blackfire Torch over-rank relative to empirical outcomes - validate those scoring paths.
