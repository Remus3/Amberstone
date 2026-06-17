# DS Cross-Eval: Zoe

**Verdict: MINOR**

Scorer: ability | Archetype: mage/assassin | Anchor: ARAM | Evidence: outcome_all (n=161, baseline wr=42.9%)

---

## Axis 1 - archetype_ok: TRUE

Mage/assassin -> AP axis -> ability scorer is correct. Zoe's damage is 100% AP ability-based (Q Paddle Star
is the primary damage vector). All scorer top items are AP (Wooglet's, Liandry's, Rabadon's, Shadowflame,
Void Staff). Empirical items confirm AP identity (Luden's Echo #1, Shadowflame, Rabadon's). Axis aligned.

## Axis 2 - comp_ok: TRUE

Ability scorer -> target_resist responsiveness expected; enemy_damage_type comp_blind expected for pure AP
damage dealer.

- responsiveness.primary_axis = target_resist: correct.
- target_resist.comp_blind = false; max_positive_shift = 5 ranks. Bloodletter's Curse rises +5 vs tanky,
  Void Staff +3, Cryptbloom +2. Scorer adapts meaningfully to MR vs physical-heavy enemies.
- enemy_damage_type.comp_blind = true; max_positive_shift = 0. Expected for a mage/assassin that builds
  full AP regardless of enemy damage type. Not a defect.

## Axis 3 - outcome_ok: FALSE (MINOR pool gap + overrated item)

Using ARAM all (n=161, baseline wr=42.9%). Items above baseline wr:
  - Rabadon's Deathcap: 47.5% (scorer rank 3) - present, good.
  - Luden's Echo: 44.8% (n=143) - ABSENT from scorer pool entirely.
  - Shadowflame: 44.2% (scorer rank 5) - present, good.
  - Stormsurge: 43.8% (scorer rank 7) - present, good.

Pool gap: Luden's Echo is the most-built item (n=143, 89% of games) and highest wr above baseline (44.8%),
yet it does not appear in the scorer top-12 for any comp cell. Missing the empirically dominant first-buy
is a meaningful calibration gap.

Overrated item: Void Staff sits at scorer rank 6 (ad_squishy/bal_squishy) but has empirical wr 31.0%
(n=29) - 11.9pp below baseline. This is the worst-performing item in the pool and is ranked above staples.

## Axis 4 - rune_ok: n/a

rune_relevant = false.

---

## Nominated retune

Add Luden's Echo to Zoe's ability-scorer item pool; investigate why it is absent (likely missing echo-burst
passive registration). Audit Void Staff scoring weight for Zoe - its rank 6 position is inconsistent with
31.0% empirical wr. Consider penalizing Void Staff in non-tanky matchups (rank appropriate for tanky cells
where it already rises +3 vs ap_tanky, but over-weighted in squishy/ad_squishy).
