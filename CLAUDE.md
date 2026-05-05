# Riot Commander — Agent Context

Live League / TFT coaching dashboard. Reads Riot Live Client API,
calls Claude Haiku for fast coaching and Sonnet for vision, writes JSON to
`data/`, and serves a `:8888` HTTPS dashboard viewed in Edge fullscreen on Game-PC's secondary display.
RC is tkinter-free (T2 #6/#8, 2026-05-01); the Daemon Slayer build engine (`:8893`) computes real DPS math per champion to back Haiku's item advice.

## Topology (post-2026-04-19 migration; tailnet primary since s29-s30, 2026-05-02)

| Machine | Tailnet name / IP | LAN IP (fallback) | Display | Role |
|---|---|---|---|---|
| **Legion** | `legion-rc` / `100.70.22.55` | `192.168.8.230` | 1 monitor | Runs RC (`main.py`), supervisor, vision server, web dashboard |
| **Game-PC** | `gamepc-rc` / `100.95.66.128` | `192.168.8.237` | 2 monitors — primary TV (the game) + secondary iPad-as-monitor over Duet (1920×1280 native, 100% OS scale, no touch, no apps; the iPad is just a wireless display panel) | Runs League client; exposes Riot Live Client API on `:2999` (read by Legion). Edge runs fullscreen on the secondary display showing the RC dashboard |
| **Peer** (cross-Claude peer) | `peer-host` / `<peer-tailnet-ip>` | — | — | Separate Peer-VIP project; reachable via `core/bridge.send()` for RC↔Peer message passing |

All three nodes live in tailnet `tailc150de.ts.net` under `<operator-email>`. **Prefer tailnet hostnames** in new code (cert SAN covers `legion-rc`, `100.70.22.55`, and the FQDN). LAN IPs still resolve and are kept as fallback / for legacy probes.

Vision is **in-process on Legion** at `127.0.0.1:8889` — no Moon-PC anymore.
Historic LAN refs (`192.168.8.230:8889` from RC code) were migrated to loopback.

## Paths

- Project root: `C:\Riot Commander\`
- Python: `C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe`
- API key: `C:\Riot Commander\API-Key-Claude.txt` (gitignored)
- Health: `C:\Riot Commander\ops\runtime\health.json` (truth for current PID/mode)
- Logs: `C:\Riot Commander\logs\YYYY-MM-DD.log`

## Hard rules

- **Always `py_compile` before restart.** Syntax errors crash silently under `pythonw.exe`.
- **Atomic writes only:** `tmp.write_text(...); tmp.replace(target)`. Overlays poll mid-write.
- **Never `Stop-Process`.** Hangs MCP pipe. Use `taskkill /F /PID` if hard kill needed.
- **Restart via `restart_trigger.txt`** (write any non-empty content; supervisor clears + restarts).
- **windows-mcp is unreliable** — prefer Filesystem + Python scripts.
- **`SCRIPT_DIR` in `app/__init__.py` MUST be `Path(__file__).parent.parent`** (package layout).
- **Frozen files** (do not modify without explicit user approval — these are load-bearing
  and regression-prone):
  `main.py`, `core/log_setup.py`, `core/moon_proxy.py`, `lcu/lcu_client.py`,
  `core/game_snapshot.py`, `ops/rc_dev_runtime.py`, `ops/rc_supervisor.py`,
  `app/__init__.py`, `app/_loop.py`, `app/_health_monitor.py`, `app/_remediation.py`,
  `app/_state_authority.py`, `app/_overlay_manager.py`, `app/_game_lifecycle.py`,
  `tools/bridge_watcher.py`, `tools/bridge_watcher_classify.py`,
  `tools/bridge_watcher_actions.py`, `tools/bridge_watcher_action_prompt.md`,
  `tools/bridge_watcher_history.py`, `tools/bridge_watcher_install.ps1`,
  `tools/bridge_watcher_hook.ps1`, `tools/bridge_watcher_config.json`,
  `tools/bridge_post_result.py`, `tools/bridge_pull_tasks.py`,
  `tools/process-bridge-tasks.md`, `tools/diagnose.md`, `tools/caveman.md`,
  `dashboard/routes_bridge_pending.py`, `ops/RC-BridgeWatcher.xml`.
- **State assumptions explicitly before coding.** When a request is ambiguous
  or could be interpreted multiple ways, surface the interpretation you're
  acting on in one short sentence before doing the work. Borrowed from
  Karpathy's LLM-coding-pitfalls observations (forrestchang/andrej-karpathy-skills);
  cheap insurance against the "build the wrong thing fast" failure mode.

## Restart workflow

```
echo restart > restart_trigger.txt   # supervisor picks up within 1s, restarts in ~5s
```
Verify after restart: read `ops/runtime/health.json`, confirm new `pid`, `alive=true`,
`last_reload_ok=true`. Hard fallback: `taskkill /F /PID <pid>` then `restart.bat`.

## Session workflow (2026-05-01)

Scoped sessions, not long-lived ones — each focused task is one session.
- **End** of each task: commit + update `WAKEUP_NOTES.md` with a short hand-off + save any non-obvious learning to memory.
- **Start** of each task: `/clear`, bootstrap from CLAUDE.md + MEMORY.md + git log + WAKEUP_NOTES.
- **Auto-compact at 75%** is a safety net only — don't rely on it as the primary continuity mechanism (it's lossy).
- `/clear` between Tier items, between coding/reviewing modes, between focus area switches.
- Continue without `/clear` only when actively debugging across files where compaction would lose mid-built understanding.

## Scheduled tasks (Legion)

- `RC-Supervisor` — at logon, Administrator, HIGHEST. Runs `pythonw.exe ops/rc_supervisor.py --config ops/rc_config.json`.
- `RC-VisionServer` — at system startup, SYSTEM, HIGHEST. Runs `python.exe moon_vision_server.py`.

Supervisor has a PID lock — duplicate launches abort cleanly.

## Web dashboard (replaces tkinter overlays — RC is headless)

`web_dashboard.py` (root) — daemon thread launched from `main.py` after MetricsCache.
- GET `/`, `/api/state`, `/api/health`, `/api/health/all`, `/manifest.json`, `/icon.svg`
- GET `/api/bridge/pending` — bridge_watcher escalation queue (read by Bridge Pending sub-page)
- POST `/api/bridge/pending/<id>/{accept,defer,dismiss}` — operator triage (in `dashboard/routes_bridge_pending_actions.py`; sibling of the frozen GET module)
- POST `/api/input` `{text}` — writes to `coaching_data.json.pregame`
- POST `/api/command` `{command: "force_vision"|"refresh"|"clear_pregame"}`
Viewed in Edge fullscreen on Game-PC's secondary display (1920×1280 native, 100% OS scale → 1920×1280 effective CSS viewport). HTTPS with mkcert-signed cert (SAN covers `legion-rc`, `100.70.22.55`, `legion-rc.tailc150de.ts.net`, `192.168.8.230`, `localhost`, `127.0.0.1`); Game-PC trusts the root CA, so `https://legion-rc:8888` resolves cleanly without flags. Use `tools/regen_rc_cert.ps1` to refresh with the canonical SAN list.

## Headless mode

Tkinter overlays are gone (T2 #6, 2026-05-01). T2 #8 C1 then dropped `tk.Tk()`
itself — game polling re-arms via `app.scheduler.schedule(ms, fn)` on an
asyncio event loop owned by `app/_loop.py:AppLoop`. `app.run()` blocks on
`loop.run_forever()`; `_quit()` calls `scheduler.stop()`. `schedule()` is
thread-safe (uses `call_soon_threadsafe` from non-loop threads). The web
dashboard at :8888 is the only UI. `app.game_windows` and `app.client_windows`
are still empty dicts kept only so `.get(...)` reads on removed paths still
return None safely.

## Vision pipeline (relay-based)

RC on Legion can't see Game-PC's screen directly. The pipeline:

1. **Game-PC** runs `tools/gamepc_screen_agent.py` — `PIL.ImageGrab` every 2s,
   POSTs to `http://legion-rc:8889/upload-frame` (auth: `X-RC-Token`; LAN IP `192.168.8.230` still resolves).
2. **Vision server** caches the latest frame in memory (`_latest_frame`).
3. **Coaches on Legion** call `modes.shared_vision._capture_screen()`, which
   GETs `http://127.0.0.1:8889/latest-frame` and returns the cached b64.
4. Coaches submit the frame to `/vision` (Sonnet) or `/ocr` (Tesseract).

Tesseract installed at `C:\Program Files\Tesseract-OCR\tesseract.exe`
(via winget; not in PATH — vision server pins explicitly via `_TESSERACT_DEFAULT`).

**Game-PC deploy** (one-line bootstrap, idempotent):
```
iex (iwr https://legion-rc:8888/agent/gamepc_boot.ps1).Content
```
Pulls all 5 agents (`gamepc_screen_agent.py`, `gamepc_lcu_agent.py`,
`gamepc_liveclient_relay.py`, `gamepc_mcp_server.py`, `gamepc_hotkey_listener.py`)
plus support scripts (`start_gamepc_claude.ps1`) and the
`process-bridge-tasks.md` slash-command (deployed to `~/.claude/commands/`
for the bridge Claude session) from Legion's `/agent/` allowlist, kills
any zombie listeners, ensures the inbound firewall rule for `:8892`
(MCP), starts whatever isn't healthy, and installs scheduled tasks
(`RC-LCU`, `RC-LiveClientRelay`, `RC-MCP-Server`, `RC-HotkeyListener`,
`RC-GamePCBoot`, plus `RC-ScreenAgent-*` variants) for boot persistence.
See `tools/GAMEPC_CLAUDE.md` for the agent map.

TFT vision (`tft/tft_vision_reader.py`, `tft/tft_ocr_reader.py`) was migrated
to the same `/latest-frame` relay path; both call `modes.shared_vision._capture_screen`
and crop client-side. The only remaining `ImageGrab` callers in the production tree
are Game-PC-side tools (`tools/gamepc_screen_agent.py`, `tools/gamepc_mcp_server.py`,
`ops/rc_file_bridge.py` — all expected, since Game-PC has the screen).

## Game-PC agents (5 processes)

All deployed via one-line `iex (iwr https://legion-rc:8888/agent/gamepc_boot.ps1).Content`.
At-logon scheduled tasks: `RC-LCU`, `RC-LiveClientRelay`, `RC-MCP-Server`, `RC-HotkeyListener`, `RC-ScreenAgent-*`.

| Agent | Port | What it does | Sends to Legion |
|---|---|---|---|
| `gamepc_screen_agent.py` | — | PIL `ImageGrab` every 2s | POST `:8889/upload-frame` (X-RC-Token) |
| `gamepc_lcu_agent.py` | — | Polls Riot LCU `:2999`; full `myTeam`/`theirTeam` during ChampSelect | POST Legion `/api/lcu-state`; also receives `/api/lcu-cmd` (rune writes, accept) |
| `gamepc_liveclient_relay.py` | — | Polls Live Client API `:2999` during game | POST Legion `/api/liveclient` (full game JSON) |
| `gamepc_mcp_server.py` | **:8892** | MCP server — exposes filesystem + PowerShell to Legion Claude for cross-machine ops | Inbound from Legion; responses via MCP protocol |
| `gamepc_hotkey_listener.py` | — | Win32 hotkey hook | POST Legion `/api/hotkey` on trigger |

Legion's Claude session uses the Game-PC MCP server tools (`mcp__gamepc__*`) for all cross-machine file/command operations. When the MCP server is down post-reboot, start it manually before attempting any remote commands.

## Daemon Slayer build engine

Local DPS-math service on `:8893`. Computes actual damage-per-second for any champion × item × target combination using real stat math — no API cost per query.

### Module map (`agents/daemon_slayer/`)

| File | Purpose |
|---|---|
| `__init__.py` | `ENGINE_VERSION` constant (currently **0.58.0**); `start_server()` entry point |
| `server.py` | Flask HTTP; `/rank`, `/dps`, `/health` endpoints |
| `effects.py` | `ItemEffect` registry — **547 entries, DDragon purchasable coverage COMPLETE** |
| `dps.py` | `CallContext` dataclass + `compute_dps()` — stat walk, armor/MR pen, on-hit, periodic procs, damage amps |
| `stat_walk.py` | Champion base-stat + per-level growth interpolation |
| `beam_search.py` | `rank_for()` — beam search over item combinations; returns ranked `DpsRow` list with `delta_dps` + `gold` |
| `data_loader.py` | Versioned `DataSnapshot` loader; reads `data/daemon_slayer/<patch>/` |
| `tests/` | **911 tests passing** |

### Key data types

- **`ItemEffect`** — frozen dataclass: `periodics`, `damage_amp_pct`, `armor_reduction_pct`, `mr_reduction_pct`, `giant_slayer_*`, `unique_passive_key`, `defensive_only` flag
- **`PeriodicProc`** — `every_n_attacks` or `every_n_seconds`; `bonus_damage` is `(CallContext) -> float`
- **`CallContext`** — `base_ad, bonus_ad, level, ap, target_max_hp, caster_max_hp, caster_bonus_hp, targets_in_rotation, caster_max_mp, caster_bonus_armor, caster_lethality`
- **`unique_passive_key`** — prevents double-counting when multiple items share named passives (e.g. `"spellblade"`, `"immolate"`)

### DS-before-Haiku pattern

DS `rank_for()` must run **before** `messages.create()` so Haiku sees per-champion DPS-ranked picks in the user turn rather than generic hardcoded rules. Reuse `_ds_rows` for the post-Haiku UI write — don't call `rank_for()` twice.

```python
_ds_rows = None
_ds_picks_str = "unavailable"
try:
    _ds_rows = _ds_client.rank_for(champion=champ, level=level, item_ids=owned_ids, mode="ARAM", top=5)
    _ds_picks_str = " > ".join(f"{r.item_name}(+{r.delta_dps:.0f}dps,{r.gold}g)" for r in _ds_rows) if _ds_rows else "none"
except Exception as e:
    logger.debug("daemon_slayer pre-call: %s", e)
# ... user turn includes DS top items line ...
# post-Haiku: reuse _ds_rows for cur["daemon_slayer_picks"] — no second engine call
```

### Coach integration status

| Coach | DS call | Position | Pre-DS rules pruned |
|---|---|---|---|
| `coaches/aram_coach.py` | ✅ | **Before Haiku** | ✅ BUILD COMMITMENT + DAMAGE-TYPE + MUTUAL EXCLUSIONS removed; −37% system prompt |
| `coaches/arena_coach.py` | ✅ post-Haiku | ⚠️ needs move to pre-Haiku | (no hardcoded item lists to prune) |
| `coaches/brawl_coach.py` | ✅ post-Haiku | ⚠️ needs move to pre-Haiku | (no hardcoded item lists to prune) |
| `core/coach_integration.py` (SR) | ❌ **not wired** | — | (no DS feedback to Haiku at all) |
| TFT | N/A | N/A | N/A |

### Deferred items (8 — genuinely blocked)

All 547 DDragon purchasable items are in the registry. These 8 remain `defensive_only` or unmodeled due to schema limits:
1. Ability/ult-cast triggers (Lightning Braid, Malignance, Night Harvester SR, Innervating Locket, Fiendhunter Bolts) — blocked on ability-frequency data
2. Hellfire Hatchet Char — 3-way scaling `level × hp_diff × lethality`
3. Kinkou Jitte — directional weakpoint; positional geometry unmodelable
4. Mejai's Arena mirror — no Arena ID in DDragon (3041 SR only)

## Architecture map

```
main.py                   entry: logging, key, DevRuntime, MetricsCache, web_dashboard, OverlayApp
overlay.py                shim → app/__init__.py
app/                      OverlayApp + decomposed managers (ARCH-001 complete)
  __init__.py             OverlayApp orchestrator (~300L, Tk-free since T2 #8)
  _loop.py                AppLoop — asyncio scheduler (T2 #8 C1, replaces tk.Tk())
  _health_monitor.py      heartbeat
  _remediation.py         restart_game_poll, rebuild_panel_*
  _state_authority.py     envelope + win-pct
  _overlay_manager.py     dashboard-only shell (Tk windows removed in T2 #6)
  _game_lifecycle.py      game start/end, worker dispatch
coaches/                  BaseCoach (ARCH-002) + aram/arena/brawl/sr/tft variants
  _base_coach.py          shared poll/vision loops, debounce, hotkey reg
  aram_coach.py           ARAM coach — DS-before-Haiku ✅, pre-DS rules pruned ✅
  arena_coach.py          Arena coach — DS wired post-Haiku (move pending)
  brawl_coach.py          Brawl coach — DS wired post-Haiku (move pending)
  coach_integration.py    SR coach — DS not wired (highest-value remaining gap)
modes/                    shared_vision (relay screen-grab client used by coaches)
                          [aram/arena/brawl_overlay archived in T2 #8 C2 — _archive/2026-05-01-audit/modes/]
core/                     game_snapshot, sr_aram_worker, tft_worker, theme, hotkeys, log_setup,
                          moon_proxy (vision client), metrics_cache, lcu integration helpers,
                          prom_metrics (T3 #12 — Prometheus exposition, zero-dep),
                          daemon_slayer_client (HTTP client to :8893), daemon_slayer_resolver
agents/                   Phase 3 supervisor (:8890/:8891) + Daemon Slayer engine
  daemon_slayer/          DPS build engine — effects.py (547 items), dps.py, beam_search.py,
                          stat_walk.py, data_loader.py, server.py; 911 tests, ENGINE_VERSION 0.58.0
tft/                      TFT engine (tft_state_reader, tft_live_analysis, tft_coach_engine, tft_data, tft_pbe_*)
                          [tft_overlay + comp_control archived in T2 #8 C2]
ui/                       (empty — entire package archived in T2 #8 C2; see _archive/2026-05-01-audit/ui/)
ops/                      rc_supervisor, rc_self_monitor, rc_dev_runtime, runtime/health.json
lcu/                      LCU client, auto-accept, rune writer, postgame collector
data/                     coaching artifacts (atomic-written, polled by overlays + dashboard)
  daemon_slayer/          versioned patch snapshots (champions.json, items.json, scenarios.json)
web_dashboard.py          :8888 HTTPS dashboard (Edge fullscreen on Game-PC's secondary display)
moon_vision_server.py     :8889 local vision server (Sonnet screenshots)
```

## Mode detection

`game_reader.py._process_game()` → `core/game_snapshot.py` → mode strings.
ARAM Mayhem internal name: `KIWI` → mapped to `MODE_ARAM`.

## Where to find current state (don't trust memory — check files)

- Live PID + mode + health: `ops/runtime/health.json`
- Current game state: `data/{aram,arena,brawl,tft}_coaching_data.json` (or root `coaching_data.json` for SR/client)
- Recent activity: `logs/YYYY-MM-DD.log` (rotating)
- Status ledger: `AUDIT_PHASE_2_STATUS.md` (root) — superseded sections marked
- Audit findings (historical): `docs/AUDIT_HANDOFF_OPUS.md`, `docs/AUDIT_OPUS_REPORT_2026-04-18.md`
- `docs/PROJECT_STATE.md` is **stale** — banner at top points elsewhere

## Useful commands

```bash
# Health snapshot
python -c "import json; print(json.dumps(json.loads(open(r'ops/runtime/health.json').read()), indent=2))"

# Tail today's log
python -c "import time; from pathlib import Path; \
  print(Path('logs/'+time.strftime('%Y-%m-%d')+'.log').read_text(encoding='utf-8',errors='replace')[-4000:])"

# Restart RC
echo manual > restart_trigger.txt

# Probe vision server
curl http://127.0.0.1:8889/health

# Probe web dashboard
curl http://127.0.0.1:8888/api/state

# Prometheus metrics (T3 #12 — text/plain exposition for any scraper)
curl -k https://127.0.0.1:8888/metrics

# Data pipeline (patch day)
cd scripts && python data_pipeline.py meta          # check version
python data_pipeline.py aram_builds                  # ARAM tier refresh
python data_pipeline.py all                          # full refresh
```

## Active priorities (as of 2026-05-04, s95)

1. ✅ Web dashboard `:8888` (Edge fullscreen on Game-PC's secondary display)
2. ✅ Tkinter-free (T2 #6/#8 complete; asyncio-native)
3. ✅ Daemon Slayer item coverage complete — 547/547 DDragon purchasable items, ENGINE_VERSION 0.58.0, 911 tests
4. ✅ ARAM coach DS-before-Haiku — DS picks injected in user turn; pre-DS hardcoded item rules removed (−37% system prompt)
5. 🔴 **Arena + Brawl coaches** — move DS call from post-Haiku to pre-Haiku (same code pattern as ARAM; ~30 min each)
6. 🔴 **SR coach** (`core/coach_integration.py`) — DS not wired at all; `sr_build_note` is static JSON; highest-value remaining DS integration
7. 🟡 Tiered vision — relay live, Tesseract installed; needs calibration against in-game 1920×1080 frame and coach-side routing (cheap OCR → Sonnet escalate)
8. 🟡 Bridge Watcher acceptance-criteria measurement — accumulate 50+ real-traffic samples for ≥90%/≥95% auto-action validation
