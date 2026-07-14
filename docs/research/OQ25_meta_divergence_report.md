# OQ25 - Meta-Divergence Report: Daemon Slayer build reco vs real-meta build habits

Purpose: sweep where the Daemon Slayer (DS) item recommendation diverges from the
established real-meta build core for 16 AD carries / assassins, and bucket each gap
NOW (an existing engine lever covers it) or FUTURE (needs a schema / weights lift).
Documentation only - this report recommends NO live change and flips nothing.

GROUNDED-AGAINST: DS engine :8893, ENGINE_VERSION 1.210.0, patch 16.13.1, 173
champions. Live sweep 2026-07-13: POST /rank (carry / sustained-DPS scorer =
rank_items) and POST /rank-assassin (burst scorer = rank_items_by_burst), each
champion at level 11, target_armor=100, mode SR. Every DS-reco item below is quoted
verbatim from that sweep.

## Method

- Two live scorers were probed per champion: the carry path /rank (sustained
  auto-attack DPS) and the burst path /rank-assassin (one-rotation burst).
- Distilled meta core = established domain knowledge (on-hit / attack-speed / crit /
  lethality), not a scraped external winrate table.
- IMPORTANT probe caveat: the sweep hit POST /rank DIRECTLY (the raw engine endpoint).
  That endpoint defaults fight_length=None (agents/daemon_slayer/server.py:464), so it
  returns the pure sustained-DPS ranking with NO per-champion burst blend and NO
  squishy-target swap. The LIVE coach path is different - it runs through
  core.daemon_slayer_client.rank_for_primary_archetype, which consults the
  per-champion fight_length allow-map (core/ds_champion_fight_length.py), forwards
  fight_length into the /rank body (daemon_slayer_client.py:1351), swaps to a
  squishy-carry target (daemon_slayer_client.py:1317), and re-ranks respecting the
  burst-inclusive effective_score (daemon_slayer_client.py:1370). So for any champion
  IN that allow-map the raw-probe reco below is the pre-policy baseline, not what the
  live coach serves. This distinction is load-bearing for the Jhin finding.
- Archetype routing (coach_integration/archetype_dispatch.py) is operator-picked at
  champ-select: carry -> /rank | assassin -> /rank-assassin | bruiser -> /hybrid |
  tank -> /ehp | mage -> /ability | enchanter -> /hps. A marksman gets the carry
  scorer; only an operator "assassin" pick routes to the burst scorer.

## Findings (16 champions)

DS reco = top items from the live sweep (verbatim, top 3-4 shown).

| Champion | Live scorer | DS reco top items | Distilled meta core | Divergence | Bucket |
|---|---|---|---|---|---|
| Jhin | carry /rank | Runaan's Hurricane, Dusk and Dawn, Stormrazor, Essence Reaver (IE #5; ZERO lethality top-8) | lethality-crit burst (IE + execute + lethality) | raw /rank omits lethality; LIVE path already corrected by shipped fight_length=0.5 | NOW (SHIPPED for Jhin) |
| Ashe | carry /rank | Stormrazor, Kraken Slayer, Runaan's Hurricane, Guinsoo's Rageblade | crit-utility + on-hit AS | none | VALIDATED |
| Kalista | carry /rank | Stormrazor, Kraken Slayer, Runaan's Hurricane, Guinsoo's Rageblade | on-hit AS | none | VALIDATED |
| Kai'Sa | carry /rank | Stormrazor, Kraken Slayer, Guinsoo's Rageblade, Terminus | on-hit / hybrid AS | none | VALIDATED |
| Kog'Maw | carry /rank | Stormrazor, Runaan's Hurricane, Kraken Slayer, Dusk and Dawn | on-hit AS | none | VALIDATED |
| Vayne | carry /rank | Stormrazor, Guinsoo's Rageblade, Kraken Slayer, Terminus | on-hit (control champ) | none | VALIDATED |
| Aphelios | carry /rank | Yun Tal Wildarrows, Infinity Edge, Stormrazor, Kraken Slayer | crit (Yun Tal / IE) | none | VALIDATED |
| Jinx | carry /rank | Dusk and Dawn, Cruelty, Stormrazor, Lich Bane | crit AS hypercarry | none (also fight_length-mapped) | VALIDATED |
| Caitlyn | carry /rank | Dusk and Dawn, Stormrazor, Runaan's Hurricane, Essence Reaver | crit | none (also fight_length-mapped) | VALIDATED |
| Draven | carry /rank | Dusk and Dawn, Stormrazor, Runaan's Hurricane, Kraken Slayer | crit snowball | none (also fight_length-mapped) | VALIDATED |
| Samira | carry /rank | Dusk and Dawn, Stormrazor, Essence Reaver, Lich Bane | crit-lifesteal | none (also fight_length-mapped) | VALIDATED |
| Varus | carry /rank | Stormrazor, Runaan's Hurricane, Kraken Slayer, Guinsoo's Rageblade | on-hit AS (primary) / lethality poke (alt) | on-hit build correct; lethality-poke tail = allow-map candidate | VALIDATED (on-hit) |
| Miss Fortune | carry /rank | Stormrazor, Kraken Slayer, Guinsoo's Rageblade, Terminus | crit + Q-poke / lethality | on-hit core defensible; crit-primary tail = allow-map candidate | VALIDATED (with tail) |
| Zed | assassin /rank-assassin | Serylda's Grudge, Infinity Edge, Sundered Sky, Essence Reaver | pure-lethality snowball | armor-pen + crit surfaced; pure-lethality under-weighted | FUTURE |
| Talon | assassin /rank-assassin | Essence Reaver, Trinity Force, Infinity Edge, Serylda's Grudge | lethality snowball | same as Zed | FUTURE |
| Qiyana | assassin /rank-assassin | Infinity Edge, Sundered Sky, Essence Reaver, Serylda's Grudge | lethality snowball | same as Zed | FUTURE |

## DIVERGENT-NOW - Jhin (lever exists AND is already shipped)

Raw evidence: Jhin's carry /rank top-8 is Runaan's Hurricane, Dusk and Dawn,
Stormrazor, Essence Reaver, Infinity Edge, Terminus, Lich Bane, Kraken Slayer -
burst_keys empty, ZERO lethality items. Jhin's real meta is lethality-crit BURST:
his Whisper passive hard-locks attack speed, so his value is a few high-impact shots
(the 4th-shot execute + AD/lethality-scaling Q/W/R), rewarding per-shot one/two-shot
power (IE retained crit core + lethality + execute), NOT sustained auto uptime.

Is the assassin reroute the fix? No. Probing Jhin through /rank-assassin returns
Lich Bane, Essence Reaver, Lord Dominik's Regards, Trinity Force, Infinity Edge,
Terminus - AP-spellblade / on-hit ARTIFACTS (Lich Bane #1, Terminus #6), not his
lethality-crit core. The same control probe hands other marksmen AP artifacts too
(Miss Fortune -> Rabadon's Deathcap + Mejai's Soulstealer; Ashe -> Lich Bane +
Rabadon's Deathcap; Kai'Sa / Varus -> Lich Bane). So the burst scorer as-is mis-serves
AD marksmen - the fix must live in the CARRY path, via the fight_length blend, not by
rerouting Jhin to /rank-assassin.

The lever: rank.py already ships the fight_length reweight
(effective = burst_delta + delta_dps * fight_length), and burst.py ships
rank_items_by_burst. The NOW mechanism is to wire a SHORT per-champion fight_length at
the carry chokepoint so the ranking tilts toward the one-rotation burst core.

SHIPPED-STATE (do NOT re-pitch or re-wire): this lever is ALREADY LIVE for Jhin. The
allow-map core/ds_champion_fight_length.py pins jhin=0.5 (plus five crit ADCs -
draven/samira 0.3, twitch/caitlyn/jinx 0.5), consulted at
daemon_slayer_client.py:1297 and threaded through both the /rank body and the burst-
respecting coherence re-rank; the L1-L4 crit-burst fix shipped + live-validated at
ENGINE 1.208.0 (LEDGER 875; docs/specs/2026-07-13-ds-crit-burst-fix.md). The raw
/rank divergence above is exactly the pre-policy baseline that shipped lever corrects.
Jhin is therefore the PROOF the NOW mechanism works, not an open ticket. The only open
NOW tail is EXTENDING the same allow-map to unmapped lethality/crit-primary carries
(Varus poke, Miss Fortune crit are candidates) and the spec's own L5 (fed-conditional
fight_length) + L6 (stale-catalog hygiene) follow-ups - each per-champion validated,
never a blind bulk flip.

## DIVERGENT-FUTURE - AD assassins Zed / Talon / Qiyana (needs a weights lift)

Under an operator "assassin" pick these route to /rank-assassin (the burst scorer).
That scorer surfaces armor-pen and crit but under-weights the pure-lethality snowball
core that IS their real meta (Youmuu's / Opportunity / Profane Hydra / Edge of Night):

- Zed: Serylda's Grudge, Infinity Edge, Sundered Sky, Essence Reaver, Lord Dominik's
  Regards, Umbral Glaive - armor-pen (Serylda's, Lord Dominik's, Umbral Glaive) + crit
  (IE, Sundered Sky, Essence Reaver); ZERO pure-lethality snowball items.
- Talon: Essence Reaver, Trinity Force, Infinity Edge, Serylda's Grudge, Bloodthirster,
  Umbral Glaive - crit / on-hit-value lean; same lethality omission.
- Qiyana: Infinity Edge, Sundered Sky, Essence Reaver, Serylda's Grudge, Bloodthirster,
  Umbral Glaive - crit lean; same lethality omission.

The burst ranker values raw penetration + crit multipliers but has no lethality-as-
burst-enabler weighting (flat lethality front-loads the exact one-combo damage these
champions win on). Closing this is a scoring-model change (a lethality-valuation term /
weight in rank_items_by_burst), not a caller-side toggle - a schema / weights lift.
The existing crit-burst spec explicitly scopes this OUT as a separate future widening
("widen to lethality champs Zed/Talon only on separate test evidence"), and BACKLOG
has no entry for it yet. FUTURE -> add to BACKLOG.

## VALIDATED-CORRECT - the on-hit / AS / crit marksman cluster (no change; do NOT touch)

For the sustained / on-hit / crit marksmen the carry /rank reproduces the real meta
core faithfully - the engine is right where it should be. Evidence:

- Kai'Sa (on-hit hybrid): Stormrazor, Kraken Slayer, Guinsoo's Rageblade, Terminus,
  Runaan's Hurricane - the canonical on-hit stack (Kraken / Guinsoo's / Terminus /
  Runaan's), correct.
- Aphelios (crit): Yun Tal Wildarrows, Infinity Edge, Stormrazor, Kraken Slayer - the
  crit core (Yun Tal + IE) leads, correct.
- Kalista (on-hit AS): Stormrazor, Kraken Slayer, Runaan's Hurricane, Guinsoo's
  Rageblade, Terminus - pure on-hit, correct.

Ashe, Kog'Maw, Vayne, Jinx, Caitlyn, Draven, Samira reproduce the same way (Vayne is
the deliberate on-hit control; Jinx/Caitlyn/Draven/Samira are additionally in the
shipped fight_length allow-map, so their live path is doubly correct). Varus and Miss
Fortune land here on their on-hit / crit builds; their lethality-poke / crit-primary
variants are the same class as the shipped Jhin lever and would be handled by extending
the allow-map (the NOW tail above), not by any new mechanism. Do NOT touch this cluster.

## Recommendation (no blind flip - live routing is UNCHANGED by this report)

- NOW (a future ds-engine cycle, NOT this research slice): extend the SHIPPED
  core/ds_champion_fight_length.py allow-map to the remaining lethality / crit-primary
  carries the sustained scorer under-serves, each TDD RED-first and per-champion
  validated at the live target (the repo habit), reusing the Jhin pilot mechanism.
  Do NOT rebuild the burst machinery and do NOT re-wire Jhin - both are shipped.
- FUTURE (BACKLOG): a lethality-valuation weighting in the burst scorer
  (agents/daemon_slayer/burst.py rank_items_by_burst) so /rank-assassin surfaces the
  pure-lethality snowball cores for Zed / Talon / Qiyana. Schema / weights lift; gate
  on separate per-champion test evidence per the crit-burst spec scope guard.
- This report changes NOTHING live. No item flip, no ENGINE bump, no routing change.
