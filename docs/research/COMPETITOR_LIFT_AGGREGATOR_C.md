# Competitor Lift Teardown - Aggregator C PC Desktop App overlay (2026-07-14)

Target: the **Aggregator C PC Desktop App** for League of Legends - the downloadable
Windows companion and its IN-GAME OVERLAY plus champ-select Live Companion. NOT the
aggregator C website (torn down R89 2026-07-10 / re-confirmed R112 2026-07-13).
Section-7b heavyweight deep-dive. Method: full-browser render of Aggregator C' own
overlay guide, corroborated by WebSearch feature copy and the Overlay Platform M store
listing, then a grep-verify pass against the live RC working tree at
C:\Riot Commander. 6-point depth checklist per surviving candidate.

## Verdict up front

DRAINED-NO-SHIP. The Aggregator C desktop overlay maps ~90 percent onto the R89 /
R100 / R117 / R120 don't-redo set exactly like the two other PC overlays already
torn down (Overlay App F R100, Overlay App E R117). ONE genuinely net-new residual survives:
an ENEMY / per-opponent ultimate power-spike readout (the Tab+W "enemy hit level 6,
ult unlocked" pop-up). It is net-new and needs no new external dependency, but it is
NOT presentation-only-over-existing-envelope-data: the per-enemy `level` is present
in the raw :2999 payload yet is NOT currently plumbed into RC's state envelope, so
it needs a one-field backend extract plus a new edge-detecting overlay panel. That
fails the strict ship-in-run gate (presentation-only + no-schema) that R117 F1 and
R89 F2 cleanly met. It is routed to BACKLOG-FUTURE (MED). No in-run ship.

## Observation provenance (same discipline as R89)

RENDERED HTTP 200 (observed - pixels/DOM seen):
- `https://aggregator-c.invalid/blog/lol-how-to-use-aggregator-c-overlay-live-companion/`
  via Apify apify/rag-web-browser, HTTP 200, full article body. THIS is the
  definitive overlay + Live Companion guide (Aggregator C' own long-form walkthrough
  with the Tab+Q/W/E/S hotkey map and per-widget screenshots described inline).
  Everything tagged "observed" below is from this render.

RENDERED but 404:
- `https://aggregator-c.invalid/lol/desktop-app` via Apify, HTTP 404. Not a content page,
  but its nav confirmed the download path `?isElectron=true&utm_medium=owaa` and an
  "In-game Overlay" footer link, corroborating the Electron/Overlay Platform M desktop client.

REPORTED (secondary snippet copy, NOT a render - Cloudflare-gated or search-only):
- The app-download / `lol-overlay` landing-page feature copy ("powerspike
  notifications, live gold leads, and jungle timers"; "power spikes for every role
  for early/mid/late game"; "live-updating stats with standings for gold spent, gold
  difference, number of completed items") came from WebSearch result summaries of
  `aggregator C/lol/glp/app-download` and `aggregator C/lol-overlay/`, not a
  render.
- Platform: the Overlay Platform M store listings `overlay platform M/app/aggregator C` (multiple)
  appeared in search, confirming Aggregator C Desktop is an **Overlay Platform M app** (decisive
  for the data-source wall below). Reported, not rendered.

Provenance honesty: 1 page rendered with full content (HTTP 200), 1 rendered as a
404 nav-only, remainder reported from search snippets. This is a stronger
observation base than R89 had for the overlay (R89 explicitly saw only the website
and called the overlay "reported, not observed"); this teardown observed the
overlay guide directly.

## The architectural wall (decisive, same as R120)

Aggregator C Desktop is an Overlay Platform M app. Overlay Platform M apps consume the Overlay Platform M Game
Events Provider (GEP), which exposes signals RC's pipeline architecturally cannot
see. RC is Live Client `:2999`-only per ADR-006. `:2999` for the operator's OWN
game exposes `activePlayer` (self hp/mana/level/gold/cs/abilities),
`allPlayers` (public scoreboard: championName, level, scores kills/deaths/assists/
creepScore/wardScore, items, summonerSpells, team, position, isDead, respawnTimer),
`events`, and `gameData`. It emits NO jungle-camp events, NO enemy cooldowns/buffs/
wards, NO enemy gold, NO positions. Any Aggregator C overlay feature that needs GEP
(jungle timers) or arbitrary-summoner Match-V5 history for all 10 players (the
per-player win-rate scout, which needs a Riot PRODUCTION key RC does not have) is
CLOSED, not a lift.

---

## Feature 1 - Tab+Q Player Stats and Insights (per-player WR + playstyle badges)

1. WHAT (observed) - a Tab-held overlay pane showing, for all 10 players: games
   played + win rate in their role, games played + win rate on that champion, plus
   colored "playstyle badges" (green = positive trait, red = negative, yellow =
   neutral; hover for detail). Observed examples: "Wrecking Ball" (excels at
   structure damage), "Ready to Rumble" (creates early-game action), "Improbable
   Pinks" (rarely uses control wards). It re-surfaces the champ-select scouting
   inside the game.
2. HOW (observed/inferred) - per-player role/champ WR needs each summoner's Match-V5
   history aggregated; the badges are described as algorithmic over every player's
   match stats with a green/red/yellow polarity. Both need each of the 10 players'
   ranked match history keyed by PUUID.
3. HAVE - PARTIAL / CLOSED for enemies. RC's FU02 team-context
   (`dashboard/routes_team_context.py`, pre-game rank/LP/WR/mastery card) covers the
   ALLY/self scouting card. The behavioral badges over a player's full history are
   CLOSED per ADR-006 single-player-corpus (R112 explicitly: "pre-game behavioral
   badges stays CLOSED"). Scouting all 10 (enemies included) by arbitrary-summoner
   Match-V5 is CLOSED for RC's personal key (R100 / R120).
4. WHERE - would extend `dashboard/routes_team_context.py`; but the enemy half has no
   in-scope data source.
5. EFFORT + RISK - CLOSED: enemy per-player history needs a production key; the
   behavioral-badge taxonomy is a single-player-corpus violation + a content/ML
   dependency.
6. LIFT verdict - CLOSED (data-source + ADR-006; reaffirms R112).

## Feature 2 - Tab+W Game Overview (the money pane; decomposed 2a-2d)

Observed: a live in-game feed that "condenses information you could have gathered by
interpreting your scoreboard - which lanes have hit their power spikes, who has a
gold lead" plus pop-ups and a Standings section. Four distinct mechanics:

### 2a - "which lanes hit power spikes" + team power-spike phase
1. WHAT (observed) - a live read of which lanes/teams have hit their power spike,
   early/mid/late phase colors (green strong / yellow average / red weak).
2. HOW - champion level/item breakpoint math over the public scoreboard.
3. HAVE - YES. Daemon Slayer is deterministic DPS math (706 items / 173 champs,
   ENGINE 1.212.0) and R81 `/api/spike-curve` emits phase stoplights
   (`dashboard/routes_spike_curve.py`, `web/js/panels/spike_curve.js:279` renders
   an ally-vs-enemy spike-peak tooltip, `agents/daemon_slayer/spike_markers.py`).
4. WHERE - already built.
5. EFFORT + RISK - none; duplicate.
6. LIFT verdict - COVERED (this is the R89 / R120 power-spike finding; RC's is
   deeper than the competitor's precomputed tiles).

### 2b - Enemy ultimate power-spike pop-up (enemy hit level 6 -> ult unlocked)   <- THE NET-NEW RESIDUAL
1. WHAT (observed) - "when your enemies hit level 6 and unlock their ultimate,
   you'll receive a handy pop-up" (and the same for major-item completions). An
   edge-triggered per-ENEMY milestone alert: this specific enemy just crossed the
   ult-unlock breakpoint (level 6 = R online, 11 = R2, 16 = R3).
2. HOW - poll `allPlayers[].level` from :2999; detect the not-spiked -> spiked
   rising edge per enemy; fire a transient glyph. Pure client arithmetic over a
   field the API already carries.
3. HAVE - NO (verified). RC has the EXACT mechanism but SELF-only:
   - `web/js/panels/spike_cue.js:45` `crossedSpike(prev,cur)` + `_SPIKE_LEVELS =
     [6,11,16]` fires "ULT ONLINE"/"ULT R2"/"ULT R3", but reads only
     `lc.level` (the active player - `spike_cue.js:10,104`), i.e. the operator.
   - `core/event_callouts.py:117,355` `_level_spike_callouts(level)` emits "Your
     lvl-6 spike - look for all-in" - keyed to the operator's own single `level`.
   - `web/js/main.js:1048-1052` toggles a `.spike` class on the operator's OWN
     level pill at 6/11/16 (self).
   - No panel reads a per-ENEMY level for a spike edge. The vision-tracker roster
     (`web/js/panels/active_match.js:1567` `if (e.level)`) shows a best-effort
     OCR level, not a reliable :2999 feed, and does no spike edge-detection.
   - DATA GAP: `dashboard/_liveclient.py:101` extracts `out["level"]` for the
     ACTIVE player only; the per-player list `out["players"]`
     (`_liveclient.py:177-186`) carries position/team/creep_score/is_active but
     NOT `level`. So per-enemy level is in the raw payload (same schema as
     `ap.get("level")`) yet not plumbed into the envelope.
4. WHERE - (1) add `"level": int(p.get("level") or 0)` to the `out["players"]`
   dict in `dashboard/_liveclient.py:177-186` (one line, no new source); (2) a new
   overlay panel `web/js/panels/enemy_spike_cue.js` reusing the `spike_cue.js`
   `crossedSpike` edge logic per enemy, gated on `body[data-shell="overlay"]`.
5. EFFORT + RISK - MED. No new Riot call (:2999 already polled every tick), no
   Claude, no DS engine/ENGINE_VERSION bump. BUT it is NOT presentation-only: it
   needs the one-field backend envelope extract + a new stateful panel (per-enemy
   prev-level edge state). That is a (small) schema/envelope touch, so it clears the
   no-new-dependency + testable gates but fails the strict presentation-only +
   no-schema ship-in-run gate.
6. LIFT verdict - MED, net-new -> BACKLOG-FUTURE. Distinct from and MORE feasible
   than R100 F1 (which is a MANUAL enemy ult/summ COOLDOWN tracker with no data
   feed); this is a DETERMINISTIC level-unlock edge from :2999, no manual input.

### 2c - Completed-item event feed / per-player completed-item count
1. WHAT (observed) - pop-ups when a player finishes a major item (Trinity Force,
   upgraded boots) and a completed-item count ("Warwick leads with four completed
   items").
2. HOW - diff `allPlayers[].items` tick-over-tick; flag new finished (>= major
   cost) items.
3. HAVE - PARTIAL / duplicate. `enemy_item_ids` IS in the envelope
   (`dashboard/_liveclient.py:150`) and item costs are client-side
   (`web/js/lib/items_index.js` `ITEM_COSTS.byId`; `active_match.js:1143`
   `_amCompletedItemCount` already counts finished >= 2000g items). The economy
   LENS this drives is the team item-value differential, SHIPPED R117 F1
   (`web/js/lib/item_value.js` `teamItemValueDiff`, `web/js/panels/map_state.js`
   `renderItemValueDiff`). A per-player completed-item count/event is a
   lower-fidelity, more granular restatement of that same item-value lens.
4. WHERE - would be an event feed over `enemy_item_ids`; but see risk.
5. EFFORT + RISK - LOW data-wise, but R120 already rejected a gold-gap estimate
   chip as a "lower-fidelity duplicate of the R117-shipped item-value differential";
   a per-player completed-item count is the same class of duplicate.
6. LIFT verdict - COVERED (duplicate of the R117 F1 item-value lens).

### 2d - Live "Standings" (rank all 10 players by stats, head-to-head)
1. WHAT (observed) - a Standings section ranking all 10 players by statistical
   standing (gold, CS, items) plus head-to-head lane comparisons.
2. HOW - sort the public scoreboard by CS / KDA / item value.
3. HAVE - PARTIAL. RC surfaces the live per-player scoreboard fields it holds (CS
   via `out["players"][].creep_score`, kills/assists via scores, item pools) and a
   live match panel (`web/js/panels/active_match.js`), plus Kill Participation
   (`_liveclient.py:187-204`), but does NOT render an explicit 1-to-10 ranking. A
   grep for standings/leaderboard/player-ranking in web/ + core/ is clean (only
   `coaches/adaptation_hint*.py`, unrelated).
4. WHERE - a presentation-only ranking over the existing `out["players"]` +
   score fields could live in `active_match.js`, but the highest-value ranking axes
   (item value, level) are the same data-gap as 2b/2c.
5. EFFORT + RISK - LOW-MED, but it is a re-presentation of the same economy/CS
   signals RC already shows (item-value diff, CS pills), not a new insight.
6. LIFT verdict - COVERED / LOW (repackaging of existing economy + CS lenses).

## Feature 3 - Tab+E Matchup Info in-game (power spikes, ability CDs, matchup advice)
1. WHAT (observed) - per-role lane-matchup context in-game: individual power spikes
   early/mid/late, ability cooldowns, and matchup-specific advice.
2. HOW - curated per-champion/patch content + level/item breakpoints + enemy
   ability CDs.
3. HAVE - COVERED / CLOSED per prior teardowns: power spikes = DS spike-curve
   (COVERED, 2a); the 1v1 matchup verdict = `dashboard/routes_ds_matchup.py` +
   `web/js/panels/ds_matchup.js` (R89); ability cooldowns = the MANUAL enemy tracker
   (`web/js/panels/enemy_spells.js`, summoner-spell version shipped; the ult-CD
   version is R100 F1 BACKLOG); curated "how to play against" prose = CLOSED R89
   (no-new-Claude-dependency + Error-Handling guardrails).
4. WHERE - already built / already triaged.
5. EFFORT + RISK - none new.
6. LIFT verdict - COVERED / CLOSED.

## Feature 4 - Jungle timers (Tab settings toggle)
1. WHAT (reported) - live per-camp jungle respawn timers as a toggle.
2. HOW - needs a camp-clear event = Overlay Platform M GEP `jungle_camps`.
3. HAVE - objective layer YES (`core/event_callouts.py` dragon/baron/herald/
   inhibitor/soul); per-camp layer NO and confirmed absent by design (R120 grep:
   0 camp matches in event_callouts).
4. WHERE - no feeding event on :2999.
5. EFFORT + RISK - CLOSED: sole source is Overlay Platform M GEP; SR-only, off RC's
   ARAM/Arena axis.
6. LIFT verdict - CLOSED (reaffirms R117 F4 / R120).

## Feature 5 - Champ-select Live Companion (pre-game scouting, builds, combos, team analysis, gank ops)
1. WHAT (observed) - the champ-select pane: player scouting (rank, role/champ WR,
   spells, runes, playstyle badges), build/rune/skill/summoner import (auto-import),
   champion combos, matchup stats (WR, gold@15, kills), Opponent Insight, champion +
   TEAM power spikes, damage-type distribution, gank opportunities, post-game report.
2. HOW - LCU + pre-computed content + Match-V5 aggregates.
3. HAVE - COVERED across the board (grep-cited): builds/runes/skill = DS engine +
   overlay item-1 rune-follows-build (shipped); combos = `dashboard/routes_ds_combo.py`
   + `ds_combo.js`; matchup = `routes_ds_matchup.py`; champion power spikes =
   spike-curve; team context / scouting = FU02 `dashboard/routes_team_context.py`;
   duo/team synergy = `dashboard/routes_duo_synergy.py` + `core/synergy_external_source.py`
   + `core/build_planner/kit_synergy.py`; damage-type mix = `routes_damage_mix.py`; combat-style
   archetype chip = `web/js/panels/archetype_chip.js` (R89 F2 shipped); post-game =
   the PGR suite (`routes_post_game_rubric.py`, `pgr_*.js`, `core/post_game_score.py`).
   The playstyle/behavioral badges half = CLOSED (Feature 1). Gank-opportunity
   scoring is the one sub-widget with no direct RC analog, but it needs enemy
   position/jungle-state modeling off RC's live axis and is not presentation-only.
4. WHERE - already built.
5. EFFORT + RISK - none new (gank-ops is off-axis).
6. LIFT verdict - COVERED (with gank-ops CLOSED as off-axis).

---

## Summary table

| Feature | net-new? | LIFT | ship-eligible in-run? |
|---|---|---|---|
| 1 - Tab+Q per-player WR + playstyle badges | no (enemy scout + badges CLOSED) | CLOSED | no |
| 2a - lanes/team hit power spikes | no | COVERED | no (already built) |
| **2b - ENEMY ult power-spike pop-up (lvl 6/11/16)** | **YES** | **MED** | **no (needs 1-field backend extract; not presentation-only)** |
| 2c - completed-item event / count | no | COVERED | no (dup of R117 F1 item-value) |
| 2d - live all-10 Standings ranking | marginal | COVERED/LOW | no (repackages existing lenses) |
| 3 - Tab+E in-game matchup info | no | COVERED/CLOSED | no |
| 4 - jungle timers | no | CLOSED | no (Overlay Platform M GEP only) |
| 5 - champ-select Live Companion | no | COVERED | no (already built) |

## Final VERDICT: (B) DRAINED-NO-SHIP

The Aggregator C desktop overlay is the third PC in-game overlay (after Overlay App F
R100 and Overlay App E R117) to tear down ~90 percent duplicate against RC's shipped
surface. No candidate is simultaneously presentation-only + no-new-dependency +
no-schema + snapshot-testable AND net-new, so there is no in-run ship. This matches
the R44 / R100 / R112 / R120 research-only precedent.

BACKLOG-FUTURE residual (MED, the one genuinely net-new mechanic):
- **Enemy ultimate power-spike readout (Feature 2b).** An overlay glyph that fires
  when an enemy crosses level 6 / 11 / 16 (R online / R2 / R3), reusing the
  `web/js/panels/spike_cue.js` `crossedSpike` edge logic per enemy. Deferred because
  it needs a one-field backend extract - add `level` to the `out["players"]` dict in
  `dashboard/_liveclient.py:177-186` (the raw :2999 `allPlayers[].level` already
  exists; RC just does not plumb it) - plus a new stateful panel, so it is a small
  schema/envelope + new-panel job, not a presentation-only slice. It is DISTINCT
  from and more feasible than the already-parked R100 F1 (manual enemy ult/summ
  COOLDOWN tracker): this is a deterministic level-unlock edge, no manual input, no
  cooldown feed. Do NOT build blind - scope it in a live game with a real enemy
  roster so the per-enemy level field and the SR/ARAM/Arena gating are verified
  against `/api/state.liveclient`.

Why the overlay category is drained: every high-value Aggregator C overlay mechanic is
either already shipped by RC (power-spike curve, item-value differential, matchup
verdict, combat-style chip, objective/soul/epic-buff callouts, team context,
synergy, PGR post-game), CLOSED by the :2999-only data wall (jungle timers = GEP;
per-player enemy WR + behavioral badges = production key + ADR-006 single-player
corpus), or a lower-fidelity duplicate of an existing RC lens (completed-item count,
gold-gap, standings). The sole net-new seam (enemy level-unlock spike) is data-gated
on a field RC has never plumbed and is not presentation-only.

Loop-health steer: this is the fourth explicit competitor-overlay drain flag (R100,
R112, R117, R120). A future competitor pick should target a category with no prior
RC teardown (draft theory, replay/VOD analysis, economy/wave tooling), not another
overlay/companion/stat-site whose value chain is an Overlay Platform M GEP signal or a
production-key warehouse RC's :2999-only pipeline cannot see.

ENGINE-IMPACT: NONE (docs-only; repo + live DS both ENGINE 1.212.0 patch 16.13.1,
no bump, no Share, no DS restart, no route/schema change). Competitor name retained
in this research artifact only; RC repo code carries none (name-scrub policy). Plain
ASCII throughout.
