# Riot Commander — Agent Context

Live League / TFT coaching dashboard. Reads Riot Live Client API, calls Claude Haiku for coaching and Sonnet for vision, writes JSON to `data/`, serves `:8888` HTTPS dashboard on Game-PC's secondary display. RC is tkinter-free; Daemon Slayer (`:8893`) computes real DPS math per champion.

> **Living docs (read at session start):** `docs/ARCHITECTURE.md` · `docs/OPERATIONS.md` · `docs/BRIDGE.md` · `ROADMAP.md` · `docs/API.md`
> **Deep references:** `docs/DAEMON_SLAYER.md` (DS engine · 547 items · ENGINE_VERSION 0.60.0) · `docs/AGENTS.md` (Phase 3 framework) · `BACKLOG.md` (aspirational)
> **Architectural decisions:** `docs/adr/` — before re-litigating a past choice, check here first.
> **Dated artifacts** in `docs/_archive/` (excluded from ripgrep searches).

## Topology

| Machine | Tailnet / IP | LAN IP | Role |
|---|---|---|---|
| **Legion** | `legion-rc` / `100.70.22.55` | `192.168.8.230` | Runs RC, supervisor, vision server, web dashboard |
| **Game-PC** | `gamepc-rc` / `100.95.66.128` | `192.168.8.237` | Runs League; Chrome on secondary display (panel is 1920×1280 native @ 100% scale) shows the dashboard |
| **Peer** | `peer-host` / `<peer-tailnet-ip>` | — | Cross-Claude peer; RC↔Peer bridge |

All three in tailnet `tailc150de.ts.net`. Prefer tailnet hostnames. Vision runs in-process at `127.0.0.1:8889`.

## Paths

- Project root: `C:\Riot Commander\`
- Python: `C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe`
- API key: `C:\Riot Commander\API-Key-Claude.txt` (gitignored)
- Health: `C:\Riot Commander\ops\runtime\health.json`
- Logs: `C:\Riot Commander\logs\YYYY-MM-DD.log`

## Hard rules

- **Always `py_compile` before restart.** Syntax errors crash silently under `pythonw.exe`.
- **Atomic writes only:** `tmp.write_text(...); tmp.replace(target)`. Overlays poll mid-write.
- **Never `Stop-Process`.** Hangs MCP pipe. Use `taskkill /F /PID`.
- **Restart via `restart_trigger.txt`** (write any content; supervisor clears + restarts within ~5s).
- **`SCRIPT_DIR` in `app/__init__.py` MUST be `Path(__file__).parent.parent`** (package layout).
- **State assumptions explicitly before coding.**
- **Frozen files** (do not modify without explicit user approval):
  `main.py`, `core/log_setup.py`, `core/moon_proxy.py`, `lcu/lcu_client.py`,
  `core/game_snapshot.py`, `ops/rc_dev_runtime.py`, `ops/rc_supervisor.py`,
  `app/__init__.py`, `app/_loop.py`, `app/_health_monitor.py`, `app/_remediation.py`,
  `app/_state_authority.py`, `app/_overlay_manager.py`, `app/_game_lifecycle.py`,
  `tools/bridge_watcher_classify.py`,
  `tools/bridge_watcher_actions.py`, `tools/bridge_watcher_action_prompt.md`,
  `tools/bridge_watcher_history.py`, `tools/bridge_watcher_install.ps1`,
  `tools/bridge_watcher_hook.ps1`, `tools/bridge_watcher_config.json`,
  `tools/bridge_post_result.py`, `tools/bridge_pull_tasks.py`,
  `tools/process-bridge-tasks.md`, `tools/diagnose.md`, `tools/caveman.md`,
  `dashboard/routes_bridge_pending.py`, `ops/RC-BridgeWatcher.xml`.

## Restart workflow

```
echo restart > restart_trigger.txt
```
Verify: read `ops/runtime/health.json`, confirm new `pid`, `alive=true`, `last_reload_ok=true`.
Hard fallback: `taskkill /F /PID <pid>` then `restart.bat`.

## Session workflow

Scoped sessions — each focused task is one session.
- **End:** commit + update `WAKEUP_NOTES.md` (keep last 2–3 sessions at full fidelity; archive older to `docs/history_notes.md`) + push.
- **Start:** `/clear`, bootstrap from CLAUDE.md + MEMORY.md + git log + WAKEUP_NOTES + `docs/ARCHITECTURE.md` + `ROADMAP.md` (all 4 under 800 lines total).
- `/clear` between Tier items, between coding/reviewing modes, between focus-area switches.

## Web dashboard

`web_dashboard.py` at `:8888` HTTPS. Key endpoints: `/`, `/api/state`, `/api/health/all`, `/api/bridge/pending`, `/api/input`, `/api/command`, `/api/ds-preview`, `/metrics`. Viewed in Chrome on Game-PC secondary at `https://legion-rc:8888/` — design baseline is **standard 1920×1080 with Chrome chrome present** (titlebar + URL bar + bookmarks bar visible, usable viewport ≈ 1920×~920). F11 fullscreen is optional and recovers the chrome chrome — `main` flex-grows into the extra height (no layout pinned to 1280). Cert via `tools/regen_rc_cert.ps1`. Each machine has its own Anthropic API key (`riot-commander-legion`, `riot-commander-gamepc`, `riot-commander-peer`).

## Scheduled tasks (Legion)

Key: `RC-Supervisor` (logon, Administrator, HIGHEST) · `RC-VisionServer` (startup, SYSTEM, HIGHEST) · `RC-BridgeWatcher` (logon, daemon). Full list + Game-PC tasks: `docs/OPERATIONS.md`.

## Vision pipeline

Game-PC `gamepc_screen_agent.py` POSTs frames every 2s to `:8889/upload-frame`. Coaches call `modes.shared_vision._capture_screen()` → GET `:8889/latest-frame`. **`_run_vision()` gates on `_fetch_game_data() is not None`** — vision never fires during lobby/idle. Tiered: OCR first, Sonnet escalation for misses. Calibrate `data/vision_regions.json` to expand OCR coverage.

## Mode detection

`game_reader.py._process_game()` → `core/game_snapshot.py` → mode strings. ARAM Mayhem (`KIWI`) → `MODE_ARAM`.

## Where to find current state

- Live PID + mode + health: `ops/runtime/health.json`
- Current game state: `data/{aram,arena,brawl,tft}_coaching_data.json`
- Recent activity: `logs/YYYY-MM-DD.log`
- Architecture / module map: `docs/ARCHITECTURE.md`
- Ops commands + restart: `docs/OPERATIONS.md`
- Bridge wire format + watcher: `docs/BRIDGE.md`
- Open work: `ROADMAP.md` · Aspirational: `BACKLOG.md` · History: `docs/_archive/CHANGELOG.md`

## Useful commands

Full reference: `docs/OPERATIONS.md`. Quick-start:
```
python -c "import json; print(json.dumps(json.loads(open(r'ops/runtime/health.json').read()), indent=2))"
echo restart > restart_trigger.txt
curl -k https://127.0.0.1:8888/api/health/all
```

## Memory frontmatter — cross-project sync fields

Standard memory files carry `name`, `description`, `type`. Two optional fields
are valid for memories that should ride the RC↔Peer bridge (Phase 1 schema,
`docs io RC peer/RC_PHASE1_LESSON_SCHEMA_2026-05-02.md`):

```yaml
cross_project: true          # opt-in; default false. Only feedback/reference/project eligible.
applies_when: "<trigger>"    # required when cross_project=true; free-form grep-able phrase
does_not_apply_when:         # optional list; receiver skips if any entry matches local context
  - "<neg-trigger>"
```

`type: user` memories are never eligible. Default is OFF — author decides at write-time.
False-negatives are recoverable (edit frontmatter later); false-positives are bridge spam.

## Testing Discipline

Always run the full test suite after schema changes, engine version bumps, or item-effect additions. Avoid data-fragile cross-item comparison assertions; prefer assertions on computed quantities. When stubbing methods accessed via class, wrap with `@staticmethod` correctly.

## Windows Environment Notes

Claude Desktop on Windows may be installed via the Microsoft Store (check `%LOCALAPPDATA%\Packages`) in addition to standard install paths. Use `pythonw.exe` (not `python.exe`) for background daemons to avoid flashing console windows.

## Daemon Slayer Batch Workflow

When continuing Daemon Slayer work: pick the next batch from ROADMAP, implement schema/engine changes, add tests (target green before commit), bump engine version, commit + push, verify live, update hand-off notes.

## Session Wrap-up

When invoked with `/done` or asked to wrap a session: (1) audit pending changes, (2) commit and push, (3) update ROADMAP/CLAUDE/README if relevant, (4) process lessons/WAKEUP_NOTES, (5) run bridge probe, (6) print final banner. Run independent steps in parallel.

## Active priorities

1. ✅ Phase 1 — Knowledge architecture complete (fc1361b, s125+s126): living docs + archmap + 5 ADRs.
2. ✅ Phase 2.1 — champion_profiles.py split complete (8fa11f4): 902→29 LOC + 168 JSONs.
3. ✅ Phase 5 — CI gate + smoke harness complete (d21f533, s128): 380 tests pass, ruff 0 violations.
4. ✅ Phase 4 — Contracts/schemas complete (s129 + s143 + s144): `core/coaching_payload.py` (5 pydantic models, soft-validate in state-builder) + `dashboard/api_schema.py` (HTTP shapes) + `core/bridge_envelope.py` + `docs/API.md` (40 routes); s143 added soft-warn dispatch-level validator in `dashboard/_dispatch.py` (5 paths, 26 tests); s144 closed 4.2 tool-rewrite via the Phase 6 `tools/bridge_cli.py` consolidation.
5. ✅ TFT 17.3 — shipped 0e9617b (s131): Morgana 4g, Anima/Stargazer reworks, Primordian AVOID, AP comps buffed.
5b. ✅ Phase 3 complete (s133+s135+s136+s137): ESM panels, CSS panels, JSDoc typedefs, Playwright snapshots. 6-fixture harness in `tests/snapshot_panels/`; WS stub prevents live-supervisor interference; CI gate live.
5c. ✅ Phase 2.3 — coach_integration split complete (s138): 1225 LOC → `coach_integration/` pkg (_profiles 181 + _sr_prompt 455 + _coach 607 + __init__ 6). 386 tests, ruff clean.
5d. ✅ Phase 2.2 — game_reader split complete (s139): 1474 LOC → `game_reader/` root pkg via `_PollerMixin` + `_NormalizerMixin` (poller 281 + snapshot_normalizer ~700 + mode_router 74 + __init__ 92). 386 tests, ruff clean, RC restarted clean.
5e. ✅ Phase 2.4 — moon_vision_server split complete (s140): 710 LOC → 21-LOC entrypoint shim + `vision_server/` pkg (_config 75 + _stats 65 + _frame 117 + _relay 118 + _inference 264 + _http 245 + __init__ 79). 386 tests, ruff clean, :8889/health verified, build_portable.py patched.
5f. ✅ Phase 7 — Process polish complete (s141 48d11be + s142): phase-markers normalized + archmap phase journal; `scripts/wakeup_prune.py` auto-prunes WAKEUP_NOTES (last 3 sessions, atomic, idempotent); `.githooks/commit-msg` enforces Conventional Commits subject lines (`<type>(<scope>)?!?: <description>`); 412 tests pass.
6. ✅ Phase 6 — Bridge consolidation complete (s144): `tools/bridge_cli.py` (574 LOC) + 7 thin shims (139 LOC) replacing 7 originals (772 LOC); `BridgeMetrics` namespace in `core/prom_metrics.py`; 42 tests pass. State-file consolidation + 5 watcher daemons (`bridge_watcher*.py`) explicitly out of scope. Cron contracts preserved — `process-bridge-tasks.md` skill spec untouched.
7. ✅ Riot API key policy — ADR-006 (s145, 2026-05-09) reverses the "no key" rule for full-team champ-select context. Personal-tier; Web API limited to champ-select + post-game; live in-game advisory stays LCU/LiveClient-only. Implementation tickets are FU02 (`core/riot_api.py`) + FU04 (Personal-tier application).
8. ✅ **FU04** Riot Personal-tier API key — applied + **approved same-day 2026-05-09** (App ID 834837, well inside the documented 2–6 week window). Bundle preserved at `Desktop/FU04-Application-Evidence/`. Key staged into `API-Key-Riot.txt` (gitignored).
9. ✅ **FU02** `core/riot_api.py` + champ-select team-context fan-out — shipped s148 (`dfa13f0`). Personal-tier key resolver + dual token bucket (20/s + 100/120s + 429 cooldown) + SQLite cache (immutable for match data + Account, 5-min TTL for ranks + mastery) + 6 endpoint wrappers + priority-1/priority-2 fan-out via daemon thread + progressive reveal + backend ranked-name-blanking (queue 420/440). 63 new tests, 565 total. `/metrics` exposes `rc_riot_api_calls_total{endpoint,outcome}` + bucket gauges.
10. ✅ **LCU agent → team-context refresh wiring** — shipped s149 (`e7b5af1`). Game-PC `tools/gamepc_lcu_agent.py` POSTs roster (with PUUIDs) to `https://192.168.8.230:8888/api/team-context/refresh` on ChampSelect entry + on lock/swap. Bridge-secret resolver, edge-trigger w/ 3s repost rate-limit, LCU champion-id→name cache. 30 new tests, 595 total. Game-PC deployed live; live-fire verification awaits next CS pop.
10b. ✅ **DS surfacing — header pill + ARAM Build-row fallback + match-record wire** — shipped s152 (`091d18c`). Glanceable `#ds-pill` in header row 2 (info-blue, ◆ glyph, mode-gated to in-game). Next/ARAM `Build` row falls back to `DS: <name> +Ndps` when coach hasn't emitted `item_extra`/`objective`. `performance_tracker.save_rating` folds the engine's last DS pick set into `matches.raw_data["daemon_slayer_picks"]` so calibration analysis loses the JSONL ⨝ on (champion, mode, ~ts). 8 new tests, 624 total. Pre-existing `gameTime` ref-error at `panels/map_state.js:720` still pending (s151 follow-up).
11. ✅ **FU01** minimap-locate — shipped s168 (2026-05-11). New `agents/_minimap_bbox.py` resolver + `agents/supervisor.py:597` rewire. 3-path order: HTTP `?bbox=` override → `data/vision_regions.json` `_minimap_<mode>` key (NEW) → hardcoded 1920×1080 fallback. Persisted entry shape validated (4 ints, `r>l`, `b>t`); malformed values silently fall back. Behavior byte-identical to pre-FU01 until calibration entries are added. 19 new tests under `tests/fu01_minimap/`. Phase 3 supervisor restart pending to pick it up live.
12. 🚫 **FU03** clipboard helper — superseded by FU04 same-day approval (Personal keys don't expire; daily-renewal helper no longer needed).
13. 🟡 Vision regions calibration — tune `data/vision_regions.json` bboxes. Blocked on live game.
14. 🟡 DS calibration pipeline — blocked on rewind_history.db staleness (last entry Dec 2025).
15. 🟡 gamepc_boot.ps1 hardening — add `RC-WatcherHealthPublisher-GamePC` + `RC-BridgeWatcher-GamePC`.
16. 🟡 Bridge Watcher acceptance-criteria — need 50+ real-traffic samples.
17. ✅ **Mode-flicker chain + DS resolver + LCU agent fixes** — shipped s153/s154/s155/s156/s157/s158 (2026-05-10). s153 (`96bf4ee`) + s157 (`0e3d87a`) mirror the s150 LCU lobby/CS pre-flip into both HTTP `/api/state` and WS push paths via shared `resolve_mode_key` + `apply_preflip_mirror` helpers. s154 (`3a3bf58`) fallback for LCU CS-session missing `gameData.queue.id` during BAN_PICK — uses `/lol-gameflow/v1/session`. s155 (`5c39b9b`) `lock_pick` race-tolerance (already-locked → success) + dashboard reply surfacing via `lcuPollResult`. s156 (`6c4a940`) DS server display-name reverse map (covers Kai'Sa/Kaisa, Wukong/MonkeyKing, Renata Glasc/Renata, apostrophe family) + new `resolve_inventory` that drops trinkets/consumables. s158 (`bd0c88e`) `?dbg=1` mode/view transition log. 15 new tests, live-verified.
18. 🟡 **Active Match view** — steps 1–4 shipped; step 5 pending. Step 1 scaffold (s159 `3f72795` / s160 `57886e1` / s161 `8a857c4`). Step 2 + 3 shipped s170 (`85461e2`). ✅ **Step 4 shipped s171** (`73b66ec`): static SR/ARAM map base from `/data/ddragon/16.8.1/img/map/*` + champion-dot canvas overlay polled from `/api/vision-state` at 500ms + MIA badges when `missing_for_s > 12` + JG-gank warning band when enemy MIA > 20s in ENEMY_JUNGLE/RIVER + view-gated polling so opt-out operators don't burn CPU. **Step 5 pending:** zen-lock in-game + RIGHT NOW fold + bridge-pending → dev-panel button + fleet view removal.
19. ✅ **Pre-Game Lobby v2 redesign + handleChampSelect bug fix** — shipped s162 (`5c019f9`, 2026-05-10). Phase 3 step 1 of the 14-fixture flow. QUEUE / Mains tabs / Party / My Top 8 panels rebuilt; `handleChampSelect` ReferenceError chain closed via `handleLcuEnvelope` wrapper in `main.js`; 5 live menu views removed; 46 fixtures archived; sim banner → corner pill; EventSource stubbed in sim mode.
20. ✅ **Pre-Game Lobby v3 polish + conflict UI + AVG/Match grade** — shipped s163 (`e316291`, 2026-05-10). Phase 3 step 1 LOCKED for both solo + multi-member states (placeholder-driven; no separate flow_02 fixture pass needed). Visual-hierarchy audit subagent ran mid-session; 5 must-fix items shipped (drop shadow, font floors, lane gap, "live" hide, title alignment). Self-row mirror + Primary-lane CONFLICT detection + AVG 5 grade letter (S→D color-coded, KP%-style 5-tier band) + Mains 2x2 Overall + 2x3 AVG/Match (Gold dropped, Vision moved up) + League captain-icon-crown PNG + Phosphor copy SVG + LVL ### : Unranked fallback + JGL→JNG / SUPP→SUP role normalizer. Page fits 1080-viewport without scrollbar. 913 ins / 181 del across 7 files.
21. ✅ **Phase 3 step 2 + step 3 — Champ Select view scaffold + Pick&Ban panel + trade popup** — shipped s164 (`c0e6043`, 2026-05-10). Step 2 (`flow_02_lobby_with_others`) was a renaming pass; step 3 built the new top-level `view-champ-select` page (3-col grid: Allies + Pick&Ban left, My Pick + Builds center, Enemies right). Auto-promotes on `?cs=1` + `phase=ChampSelect`. Pick&Ban Recommendations panel with 3 source rows + 4-button mood toggle + quick-select with lock-after-click (gated to skip BAN_PICK so user can't accidentally ban their own pick). Trade popup: SWAP/TRADE header + CHAMPION/Nth-PICK/ROLE buttons appended to `<html>` to bypass body's `zoom:1.33` with matching `transform:scale`. Enemy "(guess)" tag + cyan countdown timer + 2px round-border (red ban / gold pick). 1986 ins / 4 del across 10 files (3 new).
22. ✅ **Phase 3 step 3 follow-ups — central panel + enemies redesign for ALL game modes** — shipped s165 (`91a42e1`, 2026-05-10). New `_csvDetectMode(cs)` → `sr|aram|arena|brawl` from queue_id + is_aram/is_brawl flags; `section.dataset.csMode` stamped so CSS branches via `[data-cs-mode]`. SR: 3-variant Build Chooser populated (was empty placeholder). ARAM: 5-cell horizontal Bench under My Pick + ARAM Build Chooser; enemy lock/timer reflowed to right edge (was clipping names from SR's absolute-50% layout). Arena: 2-cell allies, central pane = Duo+Augments (3 slots silver/gold/prismatic + augment options wired to `set_augment_intent`), enemies = 3 sub-team cards (TEAM 2/3/4 × 2 champs each). Brawl: 5v5 no roles/bans, Brawl Build Chooser. Pick&Ban hidden on non-SR via CSS rules; grid reflowed. Pick&Ban + Allies panels UNTOUCHED (LOCKED per operator). 3 new fixtures (flow_03b_aram_select / flow_03c_arena_select / flow_03d_brawl_select). 1112 ins / 34 del across 7 files.
23. ✅ **Phase B — LCU agent handlers + champ-select state population** — shipped s166 (2026-05-10). 5 new command handlers in `tools/gamepc_lcu_agent.py` (set_ban_intent / set_pick_intent / request_position_swap / request_pick_order_swap; set_augment_intent stub pending live `/lol-cherry/v1/*` discovery) + new champ-select state fields (active_round / is_brawl / position_swaps / pick_order_swaps / arena_teams / augments scaffold) + per-player summoners on `_team_picks`. 30 new tests under `tests/phase_b_champ_select/` (665 total green).
24. ✅ **Phase 3 step 4 — Loading Screen view scaffold** — shipped s166 (2026-05-10). New top-level `view-loading`, mode-conditional team panels, `?ld=1` opt-in + `phase=GameStart` auto-promote. Briefing card removed before commit per operator. New files: `web/js/panels/loading.js`, `web/css/panels/loading_view.css`, `data/sim/flow_04_loading_screen.json`.
25. ✅ **Backend sweep (s167, 2026-05-11, `1522b90`)** — per `NEXT_SESSION_PLAN_2026-05-10.md`. UI paused; five backend ships in one commit: (P1a) DS per-level DPS curve helper `compute_dps_curve()` 1/6/11/16/18 + `DpsCurvePoint` + 12 tests, ENGINE 0.60.0 → 0.61.0 (`agents/daemon_slayer/dps.py`); (P2) `scripts/rewind_catchup.py` Match-V5 → rewind_history.db + `core/riot_api.get_recent_matches` pagination params (`start`/`startTime`/`endTime`/`queue`/`type`), auto-rotates PUUID via Account-V1 when DB PUUID stale (2846 → 2851 rows); (P8) LCU mastery cache in `tools/gamepc_lcu_agent.py` via `/lol-collections/v1/inventories/<sid>/champion-mastery`, 5-min TTL, surfaced at `state["lcu"]["mastery"]` on Lobby/CS/InGame phases + 10 tests; (P9) `scripts/audit_api_surface.py` + `docs/API_SURFACE_AUDIT.md` (89 internal / 70 LCU / 6 web / 2 LiveClient endpoints); (P7) `scripts/prune_synthetic_matches.py` removed 56 dev-test rows from `match_history.db`. Full sweep: 601 + 949 + 40 green.
26. 🟡 **Deferred post-s168:** (a) ✅ **resolved** — Game-PC `gamepc_lcu_agent.py` redeployed s168 (2026-05-11) via one-shot `http.server` mechanism; s167 endpoint was stale (`/lol-collections/v1/inventories/<sid>/champion-mastery` → 404 on current LCU) — replaced with `/lol-champion-mastery/v1/local-player/champion-mastery`; mastery state-shape was double-nested (`state["lcu"]["lcu"]["mastery"]`) — flattened to top-level `state["mastery"]` so Legion's wrap produces correct `state["lcu"]["mastery"]`. Live-verified at Lobby phase, 40 mastery entries, summoner 3911621734024704. (b) **P6** Sonnet/Haiku → Claude Desktop API key — still needs operator clarification on which key file (current path: `coaches/_base_coach.py:read_api_key()` reads `API-Key-Claude.txt` then `$ANTHROPIC_API_KEY` env); (c) **P1b** Arena augment registry expansion — needs `as_pct` overlay channel (architectural, not 1-hr); (d) **P5** Default DS build #4 — waits on richer rewind data (currently sparse: 5 games since Dec 2025); (e) **P3/P4** History season-WR + Replay tab — UI work, deferred per operator; (f) ✅ **resolved s170** — RC-LCU scheduled-task action path fixed via cross-Claude bridge dispatch (`task-454fde72f190`, Game-PC Claude resolved 63s round-trip). Action now uses absolute python path `C:/Users/Administrator/AppData/Local/Python/pythoncore-3.14-64/python.exe`; running agent (pid 15480) deliberately not restarted — fix applies on next reboot.

27. ✅ **LCU wiring punch list — pre-game lobby + champ-select + DS active match** — shipped s170 (`85461e2`, 2026-05-11). 6 of 7 items closed in one session per operator's "what's needed to finish LCU wiring" audit: (#1) `state.lcu.lobby` forwarder w/ `members[]` + `local_member` + `is_leader` + `party_type` + `queue_name` + `search_state` + `position_preferences`; is_self via summoner-id match; name enrichment via `/lol-summoner/v1/summoners/{sid}`; 31 tests. (#2) `coach_integration/enemy_stats.py` `compute_enemy_stats(mode, level, …)` mode + level scaled curve; 27 tests. (#3) Active Match per-tick DS rerank + CommunityDragon icons. (#4) `GET /api/champ-select/pickban-recs` route querying `rewind_history.db`; 17 tests; 33ms live response with real WR + ban suggestions. (#5) RC-LCU scheduled-task fix via bridge. (#7) Top 8 dummy purge. 788 total green (was 719). **Pending #6:** Cherry/Arena `set_augment_intent` endpoint discovery, blocked on live Arena lobby.
29. ✅ **s171.8 view-router + cache-bust unification** — 6 commits 2026-05-12 (`eba274b`→`876fd01`). (a) 4 ruff fixes (CI unblock + real F601 dup-key bug in `gamepc_lcu_agent.py`). (b) FU01 audit-6 ship: `parse_http_override` validates bbox bounds. (c) CI Node.js 24 bump. (d) Loading-view sticky-guard inference (CS→null→loading) + dodge clear in `web/js/main.js:_viewAutoDerive`. (e) Phase 3 mode-detector LCU phase overlay in `agents/agent2_backend/file_ingest._compute_effective_mode` — warm-Agent-7 prime fires on champ_select/game transitions even when Legion can't see Game-PC LCU lockfile. (f) **Unified asset-hash + auto-reload** in `dashboard/_static.compute_asset_hash` + `dashboard/routes_state._serve_ui_version` — closes the s164→s171.7 cache staleness where two divergent file lists left operator's browser serving pre-s171.7 `champ_select.js` (opt-in gate) for ~10 days. Build-variant persistence shipped alongside (`_csvBuildVariantsFor` + `_csvSaveChoice` → `rc-ingame-build-<champion>` localStorage key, shared with `item_build.js`). 9 file_ingest tests + 289 phase2/phase8/snapshot tests green. (g) **Docs+tests backfill — overnight headless brief** (5 commits `a43981b`→`f3ff7dd`, 2026-05-12 02:25→02:36): `dashboard/view_router_state.py` Python mirror of `_viewAutoDerive` + 27 tests in `tests/test_view_router_state.py`; ROADMAP synced; ADR-008 (`docs/adr/ADR-008-unified-asset-hash.md`) captures the two-allow-list drift lesson; WAKEUP_NOTES rotated (s170 → `docs/history_notes.md`). All 5 commits CI-green on first push.

30. ✅ **s173 anti-drift audit run** — 3 commits 2026-05-12 (`3096e8c` + `907543f` + `139472d`). Daytime ADR-008 follow-up sweeping 10 candidate drift pairs. **Two unifications shipped:** (a) `agents/supervisor._file_post_game_summary` candidates list deferred to new `dashboard._state_builder.MODE_FILES` (deduped tuple from `MODE_TO_FILE.values()` via `dict.fromkeys()`) — closes a third independent enumeration of the coaching JSON file set; (b) `web/js/panels/champ_select.js:1223` legacy `dsMode` ternary deferred to `_csvDsModeFor` — closes the second of two mode→DS-name implementations inside the same module. **Eight hunts skipped/deferred** with rationale documented inline in WAKEUP_NOTES: 1/4/9 already-unified, 6/8 different intents (not drift), 3 touches frozen file, 7 doc-sync not structural, 10 multi-language scope. **Three open audit findings carried forward** for future sessions: frozen-file list duplication, ENGINE_VERSION doc drift, multi-table champion alias unification.

28. ✅ **s171 LCU + DS + UX bug crawl** — 8 commits 2026-05-12 (`73b66ec`→`d12a330`). (a) **`lcuCmd`/`lcuPollResult` restored to `main.js` module scope** — 22 callsites had been silently throwing ReferenceError since the s133 Phase 3.1 ESM split (38ac760); all lobby buttons (Find Match / Cancel / queue-change / party toggle) now work. (b) **6 new lobby LCU handlers** (set_party_type / set_position_prefs / invite_player / create_practice_tool / promote_leader / kick_member) + **5 P&B commands added to dashboard allowlist** that were silently 400-rejected since s166 (set_pick_intent / set_ban_intent / request_position_swap / request_pick_order_swap / set_augment_intent). (c) **New champ-select view ships** — lock button on My Pick card, DS-driven build chooser (replaces hardcoded variants), `champSelectViewEnabled()` flipped opt-in→opt-out. (d) **Active-match view** — opt-in→opt-out, `coach.immediate` now renders as RIGHT NOW (was being dropped), freshness guard clears stale prompts between games, **step 4 map overlay** (static SR/ARAM + champion-dot canvas overlay + MIA badges + JG-gank warning). (e) **Enemy-aware DS ranking** (`core/enemy_aware_stats.py`) — `/api/ds-preview` now computes target_armor/_mr/_max_hp from liveclient `allPlayers[i].items[]` via ddragon_items.json; rankings shift as enemies build defense (BoRK +101 vs synthetic 150 armor). (f) **Defensive-pick ranker** (`core/defensive_picks.py`) — classifies enemy threat profile (AD/AP/burst/tank) + recommends from 22-item curated catalog (Maw/Sterak/GA/Plated/Randuin/etc.) when `burst≥5 OR ad≥7 OR ap≥7`. (g) **Top 8 server-side persistence** (`/api/top8`) — moved from localStorage (origin-dependent, wiped on cache-clear) to `data/top8_list.json`. (h) **`/api/mains` backend** — top-N main champions joined from `rewind_history.db.participants` + LCU mastery overlay. (i) **`my_completed` derivation fix** — was reading non-existent `myTeam[i].completed`, now walks `sess.actions[][]`; `local_cell` surfaced. (j) **championPickIntent hover fallback** + **auto_accept default flipped True→False**. (k) **Post-CS view-routing sticky guard** (`_VIEW.gameStarted`) rides through transient phase=null/Lobby during CS→loading→game flip.

Full open work + future: `ROADMAP.md` + `BACKLOG.md`. Completed work: `docs/_archive/CHANGELOG.md`.
