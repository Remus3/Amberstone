# Riot Commander — Roadmap

_Now + Next only. Full history in `docs/_archive/CHANGELOG.md`. Aspirational in `BACKLOG.md`._

---

## Open items — High priority

- ✅ **TFT 17.3 patch** — shipped 0e9617b (2026-05-08). Morgana 4g, Anima/Stargazer reworks, Primordian AVOID, AP comps buffed.
- ✅ **Riot API key policy reversal** — ADR-006 shipped (s145, 2026-05-09). Personal-tier key permitted for full-team champ-select context + post-game review. Live in-game advisory stays LCU/LiveClient-only per Riot ToS. Implementation tickets: FU02 + FU04 (next).
- ✅ **FU04 — Riot Personal-tier API key application** — submitted + approved same-day on 2026-05-09 (App ID 834837, well inside the documented 2–6 week window). f1c8b10. Bundle preserved at `Desktop/FU04-Application-Evidence/`; key staged in `API-Key-Riot.txt` (gitignored on Legion only).
- ✅ **FU02 — `core/riot_api.py` + champ-select team-context fan-out** — shipped s148 (`dfa13f0`). Personal-tier key resolver, dual token bucket (20/s + 100/120s + 429 cooldown), SQLite cache (immutable + 5-min TTL), six endpoint wrappers (Account-V1, Match-V5 ids/detail/timeline, League-V4, Mastery-V4), priority-1/priority-2 fan-out via daemon thread with swappable dispatcher, progressive reveal, backend ranked-name-blanking. `/metrics` exposes `rc_riot_api_calls_total{endpoint,outcome}`. 63 new tests, 565 total. **Last mile remaining:** Game-PC `tools/gamepc_lcu_agent.py` doesn't yet POST to `/api/team-context/refresh` on `ChampSelect` transition — manual roster posts work; LCU agent extension is independent.
- **FU01 — minimap-locate** — 3-path resolver (override → PersistedSettings → hardcoded). Independent. `Desktop/Tickets/RC_TICKET_FU01_minimap_locate.md`.
- ✅ **LCU agent → team-context refresh wiring** — shipped s149 (`e7b5af1`). Game-PC `tools/gamepc_lcu_agent.py` POSTs roster (with PUUIDs) to `https://192.168.8.230:8888/api/team-context/refresh` on ChampSelect entry + on lock/swap. Bridge-secret resolver (env → `bridge_secret.txt` → `local_paths.json`); LCU champion-id→name cache; edge-trigger w/ 3s repost rate-limit. 30 new tests, 595 total. Game-PC deployed live (RC-LCU PID 16080); resolver self-test confirmed. Live verification awaits next CS pop.
- ✅ **DS surfacing — header pill + ARAM Build-row fallback + match-record wire** — shipped s152 (`091d18c`). Glanceable `#ds-pill` in header row 2 (info-blue, ◆ glyph, mode-gated), Next panel ARAM/Brawl `Build` row falls back to `DS: <name> +Ndps` when coach hasn't emitted `item_extra`/`objective` (coach copy still wins), and `performance_tracker.save_rating` folds the engine's last DS pick set into `matches.raw_data["daemon_slayer_picks"]` so calibration analysis loses the JSONL ⨝ on (champion, mode, ~ts). 8 new tests, 624 total. Smoketested live: pill rendering `Stormrazor +54dps` from real coach state.
- ✅ **Mode-flicker chain + DS resolver + LCU agent fixes** — shipped s153–s158 (2026-05-10). s153 (`96bf4ee`) + s157 (`0e3d87a`) close the SR-lobby pre-flip flicker by mirroring into both HTTP `/api/state` and WS push paths via shared `resolve_mode_key` + `apply_preflip_mirror` helpers in `dashboard/_state_builder.py`. s154 (`3a3bf58`) Game-PC LCU agent falls back to `/lol-gameflow/v1/session.gameData.queue.id` when CS-session omits `gameData` during BAN_PICK. s155 (`5c39b9b`) `lock_pick` race-tolerance + UI failure feedback. s156 (`6c4a940`) DS server display-name reverse map (Kai'Sa→Kaisa, Wukong→MonkeyKing, Renata Glasc→Renata, full apostrophe family) + new `resolve_inventory` dropping trinkets/consumables/elixirs from `/rank` current_item_ids; SR coach uses it. s158 (`bd0c88e`) `?dbg=1` mode/view transition log + floating debug overlay. 15 new tests; live-verified `daemon_slayer_picks=5` mid-Kai'Sa.
- ✅ **Pre-Game Lobby v2 redesign + handleChampSelect bug fix** — shipped s162 (`5c019f9`, 2026-05-10). Phase 3 step 1 of the 14-fixture game-flow build. Rebuilt QUEUE / Mains (YOUR + PARTY tabs) / Party / "My Top 8" panels with unified 15px typography, color palette per member (`data/sim/flow_01_lobby_solo.json`). `handleChampSelect` ReferenceError chain closed (cross-module calls were silently failing in SSE try/catch → lobby never re-rendered post-refresh); orchestration moved to new `handleLcuEnvelope` wrapper in `main.js` (4 call sites). Phase 1 + 2 prep: removed 5 live menu views (Loadouts/Diagnostics/Coach Calls/Bridge Pending/Fleet), slimmed dev page, sim DEV banner → corner pill, archived 46 prior fixtures, EventSource stub in sim mode. Doc baseline: Edge / 1920×1280 → Chrome windowed / 1920×1080.
- ✅ **Pre-Game Lobby v3 polish + conflict UI + AVG/Match grade** — shipped s163 (`e316291`, 2026-05-10). Phase 3 step 1 LOCKED for both solo + multi-member states (placeholder-driven 5-slot renderer; no separate flow_02 fixture pass needed). Visual-hierarchy audit subagent ran mid-session; 5 must-fix items shipped. Self-row mirror (operator's lane prefs col 2 + DB-assessed role pip col 3); Primary-lane CONFLICT detection (red outline + diagonal CONFLICT overlay when self clashes; orange when two non-self members clash; cleared on resolution); AVG 5 grade letter (S/A/B/C/D, KP%-style 5-tier color band) — Gold dropped, Vision moved up; Mains Overall 2x2 grid; League captain-icon-crown PNG (CommunityDragon mirror) + Phosphor copy SVG; LVL ### : Unranked fallback in MY TOP 8; JGL→JNG / SUPP→SUP role normalizer; font floors 9→13px; drop shadow on tooltips/mode menu; page fits 1080-viewport without scrollbar. 913 ins / 181 del across 7 files.
- ✅ **Phase 3 step 2 + step 3 — Champ Select view scaffold + Pick&Ban panel + trade popup** — shipped s164 (`c0e6043`, 2026-05-10). Step 2 (`flow_02_lobby_with_others.json`) was a renaming pass; step 3 built the new top-level `view-champ-select` page from scratch. 3-col grid (Allies + Pick&Ban left, My Pick + Builds center, Enemies right); auto-promotes on `?cs=1` + `phase=ChampSelect`. Pick&Ban Recommendations panel: 3 source rows (perf/mastery/meta) + 4-button mood toggle (Comfort/Limit/New/Comp Synergy) + quick-select with lock-after-click (gated to skip BAN_PICK so user can't accidentally ban their own pick). Trade popup: SWAP/TRADE header + CHAMPION/Nth-PICK/ROLE buttons appended to `<html>` to bypass body's `zoom:1.33` with matching `transform:scale`. Enemy "(guess)" tag + cyan timer (no "s" suffix) + 2px round-border (red ban / gold pick). LED-dot animation explored + removed (didn't render reliably). 1986 ins / 4 del across 10 files (3 new: flow_02 fixture, flow_03 fixture, champ_select_view.css).
- ✅ **Phase B — LCU agent handlers + champ-select state population** — shipped s166 (2026-05-10). 5 new command handlers in `tools/gamepc_lcu_agent.py` (set_ban_intent / set_pick_intent / set_augment_intent stub / request_position_swap / request_pick_order_swap) + new champ-select state fields (active_round / is_brawl / position_swaps / pick_order_swaps / arena_teams / augments scaffold) + per-player summoners on `_team_picks`. 30 new tests under `tests/phase_b_champ_select/` (665 total green). set_augment_intent returns explicit "unsupported" until `/lol-cherry/v1/*` endpoint can be confirmed against a live Arena lobby.
- ✅ **Phase 3 step 4 — Loading Screen view scaffold** — shipped s166 (2026-05-10). New top-level `view-loading` with mode-conditional team panels (sr/aram/arena/brawl), `?ld=1` opt-in, `phase=GameStart` auto-promote. Briefing card removed before commit per operator (defer copy iteration to a later session). New files: `web/js/panels/loading.js`, `web/css/panels/loading_view.css`, `data/sim/flow_04_loading_screen.json`. Backend population paths for the new view land via the Phase B `_team_picks` summoners change above.
- ✅ **Phase 3 step 3 follow-ups — central panel + enemies redesign for ALL game modes** — shipped s165 (`91a42e1`, 2026-05-10). New `_csvDetectMode(cs)` returns `sr|aram|arena|brawl` from queue_id + is_aram/is_brawl flags; `section.dataset.csMode` stamped on render; CSS branches via `[data-cs-mode]`. SR: 3-variant Build Chooser populated (was empty placeholder). ARAM: 5-cell horizontal Bench (`bench_swap` wired) + ARAM Build Chooser. Arena: 2-cell allies, central pane swaps to Duo+Augments (3 slots silver/gold/prismatic + options w/ `set_augment_intent`), enemies = 3 sub-team cards. Brawl: 5v5 no roles/bans, Brawl Build Chooser. Pick&Ban + Allies panels untouched (LOCKED per operator). 3 new fixtures (flow_03b/c/d). Phase B follow-ups merged into the LCU agent ticket: handlers for `set_augment_intent` + populate `cs.arena_teams`/`cs.augments`/`cs.is_brawl`; real build variants from `/api/loadout/list`.
- 🟡 **Phase 3 fixture flow (steps 5–14)** — remaining canonical fixtures: champ-select 1st/5th/locked variants, active match @ 0/6/12/20/30/40 min, game summary (NEW view), last match. **PAUSED per operator 2026-05-10** while backend work catches up. Step 4 (Loading Screen) shipped in s166. Per `feedback_phase3_fixture_ritual.md` — each fixture begins with visual-hierarchy audit subagent, ends with `/done` + `/clear`.
- 🟡 **Active Match view (steps 2–5)** — step 1 scaffold shipped s159–s161 (`3f72795` / `57886e1` / `8a857c4`): new `active-match` view + 2-col grid (CALL stacked over BUILD left, MAP full-height right) + `?am=1` opt-in auto-promote on in-game modes + ZEN/DEV pill removal + tooltip 14→17px. Steps 2–5 detailed in WAKEUP_NOTES s153–s161 entry: (2) DS icons + owned-as-text + per-tick rerank, (3) enemy-comp threading into `target_armor/mr/bonus_hp` (currently hardcoded `target_armor=80.0`), (4) static SR/ARAM/Arena/Brawl map + ZOI/gank/MIA overlay, (5) zen-lock in-game + RIGHT NOW fold + bridge-pending → dev-panel button + fleet view removal.
- 🚫 **FU03 — clipboard helper** — permanently superseded by FU04 same-day approval (Personal keys don't expire; daily-renewal helper unnecessary).
- **rewind_history.db staleness** — blocked on live SR game (last entry Dec 2025; needs game_id wired to new session records).
- **Vision regions calibration** — tune `data/vision_regions.json` bboxes. Blocked on live game for calibration frame.
- **Bridge Watcher acceptance-criteria** — need 50+ real-traffic auto-action samples (currently synthetic only). Watch `auto_ok_since_boot` vs `auto_err_since_boot` on RC heartbeat.
- **gamepc_boot.ps1 hardening** — add `RC-WatcherHealthPublisher-GamePC` + `RC-BridgeWatcher-GamePC` to idempotent start sequence; currently missing (must be `Start-ScheduledTask`'d manually after socket exhaustion events).

## Open items — Medium priority

- **Auto-ops verb expansion** — once Phase 3 auto-action success rate clears 95%, add: `tail .* log`, `restart agent .*`, `verify .*` to Legion `auto_ops_verbs`.
- **Game-PC + Peer auto-action lanes** — watchers installed but `--enable-auto-action-lanes` is OFF. Enable when success rate is proven.
- **RC-DaemonSlayer task context** — runs as SYSTEM; `_log_startup` writes silently fail. Change to LogonTrigger + Administrator context if traceability matters after next boot.

## Future-Proofing Plan (retired 2026-05-09 — all 7 phases ✅)

Retired to `docs/_archive/RC_FUTUREPROOFING_PLAN_retired_2026-05-09.md` after all phases shipped.

| Phase | Status |
|---|---|
| 1 — Knowledge architecture | ✅ Done (fc1361b — s125+s126) |
| 2.1 — champion_profiles split | ✅ Done (s127 — 902→29 LOC + 168 JSONs) |
| 5 — CI + smoke harness | ✅ Done (d21f533 — 343→380 tests, ruff 0 violations, CI gate live) |
| 4 — Contracts/schemas | ✅ Done (791e2db — s143 dispatch soft-warn validator + 26 tests; closes s129 4.1+4.3 partial) |
| 3 — Frontend modules | ✅ Done (s137 — 3.1+3.2+3.3; 6-fixture Playwright snapshots, WS-stub isolation) |
| 2.3 — coach_integration split | ✅ Done (s138 — 1225 LOC → _profiles/\_sr\_prompt/\_coach pkg, 386 tests) |
| 6 — Bridge consolidation | ✅ Done (s144 — `tools/bridge_cli.py` + 7 shims, BridgeMetrics namespace in `core/prom_metrics.py`, 42 tests; state consolidation + 5 watcher daemons explicitly out of scope) |
| 2.2 — game_reader split | ✅ Done (ea7589e — s139, 1474 LOC → mixin pkg, 386 tests) |
| 2.4 — vision server split | ✅ Done (9cf262a — s140, 710 LOC → shim + vision_server/ pkg, 386 tests) |
| 7 — Process polish | ✅ Done (s141 48d11be + s142, phase-marker normalization + archmap journal + WAKEUP_NOTES auto-prune + Conventional Commits commit-msg hook, 412 tests) |

---

## Fleet status at a glance

| Layer | State |
|---|---|
| RC supervisor + main | Stable (pid=1108 at last check) |
| Web dashboard `:8888` | All endpoints green |
| Vision relay `:8889` | Stale-frame rejection live; auth via rotated token |
| MCP server `:8892` (Game-PC) | HTTP 200 |
| Bridge Watcher (Legion) | pid=15004 cadence=active; 24h ring live |
| Game-PC bridge daemon | watcher=alive queue=0 |
| Peer bridge daemon | watcher=alive queue=0 |
| Coaches | All 4 modes DS-before-Haiku ✅ |
| Daemon Slayer `:8893` | ENGINE 0.60.0 · 547 items · 911 tests |
| TFT | Set 17 patch 17.3 live (0e9617b) |

---

## Cross-cutting principles (never violate)

- **Frozen files** — see CLAUDE.md. Explicit operator sign-off required for any change.
- **Atomic writes only** — `tmp.write_text(...); tmp.replace(target)`. Overlays + dashboard poll mid-write.
- **`py_compile` before restart** — syntax errors crash silently under `pythonw.exe`.
- **Restart via `restart_trigger.txt`** — never `Stop-Process`; `taskkill /F /PID` for hard kills.
- **Coach prompt edits require RC restart** — batch edits, restart once.
- **Don't break the cross-Claude bridge** — `vision_token` + `mcp_token` are SEPARATE; never let one resolver fall back to the other's file.
