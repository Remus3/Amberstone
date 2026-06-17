# DS Cross-Eval Verdict: Kayle

**Verdict: MISMATCH**

Scorer: ability (mage primary, carry secondary)
Evidence tier ARAM: outcome_self (n=18, wr=50.0%)
Anchor mode: ARAM

---

## 1. archetype_ok: FALSE

Scorer=ability maps to the mage/AP axis. Kayle's kit is dual-form (early spell, late on-hit AA storm), and empirical data shows the on-hit/AD-hybrid build wins, not AP.

ARAM self (n=18, baseline wr=50.0%) above-baseline items:
- Recurve Bow (n=5, wr=80.0%) - pure AS/on-hit
- Blade of the Ruined King (n=10, wr=60.0%) - AD on-hit
- Guinsoo's Rageblade (n=11, wr=54.5%) - on-hit amplifier

ARAM all (n=143, baseline wr=53.8%) above-baseline top performers:
- Blade of the Ruined King (n=69, wr=62.3%)
- Terminus (n=39, wr=59.0%)
- Wit's End (n=53, wr=56.6%)
- Riftmaker (n=33, wr=57.6%) - only AP item in the winner group; appears in scorer at rank 10
- Guinsoo's Rageblade (n=92, wr=54.3%)
- Berserker's Greaves (n=116, wr=55.2%)

The winning empirical build is solidly on-hit/carry. The ability scorer correctly identifies AP items but that is not the winning archetype. Archetype label mage/ability does not match what wins. Secondary=carry is the empirically correct axis.

---

## 2. comp_ok: TRUE

Scorer=ability -> target_resist should respond to tanky comps. It does.

responsiveness.target_resist.comp_blind = false, max_positive_shift = 4.
Top risers vs tanky: Bloodletter's Curse (+4 ranks), Cryptbloom (+3), Void Staff (+1).
Top fallers vs tanky: Stormsurge (-3), Shadowflame (-2), Hextech Gunblade (-1).

The ability scorer correctly reorders its pool for tanky vs squishy targets. Comp responsiveness is working as expected for the ability scorer type.

Note: enemy_damage_type.comp_blind = true with max_positive_shift = 0. The ability scorer does not gate on EHP (no d_ehp movement in any cell - all 0.0), so enemy damage-type blindness is expected behavior for this scorer type. No defect here.

---

## 3. outcome_ok: FALSE

Scorer top-8 in reference cells (ad_squishy / bal_squishy):
1. Liandry's Torment (score 24.23)
2. Blackfire Torch (score 15.07)
3. Wooglet's Witchcap (score 7.82)
4. Rabadon's Deathcap (score 2.94)
5. Void Staff (score 2.75)
6. Shadowflame (score 2.73)
7. Stormsurge (score 2.35)
8. Hextech Gunblade (score 2.10)

Zero overlap with the empirical above-baseline winners in ARAM self (Recurve Bow, BotRK, Guinsoo). Riftmaker (the one AP item with above-baseline wr in "all") is scorer rank 10, outside top-8. Every scorer top-8 item is AP; every empirical winner is on-hit/AD. The scorer recommends a build that empirically loses, and the empirically winning build is entirely absent from top-8.

---

## 4. rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

Switch Kayle primary archetype from mage to carry (or carry/mage hybrid). The carry scorer will surface on-hit items (Guinsoo, BotRK, Terminus, Nashor's Tooth) that dominate empirical winrates. The current ability scorer is calibrated for a pure AP Kayle that does not match how the champion actually wins games. If a hybrid carry+ability mode is available, weight carry axis heavier to match the on-hit-first empirical pattern.
