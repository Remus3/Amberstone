# XinZhao DS Scorer Cross-Eval

**Verdict: MISMATCH**

Scorer rank-1 item (BotRK) is empirically losing in ARAM; the three above-baseline staples are absent from the scorer top-8.

---

## Axis 1 - archetype_ok: TRUE

- archetype: bruiser/tank, source=default
- scorer: hybrid (AD axis)
- Xin Zhao is a melee AD diver/bruiser; hybrid scorer on AD axis is correct.
- Empirical above-baseline ARAM items: Death's Dance (wr 60.0), Boots of Swiftness (57.1), Titanic Hydra (66.7), Sundered Sky (52.0) - all AD/bruiser items. No AP crossover.
- Axis aligned.

## Axis 2 - comp_ok: TRUE

- scorer: hybrid has an EHP component, so enemy_damage_type MUST move.
- comp_blind=false (responsiveness.enemy_damage_type.comp_blind=false, responsiveness.comp_blind=false).
- Void Immolation d_ehp shifts: ad_squishy=4347.5, ap_squishy=3714.9 - the MR-EHP component correctly contracts vs AP enemies.
- enemy_damage_type max_positive_shift=9 (Wit's End rises +9 when AP). target_resist max_positive_shift=24 (Liandry's Torment rises +24 vs tanky AP).
- Scorer is responsive; not comp-blind. comp_ok=true.

## Axis 3 - outcome_ok: FALSE

- Evidence: ARAM self (n=38 >= 8, baseline wr=50.0).
- Above-baseline empirical items (wr > 50.0):
  - Sundered Sky (6610): n=25, wr=52.0 - most-played item, above baseline
  - Death's Dance (6333): n=10, wr=60.0 - strong above-baseline
  - Boots of Swiftness (3009): n=7, wr=57.1 (boots, not expected in scorer)
  - Titanic Hydra (3748): n=6, wr=66.7 - small sample but high wr
- Scorer top-8 (ad_squishy / bal_squishy):
  1. BotRK (3153) - empirical wr=42.9 BELOW baseline 50.0
  2. Void Immolation (223069) - not in empirical top items
  3. Runaan's Hurricane (3085) - not in empirical top items
  4. Trinity Force (3078) - not in empirical top items
  5. Kraken Slayer (6672) - not in empirical top items
  6. Essence Reaver (3508) - not in empirical top items
  7. Stormrazor (3097) - not in empirical top items
  8. Heartsteel (3084) - not in empirical top items

- BotRK is scorer #1 but empirically loses at wr 42.9 (delta -7.1 vs baseline). This is the primary defect.
- Sundered Sky (most-played ARAM item, wr 52.0) absent from scorer top-8.
- Death's Dance (wr 60.0) absent from scorer top-8.
- Titanic Hydra (wr 66.7 small sample) absent from scorer top-8.
- outcome_ok=false.

## Axis 4 - rune_ok: N/A

- rune_relevant=false.

---

## Nominated Retune

Reduce BotRK weight on Xin Zhao hybrid scorer or add a bruiser-diver correction: the %max-HP on-hit passive is less impactful on a dive-oriented champion vs DPS carries. Add Sundered Sky and Death's Dance to the scorer item pool / verify their EHP+DPS contributions are computed; both are staple bruiser-diver items that should surface in the top tier. Review whether the hybrid DPS component over-weights raw attack-speed/on-hit multipliers (BotRK, Runaan's, Kraken) vs the bruiser staples (Sundered Sky, Death's Dance, Sterak's Gage).
