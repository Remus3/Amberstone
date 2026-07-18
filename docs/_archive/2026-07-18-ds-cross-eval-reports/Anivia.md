# DS Cross-Eval: Anivia

**Verdict: MINOR**

Scorer: ability | Archetype: mage (secondary: assassin) | Anchor: ARAM | Evidence tier: outcome_all (n=147)

---

## Axis 1 - archetype_ok: PASS

Primary mage + ability scorer = AP axis. Correct for Anivia: full-AP kit (Q freeze/stun, W wall, E amplified nuke, R sustained AoE slow). Empirical ARAM confirms AP dominance - Rod of Ages 60.6% wr (n=104), Rabadon's 63.3% (n=30), Seraph's Embrace 56.6% (n=113). Scorer top items are Wooglet's (rank 1), Liandry's (rank 2), Blackfire Torch (rank 3), Rabadon's (rank 4) - all AP. No axis conflict.

## Axis 2 - comp_ok: PASS (with note)

Ability scorer, primary_axis = target_resist. Target_resist is responsive: max_positive_shift=3 (Cryptbloom +3 ranks vs ad_tanky->ap_tanky, Bloodletter's +2, Void Staff +1, Liandry's +1). comp_blind = false here - correct behavior for a DPS-output scorer that prices magic pen vs tanky targets.

Note: enemy_damage_type sub-axis is comp_blind (max_positive_shift=0, no risers or fallers). For an ability scorer this is acceptable - self-survivability vs incoming damage type is outside ability scorer scope. Not a defect.

## Axis 3 - outcome_ok: FAIL (MINOR)

Baseline ARAM wr = 55.1% (n=147, outcome_all).

Above-baseline empirical items:
- Rod of Ages: wr 60.6%, n=104 - ABSENT from scorer top-8 (not in top-12)
- Seraph's Embrace: wr 56.6%, n=113 - ABSENT from scorer top-8 (not in top-12)
- Rabadon's Deathcap: wr 63.3%, n=30 - scorer rank 4 ad_squishy. OK.
- Liandry's Torment: wr 55.4%, n=101 - scorer rank 2. OK.
- Refillable Potion: wr 64.0%, n=25 - consumable, not scored. Expected absent.

Scorer top-8 items with below-baseline empirical wr:
- Shadowflame: scorer rank 6 (ad_squishy/bal_squishy), empirical wr 36.4% (n=22) - well below baseline. Actively losing.
- Stormsurge: scorer rank 7, no empirical presence (low n, not listed).
- Wooglet's Witchcap: scorer rank 1, no empirical presence (ARAM exclusive item - may not appear in DB).
- Blackfire Torch: scorer rank 3, no empirical presence.

Root gap: Rod of Ages (the 2nd most-built item in ARAM at n=104, 60.6% wr) is entirely absent from scorer consideration. Same for Seraph's Embrace (n=113, 56.6% wr). Both are mana-scaling items that suit Anivia's sustained AoE pattern. Ability scorer appears to not model mana/mana-scaling as a damage-enabling stat, missing these staples.

Shadowflame in rank 6 is a real pool pollution issue - empirically it loses at 36.4%.

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

Add Rod of Ages and Seraph's Embrace to ability scorer item pool for sustained-AP mages (mana-scaling path). Investigate Shadowflame scoring weight: scorer values it for magic pen + AP, but empirically it underperforms for Anivia (36.4% wr, n=22) - likely over-rewarding burst-crit synergy that does not fit her sustained poke/wave-clear pattern. Recommend deprioritizing Shadowflame below at least Cryptbloom and Riftmaker for ability scorers with a poke/sustained archetype tag.
