# Riot Commander - Backlog

_Aspirational / longer-term items. Extracted from ROADMAP.md "Future" section 2026-05-08._
_When an item moves to active work, migrate it to ROADMAP.md "Open items"._

---

## Bridge Watcher hardening

- ~~**Per-call cost histogram**~~: shipped 2026-05-19 (Phase 2) - `rc_coach_cost_usd_per_call` Histogram in `core/cost_tracker.record_call` (model+purpose labels, USD buckets), rendered at `/metrics`; week-over-week p95-doubling lane signal folded into the existing `tools/cost_health_watchdog.py` (no second cron; detect+log+propose only).
- **`bridge_watcher_install.ps1` self-update**: detect stale local copy and prompt to re-pull when a new watcher ships.
- ~~**Bridge contract v1**~~: shipped - `core/bridge_envelope.py` (Phase 4.2, s129) defines `body_path` / `claimed_by` / `ttl_at` / `suggestions`; `tools/bridge_cli.py` (Phase 6, s144) consolidates the 7 small CLIs over it. Watcher daemon refactor (bigger envelope-aware rewrite) deferred separately.

## Cross-Claude infrastructure

- **Cross-Claude lessons Phase 4**: confidence scoring, symmetry check, auto-revert (Phases 1-3 shipped 2026-05-06).
- **Bridge MCP tool wrapper**: REPL-style access to `/api/bridge` query params from any Claude session.

## Coaching depth

- **rewind_history.db SR records with game_id**: post-live SR game; wired in code (d66d14b) but blocked on new records.
- **LCU deeper integration**: Pengu Loader Discord/GitHub research for endpoints RC doesn't use yet (richer pre/post-game data). Research-first, no code scheduled. **Reference catalog identified 2026-05-17:** `KebsCS/lcu-and-riotclient-api` (lcu.kebs.dev) is a current (client 26.05), exhaustive (2839 ops) endpoint map - the authoritative source for the richer endpoints (mastery-by-puuid, `match-history .../games/{gameId}` + `game-timelines`, `loadouts/v4`, `signed-ranked-stats`). No LICENSE → reference only, don't vendor; optionally diff its `data.json` per patch. This supersedes the Discord crawl as the primary endpoint-discovery method.
- **Interactive Item Shaper (post-DS-100%)** _(noted s214, 2026-05-15)_: final-polish layer on top of the per-archetype scorers. UI exposes 3 modifiers - `DAMAGE` / `SURVIVABILITY` / `UTILITY` - each with a +/- nudge that reshapes the active scorer's weighting on the fly (e.g. Bruiser α=0.65/β=0.35 default → DAMAGE+ pushes toward α=0.80, SURVIVABILITY+ pushes toward α=0.45). The shaper reads + writes the running coach's archetype weights without persisting them; on match end the weights snap back to the archetype default. Intended as a real-time "I'm in a fight-heavy comp, push damage" / "they're snowballing, hold survivability" hint loop. **Block on**: DS engine reaches 100% champion coverage so the weight knobs sit on a complete underlying scorer surface before exposing them to operator-driven tuning.

## Platform / observability

- ~~**Memory watchdog remediation wiring**~~: shipped 2026-05-19 (Phase 2) - `core/resource_manager.py` `set_remediation_hook` dependency-injection (did NOT edit frozen `app/_remediation.py`); sustained 3-consecutive-500MB-breach + 600s cooldown latched-before-hook + structured log. Hook defaults None (live behavior unchanged); the one-line `main.py` wire to `RemediationService.restart_game_poll` is the remaining OPERATOR-GATED step.
- **Streaming vision**: delta-encoded frames instead of full JPEG every 2s. ~5× bandwidth reduction.
- **Mobile-native dashboard**: current PWA adds ~2s touch latency. Native iOS/Android would reduce that.

## Data pipeline

- **TFT vision relay frame dimensions**: lock OCR pipeline to 1920×1080 once validated (pair with NOTE-025 calibration).
- ~~**Adversarial sim fixtures**~~: shipped s173.1 (`38ca915`) - 4 fixtures + 2 tests under `tests/snapshot_panels/`; uncovered s151 `gameTime` ref-error during initial run.

## Developer experience

- **Type hints + ruff one-time pass**: codebase mixes annotated/unannotated. `ruff --fix` + annotations on public coach API.
- ~~**Test fixtures for adversarial paths**~~: shipped s173.1 (`38ca915`) - see Data pipeline entry above; this was a duplicate of the same item.
- ~~**Console-pipe localStorage flush failure-recovery loop**~~: shipped s173.1 (`51e0da7`) - `flushQueueAfterSuccess` now preserves entries on replay failure (per-entry removal via `_dropQueuedEntry`).

## Reliability / hardening

- ~~**MCP server hung-tool watchdog**~~: shipped 2026-05-19 (Phase 2) - bounded `ThreadPoolExecutor` dispatch watchdog (45s default, `RC_MCP_DISPATCH_TIMEOUT_S`) in `tools/ds_matchdb_mcp_server.py` + `tools/gamepc_mcp_server.py`; structured MCP timeout error, future abandoned/cancelled; `run_powershell` backstopped at 630s (its own subprocess timeout still governs, not double-wrapped). NOTE: those MCP servers need their own restart to run the new code (operator-gated; not RC-process).
- ~~**`MatchDB` thread-safety validation**~~: moot - `core/match_db.py` was refactored 2026-04-28 (audit proposal 1.2) from RLock to WAL + per-thread connections. FIX-021 lock no longer exists; serialization is now SQLite WAL.
- **`/api/analyze` streaming response**: current 30s timeout fine for ARAM (sub-second); may need SSE if full-mode analyses scale.

## Speculative

- **`.rofl` file replay coaching**: `coaches/replay_coach.py` shipped lite version (rewind_history.db). Full `.rofl` parsing **confirmed dead-end 2026-05-17** - fraxiinus `roflxd` (the maintained .ROFL parser family) shows a parsed .ROFL exposes only end-of-game aggregate `PlayerStatistics[]`, a strict *subset* of RC's existing Match-V5 SQLite; the in-game packet stream (frame positions / ability casts / event stream a replay-review page would want) is Riot-obfuscated and unparseable on the current patch. The planned s220 **S5 Replay page stays Match-V5-timeline-driven**; do not re-pitch .rofl parsing.
- **PyInstaller packaging**: `riot-commander.spec` exists as opt-in starter. Not prioritized.
- **OBS publisher activation**: `T3 #11` shipped (264 LOC, opt-in); not wired to any active workflow.

## Research / inspiration (s219, 2026-05-15)

- **coachless.gg teardown**: analyze https://coachless.gg/ - both the site and its app - for build patterns, post-game analysis UX, and any insight worth lifting into the Post Game Review or future Deep Review page. Operator can re-subscribe for a month to access the locked content if a deeper teardown is warranted.
- **Local DDragon mirror auto-refresh**: download every icon path (champions, items, summoner spells, runes, augments, profile-icons) into `/data/ddragon/<patch>/` on each patch flip + auto-update when DDragon ships new assets mid-patch. Today the mirror lags at 16.8.1 while live patch is 16.10.1 - Post Game Review pinned to 16.8.1 + CDN fallback as workaround (s219). A real mirror keeper would be one cron + a manifest diff. **Vendor-safe tooling found 2026-05-17 (`open item research.txt` triage):** `magisteriis/download-league-of-legends-data-dragon` (**Unlicense/public-domain**) = realms→version resolve + dragontail fetch + version output; `marvinscham/get-league-patch` (**MIT**) = minimal `ddragon/api/versions.json`→`MAJOR.MINOR` patch-flip trigger; `Nyx0ra/lol-asset-downloader` (**MIT, 2026**) = the per-asset *incremental diff* half; `molenzwiebel/OriannaBot` (**MIT**) = mature production refresh internals if the action proves too coarse. Pair (trigger + resolve + diff) ≈ the whole item; all vendor-safe.
- ~~**Pengu.lol MCP - adapt to RC**~~: **rejected 2026-05-17.** Evaluated `rumi-chan/league-client-mcp` (the MIT candidate): it is a thin generic `fetch()` passthrough that *requires* Pengu Loader injected + a live client running just to make an LCU call, and inherits the exact same LCU surface RC already hits. Strictly worse than RC's out-of-process Python lockfile client (no Pengu/live-game dependency, more robust). Exposes no richer endpoints and no augment access. Do not re-adopt or re-research.
- **Pengu.lol Discord crawl** _(demoted 2026-05-17)_: the static KebsCS catalog now covers released endpoint knowledge; keep this only as a *secondary* sweep for unreleased / in-progress community work (replay-timeline access, novel Mayhem detection). Research-only; surface findings before scheduling code work. **One concrete lift already surfaced** (Mayhem-Doctor, 2026-05-17): the static asset `/lol-game-data/assets/v1/cherry-augments.json` resolves augment id → name/icon/rarity (`kSilver/kGold/kPrismatic`) - authoritative augment table without screen-OCR for *naming* (OCR still needed for *which* augments are offered live). Independently re-confirmed: zero `/lol-cherry/*` and zero `/lol-game-augments/*` live endpoints exist (KebsCS full 26.05 catalog) - augment-OCR stays; do not re-pitch an LCU augment API.

### `open item research.txt` (~90 links) triage - 2026-05-17 (multi-agent, s234 methodology)

3 decisions LOCKED + integrated to ROADMAP + CLAUDE #90 (do not re-litigate): fold `Morello` (MIT) into the s220 PGR 0-100 score; build ONE shared smoothed-rate primitive (Laplace/Beta over own match DB) for #88 augment + pick/ban synergy + PGR score; 101.qq.com CN duo-synergy is worth a one-off Game-PC Network-tab capture.

**FUTURE (noted, not scheduled):**
- **baronbuff.com** - closed-source *methodology* template: draft = single win-prob model fusing counters+synergy+comp+pool; PGR = "the decisions/phases that mattered, with evidence." Frames pick/ban + the s220 Deep-Review. Reference-only.
- **league_record** (GPLv3 - **cleanroom only, do NOT vendor**) - local OBS *video* capture keyed to LCU game-lifecycle + an event-timeline sidecar. NOT .rofl (sidesteps the CLOSED .rofl dead-end). The architecture reference for the s220 **S5 Replay** page.
- **aggregator Z13** builds-tier-list (ranks champ×rune×first-item *tuples*, not just champs) · **aggregator J** (item tierlist bucketed by stat-type / tankiness / early-late) - METHOD refs for ARAM build data + DS presentation. Reference-only (closed Next.js SPAs, no JSON API exposed).
- **quick-aggregator-a-scraper** (MIT) - clean browserless Axios+Cheerio + TTL-cache aggregator A scrape = the *fallback* technique if RC ever needs an aggregator A tier/meta source.
- **AsperaDesu/LoL-AI-Draft-Picker** (MIT) draft-as-ordered-token-sequence idea · **junlarsen/league-connect** (MIT) per-endpoint WS `subscribe()` event-bus pattern (if RC ever moves champ-select/lobby off polling) · **CookieDecide/LeagueBuilds** (GPL, actively maintained) server-side build/rune/skill data pipeline (study, don't vendor) · **lolsite** `Greatest(field,1)` zero-guard per-min idiom. All reference-only.

**CLOSED - recorded so it is never re-spent:**
- **All 27 LCU client / event-viewer / swagger-codegen repos** (jjmaldonis · sousa-andre · Willump · PoniLCU · junlarsen · overlay app Z6 · GlassLCU · lcu-api-generator · clean-cuts · Briar · lcu-event-viewer · sunneydev/lcu-events · stirante/lol-client-java-api · bryanhitc/lcu-sharp · Pupix/rift-explorer · ratRequ3ster · RitoClient · ImOlli/go-lcu · legendary-rune-maker · Guava · CharmingDays/LeagueCU · zquaa/LCU-Stats · zquaa/league-refresher · Aventurine-League-Tools · LolyTools · simple-debugger): every one a generic client / event-viewer / codegen strictly inferior to RC's out-of-process lockfile Python client; **KebsCS stays the canonical endpoint catalog**; the entire corpus contains **ZERO Arena/Cherry/Mayhem lobby-create payloads** → #89's bespoke payload must come from live LCU capture or KebsCS, not a library (a confirmed negative result - close that search path). `CharmingDays/LeagueCU` (MIT) only re-confirms the Practice-Tool `{"queueId":"PRACTICETOOL"}` string-sentinel RC already implements.
- ML / CV / misc: `LoL-Match-Predictor-ML` (Kaggle 10-min win-pred, no draft) · `League-Of-Legend-Items-Analysis` (item K-means - DS already richer) · `ARAMNet` (solves champ-pool *fairness*, not balance) · `LeagueMinimapDetectionOpenCV` / `LAVA` (RC's Live-Client position-freshness already covers; GPL anyway) · `LeagueAiCoach` / `LoLvoice` (voice) · `riot-offline-mode` (verified: Windows-Firewall toggle, **not** an offline-LCU test harness) · `Neeko-Server` (replay emulator, broken @ patch 14.1+) · `letter.gg` (TFT) · `malPHPhite` (PHP) · plus archived/dead/stale. None re-open.

### `draft tool L (the community fork)` (HuyTheSkeleton fork of `draft tool L`) triage - 2026-05-19

Single-repo liftability review (operator-handed GitHub link; focused triage, not the multi-agent list method).

**FUTURE (noted, not scheduled):** the **Elo log-odds draft-composition aggregator** is the team-vs-team draft layer `dashboard/routes_pickban.py` does not have - `winrateToRating = -400*log10(1/w-1)`, team score = sum(ally champ + ally-duo + matchup ratings) minus sum(enemy champ + enemy-duo), `ratingToWinrate = 1/(1+10^(-d/400))`. Composes **on top of** `core/smoothed_rates.py` (smoothed rates feed the rating transform - orthogonal, NOT a duplicate; smoothing/priors are RC's existing edge and are absent here). Trigger: when RC wants true team-vs-team draft scoring beyond the current recent-form / joint-WR proxy, with pairwise WR sourced off `rewind_history.db`. Reference-algorithm-reimplement only.

**CLOSED - recorded so it is never re-spent:** (1) **No license** on draft tool L (the community fork) AND upstream `draft tool L` (neither OSI nor permissive) - vendoring either is legally unsafe; algorithm-only, reimplement clean from the formula above. (2) Its data is a **aggregator D HTML scrape** (`apps/dataset/.../aggregator D/qwik.ts` parsing the embedded `qwik/json` blob) RC cannot legally cache or redistribute - the dataset half is a dead end; pairwise WR must come from `rewind_history.db`, not aggregator D. (3) The "+" fork adds **zero algorithmic value** (UI delta column / dynamic tier-list only; 2 stars, solo) - reason from upstream's math, never prefer the fork. (4) Does NOT duplicate `core/smoothed_rates` (no smoothing/priors anywhere). (5) Tauri/Qwik/SolidJS desktop stack - irrelevant to RC's Python/JS dashboard.
