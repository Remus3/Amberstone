# DS Cross-Eval: Elise

VERDICT: MINOR
Scorer: ability | Archetype: mage/assassin (source: default) | Anchor: ARAM

## Axis 1: Archetype OK - TRUE

Elise is a pure AP burst kit (Neurotoxin, Volatile Spiderling, Cocoon, Spiderling AAs all scale AP).
Mage/assassin -> ability scorer -> AP axis. Correct.
Empirical ARAM above-baseline (baseline wr 57.9%): Shadowflame 62.1%, Blackfire Torch 62.5%,
Sorcerer's Shoes 58.3% -- all AP damage items. No AD staple appears above baseline. Axis aligned.

## Axis 2: Comp OK - TRUE

Scorer=ability. Expectation: target_resist moves (tanky comps should shift item rankings);
enemy_damage_type invariance is acceptable (mage items are not defensive; enemy damage type
doesn't change what AP items to buy).

target_resist: comp_blind=false, max_positive_shift=3. Cryptbloom and Bloodletter's Curse
each shift +3 ranks vs AP tanky (pen items promoted vs tanks). Shadowflame -3, Stormsurge -2
vs tanky (burst-on-squishy items correctly deprioritized vs tanks). Responsive as expected.

enemy_damage_type: comp_blind=true, max_positive_shift=0. No items move based on enemy damage
mix. This is EXPECTED for an ability/mage scorer -- Elise doesn't build resistances, so
enemy AD vs AP split should not change her item order. comp_ok=true.

## Axis 3: Outcome OK - FALSE

Evidence tier: outcome_all (ARAM self n=0). ARAM all: n=57, baseline wr=57.9%.

Scorer top-8 (ad_squishy / bal_squishy cells, identical ranking):
  Rank 1 Liandry's Torment   -- empirical n=26, wr=50.0% (7.9 pp BELOW baseline) DEFECT
  Rank 2 Blackfire Torch     -- empirical n=8,  wr=62.5% (above baseline) OK
  Rank 3 Wooglet's Witchcap  -- absent from empirical top-10 (n too low to assess)
  Rank 4 Void Staff          -- empirical n=10, wr=40.0% (17.9 pp BELOW baseline) DEFECT
  Rank 5 Shadowflame         -- empirical n=29, wr=62.1% (above baseline) OK
  Rank 6 Rabadon's Deathcap  -- empirical n=21, wr=57.1% (near baseline) acceptable
  Rank 7 Stormsurge          -- empirical n=21, wr=57.1% (near baseline) acceptable
  Rank 8 Cryptbloom          -- absent from empirical top-10

Absent staple: Luden's Echo (empirical n=39, wr=56.4%) does not appear anywhere in the
12-item scorer list for any comp cell. High-frequency empirical staple missing from scorer pool.

Summary: Liandry's (#1 scorer) and Void Staff (#4 scorer) are empirical losers in ARAM.
Void Staff at 40.0% wr is a significant anchor item that the scorer overvalues.
Luden's Echo is the highest-n item in the empirical set and is entirely absent from the scorer.

## Axis 4: Rune OK - N/A

rune_relevant=false.

## Nominated Retune

1. Liandry's Torment over-scored: burn-on-ability passive amplified too heavily for a burst/execute
   kit (Neurotoxin max-% execute doesn't synergize with sustained burn; empirical wr 50.0%).
2. Void Staff over-scored: %pen value over-rated for a burst kit that aims to oneshot squishies
   who are already low MR; empirical wr 40.0% in ARAM.
3. Luden's Echo missing from scorer pool entirely: re-evaluate echo passive (on-ability nuke)
   vs Elise's cast pattern; should appear in pool at minimum.
