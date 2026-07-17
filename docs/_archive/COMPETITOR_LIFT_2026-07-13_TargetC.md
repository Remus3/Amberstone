# Competitor Lift Teardown - Target C (Section 7b deep-dive, 2026-07-13, R117)

**Target C** = a major live-companion + build-path/tier-list aggregator (a
desktop app plus web tier-lists; brand withheld per the pre-release name-scrub).
Distinct from the already-torn-down family: stat-sites (aggregator B 2026-06-21, aggregator N
2026-06-22, aggregator D 2026-06-27, aggregator C 2026-07-10), guide-sites (guide site Q
2026-06-30, aggregator S 2026-07-01, aggregator H 2026-07-03), and live-scout
(overlay app F 2026-07-10). This teardown covers the desktop-companion + auto-build
product line, which had no prior RC artifact.

## Verdict up front

**SHIP-CANDIDATE found + shipped in-run: F1 - team item-value differential.**
It is the one economy lens RC lacked, computable entirely from data RC already
ingests, and it lights up a UI bar that was wired to a field nothing produces
live. All other candidates are already-haves (CLOSED) or need a new data
source / retention mechanism (BACKLOG-FUTURE).

Feature inventory captured (public marketing + overlay pages): auto-import
runes/builds, tier lists (WR + WR-delta), pro builds, post-match analysis,
suggested picks/bans, profile/match history, and ~12 in-game overlays (ARAM
augments, benchmarking, ARAM health timers, skill order, **item value
difference**, minimap timers, ultimate timers, arena augments, jungle pathing,
loading-screen scouting, trinket reminder). Every feature was grepped against RC.

---

## F1 - Item Value Difference  ->  SHIPPED IN-RUN

1. **WHAT** - a live per-team readout of item gold-worth, so you see who is
   economy-ahead even though the scoreboard hides enemy gold. Target C surfaces
   it as an overlay ("compare the value of players' item inventories").
2. **HOW** - the only per-player economic signal the Live Client exposes for all
   10 is `allPlayers[].items` (item id per slot). Sum each player's item gold
   cost (DDragon `gold.total`) and diff ally-team vs enemy-team. Pure client-side
   arithmetic over public scoreboard items + a static cost table.
3. **HAVE - NO (verified).** RC ingests both inputs but never valued them:
   - per-player items for all 10 are read server-side (`dashboard/_liveclient.py`
     builds team item pools, comment notes "allPlayers[].items is PUBLIC
     scoreboard data for ALL 10 players (unlike gold, which is
     activePlayer-only)") - but only pooled for the heal-threat nudge, never
     summed to value.
   - item gold costs exist client-side: `web/js/lib/items_index.js:14,143`
     (`ITEM_COSTS.byId`), used only to count finished items
     (`web/js/panels/active_match.js:1143` `_amCompletedItemCount`, >=2000g) and
     price single build items. No JS summed an inventory or diffed two players.
   - a dormant gold-diff bar existed: `web/js/panels/map_state.js` `renderGoldDiff`
     read `p.team_gold_diff`, a field with **zero live producers** (only a
     post-game trend text at `core/match_metrics.py:321` + test fixtures), so the
     bar was permanently hidden. A true live team gold-diff is uncomputable
     (enemy gold is activePlayer-only), so the bar could never light up as
     designed.
4. **WHERE** - client-side, presentation-only: new pure helper
   `web/js/lib/item_value.js` (`teamItemValueDiff(liveclient, ITEM_COSTS)`) +
   repurpose the dormant bar in `web/js/panels/map_state.js`
   (`renderItemValueDiff`), reading `state.latest.liveclient` (the canonical path,
   `web/js/main.js:600`). `ITEM_COSTS` already loaded - no new asset.
5. **EFFORT + RISK** - LOW. No new Riot call (items already polled), no Claude,
   no DS schema lift, no backend/state-envelope change, no RC restart (asset-hash
   auto-reload, ADR-008). Deterministic -> unit + contract tested. Touch-points
   confirmed NOT frozen.
6. **LIFT: HIGH** - lights a dead bar and adds the one economy lens RC lacked,
   entirely from data it already ingests. **Shipped this cycle** (see below).

**Honesty correction applied:** item value is an economy *proxy*, not literal
gold-in-hand (it excludes unspent gold, which is unknowable for the enemy
anyway). The bar is relabeled "item value" (not "gold") with a clarifying
tooltip, matching the R81 honest-comparative-form discipline.

### F1 slice (shipped)
- `web/js/lib/item_value.js` - pure `teamItemValueDiff` / `_resolveMyTeam` /
  `_playerItemValue`; fail-soft null (bar hides) on any missing input; unknown
  ids contribute 0 (truthful undercount).
- `web/js/lib/item_value.test.mjs` - 8 node tests (`node --test`).
- `web/js/panels/map_state.js` - `renderItemValueDiff` sources item value from
  `state.latest.liveclient`; the dead `p.team_gold_diff` read is gone.
- `web/index.html` - bar relabeled "item value" + tooltip.
- `tests/snapshot_panels/test_item_value_diff.py` - 8 contract tests (CI-gated).

Visual pixel capture OWED (carry-forward): the bar only renders in a live game
with `liveclient.allPlayers`; RC was in `client` mode (no game) this cycle. The
5-phase code-side audit passed (no MUST-FIX).

---

## F2 - Tier-list "WR-delta" patch-over-patch trend  ->  BACKLOG-FUTURE
1. **WHAT** - tier list shows a win-rate delta vs the previous patch (rising/
   falling meta arrow), e.g. "50.1% +1.1%".
2. **HOW** - needs a stored snapshot of last patch's per-champ WR; delta =
   current - previous.
3. **HAVE - NO.** RC has current WRs (`core/smoothed_rates*.py`) but no retained
   prior-patch WR snapshot to diff (grep found no champ-WR patch-delta field).
4. **WHERE** - a patch-keyed WR snapshot store + a delta field on the champ/tier
   route (`dashboard/routes_champions.py`).
5. **EFFORT + RISK** - MED. Not presentation-only - needs cross-patch data
   retention (a new stored artifact), though no new external dependency.
6. **LIFT: MED** - nice meta-trend signal, gated on a retention mechanism RC
   lacks. -> BACKLOG.

## F3 - ARAM health-relic respawn timer  ->  BACKLOG-FUTURE (minor)
1. **WHAT** - counts down Howling Abyss health-relic respawn.
2. **HOW** - fixed spawn cadence -> pure game-clock arithmetic (RC's objective
   pattern).
3. **HAVE - NO.** grep for relic/health-timer empty; RC objective timers are
   SR-only (`objective_gauges.js`).
4. **WHERE** - an ARAM-gated panel over `liveclient.game_time_s`, mirroring
   `objective_gauges.js`; constants alongside `core/event_callouts.py`.
5. **EFFORT + RISK** - LOW-MED. Clock-only (no dep), but the Live Client emits no
   relic-pickup event, so it can only show the fixed cadence, not consumed/next -
   lower fidelity than Target C.
6. **LIFT: LOW-MED** - feasible + on-brand for RC's ARAM focus but niche and
   fidelity-limited. -> BACKLOG.

## F4 - Jungle pathing overlay  ->  CLOSED (LOW)
New clear-route logic + camp data; the Live Client emits no jungle-camp events
(noted in `objective_chips.js`), and it is off RC's ARAM/Arena axis. Not
presentation-over-existing-data.

## F5 - Pro builds (import what pros run)  ->  CLOSED (LOW)
Needs a pro-match data source (new external dependency) and runs against RC's
deliberate pure-simulation build philosophy (DS is optimal-not-copied).

---

## CLOSED - RC already has these (grep-cited)

| Target C feature | RC equivalent |
|---|---|
| Benchmarking overlay | `dashboard/routes_bench_rank_tier.py` (`/api/rank-tier-bench`) + `champ_benchmarks.js` |
| Ultimate / summ timers | `web/js/panels/cd_ledger.js` + `core/summoner_cooldowns.py`; enemy tracker `enemy_spells.js` |
| Minimap objective timers | `web/js/panels/objective_gauges.js` + `objective_chips.js` + `core/event_callouts.py` |
| Recommended skill order | `dashboard/routes_ds_skill_order.py` + `ds_skill_order.js` |
| ARAM / Arena augments | `web/js/panels/augment_reco.js` |
| Suggested picks & bans | `routes_ban_suggest.py`, `routes_pickban.py`, `routes_sr_draft.py`, `routes_duo_synergy.py` |
| Post-match analysis | PGR suite: `routes_post_game_rubric.py`, `pgr_*.js`, `core/post_game_score.py` |
| Profile & match history | `last_match.js`, `historical_pgr.js`, rewind DB |
| Loading-screen scouting | `dashboard/routes_scouting.py` (`/api/scouting`) |
| Trinket reminder | `web/js/main.js` (trinket/control-ward READY cue) |
| Auto-import runes & builds | overlay item 1 rune-follows-build (shipped) + DS build engine |
| Tier lists | DS/win-rate tier surfaces (the WR-delta *trend* is the only novel slice -> F2) |

## Bottom line
One net-new economy lens (F1) shipped in-run, presentation-only over
already-ingested data. F2/F3 -> BACKLOG-FUTURE. F4/F5 CLOSED. The
desktop-companion aggregator family is now substantially torn down; remaining
novelty is gated on data RC does not retain (patch-over-patch WR) or events the
Live Client does not emit (jungle camps, relic pickups).
