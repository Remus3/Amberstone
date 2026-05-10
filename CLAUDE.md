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
| **Game-PC** | `gamepc-rc` / `100.95.66.128` | `192.168.8.237` | Runs League; Edge fullscreen on secondary display (1920×1280, 100% scale) |
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

`web_dashboard.py` at `:8888` HTTPS. Key endpoints: `/`, `/api/state`, `/api/health/all`, `/api/bridge/pending`, `/api/input`, `/api/command`, `/api/ds-preview`, `/metrics`. Viewed in Edge fullscreen on Game-PC secondary (1920×1280, 100% scale). Cert via `tools/regen_rc_cert.ps1`. Each machine has its own Anthropic API key (`riot-commander-legion`, `riot-commander-gamepc`, `riot-commander-peer`).

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
11. 🟡 **FU01** minimap-locate — replace hardcoded bbox in `agents/supervisor.py:597` with 3-path resolver (override → PersistedSettings → hardcoded fallback). Ticket at `Desktop/Tickets/RC_TICKET_FU01_minimap_locate.md`. Independent.
12. 🚫 **FU03** clipboard helper — superseded by FU04 same-day approval (Personal keys don't expire; daily-renewal helper no longer needed).
13. 🟡 Vision regions calibration — tune `data/vision_regions.json` bboxes. Blocked on live game.
14. 🟡 DS calibration pipeline — blocked on rewind_history.db staleness (last entry Dec 2025).
15. 🟡 gamepc_boot.ps1 hardening — add `RC-WatcherHealthPublisher-GamePC` + `RC-BridgeWatcher-GamePC`.
16. 🟡 Bridge Watcher acceptance-criteria — need 50+ real-traffic samples.
17. ✅ **Mode-flicker chain + DS resolver + LCU agent fixes** — shipped s153/s154/s155/s156/s157/s158 (2026-05-10). s153 (`96bf4ee`) + s157 (`0e3d87a`) mirror the s150 LCU lobby/CS pre-flip into both HTTP `/api/state` and WS push paths via shared `resolve_mode_key` + `apply_preflip_mirror` helpers. s154 (`3a3bf58`) fallback for LCU CS-session missing `gameData.queue.id` during BAN_PICK — uses `/lol-gameflow/v1/session`. s155 (`5c39b9b`) `lock_pick` race-tolerance (already-locked → success) + dashboard reply surfacing via `lcuPollResult`. s156 (`6c4a940`) DS server display-name reverse map (covers Kai'Sa/Kaisa, Wukong/MonkeyKing, Renata Glasc/Renata, apostrophe family) + new `resolve_inventory` that drops trinkets/consumables. s158 (`bd0c88e`) `?dbg=1` mode/view transition log. 15 new tests, live-verified.
18. 🟡 **Active Match view** — step 1 scaffold shipped (s159 `3f72795` + s160 `57886e1` + s161 `8a857c4`): new view ID + 2-col grid (CALL stacked over BUILD left, MAP full-height right) + `?am=1` opt-in auto-promote on in-game modes + ZEN/DEV pill removal + tooltip font 14→17px. **Steps 2–5 pending** per WAKEUP_NOTES s153–s161: (2) DS icons + owned-as-text + per-tick rerank, (3) enemy-comp threading into target_armor/mr/bonus_hp, (4) static SR/ARAM/Arena/Brawl map + ZOI/threat/gank/MIA overlay, (5) zen-lock in-game + RIGHT NOW fold + bridge-pending → dev-panel button + fleet view removal.

Full open work + future: `ROADMAP.md` + `BACKLOG.md`. Completed work: `docs/_archive/CHANGELOG.md`.
