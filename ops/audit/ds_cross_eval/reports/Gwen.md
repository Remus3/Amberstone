# DS Cross-Eval: Gwen

VERDICT: MINOR

Scorer: ability | Archetype: mage/bruiser | Anchor: ARAM | Evidence: outcome_all (n=49, wr=42.9%)

## Axis 1 - archetype_ok: PASS

Archetype primary=mage, secondary=bruiser. Scorer=ability. Mage/ability maps to AP axis - correct
for Gwen whose kit deals magic damage via abilities (snip snip, Hallowed Mist, Needlework).
Empirical above-baseline items (ARAM all, baseline 42.9%) include Shadowflame 50.0% (n=8),
Sorcerer's Shoes 50.0% (n=10), Rabadon's Deathcap 83.3% (n=6), Cosmic Drive 57.1% (n=7),
Spirit Visage 54.5% (n=11) - all AP or AP-synergy items. No AD-build divergence detected.

## Axis 2 - comp_ok: PASS

Scorer=ability falls under the dps/burst/ability/mage rule: target_resist should respond vs tanky.
responsiveness.target_resist.comp_blind=false; max_positive_shift=5; top risers vs AP-tanky enemy:
Abyssal Mask (+5), Cryptbloom (+3), Bloodletter's Curse (+3). Real responsiveness confirmed.

responsiveness.enemy_damage_type.comp_blind=true (max_positive_shift=0, no risers/fallers). This
is EXPECTED for an ability scorer - enemy AD/AP share does not change what Gwen buys to deal
damage outbound. No defect here.

## Axis 3 - outcome_ok: FAIL (MINOR)

Scorer top-8 (ad_squishy / bal_squishy): Liandry's Torment (#1, 27.6), Blackfire Torch (#2, 17.2),
Wooglet's Witchcap (#3, 14.1), Void Staff (#4, 6.4), Shadowflame (#5, 6.0), Stormsurge (#6, 5.3),
Rabadon's Deathcap (#7, 5.3), Cryptbloom (#8, 4.8).

Empirical items above baseline 42.9% (ARAM all):
- Spirit Visage: wr=54.5%, n=11 - ABSENT from scorer top-12 entirely.
- Cosmic Drive: wr=57.1%, n=7 - ABSENT from scorer top-12 entirely.
- Rabadon's Deathcap: wr=83.3%, n=6 - scorer rank #7. ALIGNED.
- Shadowflame: wr=50.0%, n=8 - scorer rank #5. ALIGNED.
- Sorcerer's Shoes / Plated Steelcaps: boots, out of scope for item scorer pool.

Riftmaker: scorer rank #10 (score 4.2 vs squishy, 2.6 vs tanky), empirical wr=37.8% (n=45) -
below baseline. This is a weak pool inclusion but not a top-build loss (rank 10).

Key gaps: Spirit Visage (heal-amp synergy with Gwen passive) and Cosmic Drive (AP/HP bruiser)
both win above average with decent n but are not scored. These are MINOR pool misses.

## Axis 4 - rune_ok: N/A

rune_relevant=false.

## Nominated Retune

Add Spirit Visage and Cosmic Drive to ability scorer consideration for mage/bruiser hybrids.
Optionally reduce Riftmaker weight (rank 10 empirically loses at -5.1pp below baseline, n=45).
