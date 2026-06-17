# Khazix DS Scorer Cross-Eval

**Verdict: MISMATCH**

Scorer: burst | Archetype: assassin (primary), mage (secondary) | Anchor: ARAM | Evidence: outcome_all (n=112, wr=50.9%)

---

## Axis 1: archetype_ok - PASS

burst scorer is AD-anchored. Khazix is a pure AD lethality assassin; all damage scales off AD (Q, W, E, R). assassin + burst is the correct scorer axis. No issue here.

---

## Axis 2: comp_ok - PASS

scorer=burst is a pure-offense scorer (d_ehp=0.0 across all grid cells confirmed). Enemy damage type comp_blind=true is EXPECTED: the burst scorer scores outgoing damage only, survival against enemy comp is not in its formula. This is correct behavior, not a defect.

target_resist responsiveness is healthy: primary_axis=target_resist, comp_blind=false, max_positive_shift=+15.
- BotK rises +15 ranks (rank 3 in squishy -> rank 1 in tanky cells) as expected for %health AD item vs tanks.
- Armor-pen items (Serylda's Grudge rank 4, Lord Dom's rank 6, Mortal Reminder rank 8) appear in tanky cells but not in squishy top-8: correctly gated.
- Squishy-cell scores drop sharply vs tanky (Essence Reaver 412 -> 235), showing meaningful score differentiation.

comp_ok=true.

---

## Axis 3: outcome_ok - FAIL (MISMATCH)

Using outcome_all (ARAM, n=112, baseline wr=50.9%) per evidence_tier directive.

Scorer top-8 in ad_squishy (primary comp): Essence Reaver (#1, 412.0), Trinity Force (#2, 399.7), BotK (#3, 379.8), Infinity Edge (#4, 355.4), Umbral Glaive (#5, 332.7), Bloodthirster (#6, 314.1), Axiom Arc (#7, 310.5), Youmuu's Ghostblade (#8, 310.5).

Empirical ARAM items above baseline (>50.9%):
- Eclipse: wr=63.6% (n=22) - scorer rank 10 (score 309.8). Present but buried.
- Edge of Night: wr=60.0% (n=25) - NOT in scorer top-12 at all.
- Opportunity: wr=56.2% (n=16) - NOT in scorer top-12 at all.
- Hubris: wr=53.9% (n=76) - scorer rank 9 (score 310.5). Present but buried.
- Ionian Boots of Lucidity: wr=55.4% (n=65) - boots, out of item pool scope.

Scorer top-4 items (Essence Reaver, Trinity Force, BotK, Infinity Edge) do not appear in the empirical ARAM item list at any meaningful n. These are crit/sustain/on-hit items not built on Khazix. Essence Reaver (#1) is a crit-mana ADC item. Trinity Force (#2) is an on-hit bruiser item. Infinity Edge (#4) is a crit scaler. None of these belong in a lethality assassin pool.

Meanwhile, Edge of Night (60.0% wr, n=25) is absent from top-12 entirely and Opportunity (56.2%, n=16) is also absent. These are core Khazix lethality items that win games but the scorer does not surface them.

The burst scorer is over-weighting raw AD stat value without assassin archetype gating, pulling crit/on-hit items to the top. Lethality + ability-haste items that win empirically rank near the bottom or fall off the list.

---

## Axis 4: rune_ok - true

rune_relevant=true. No rune data in the cross-eval JSON to judge specific rune picks, but the flag is correctly set - Khazix rune choices (Dark Harvest vs Electrocute, lethality keystones) meaningfully affect burst window and are worth surfacing.

---

## Nominated Retune

Add assassin-archetype item affinity weights inside the burst scorer that penalize crit-class items (Essence Reaver, Infinity Edge, Bloodthirster, Trinity Force) for archetype=assassin. These items provide crit or sustained-damage passive bonuses that do not interact with Khazix's single-target burst rotation. Lethality items with AH (Edge of Night, Opportunity) should receive a positive affinity adjustment for assassin burst builds. This is an assassin-specific pool filter, not a global burst scorer change.
