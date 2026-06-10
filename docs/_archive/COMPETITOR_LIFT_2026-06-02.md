# Competitor Lift Teardown - the competitor site

Date: 2026-06-02
Target: the competitor site (site + companion web app; there is NO desktop app - see Finding 0)
Method: live browser render (Chrome DevTools MCP) + captured XHR payloads on
the competitor API, plus xPetu's published WPA thesis / explainer video.
All claims below verified against the LIVE network responses, not marketing copy.

## TL;DR

the competitor site is ONE WPA (Win Probability Added) stat engine wearing 5 hats
(Builds / Items / Runes / Spells / Review). Its whole pitch: raw winrate is
selection-biased, so it reports `winrateObserved - winrateExpected` where the
expected term comes from a calibrated deep-net win-prob model trained on 44M
games. RC already owns the closest-twin mechanic (a 13-feature LR WPA scorer
in `core/post_game_score.py` driving `/api/post-game-wpa`). The win-prob MODEL
itself is RC's documented CLOSED ceiling (44M-game deep net is not reproducible
+ the per-comp winrate data is the redistributable-scrape RC cannot legally
cache). The ONE genuinely-new + liftable mechanic is **per-item WPA computed
over RC's OWN rewind_history.db** - a residual that de-confounds item value
without any scrape, riding the WpaModel RC already has.

---

## Finding 0 - There is no "app", and the architecture is a thin SPA over one API

1. WHAT - The BACKLOG item says "the site AND its app". There is no Electron /
   desktop / overlay app. "the competitor site" is a single-page web app (React-ish
   SPA) plus a marketing landing page. The "app" is the in-browser tool.
2. HOW - Verified live. Every page (`/builds`, `/items`, `/runes`, `/spells`,
   `/review`, `/leaderboard`) is the same SPA bundle hitting `the competitor API`
   (.NET / nginx 1.24 Ubuntu backend, JWT `Authorization: Bearer` auth) and a
   static CDN `cdn.the competitor site` for DDragon mirrors + their own
   `item-base-v2/items-bundled.json` + `rune-translations-v2`. Billing is
   ProfitWell + localized pricing. Telemetry is PostHog (EU). No game-client
   integration, no LCU, no live overlay, no frame capture.
3. HAVE - n/a (orientation).
4. WHERE - n/a.
5. EFFORT/RISK - n/a.
6. LIFT - n/a. Recorded so the BACKLOG "app" phrasing is closed: there is no
   second surface to teardown.

---

## Finding 1 - Per-item WPA = winrateObserved minus winrateExpected (selection-bias decompose)

1. WHAT - The Items page (`/items/all/legendaries`) renders an item tierlist
   ranked NOT by raw winrate but by `wpaOverall`. Per item the engine returns:
   `winrateExpected`, `winrateObserved`, `wpaOverall` (the residual),
   `occurrence` / `occurrenceRelative` (sample + pickrate), `averagePurchaseTime`
   (ms), `bias` (cohort-strength selection bias), `goodPurchaseSituations[]`.
   The headline insight: an item's RAW winrate is confounded - snowbally champs
   buy snowbally items so their winrate looks high regardless of the item. WPA
   subtracts the model's EXPECTED winrate for that exact cohort, leaving the
   item's marginal contribution.
2. HOW - Captured POST `api/ChampionWinprob/GetGlobalItemStatistics`. Request
   body is a filter object:
   `{commonFilters:{patch:{major,patch,patchAdditions}, championIds, matchupChampionIds, leagueTiers:[5,6,7], regions, role}, itemSlots, itemType, keystone, starterId, firstPurchaseId, firstLegendaryId, secondLegendaryId, includeSupportItems}`.
   Response (real values, patch 16.10, master+ ADC):
   - Infinity Edge 3031: occurrence 3.75M, expected 54.93%, observed 54.76%,
     `wpaOverall` -0.171 (buying it is slightly BELOW expectation for this cohort).
   - Bloodthirster 3072: observed 56.09% raw (looks great) but `wpaOverall`
     -0.350 (the cohort was already winning; BT did not add).
   - Lord Dominik's 3036: `wpaOverall` +0.492 (genuine marginal lift).
   The math: `wpaOverall = f(winrateObserved - winrateExpected)` over the
   comp/skill-conditioned cohort; `winrateExpected` is the deep-net pre-game
   win prob averaged across the games where the item was bought. `bias` is the
   cohort's baseline strength so the reader can see HOW selected the sample is.
   The same engine backs `GetGlobalSummonerSpellStatistics` (Spells page) and
   the Runes page - one parameterized stat service, entity-typed.
3. HAVE - **Partial / NO for items.** RC has the WPA *primitive*
   (`core/post_game_score.py::compute_match_wpa` already computes prob_before /
   prob_after / wpa per timeline event over its own `rewind_history.db`), and a
   curated per-champ loadout + 6-scorer build engine. But RC has NO per-ITEM
   aggregated WPA tierlist - its item selection is DS damage/EHP-math + curated
   loadouts, never "what did this item add to win prob across my games". The
   de-confounded `observed - expected` residual is the new idea.
4. WHERE - New engine `agents/daemon_slayer/` is the wrong home (that's combat
   math, not win-prob). Correct home: a NEW `core/item_wpa.py` that walks
   `data/rewind_history.db` timeline_events for ITEM_PURCHASED / item-completion
   per match, calls the EXISTING `core.post_game_score.predict_prob` /
   `compute_match_wpa` machinery to get prob_before / prob_after around each
   item-completion window, aggregates `mean(wpa)` per item (+ occurrence + a
   Laplace-shrunk CI using `core/smoothed_rates.py`), surfaced via a NEW
   `dashboard/routes_item_wpa.py` and a `web/js/panels/item_wpa.js` tierlist.
5. EFFORT/RISK - MED. NO new Riot dep (rewind_history.db is already local +
   already carries timelines). NO Claude dep. NO redistributable scrape (it is
   RC's OWN games, computed locally - this is the exact thing that dodges the
   CLOSED "winrate scrape" rule). The one real risk: RC's local match corpus is
   ~2900 games of mostly ONE operator, so per-item N is small and the residual
   is noisy - must shrink hard (Laplace/Wilson) + gate display on a min-N, and
   it is a personal "which items added WP in MY games" lens, NOT a global
   tierlist. The timeline must actually carry ITEM_PURCHASED events (verify -
   rewind ingest may only keep CHAMPION_KILL/BUILDING_KILL/ELITE_MONSTER_KILL
   per `post_game_score._STRONG_EVENT_TYPES`; if item events are absent this
   becomes a rewind-ingest schema lift = bumps to FUTURE).
6. LIFT - **MED-HIGH if item events are already ingested; FUTURE if they need a
   rewind-ingest schema lift.** This is the single most on-brand the competitor idea
   for RC (build engine + own data + WPA primitive already present) and the only
   one that clears every CLOSED rule. It is a personal-corpus item-WPA lens, not
   a market tierlist.

---

## Finding 2 - WPA "phases that mattered" replay review (this is RC's existing Post Game Review)

1. WHAT - The Review page lists your recent ranked matches (by linked Riot
   account) and, per match, plots the win-prob curve over the game and lets you
   jump to the moments where WP swung most. "Review your replay in a fraction of
   the time" = navigate the WP graph, not watch 30 minutes.
2. HOW - Captured: `Review/GetMatchHistory` (POST, by puuid) -> list;
   `Review/GetMatchPreviewForId/{puuid}/{EUW1_matchid}` -> per-match
   {championId, item0..6, keystone, role, kills/deaths/assists, win,
   opponentChampionId} sourced straight from Riot Match-V5; and clicking a match
   fetches the SAME `gameStates[]` time-series the landing page exposes via
   `LandingPage/LandingPagePreGameAnalysis`: an array of 60s-spaced frames, each
   `{timestamp, players:[{participantId,xPos,yPos,k,d,a,gold,level,inventory[],
   creepScore,pContribution,cumulativePContribution,lContribution,...}],
   destroyedStructures, blue/redEliteMonsterKills, redWinProbability,
   blueWinProbability}`. WPA per window = the delta of `redWinProbability`
   between consecutive frames; "phases that mattered" = top-|delta| windows.
   Note the `pContribution`/`lContribution` fields = per-player point/lane
   contribution attribution (who drove the swing).
3. HAVE - **YES.** RC's `dashboard/routes_post_game_wpa.py` +
   `core/post_game_score.py::compute_match_wpa` ALREADY does this: replays
   `rewind_history.db` timeline events through a WpaModel, returns per-event
   `wpa`/`prob_before`/`prob_after` + `top_phases` (top-3 by abs wpa) + the
   trained-vs-fallback flag. RC even cites the same lineage (LoLytics WPA
   decomposition). The S2 post-game reframe is built around exactly this.
4. WHERE - Already shipped: `routes_post_game_wpa.py`, `post_game_score.py`,
   `post_game_rubric.py`, `post_game_score` model at
   `data/post_game_wpa_model.json`.
5. EFFORT/RISK - n/a (already have it).
6. LIFT - **CLOSED (already shipped).** The only deltas worth noting as small
   future polish, NOT a rebuild: (a) the competitor surfaces a per-player
   contribution attribution (`pContribution`/`lContribution`) on each swing -
   RC's `compute_match_wpa` already returns `actor`/`actor_team`/`victim` per
   event which is the same idea at event granularity. (b) the competitor renders a
   continuous WP line; RC returns discrete events - a line-render of the
   frame-by-frame prob is a pure panel-JS polish over data RC already computes.

---

## Finding 3 - Pre-game win-prob model (44M games, calibrated deep net)

1. WHAT - Landing page advertises a pre-game model: champ winrates + synergies +
   matchups + per-player skill -> P(blue win) / P(red win). Stats shown: 44M+
   training games, 57.22% validation accuracy, 0.27% Expected Calibration Error,
   0.676 BCE loss. Backed by xPetu's 9-month master's thesis on deep-net win-prob
   for strategy optimization.
2. HOW - A trained deep neural network over a 10-champ + keystone + summoner-spell
   + skill feature space (captured `participantStaticInfos` carries exactly
   {keystone, secondaryTree, summonerSpell1/2, championId, participantId,
   teamId} per player - that is the model's pre-game input). `GetPatches` shows
   they retrain per patch over 6-9M games/patch. The IN-game model is a second
   net over the gameStates timeline.
3. HAVE - **Partial, and deliberately so.** RC has `core/draft_elo.py` (draft
   Elo aggregator) + `core/pickban_targets.py`, and its in-game WP is the LR in
   `post_game_score.py`. RC's matchup engine is a documented validated MODELING
   CEILING and the pickban counter-DB is NO_SIGNAL.
4. WHERE - n/a (would be a model retrain, not a panel).
5. EFFORT/RISK - HIGH + tripwires. A 44M-game deep net is not reproducible on
   the RC fleet; the per-comp winrate substrate is the redistributable data RC
   cannot legally cache; and a champ-select win-prob display is squarely the
   "add a win-prediction model" pitch RC has CLOSED.
6. LIFT - **CLOSED.** Explicitly on RC's don't-redo list (win-prediction model /
   MODELING CEILING / no redistributable winrate scrape). Do not re-pitch.

---

## Finding 4 - Build creator with WPA-scored item-path optimization

1. WHAT - `/builds/creator` (premium to SAVE, free to evaluate): pick champ +
   matchup, assemble runes + starter + item purchases, and the tool scores /
   optimizes the path by WPA. Marketed as "discover OP builds before they are
   meta" + a "theorycrafting interface using data-driven insights and
   mathematical optimization" (the Dec-2024 release added situational WPA +
   item tierlists).
2. HOW - Same `GetGlobalItemStatistics` engine, now CONDITIONED on the build
   prefix via the `firstLegendaryId` / `secondLegendaryId` / `keystone` /
   `starterId` / `firstPurchaseId` filters in the request body. So the optimizer
   is greedy/path-conditioned: given items already chosen, query the WPA of each
   next-item candidate conditioned on that prefix, pick the max-WPA next item.
   The path-conditional filters ARE the "mathematical optimization".
3. HAVE - **Partial / different axis.** RC HAS a build engine
   (`core/build_order.py` + 6 archetype scorers + curated loadouts) that orders
   items by DS damage/EHP math + a no-double-unique-passive rule. The competitor
   orders by empirical conditional-WPA. These are complementary: RC = mechanistic
   "what does this item DO" (deterministic, no data needed); the competitor =
   empirical "what correlated with winning given the prefix".
4. WHERE - If lifted, it is the same engine as Finding 1 (`core/item_wpa.py`)
   with a path-prefix filter param, consumed by the existing build-order UI as a
   secondary "WP-added next-item" hint alongside the DS-math ordering.
5. EFFORT/RISK - Inherits Finding 1's risk (small local-N) PLUS the
   path-conditioning shreds N further (items bought AFTER a specific prefix in
   MY ~2900 games is a tiny cell). Likely too sparse to be useful on a personal
   corpus; it is exactly where the competitor's 44M-game scale is load-bearing.
6. LIFT - **FUTURE (operator-gated) at best, leaning CLOSED.** The
   path-conditional optimizer is the one piece that genuinely needs big-N
   redistributable data; on RC's personal corpus it degrades to noise. Keep RC's
   DS-math build ordering as primary; only the UNconditioned per-item WPA
   (Finding 1) is corpus-viable.

---

## Finding 5 - Per-patch retrain cadence + match-count surfacing

1. WHAT - `GetPatches` returns every patch with its `matchCount` (16.1 = 7.5M
   ... 16.11 = 1.45M and climbing), so the UI shows data freshness/volume and
   lets the user pick the patch their analysis runs over. Tierlists explicitly
   re-baseline per patch.
2. HOW - Captured `ChampionWinprob/GetPatches` -> `[{label,major,patch,matchCount}]`.
   Every stat call carries a `patch:{major,patch,patchAdditions}` filter so the
   reader controls the patch window.
3. HAVE - **Partial.** RC pins a single live patch (`data/daemon_slayer/current.txt`,
   16.11.1) and its DS data is patch-locked; rewind_history.db carries
   `game_version_major/patch` per row but RC does not expose a patch selector or
   a per-patch match-count freshness chip on any analytics panel.
4. WHERE - A small `dashboard/routes_*` addition + a freshness chip if Finding 1
   ships (so the item-WPA panel can say "computed over N of your patch-16.11
   games").
5. EFFORT/RISK - LOW, but only meaningful as a companion to Finding 1.
6. LIFT - **LOW** (cosmetic; bundle it into Finding 1's panel rather than ship
   standalone).

---

## Summary table

| Finding | HAVE | WHERE | EFFORT | LIFT |
|---|---|---|---|---|
| 0 - no desktop app, thin SPA over 1 API | n/a | n/a | n/a | orientation |
| 1 - per-item WPA (observed-expected residual) | partial (WPA primitive yes, item-WPA no) | core/item_wpa.py + routes_item_wpa.py + panel | MED | **MED-HIGH** (FUTURE if rewind lacks item events) |
| 2 - WPA phases-that-mattered replay review | YES | routes_post_game_wpa.py / post_game_score.py | n/a | CLOSED (shipped) |
| 3 - pre-game 44M-game deep-net win prob | partial (draft_elo) | model retrain | HIGH | CLOSED (don't-redo) |
| 4 - path-conditional WPA build optimizer | partial (DS build engine) | item_wpa.py + prefix filter | HIGH | FUTURE-leaning-CLOSED (needs big-N) |
| 5 - per-patch retrain + match-count chip | partial | bundle into Finding 1 panel | LOW | LOW |

---

## VERDICTS

### NOW - implementable this run (HIGH-lift, low-risk, no new Riot/Claude dep, no scrape, testable)

NONE that are unconditionally safe this run. Finding 1 (per-item WPA over
rewind_history.db) is the only candidate, but it is gated on a verify-first:
RC's rewind ingest may only persist CHAMPION_KILL / BUILDING_KILL /
ELITE_MONSTER_KILL events (per `post_game_score._STRONG_EVENT_TYPES`), in which
case ITEM_PURCHASED / item-completion timestamps are absent and the residual
cannot be computed without a rewind-ingest schema lift. If a 5-minute probe of
`data/rewind_history.db` shows ITEM_PURCHASED rows in `timeline_events` (or item
inventory deltas in `timeline_frames`), Finding 1 promotes to NOW as a pure
aggregation layer over the EXISTING WpaModel; otherwise it is FUTURE. Do not
build it blind.

### FUTURE - operator-gated (HIGH-lift but high-effort / new-dependency / schema-lift / product-call)

- **Finding 1 - per-item WPA tierlist over the local corpus**, IF the rewind DB
  needs an ITEM_PURCHASED-event ingest schema lift first, OR if the operator
  wants it framed honestly as a noisy personal-corpus lens (min-N gate + heavy
  Laplace/Wilson shrink via `core/smoothed_rates.py`). Integration point:
  `core/item_wpa.py` (walk timeline item events, reuse
  `core.post_game_score.predict_prob` for prob_before/after windows, aggregate
  mean-WPA + shrunk CI per item) -> `dashboard/routes_item_wpa.py` ->
  `web/js/panels/item_wpa.js`. No Riot/Claude dep; data is RC's own games.
- **Finding 2 polish** - a continuous WP-line render + per-event contribution
  attribution on the existing post-game-wpa panel (data already computed; pure
  panel-JS). Small, operator-gated cosmetic.
- **Finding 5** - per-patch match-count freshness chip, bundled into Finding 1.

### CLOSED - not worth lifting (with reason)

- **Finding 3 - pre-game / in-game deep-net win-prob model.** On RC's explicit
  don't-redo list: 44M-game deep net is not reproducible on the fleet, the
  per-comp winrate substrate is the redistributable scrape RC cannot legally
  cache, and a champ-select win-prob display is the "add a win-prediction model"
  pitch RC closed (validated MODELING CEILING; pickban DB = NO_SIGNAL).
- **Finding 4 - path-conditional WPA build optimizer.** The path-prefix
  conditioning (firstLegendaryId/secondLegendaryId filters) is precisely where
  the competitor's 44M-game scale is load-bearing; on RC's ~2900-game personal corpus
  the conditioned cells collapse to noise. RC's DS damage/EHP build ordering is
  the better mechanistic answer and needs no data. Keep DS-math primary.
- **Finding 0 - "the app".** There is no desktop/overlay app to teardown; the
  BACKLOG "site AND app" phrasing is closed - it is one in-browser SPA.

---

## Honest bottom line

the competitor site is genuinely sharp on ONE idea - decompose winrate into
`expected + WPA` to kill selection bias - and RC already owns the engine that
makes that decomposition possible (`core/post_game_score.py` WpaModel +
`rewind_history.db` timelines). But the competitor's value is overwhelmingly in the
44M-game model + global winrate substrate, both of which are RC's documented
CLOSED ceiling. The single transferable nugget is applying RC's existing WPA
primitive to ITEMS over RC's own match corpus (Finding 1) - and even that is
verify-first-gated on whether the rewind DB carries item-purchase events, and
honest-framing-gated on small-N noise. No NOW lift ships blind this run.
