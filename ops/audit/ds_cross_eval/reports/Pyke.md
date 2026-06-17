# DS Cross-Eval: Pyke

**Verdict: MINOR**

Scorer: burst | Archetype: assassin/enchanter | Evidence: outcome_all (ARAM n=150, wr=52.0%)

---

## Axis 1 - archetype_ok: PASS

Burst scorer uses AD axis. Pyke's full kit (Q/E/R) is physical AD-scaling. Empirical
above-baseline items are all AD lethality: Youmuu's Ghostblade 57.8%, Opportunity 58.1%,
Axiom Arc 53.6%. AD axis is correct for both kit and what wins.

## Axis 2 - comp_ok: PASS

Burst scorer primary_axis = target_resist. target_resist.comp_blind = false,
max_positive_shift = 11 (Black Cleaver +11, Serylda's +10, Mortal Reminder +9).
Scorer correctly differentiates squishy vs tanky enemies.

enemy_damage_type.comp_blind = true (max_positive_shift = 0). This is expected: burst
is not an EHP scorer and does not need to react to whether the enemy team is AP or AD.
Comp-blind on damage-type is correct behavior for this scorer type.

## Axis 3 - outcome_ok: FAIL (pool gap)

Baseline ARAM wr = 52.0%. Above-baseline empirical items (outcome_all):
- Opportunity (6701): 58.1% wr, n=31 -- NOT in scorer top-8 (absent from ad_squishy/bal_squishy top-12)
- Youmuu's Ghostblade (3142): 57.8%, n=45 -- scorer rank 8 (present, OK)
- Axiom Arc (6696): 53.6%, n=125 -- scorer rank 7 (present, OK)

Scorer top-8 (ad_squishy / bal_squishy): Sundered Sky, Essence Reaver, Blade of the Ruined
King, Trinity Force, Infinity Edge, Umbral Glaive, Axiom Arc, Youmuu's Ghostblade.

Ranks 1-5 (Sundered Sky, Essence Reaver, BotRK, Trinity Force, Infinity Edge) have ZERO
empirical presence in the Pyke item pool (n=0 across all empirical lists). These items do
not appear on Pyke in practice at any frequency. The scorer is recommending items that
players never build on this champion.

Opportunity (58.1% wr, n=31) is a clear Pyke staple with above-baseline win rate and is
entirely absent from the scorer top-12.

## Axis 4 - rune_ok: true

rune_relevant = true. Plausible: Pyke keystones (First Strike, Electrocute) materially
affect gold generation and burst damage output. No rune sub-data in the eval JSON to
contradict this flag.

---

## Nominated Retune

Add Opportunity (6701) to the burst scorer AD lethality pool for Pyke. Investigate
why Sundered Sky, Essence Reaver, BotRK, Trinity Force, and Infinity Edge score so
highly (ranks 1-5) when they have zero empirical presence -- likely a base-stat scoring
artifact without a Pyke-specific lethality weight. Downweight or exclude crit/on-hit
items from the Pyke burst pool; amplify lethality items (Edge of Night, Opportunity,
Hubris, Axiom Arc, Youmuu's).
