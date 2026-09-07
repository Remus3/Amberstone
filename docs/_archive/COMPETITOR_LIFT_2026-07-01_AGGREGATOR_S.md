# Competitor Lift Teardown - Aggregator S

- Date: 2026-07-01
- Target: Aggregator S (https://aggregator-s.invalid/)
- What it is: a pro-player build aggregator - per-match probuild rows (item buy order, runes, summoner spells, KDA, CS@10) scraped from professional League games, plus a per-champion directory, free rotation, pick-rate trend board, and counters prose. Value is the EXTERNAL pro-sourced dataset.
- Fetch status: LIVE. Fetched main (`/`), and a per-champion probuilds page (`/champion/Lux/probuilds`) via WebFetch. Both rendered. Next.js app (Next Image optimizer `/_next/image?url=...`, SSR champion grids, client-side match filtering). Per-match link shape confirmed live: `/match/[REGION]/[MATCH_ID]?cat=participants&pid=[N]`. Data shapes below are OBSERVED unless tagged [INFERRED] (JSON/XHR internals were not exposed in rendered markdown, so the transport layer is inferred from the Next.js + per-match-row structure).

Framing note carried from the brief: Aggregator S's core is an aggregated PRO-BUILD DATASET. RC is simulation-first (pure DS combat math, no win-rate/aggregation dependency in-run). So nearly every lift that needs pro-build data is a NEW external dependency = FUTURE/BACKLOG by RC's own no-blind-dependency rule. The teardown below is honest about the one presentation-only exception.

Third-party name "Aggregator S" appears in THIS doc only (allowed); it is never written into RC source.

---

## Finding 1 - Per-match probuild rows (pro item buy order + runes + summoners + KDA/CS)

1. WHAT: The spine of the site. Each row = one pro's single ranked/pro game: player name, Victory/Defeat, "8 hours ago", game duration 22:45, KDA 3/0/20, CS + "+6@10" CS-diff, the item sequence left-to-right as purchased (6 items + boots), keystone + secondary tree, summoner spells, region (NA/KR/EUW), patch 16.13, and both 5-champ team comps. Granularity is PER-MATCH, not aggregated.
2. HOW: Server-side ETL over pro accounts (a curated pro-account list) pulling Riot Match-V5 + timeline, keyed by champion, rendered SSR by Next.js with client-side filter. Per-match deep link `/match/NA1/5592630365?cat=participants&pid=5` is a Match-V5 id + participant index. [INFERRED] transport: a JSON API behind the Next.js data layer (likely `/_next/data/*.json` or a REST endpoint) feeding the row list.
3. HAVE: PARTIAL, different substrate. RC has a local match store: `rewind_history.db` (reference memory `reference_rewind_history_db` - ~2952 matches full participant+timeline) written live by the post-game collector (`lcu/lcu_postgame_collector.py`; live writer per memory `reference_rewind_live_writer`). But it is the OPERATOR's own matches, not a pro-account corpus. RC has NO pro-player build aggregation and no pro-account ETL. RC's build authority is pure simulation: `agents/daemon_slayer/rank.py:527` `rank_items(` and `core/build_order.py:370` `plan_build_order(` - both compute buy order from scorer deltas, not from observed pro purchases (memory `reference_ds_simulation_default_not_winrate_hybrid`).
4. WHERE: Would need a NEW pro-account ETL feeding a NEW `data/` corpus + a NEW route + a NEW champ-select panel. Nearest existing seam is the already-live external-aggregator lane (`core/synergy_external_source.py` + `core/smoothed_rates_101qq.py`) - but that is duo-synergy, not per-match pro builds.
5. EFFORT + RISK: HIGH. New Riot-key pro-account crawl (rate-limited, event-mode 403 gaps per `reference_riot_match_v5_event_mode_403`), new persistent corpus, new schema, new panel. Adds a blind in-run external dependency, which the don't-redo set forbids for an in-run ship.
6. LIFT verdict: HIGH-effort / FUTURE. Reason: core value is a new external pro dataset RC deliberately does not carry; violates the no-blind-in-run-dependency rule.

---

## Finding 2 - Per-champion aggregated "most common" build + runes

1. WHAT: Beyond raw rows, aggregators of this class roll pro rows into a "most common build / most common runes / highest-winrate build" summary per champion. [INFERRED] for Aggregator S specifically - the rendered page led with per-match rows; the aggregate summary is the standard companion view and the FAQ references "best build."
2. HOW: Group pro rows by champion+patch, count item-set and rune-page frequency, surface modal build + win-rate. Server-side aggregation over the same corpus as Finding 1.
3. HAVE: NO for pro-frequency aggregation; YES for a computed alternative. RC produces a single optimal build order per champion+context from simulation, not a popularity mode: `core/build_order.py:370` `plan_build_order(` returns `BuildOrderResult` (`core/build_order.py:304`) with per-step delta+gold and `order_str()` (`core/build_order.py:321`). This is a DIFFERENT epistemology (what-is-mathematically-best vs what-pros-buy).
4. WHERE: Aggregation would ride on the Finding-1 corpus (does not exist). No clean insertion without that dependency.
5. EFFORT + RISK: HIGH. Same new-corpus + new-schema cost as Finding 1, plus aggregation logic.
6. LIFT verdict: HIGH-effort / FUTURE. Reason: depends entirely on the non-existent pro corpus; RC's sim build is the deliberate substitute.

---

## Finding 3 - Rune page recommendation per champion

1. WHAT: Each row/summary shows keystone + primary tree + secondary tree (e.g. Arcane Comet + Inspiration for Lux, Electrocute/Guardian/Inspiration examples on the main grid).
2. HOW: Read from the pro rune page in Match-V5 perk data; aggregated to a recommended page per champion.
3. HAVE: YES - already fully solved and AHEAD of a display-only competitor. RC carries curated rune recommendations as local data: `data/meta_build/rune_recommendations_sr.json` and `data/meta_build/rune_recommendations_aram.json`, loaded by `lcu/lcu_rune_writer.py:217` `load_rune_rec(` -> (keystone, primary_tree, secondary_tree), resolved to 9 perk ids via `lcu/lcu_rune_writer.py:150` `build_perk_ids(` (perk-name map at `lcu/lcu_rune_writer.py:120` `_perk_by_name()`). RC does not just DISPLAY runes - it AUTO-WRITES the page into the client over LCU in champ select. That is strictly more than Aggregator S does.
4. WHERE: N/A - already shipped and live-wired. Do NOT re-pitch a rune writer (explicit brief constraint).
5. EFFORT + RISK: NONE - done.
6. LIFT verdict: LOW / CLOSED. Reason: RC already auto-pushes runes via LCU; nothing to lift.

---

## Finding 4 - Skill / ability max order display (Q>E>W progression)

1. WHAT: The one place Aggregator S's rendered probuilds page is THIN - our fetch confirmed it does NOT show ability/skill max order. But skill-max order (which ability to level 1-2-3, e.g. "max Q, then E, then W") is a first-class thing coaches want in champ select, and this teardown surfaces that RC already HAS the data and does not render it.
2. HOW (in RC): The DS extractor pulls a per-champion 18-element skill_order array from lolmath at extract time: `Share/src/tools/daemon_slayer_extract.py:493` `skill_orders: dict[str, list[str]]` (DDragon-id -> ["Q","E","W",...]), written per champ at `daemon_slayer_extract.py:864` ("skill_order": ... length 18). It lands in the shipped champions.json.
3. HAVE: PARTIAL - the DATA is present, the SURFACING is missing. Runtime data confirmed: `data/daemon_slayer/16.13.1/champions.json` carries `skill_order` for 173 champions (grep count 173; sample at `champions.json:97` shows `"skill_order": ["Q","E","W","Q","Q","R",...]`). Manifest confirms `data/daemon_slayer/16.13.1/manifest.json` `"skill_orders": 173`. Loaded into the snapshot by `agents/daemon_slayer/data_loader.py:141` (`champions_doc = _read("champions.json")`). BUT: grep for `skill_order`/`skillOrder` across `web/` returns ZERO files, across `agents/daemon_slayer/server.py` ZERO matches, across `web_dashboard.py` ZERO matches. The sibling `damage_distribution` field (also in champions.json) is likewise not surfaced in `web/`. So the field is extracted, shipped, and loaded - but never exposed to any route or panel.
4. WHERE (as SHIPPED - corrected from the initial server.py sketch): the lighter, correct home is the RC DASHBOARD layer, NOT the DS `:8893` engine server. `skill_order` is a static array needing no engine, so the integration is a NEW thin dashboard route `dashboard/routes_ds_skill_order.py` mirroring `dashboard/routes_ds_profile.py` (same `equals`-dispatch, 5-min cache, `_load_id_to_slug` numeric->slug resolver, fail-soft 503, `_reset_caches` hook) that reads `data/daemon_slayer/<patch>/champions.json` `data[slug].lolmath.skill_order` DIRECTLY (zero `agents.daemon_slayer` import). Registered in `dashboard/_dispatch.py`. Panel: a champ-select card `web/js/panels/ds_skill_order.js` mirroring `ds_profile.js`, wired in `champ_select.js` NEXT TO `renderDsProfileForChampSelect` (skill order is champion-intrinsic pre-game info, so it joins ds-profile/ds-knobs/ds-statcheck on champ-select - CS3-consistent, NOT with the combat panels moved to active-match). Mount `web/index.html` sibling of `csv-sugg-ds-profile`; CSS `web/css/panels/ds_skill_order.css` + dashboard.css @import (bundle parity).
5. EFFORT + RISK: LOW / presentation-only. No new Riot/Claude/scrape dependency, no schema lift. Because it lives in the dashboard layer (not `server.py`), it is TIER-1-LITE: RC `:8888` restart to register the route, NO DS `:8893` bounce, NO Share sync, NO ENGINE/ENGINE_VERSION change. The compute is a pure array read + a deterministic collapse. Testable: route returns the known 18-element array + collapsed priority for a known champ id.
6. LIFT verdict: MED (leaning ship) / NOW - SHIPPED IN-RUN 2026-07-01. Reason: only true presentation-over-existing-local-data lift in the set; data already extracted+shipped+loaded (173 champs), the surfacing is a small additive dashboard route + panel with a clean existing pattern and a deterministic test.

SHIPPED (R54, 2026-07-01, merge `67a1bb61` / feat `9e5cda65`): the collapse orders Q/W/E by the level each reaches its 5th point (tie-break first-appearance); `ult_levels` = the R positions. TDD RED-first 17 route tests; read-only verifier CONFIRM 8/8; 5-phase UI audit 0 MUST-FIX; live-probed on `:8888` (Aatrox Q>E>W, Lux E>Q>W, numeric 266->Aatrox, cache hit). Champ-select PANEL pixel capture OWED (no live champ-select; overlay-only audit surface).

---

## Finding 5 - Counters / matchup recommendations

1. WHAT: Aggregator S references counters conceptually (FAQ) but the rendered probuilds page showed NO explicit counter table - it is prose/marketing more than a computed per-lane counter matrix on the pages we fetched.
2. HOW: Class-standard counter tables come from win-rate-into aggregation over ranked data. Aggregator S's counter surface appears light.
3. HAVE: YES and computed differently (RC is ahead on rigor here). RC computes a real 1v1 head-to-head from combat math: `agents/daemon_slayer/matchup.py:209` `compute_matchup(` -> `MatchupResult` (`matchup.py:40`) with `net_swing` in [-1,1], `pct_a_removed`/`pct_b_removed`, `verdict` (all_in/back_off/trade/even), and full-combo feasibility flags. Surfaced live via the `/api/ds-matchup` route consumed by the champ-select card `web/js/panels/ds_matchup.js:8` (documented endpoint `GET /api/ds-matchup?champ_a=..&champ_b=..&mode=SR`). This is a simulated who-wins-the-trade, not a scraped win-rate percentage.
4. WHERE: N/A for the lift - RC's version is more principled. A win-rate-flavored counter list would need the Finding-1 corpus.
5. EFFORT + RISK: HIGH for a win-rate counter list (new corpus); NONE for what RC already ships.
6. LIFT verdict: LOW / CLOSED. Reason: RC already has a live computed-matchup panel; the aggregated-counter variant needs the forbidden new corpus.

---

## Finding 6 - Item buy-order sequence rendering (left-to-right as-purchased)

1. WHAT: Aggregator S renders the pro's items in purchase order, left to right (Zaz'Zak's -> Mejai's -> Luden's -> Sorc Shoes). The UX value is the ORDERING, not just the final set.
2. HOW: Timeline purchase events ordered by timestamp per match; rendered as an icon strip.
3. HAVE: YES - RC already computes and can render an ordered buy sequence, from simulation rather than observation. `core/build_order.py:304` `BuildOrderResult` holds `order: list[BuildStep]`; `BuildStep` (`build_order.py:264`) carries `slot`, `item_id`, `item_name`, per-step `delta`, `gold`, `scorer`, `unit`; `order_str()` (`build_order.py:321`) emits the compact "Item1(+d,g) > Item2 ..." pill the dashboard/coach want. So the ordered-strip concept is already first-class in RC's build engine.
4. WHERE: N/A as a novel lift. If the ordered strip is not yet rendered in a specific panel, that would be a tiny presentation task riding on `BuildOrderResult.to_dict()` (already returns `order` + `order_str`) - but it is not a Aggregator S-unique idea and needs no Aggregator S data.
5. EFFORT + RISK: LOW if a panel wants the strip (data exists); no new dependency.
6. LIFT verdict: LOW / CLOSED (concept already owned). Reason: RC's build engine already produces an ordered, per-step-annotated buy sequence; nothing external to lift.

---

## Finding 7 - Pick-rate trend board + free rotation

1. WHAT: Main page has a "Champion Trends" board (PR pick-rate with +4.4% / -0.7% deltas, trending champs) and a free-rotation strip.
2. HOW: Pick-rate deltas are aggregate ranked-data telemetry patch-over-patch; free rotation is the DDragon/Riot rotation endpoint.
3. HAVE: NO for pick-rate telemetry (RC carries no ladder pick-rate feed and deliberately avoids win-rate/aggregation in-run per `reference_ds_simulation_default_not_winrate_hybrid`); free rotation is a trivial Riot endpoint RC does not currently surface.
4. WHERE: Pick-rate would be a new external telemetry dependency (FUTURE). Free rotation could be a small DDragon call + panel, but it is low-value for a solo single-player coaching tool and adds a live Riot call.
5. EFFORT + RISK: HIGH (pick-rate: new dependency) / LOW-but-low-value (free rotation).
6. LIFT verdict: HIGH / FUTURE (pick-rate); LOW / FUTURE (free rotation, low value). Reason: pick-rate is a new aggregation dependency; free rotation is cheap but marginal for RC's use case.

---

## TRIAGE

| Finding | LIFT | NOW/FUTURE/CLOSED | Reason |
|---|---|---|---|
| 1. Per-match pro probuild rows | HIGH | FUTURE | New pro-account ETL + corpus + schema; forbidden blind in-run dependency |
| 2. Per-champ aggregated common build/runes | HIGH | FUTURE | Rides on the non-existent pro corpus; sim build is the substitute |
| 3. Rune page recommendation | LOW | CLOSED | RC already auto-writes runes via LCU (ahead of a display-only site) |
| 4. Skill / ability max order display | MED | NOW - SHIPPED | Data already extracted+shipped+loaded (173 champs); surfacing shipped in-run as `/api/ds-skill-order` + champ-select card (merge `67a1bb61`) |
| 5. Counters / matchup | LOW | CLOSED | RC has a live computed-matchup panel; win-rate variant needs new corpus |
| 6. Item buy-order strip | LOW | CLOSED | RC build engine already produces an ordered per-step sequence |
| 7. Pick-rate trend + free rotation | HIGH / LOW | FUTURE | Pick-rate = new dependency; free rotation cheap but low-value |

---

## IN-RUN SHIP CANDIDATE

YES - Finding 4 (Skill / ability max order display). SHIPPED IN-RUN 2026-07-01 (merge `67a1bb61` / feat `9e5cda65`) after independent premise re-verification (173/173 champs carry `lolmath.skill_order`; the field is surfaced in ZERO web/route files - confirmed by orchestrator grep). Verifier CONFIRM 8/8, UI audit 0 MUST-FIX, live-probed on `:8888`. It is presentation-only over data RC ALREADY has: `skill_order` is extracted by `daemon_slayer_extract.py:493`, shipped for 173 champions in `data/daemon_slayer/16.13.1/champions.json` (verified grep count 173, sample `champions.json:97`), manifest-counted (`manifest.json` `"skill_orders": 173`), and loaded into the DS snapshot at `data_loader.py:141` - yet surfaced in ZERO web files, ZERO `server.py` routes, and ZERO `web_dashboard.py` routes. Shipping it is a small additive read-only DS route (following the existing `_route_mobility`/`_route_sustain` additive pattern at server.py:1210/:1233) plus a champ-select card next to `web/js/panels/ds_matchup.js`, with a deterministic test (route returns the known 18-element array for a known champ id; panel renders the collapsed Q>E>W priority). No new Riot/Claude/scrape dependency and no schema lift. Every other finding either needs a new external pro-build/telemetry corpus (Findings 1, 2, 7 = FUTURE) or is already owned by RC's simulation-first engine (Findings 3, 5, 6 = CLOSED).
