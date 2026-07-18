# DS Cross-Eval: Corki

Verdict: MINOR
Scorer: dps | Archetype: carry/mage | Evidence: ARAM outcome_self (n=10, wr=10.0%), ARAM outcome_all (n=130, wr=43.8%)

---

## Axis 1: archetype_ok - PASS

Scorer = dps (AD/carry axis). Corki is a hybrid AD/AP kit but empirical data confirms AD-path
items dominate actual builds: Muramana (n=99, wr=45.5%), Trinity Force (n=80, wr=46.2%),
Bloodthirster (n=21, wr=52.4%). These are all AD/hybrid items - no AP staples appear in the
top empirical frequency list. Carry/dps axis is correct for empirical win patterns.

---

## Axis 2: comp_ok - PASS

Scorer = dps. Primary axis = target_resist (correct for dps). Enemy damage type responsiveness
is comp_blind (max_positive_shift=0) which is expected - a dps scorer does not adapt to enemy
damage composition, only to target tankiness. Target_resist does respond: max_positive_shift=23
driven by Liandry's Torment (+23 rank shift vs tanky), Lord Dominik's (+7), Serylda's (+6),
Mortal Reminder (+5), Eclipse (+5). Tanky-enemy adaptation is working. No defect here.

---

## Axis 3: outcome_ok - FAIL (pool gap)

Using ARAM outcome_self (n=10 >= 8). Self wr=10.0% (1 win in ~10 games) vs baseline 43.8% -
strongly losing. However n=10 is a thin sample; the all-pool (n=130, wr=43.8%) is more stable.

Scorer top-8 in ad_squishy/bal_squishy:
  rank 1 Blade of The Ruined King (3153)
  rank 2 Kraken Slayer (6672)
  rank 3 Runaan's Hurricane (3085)
  rank 4 Void Immolation (223069)
  rank 5 Stormrazor (3097)
  rank 6 Essence Reaver (3508)
  rank 7 Infinity Edge (3031)
  rank 8 Eclipse (6692)

Empirical ARAM items above baseline (43.8%) by wr:
  Bloodthirster (3072): n=21, wr=52.4% - NOT in scorer top-8
  Long Sword (1036): n=16, wr=50.0% - component, not scored
  The Collector (6676): n=62, wr=46.8% - NOT in scorer top-8
  Trinity Force (3078): n=80, wr=46.2% - NOT in scorer top-8
  Muramana (3042): n=99, wr=45.5% - NOT in scorer top-8

The scorer top-8 is entirely pure-ADC crit/AS items (BotRK, Kraken, Hurricane, Stormrazor,
IE, Eclipse). Corki's actual winning pattern is a Muramana + Trinity Force hybrid that exploits
his Mana charge (Q shots build Muramana stacks) and Package reset burst. None of these three
high-frequency above-baseline empirical items appear in the scorer top-8. IE (rank 7) has
wr=42.6% in all-pool - slightly below baseline 43.8%. The scorer pool is misaligned with
Corki's empirical winning items.

---

## Axis 4: rune_ok - N/A

rune_relevant=false.

---

## Nominated Retune

Add Muramana (3042) and Trinity Force (3078) to Corki's champion-specific item pool with
mana-synergy or ability-haste multipliers so the scorer surfaces the Mana-stacking hybrid
path. The Collector (6676) also has above-baseline wr (46.8%) and should be evaluated for
pool inclusion. BotRK as scorer rank-1 is not in the top empirical items at all - investigate
whether the BotRK %HP passive weight is overfitting to the carry profile for a champion who
rarely autos as his primary damage source.
