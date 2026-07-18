# DS Cross-Eval: Twitch
Verdict: MINOR

## Axis 1 - archetype_ok: PASS
Archetype primary=carry secondary=assassin -> AD axis. Scorer=dps is correct for AD carry.
Empirical ARAM self (n=33, baseline 57.6%): top items are Runaan's Hurricane 65.4%, Yun Tal
66.7%, Kraken Slayer 66.7% - all AD items. Scorer (AD=carry) axis aligns with what wins.

## Axis 2 - comp_ok: PASS
Scorer=dps -> primary responsiveness axis is target_resist (correct for DPS). target_resist
comp_blind=false, max_positive_shift=22 (Liandry's Torment +22 vs AP-tanky comps). enemy_damage_type
comp_blind=true (max_positive_shift=0) - but dps scorers do NOT require damage-type sensitivity,
only target-resist sensitivity. No defect here.

## Axis 3 - outcome_ok: MINOR FLAG
Evidence tier ARAM = outcome_self (n=33 >= 8). Baseline wr=57.6%.

Above-baseline empirical items (>57.6%):
  Runaan's Hurricane  65.4%  n=26  -> scorer rank #3 (ad_squishy). OK.
  Berserker's Greaves 64.0%  n=25  -> boots, not in scorer pool. Expected.
  Yun Tal Wildarrows  66.7%  n=9   -> scorer rank #7. OK.
  Executioner's Call  66.7%  n=6   -> not in scorer top-12. Pool gap (minor; component item).
  Kraken Slayer       66.7%  n=6   -> scorer rank #4. OK.

Scorer top-8 (ad_squishy): BotRK #1, Void Immolation #2, Runaan's #3, Kraken #4,
Essence Reaver #5, Stormrazor #6, Yun Tal #7, IE #8.

Void Immolation is scorer rank #2 (score 102.9) but has n=0 empirical appearances in
ARAM self. As a 6000g mythic-tier exotic item with zero purchase rate, this over-ranking
is a minor pool concern - it inflates rank ahead of empirically-proven items.

Stormrazor is scorer rank #6 with no empirical presence (n=0). Minor pool gap.

No scorer-top item is empirically losing. Primary winners (Runaan's, Yun Tal, Kraken) all
appear in scorer top-8. Flag is pool distortion from Void Immolation at #2, not a wrong axis.

## Axis 4 - rune_ok: N/A
rune_relevant=false.

## Nominated retune
Investigate Void Immolation score basis for Twitch: it ranks #2 (score 102.9) in all squishy
and at-par in tanky cells, suggesting the poison/DoT interaction is firing strongly. With 0
empirical purchases this may be a correct theoretical score or a data artifact. Suppress or
cap Void Immolation in the pool if its score consistently outranks proven items without
empirical backing.
