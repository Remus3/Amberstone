# Next Session Plan - 2026-05-10 (post-s166)

Operator directive (end of s166):
> _"ill wait on the ui stuff for the moment, lets just finish the back end work for now and any pending backlog items that are not checked off and any roadmap items not checked off yet … priority task to check first will be the Daemon Slayer headless testing if nothing substantive - then connect to the rewind database: and run that headless overnight."_

UI work is **paused** until further notice. This session focuses on backend, DB, headless DS testing, infra hygiene, and the planning doc the operator asked for. The fixture flow steps 5–14 (champ-select variants, active-match minute fixtures, game summary, last-match) are explicitly deferred - do not start them unless the operator unblocks.

---

## Priority 1 - Daemon Slayer headless testing

The DS engine is at `ENGINE_VERSION 0.61.0`, 547 items, 929 tests. Operator wants to push it further before any new UI builds on top.

### What's already covered (don't redo)

- Item-effect testing across SR / ARAM / Arena (929 tests in `tests/daemon_slayer/`).
- Per-champion stat scaling at level 18 (`agents/daemon_slayer/champ_scaling.py` + `CHAMPION_SCALING_RULES`).
- Mode-aware item filtering (Arena ignores Smite/etc. via `resolve_inventory`).

### What's missing - candidate headless additions

1. **Per-level DPS curves** - engine computes DPS at level 18 only. Add level-by-level DPS arrays (1, 6, 11, 16, 18) so the coach can hint "Lulu peaks at lvl 6, falls off at 11" style. Schema bump + new column in `champion_profiles/*.json`.
2. **Skill-rotation DPS contribution** - DS scores items by raw stat math; ult-cast schema (Malignance batch 64) was the first step. Extend to per-spell rotation patterns (Q→W→AA→Q reset for Vayne, etc.). Probably needs a `champion_rotations.json` keyed on champion.
3. **Arena augment stat-overlay** - Cherry augments shift base stats mid-game (Searing Dawn = +X% damage, etc.). DS currently ignores augments entirely. Add an `augments[]` parameter to the engine entry-point with a static augment-effects table.
4. **Calibration replay** - once rewind_history.db is fresh (Priority 2), replay every locked match's actual purchase sequence through the engine and assert the engine's top-3 picks would have included the real purchase ≥X% of the time. Establishes a regression floor.
5. **Boots tier-2 timing** - engine knows boot upgrades exist but doesn't time them. Add a `boot_phase` field that the coach can surface ("upgrade boots after second back").

### Files of interest

- `agents/daemon_slayer/engine.py` - core ranker.
- `agents/daemon_slayer/champ_scaling.py` - stat tables.
- `data/champion_profiles/*.json` - per-champion overrides.
- `tests/daemon_slayer/` - existing 929-test suite.
- `docs/DAEMON_SLAYER.md` - extension points.

---

## Priority 2 - Connect to rewind_history.db + headless overnight run

### Current state

- `data/rewind_history.db` - 2846 matches, newest entry **2025-12-15**. Five months stale. Schema: `matches` (10 cols incl. `match_id`, `queue_id`, `game_mode`, `patch`, `game_duration_s`, `game_creation_ts`), plus `timeline_frames`, `timeline_events`, `participants`, `teams`.
- Blocker noted in ROADMAP: _"blocked on live SR game; needs game_id wired to new session records"_.
- **Unblocker that landed since:** FU04 Personal-tier Riot key approved 2026-05-09; `core/riot_api.py` exposes Match-V5 ids / detail / timeline endpoints.

### Wire plan

1. **Resolve the operator's PUUID** - already stored in some path (check `core/riot_api.py` resolver). If not, fetch via Account-V1.
2. **Walk Match-V5 ids** - paginate `/lol/match/v5/matches/by-puuid/{puuid}/ids` from `2025-12-15` forward; collect missing match ids.
3. **Hydrate matches** - for each missing id, fetch detail + timeline, write into the existing 5-table schema. Token bucket already throttles to 20/s + 100/120s + 429 cooldown, so a 500-match catch-up runs ≈10 min wall-time.
4. **Headless overnight script** - drop a `scripts/rewind_catchup.py` that's idempotent (skips rows already in `matches`), resumable (writes progress to a sentinel file), and safe under existing API rate limits. Schedule via `schtasks` or just run it manually in a background terminal before the operator goes to bed.
5. **Verification** - after the overnight, count rows, confirm newest `game_creation_ts >= today - 7d`, and re-run DS calibration analysis (the JSONL ⨝ on champion/mode/ts that s152 enabled).

### Failure modes to watch

- Riot key rate-limit (29k Match-V5 calls would burn ≈40 min of headroom). Use `core.riot_api`'s bucket explicitly; do not bypass.
- match_id collisions on `INSERT OR IGNORE` - fine, schema already has unique constraint on `match_id`.
- Disk: each match is ~30 KB across the 5 tables; 500 matches = ~15 MB. Plenty of room.

---

## Priority 3 - History tab "needs Riot key" hookup

### Location of the hole

- `web/index.html:1150` - `<span class="dim">(needs Riot key)</span>` next to the season Win-rate row.
- Wired endpoint stub: `dashboard/routes_history.py` (live).
- Now that FU04 is approved, `core/riot_api.py.fetch_league_v4_by_puuid(...)` will return real ranked-stats; the History view's season card needs wiring to that.

### Implementation steps

1. In `dashboard/routes_history.py`, add a season-stats branch that calls `core.riot_api.get_solo_queue_entry(puuid)` (or whatever the wrapper is named - verify in `core/riot_api.py`).
2. Cache result for 5 min per the existing pattern.
3. Update the JS in `web/js/main.js` (`_historyFetchAndRender`) to populate `#history-season-wr` with `wins / (wins + losses)` % rather than `-`. Drop the "(needs Riot key)" `<span class="dim">` when populated.
4. Add a fixture for the History view (`data/sim/flow_NN_history.json`) so sim mode can preview the populated state without a live Riot key. Defer the fixture until after the live wire works.

---

## Priority 4 - Replay tab + scrubber

### Current state

- `web/index.html:1295` - `<section id="view-replay">` scaffold with a `<input type="range" id="replay-slider">`, RECENT MATCHES list, and a `<table class="replay-grid">` for the per-minute player snapshot.
- The slider is `disabled` until a match is selected.
- Server side: `/api/replay/matches` + `/api/replay/match/<id>` are referenced in the HTML comment but **not confirmed shipped**. Check `dashboard/routes_*.py` and add if missing.

### Implementation steps

1. Confirm or add the two HTTP endpoints. The `match/<id>` endpoint must return `{ duration_s, snapshots: [{ minute, players: [...] }, ...] }` where each snapshot reads `timeline_frames` for that minute and joins against `participants`/`matches`.
2. In `web/js/main.js` `_replayViewRefresh`, populate the RECENT MATCHES list from `/api/replay/matches`, wire click → load + enable slider.
3. Slider `input` event → fetch (or already-loaded array) → re-render the grid.
4. Clock label shows `mm:ss` for the current slider position.
5. Snapshot test under `tests/snapshot_panels/` once UI work resumes - defer for now.

---

## Priority 5 - Default DS build #4 for SR / Arena / ARAM Mayhem

Per operator: _"a Default Daemon Slayer build as #4 based on reality and proper usage by the champion in SR & Arena & Aram Mayhem."_

The existing SR draft chooser renders 3 engine variants (Lethal Tempo default / Press the Attack / Hail of Blades for Vayne, e.g.). Operator wants a **4th "Default"** variant that reflects how the champion is *actually played at the operator's rank*, not engine-derived top-3.

### Implementation steps

1. Source: pull from `rewind_history.db` post-catchup (Priority 2). For each `(champion, mode)`, compute the modal item-build (most-common 5 items across the operator's recent N matches).
2. Add a 4th row to the build chooser. Label: `Default · <champ name> · your meta`.
3. Wire into `coaches/sr_user_builds.py` or a sibling `coaches/sr_default_builds.py` - generate at startup, refresh weekly.
4. ARAM Mayhem (queue 920) inherits ARAM build logic; just split the modal computation by queue id.
5. Arena (1700/1710) - same approach but on the 8-item-cap (Arena items + augments).

Depends on Priority 2 (DB freshness).

---

## Priority 6 - Sonnet + Haiku calls → Claude Desktop API key

Operator: _"I want to have all Sonnet & haiku calls to pass through the Claude desktop API key - not the CLI Anthropic key anymore for League of Legends work at the minimum."_

### Current state

- Coach Sonnet/Haiku calls resolve the key via [coaches/_base_coach.py:read_api_key()](coaches/_base_coach.py:41).
  - Reads `API-Key-Claude.txt` (path: project root).
  - Falls back to `$ANTHROPIC_API_KEY` env var.
- Per `reference_api_keys.md` memory: three per-machine keys exist, one per host; Legion's key is what `API-Key-Claude.txt` currently holds.
- The Claude Code CLI uses its own auth (`~/.claude/`) separate from this file. So _today_ the coaches already do NOT route through the CLI's key - they route through `API-Key-Claude.txt`.

### Action items

1. **Confirm intent** with operator: do they mean (a) `API-Key-Claude.txt` should be replaced with the Anthropic Console key that Claude Desktop uses, or (b) some other key, or (c) is this a billing-visibility ask (separate token bucket on the Console)?
2. **Audit all Sonnet/Haiku call sites** to make sure they all go through `read_api_key()` and none bypass to env or another file. Files to grep: `coaches/*.py` (all 10), `dashboard/routes_coach.py`, `dashboard/_champ_select.py`, `agents/agent7_context/warm_session.py`, `agents/supervisor.py`, `app/__init__.py`, `app/_game_lifecycle.py`, `main.py`, `ops/rc_supervisor.py`, `core/riot_api.py` (this last one uses the Riot key not Claude).
3. **Document** the resolved key file + intended billing convention in `docs/OPERATIONS.md` and the `reference_api_keys.md` memory.
4. **No code change** until intent is confirmed.

---

## Open ROADMAP items not yet checked off (snapshot)

Copied from `ROADMAP.md` as of 2026-05-10. Status notes reflect what s166 left in flight; full text is in the roadmap.

### High-priority open

- 🟡 **FU01 minimap-locate** - `agents/supervisor.py:597` hardcoded bbox; needs 3-path resolver (override → PersistedSettings → hardcoded fallback). Independent of any UI work. Ticket: `Desktop/Tickets/RC_TICKET_FU01_minimap_locate.md`.
- 🟡 **rewind_history.db staleness** - see Priority 2 above. **Unblocked by FU04**, so it's now actionable.
- 🟡 **Vision regions calibration** - `data/vision_regions.json` bboxes. Blocked on live game for calibration frames. Not actionable headless.
- 🟡 **Bridge Watcher acceptance-criteria** - need 50+ real-traffic auto-action samples. Watch `auto_ok_since_boot` vs `auto_err_since_boot`. Background ride-along; no headless work possible.
- 🟡 **gamepc_boot.ps1 hardening** - add `RC-WatcherHealthPublisher-GamePC` + `RC-BridgeWatcher-GamePC` to idempotent start sequence. Independent; Game-PC PowerShell work.
- 🟡 **Active Match view steps 2–5** (UI-blocked per operator) - DS icons + per-tick rerank, enemy-comp threading into `target_armor/mr/bonus_hp`, static map + overlay, zen-lock + RIGHT NOW fold + bridge-pending → dev-panel button. **Deferred per operator.**
- 🟡 **Phase 3 fixture flow steps 5–14** (UI-blocked) - champ-select variants, active match @ 0/6/12/20/30/40 min, game summary, last match. **Deferred per operator.**
- 🟡 **Phase B set_augment_intent** - s166 shipped the stub; real LCU `/lol-cherry/v1/*` endpoint discovery needs a live Arena lobby. Headless cannot resolve.

### Medium-priority open

- **Auto-ops verb expansion** - `tail .* log`, `restart agent .*`, `verify .*` once auto-action success ≥ 95%. Headless.
- **Game-PC + Peer auto-action lanes** - currently `--enable-auto-action-lanes` is OFF. Enable once success rate is proven. Headless.
- **RC-DaemonSlayer task context** - runs as SYSTEM; `_log_startup` writes fail silently. Change to LogonTrigger + Administrator post-boot. Independent infra.

---

## Shipped this session (s166) - for the next session's bootstrap

- **Phase B LCU agent handlers + state population** (backend) - 5 new command handlers (set_ban_intent / set_pick_intent / set_augment_intent / request_position_swap / request_pick_order_swap) + state-shape additions (active_round / is_brawl / position_swaps / pick_order_swaps / arena_teams / augments scaffold) + 30 new tests (665 total green). All changes in `tools/gamepc_lcu_agent.py` + `tests/phase_b_champ_select/`.
- **Loading Screen view scaffold** (UI, Phase 3 step 4) - new top-level `view-loading`, mode-conditional (sr/aram/arena/brawl), `?ld=1` opt-in, `phase=GameStart` auto-promote. Live-tested. Briefing card removed per operator before commit. New files: `web/js/panels/loading.js`, `web/css/panels/loading_view.css`, `data/sim/flow_04_loading_screen.json`. Wired in: `web/index.html`, `web/js/main.js`, `web/js/lib/state.js`, `web/css/dashboard.css`, `web/css/panels/header.css`, `data/sim/manifest.json`.

---

## Priority 7 - Prune My Top 8 dummies + fake test games

Per operator (mid-session amendment 2026-05-10):
> _"prune out the my top 8 list of the dummy profiles and any fake games we ran for testing etc."_

### Where the data lives

- **Live UI storage:** `localStorage` key `rc-top8-list` on the operator's browser. Each entry is `{ riot_id, tag, rank: {tier, division, lp} }`. Source: [web/js/main.js:3455](web/js/main.js:3455) (`TOP8_KEY = "rc-top8-list"`; `_top8Load` / `_top8Save`).
- **Fixture sources** (sim-only, NOT live data):
  - [data/sim/flow_01_lobby_solo.json](data/sim/flow_01_lobby_solo.json) - `lcu.top8` array
  - [data/sim/flow_02_lobby_with_others.json](data/sim/flow_02_lobby_with_others.json) - `lcu.top8` array
  - Fixture entries WIN the load (`_top8Load()` checks `lcu.top8` before localStorage) so sim preview doesn't pollute live storage - but the operator may have manually added dummies during testing that did land in `rc-top8-list`.
- **Fake test games:** `data/match_history.db` + `data/rewind_history.db` may have synthetic rows from earlier development. `data/ds_calibration.jsonl` is also a candidate.

### Cleanup steps

1. **localStorage `rc-top8-list`** - operator-driven via the existing UI delete buttons (each row has `data-action="delete"`); or one-shot clear via DevTools `localStorage.removeItem("rc-top8-list")`. No code change required if operator wants to keep some entries; otherwise add a "Clear all" button in the Top 8 management UI.
2. **Synthetic match rows** - query `match_history.db` and `rewind_history.db` for matches with `match_id` starting with `SIM_` / `TEST_` / `FAKE_` (or whatever convention was used). If no convention, look for matches with implausible `game_duration_s` (< 30 s) or fabricated `game_creation_ts` (future-dated or before launch). Delete with a one-shot script; archive the deletes to a `.bak` first.
3. **`ds_calibration.jsonl`** - read each line, drop any with `champion: "TestChamp"` / mode markers like `"sim"` / clearly synthetic `chosen_items` arrays. Rewrite atomically.
4. **Document the pruning convention** going forward so future test rows are tagged at write-time (e.g. `is_synthetic: true` column) and the cleanup is one SQL query.

Independent + headless. Can fold in alongside DB catchup (Priority 2).

---

## Priority 8 - Connect LCU mastery data

Per operator:
> _"connec the LCU mastery data"_

### Current state

- `core/riot_api.py` exposes Mastery-V4 wrappers that hit the **Riot Web API** (rate-limited, requires PUUID). Used by `dashboard/routes_team_context.py` for the team-context enrichment fan-out.
- The **LCU side** has a complementary endpoint that returns the locked-in user's full mastery list instantly + cost-free (no Riot key, no rate limit): `/lol-collections/v1/inventories/<summonerId>/champion-mastery` (full list) and `/lol-collections/v1/inventories/<summonerId>/champion-mastery/<championId>` (single champ).
- `tools/gamepc_lcu_agent.py` does NOT currently pull this. The only reference to "mastery" in the agent is a comment about server-side Riot Web enrichment.

### Wire plan

1. Add a one-shot LCU GET in `capture_state()` when phase transitions into `ChampSelect` (or earlier - on agent boot once summonerId is known):
   ```python
   me, _ = lcu_request("GET", "/lol-summoner/v1/current-summoner")
   sid = me.get("summonerId")
   masteries, _ = lcu_request("GET",
       f"/lol-collections/v1/inventories/{sid}/champion-mastery")
   # cache module-level: { championId: {level, points, last_play_time} }
   ```
2. Forward into `state["lcu"]["mastery"]` so Legion's dashboard can read instantly without waiting on the Riot Web fan-out.
3. Legion side: `dashboard/routes_team_context.py` already merges Riot Web mastery; teach it to prefer the LCU-sourced number for the local player (instantly accurate) and fall back to Riot Web for teammates/enemies.
4. **UI surfacing** (deferred - UI is paused): once data is flowing, the Champ Select view's My-Pick card + Lobby Mains tab can show mastery level + chest status. Mark the wire-up complete now; UI consumes when unblocked.

Tests: mock `lcu_request` for two cases (current-summoner returns summonerId / fails) + mastery payload shape.

---

## Priority 9 - API surface audit: map every endpoint we can hit

Per operator:
> _"connect and map every single API we can hit"_

### Why now

RC currently consumes a partial subset of LCU + Riot Web + LiveClient APIs. A full inventory is needed to:
- Spot endpoints we should be using but aren't (mastery is one example - Priority 8).
- Catalog what's already wired so future work doesn't reinvent.
- Form the basis for the "Default DS build #4" (Priority 5) which needs more per-champion data than we currently fetch.

### Deliverables

1. **`docs/API_SURFACE_AUDIT.md`** - single living doc, 4 sections:
   - **LCU** - every `/lol-*` endpoint we touch, file:line where, what state field it populates. Plus a "candidates" list of LCU endpoints we don't touch yet (mastery, perks, runes, item-sets, eog stats, hovercards, etc.).
   - **Riot Web API** - every `/lol/*` v4/v5 endpoint we call from `core/riot_api.py`, with per-endpoint rate-limit notes. Plus candidates (League-V4 division ladders, Spectator-V5 active games, Tournament-V5 if applicable).
   - **LiveClient API (`127.0.0.1:2999`)** - every endpoint we poll (game_data, player_list, active_player, events). Plus the full LiveClient surface (most is already consumed).
   - **Cross-Claude bridge + RC internal HTTPS** - every `/api/*` route on `:8888` (we have `docs/API.md` already; cross-reference).
2. **Audit scripts** - `scripts/audit_api_surface.py` greps the codebase for HTTP calls and emits a CSV of (caller_file, caller_line, endpoint, method). Idempotent + re-runnable.
3. **Backlog tagging** - for each "candidate but unused" endpoint, file a one-line entry in `BACKLOG.md` (Aspirational tier) so we don't lose them.

### Execution sketch

- Day 1: grep audit + draft the LCU section (largest surface).
- Day 2: Riot Web section + LiveClient section.
- Day 3: cross-reference with existing `docs/API.md` + sweep BACKLOG.md.

Headless-friendly. Pure analysis + doc work. Foundational for the Default DS build #4 + Priority 8 wiring.

---

## Execution order recommendation

1. **Start with Priority 1** - pick 1–2 of the DS headless candidates (per-level DPS curves + Arena augment overlay are the highest-leverage). Implement + ship tests, no UI surface.
2. **If DS testing stalls** - drop to **Priority 2** (rewind_history.db catchup script). Kick off the overnight run before EOD.
3. **Priority 9** (API surface audit) is a foundational doc pass - slot in early to surface Priority 8's mastery wiring + Priority 5's per-champion data needs. Pure-text + grep work; cheap on token budget.
4. **Priority 8** (LCU mastery) is a small concrete win once the audit is done - single LCU endpoint, single capture-state extension, ~10 tests.
5. **Priority 7** (Top 8 + fake-game pruning) folds in as a one-shot cleanup script - can ride along with Priority 2's overnight job.
6. **Priority 3 + 4** (History + Replay wiring) can fold in as small wins once Priority 1/2 are queued.
7. **Priority 5** (Default DS build #4) waits on Priority 2's DB freshness.
8. **Priority 6** (Claude Desktop key) needs operator clarification first - file an ask before touching.

Do not touch UI files (`web/**`) unless the operator explicitly unblocks. Tests + backend Python + scripts only.
