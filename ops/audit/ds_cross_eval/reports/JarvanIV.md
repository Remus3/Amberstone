
# JarvanIV scorer cross-eval - MINOR

**verdict:** MINOR - pool admits marksman crit/AS items (Runaan's rank 4, Kraken rank 5) that
Jarvan cannot proc; top-8 axis and empirical staple overlap are otherwise acceptable.

evidence_tier: ARAM=outcome_all (n=127, baseline wr=38.6%) / SR=outcome_all (n=36, baseline wr=41.7%)

---

## Axis 1: archetype_ok - PASS

scorer=hybrid (primary=bruiser, secondary=tank). Hybrid scores both d_ehp and d_dps so a
bruiser/tank kit is correctly placed here. Empirical above-baseline items in ARAM:
- Sundered Sky (wr 42.5% vs 38.6% baseline, n=80) - AD spellblade, fits hybrid.
- Sterak's Gage (wr 41.9%, n=31) - pure tank EHP, fits tank secondary.
- Death's Dance (wr 40.5%, n=42) - AD mitigation, fits hybrid.
- Caulfield's Warhammer (wr 50.0%, n=16) - AD component, fits hybrid.

In SR: Eclipse (wr 44.4%, n=18), Plated Steelcaps (wr 46.2%, n=13), Black Cleaver (wr 44.4%, n=9) all AD/tank,
consistent with bruiser axis. No AP items above baseline in either mode. Axis is correct.

---

## Axis 2: comp_ok - PASS

responsiveness.comp_blind=false. primary_axis=enemy_damage_type. max_positive_shift=7 (Wit's End rises 7
ranks when enemy is AP). Dead Man's Plate and Iceborn Gauntlet fall -9 ranks vs AD comp (correct: MR
value drops vs AD). The scorer is not comp-blind; enemy_damage_type moves the rankings meaningfully.

---

## Axis 3: outcome_ok - MINOR

Scorer top-8 for ad_squishy / bal_squishy (the anchor comp cells):
  rank 1 Void Immolation, rank 2 BotRK, rank 3 Trinity Force - all plausible for a melee bruiser.
  rank 4 Runaan's Hurricane (score 0.9867, d_ehp=0.0) - MELEE-INAPPLICABLE. Runaan's projectile
    passive only fires from ranged AAs. Jarvan gains zero passive value; DPS credit is inflated.
  rank 5 Kraken Slayer (score 0.8963, d_ehp=0.0) - MELEE-INAPPLICABLE for the crit synergy path.
    Kraken's true-damage proc applies to all AAs, so it is not purely a ranged item, but the item is
    almost never built on Jarvan (absent from empirical top-10 in both ARAM and SR).
  rank 6 Essence Reaver (score 0.8766) - Jarvan does use spells but this is a crit/mana item with
    no meaningful empirical showing.
  rank 7 Heartsteel (score 0.8737, d_ehp=1609.7) - reasonable tank-bruiser pick.
  rank 8 Stormrazor (score 0.8113) - crit item, absent from empirical data.

Above-baseline empirical staples missing from scorer top-8 (ARAM):
  - Sundered Sky (6610, wr 42.5%) - NOT present in top-8 of any comp cell (appears lower in pool or absent
    from top-12 entirely). This is the most-built above-baseline item for Jarvan and is not in the
    scorer top-8. This is the most significant outcome gap.
  - Death's Dance (6333, wr 40.5%) - also absent from top-8.
  - Black Cleaver (SR wr 44.4%) - absent from top-12 in squishy cells.

Runaan's rank 4 and Kraken rank 5 occupy slots that should belong to Sundered Sky and Death's Dance.
Pool does not filter melee-inapplicable marksman crit/AS items. Severity: MINOR (pool/credit gap,
not a wrong axis or empirically-losing top-3).

---

## Axis 4: rune_ok - N/A

rune_relevant=false (hybrid scorer, not burst/assassin). No rune wiring to evaluate.

---

## Nominated retune

Prune Runaan's Hurricane from the hybrid pool for melee champions (or apply a melee-filter flag at
item-pool generation). Consider whether Kraken Slayer should carry a melee-usable tag. Raise
Sundered Sky pool weight for bruiser/hybrid melee scorers so it surfaces in the top-8. Death's Dance
is a confirmed above-baseline staple and should appear higher. No scorer axis change needed.
