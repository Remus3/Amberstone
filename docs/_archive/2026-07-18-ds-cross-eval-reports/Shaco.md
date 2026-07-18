# Shaco DS Scorer Cross-Eval

**VERDICT: MISMATCH**

Scorer: burst | Archetype: assassin (primary), mage (secondary) | Anchor: ARAM | Evidence: outcome_all (n=124, wr=52.4%)

---

## Axis 1 - archetype_ok: FALSE

Scorer "burst" maps to AD axis (assassin). Shaco's kit IS AD-primary (backstab auto-reset, Q blink/stealth), so scorer axis matches kit in isolation. However, empirical ARAM outcome_all shows overwhelming AP build dominance among above-baseline-wr items:

- Blackfire Torch (id 2503): n=43, wr=65.1% (above baseline by +12.7)
- Liandry's Torment (id 6653): n=77, wr=62.3% (+9.9)
- Luden's Echo (id 6655): n=35, wr=60.0% (+7.6)
- Sorcerer's Shoes (id 3020): n=60, wr=61.7% (+9.3)
- Shadowflame (id 4645): n=46, wr=56.5% (+4.1)
- Malignance (id 3118): n=26, wr=53.8% (+1.4)

The only AD item with meaningful sample: The Collector (id 6676, n=25, wr=36.0%) - 16.4 points BELOW baseline. Burst scorer is wired to the AD axis; empirically the AP build path wins decisively in ARAM. Axis vs what-wins = MISMATCH.

---

## Axis 2 - comp_ok: TRUE

Scorer = burst (pure DPS, d_ehp=0.0 across all comp cells). A DPS scorer has no EHP component, so comp-blind on enemy_damage_type is correct/expected - there is nothing to shift. The target_resist axis responds correctly: max_positive_shift=18 when enemy is AP-tanky, top risers are Lord Dominik's Regards (+18), Mortal Reminder (+16), Void Staff (+11) - armor-pen and MR-pen items rise appropriately for tanky enemies. comp_ok = true.

---

## Axis 3 - outcome_ok: FALSE

Scorer top-8 (ad_squishy cell, representative of AD-squishy baseline):
1. Wooglet's Witchcap (228002, score 560.7)
2. Trinity Force (3078, score 343.3)
3. Essence Reaver (3508, score 336.9)
4. Blade of The Ruined King (3153, score 314.5)
5. Lich Bane (3100, score 281.2)
6. Infinity Edge (3031, score 249.8)
7. Sundered Sky (6610, score 234.5)
8. Eclipse (6692, score 223.7)

Cross-check vs empirical above-baseline items: none of Liandry's, Blackfire Torch, Luden's Echo, Shadowflame, Malignance, Sorcerer's Shoes appear in scorer top-8. The top-8 is dominated by crit/AD/Triforce AD items. The Collector (wr=36.0%, below baseline) IS present at scorer top-12 (rank ~9 in ad_tanky). The scorer is actively recommending the losing AD build and ignoring the winning AP build. outcome_ok = FALSE.

---

## Axis 4 - rune_ok: FALSE

rune_relevant=true. The burst scorer is AD-axis; rune recommendations downstream of this scorer would favor AD burst runes (e.g. Electrocute with AD/lethality shards). The empirically-winning AP build path would want Dark Harvest or Arcane Comet with AP shards. Since the scorer axis is wrong vs empirical, rune recommendations are also misaligned. rune_ok = false.

---

## Nominated Retune

Shaco ARAM empirically plays as AP mage-assassin. Two options:
1. Elevate secondary archetype "mage" to co-primary for ARAM anchor mode; route to mage scorer when AP damage share favors it (or when Lich Bane + AP items appear in build).
2. Add a hybrid-scalar to the burst scorer that weights Shaco's box (W) AP-scaling burst contribution so AP items (Liandry's, Blackfire Torch, Luden's) score competitively against Trinity Force and Essence Reaver.

Simpler near-term fix: dual-path archetype dispatch for Shaco (assassin/burst for AD builds, mage/burst-AP for AP builds) gated on a build-path signal or explicit ARAM override.
