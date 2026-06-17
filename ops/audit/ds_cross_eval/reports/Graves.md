# DS Cross-Eval: Graves

**Verdict: MINOR**

Scorer: dps | Archetype: carry (secondary bruiser) | Anchor: ARAM
Evidence tier: outcome_all (n=157 ARAM, wr baseline 49.7%)

---

## Axis 1 - archetype_ok: PASS

carry + dps = AD axis. Graves kit is physical: shotgun Q, dash-and-shoot E, smokescreen W, crit-scaling passive reload mechanic. AD marksman builds are correct. Empirical above-baseline item is Eclipse (wr 53.8%, n=26) - an AD lethality item. Axis aligned.

## Axis 2 - comp_ok: PASS

dps scorer. enemy_damage_type.comp_blind=true (max_positive_shift=0, no risers/fallers) - expected for a pure DPS scorer with no EHP component. Scoring raw output, not survivability adaptation.

target_resist responds correctly: max_positive_shift=25 vs tanky comps. Top risers vs tanky: Liandry's Torment +25, Serylda's Grudge +14, Mortal Reminder +6, Terminus +5, Eclipse +5. Armor-pen and %hp-damage items rise vs armor-stacked targets. This is correct dps-scorer behavior.

Top-level comp_blind=false (target_resist does respond). No defect.

## Axis 3 - outcome_ok: MINOR (pool calibration gap)

Using outcome_all (n=157 >= 8). Baseline wr=49.7%.

Only item empirically above baseline: Eclipse wr 53.8% (n=26). Eclipse ranks #8 in scorer top-8 for squishy comps. Good - scorer finds the best empirical item.

Gap: BotRK is scorer rank-1 by a large margin (score 89.77 vs rank-2 Essence Reaver 65.68) but has no empirical count in the outcome_all data - cannot validate this dominance. Similarly Runaan's Hurricane (rank 3, score 64.40) and Stormrazor (rank 6) have no empirical representation. These may be overcalibrated relative to the empirical signal.

Commonly-built items in empirical pool that are below baseline:
- The Collector: n=135, wr 48.1% (scorer rank 11 - scorer correctly deprioritizes it)
- Infinity Edge: n=92, wr 46.7% (scorer rank 5 squishy - slight overrank vs empirical)
- Bloodthirster: n=92, wr 47.8% (not in scorer top-8 - appropriate exclusion)
- Lord Dominik's: n=67, wr 41.8% (scorer rank 10 ad_tanky - appropriate demotion)

Infinity Edge at scorer rank 5 squishy (score 53.26) vs empirical wr 46.7% is a mild overrank but IE wr is noisy (high-n but comp-dependent). Not a hard flag.

No scorer top-8 item is empirically losing at meaningful sample size. Eclipse alignment is good.

## Axis 4 - rune_ok: n/a

rune_relevant=false.

---

## Nominated retune

BotRK score anchoring investigation: score 89.77 is 36% above rank-2 (65.68). If BotRK's %max-HP damage or on-hit formula is driving this gap, verify Graves qualifies for on-hit synergy weight. Reduce if overcalibrated. Secondarily check IE rank-5 squishy vs its empirical 46.7% wr.
