# Riot Commander — Agent Context

Live League / TFT coaching overlay + dashboard. Reads Riot Live Client API,
calls Claude Haiku for fast coaching and Sonnet for vision, writes JSON to
`data/`, and serves a tkinter overlay + a `:8888` web dashboard viewed in Edge fullscreen on Game-PC's secondary display.

## Topology (post-2026-04-19 migration)

| Machine | IP | Display | Role |
|---|---|---|---|
| **Legion** | 192.168.8.230 | 1 monitor | Runs RC (`main.py`), supervisor, vision server, web dashboard |
| **Game-PC** | 192.168.8.237 | 2 monitors — primary TV (the game) + secondary iPad-as-monitor over Duet (1920×1280 native, 100% OS scale, no touch, no apps; the iPad is just a wireless display panel) | Runs League client; exposes Riot Live Client API on `:2999` (read by Legion over LAN). Edge runs fullscreen on the secondary display showing the RC dashboard |

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
  `app/_state_authority.py`, `app/_overlay_manager.py`, `app/_game_lifecycle.py`.

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
- GET `/`, `/api/state`, `/api/health`, `/manifest.json`, `/icon.svg`
- POST `/api/input` `{text}` — writes to `coaching_data.json.pregame`
- POST `/api/command` `{command: "force_vision"|"refresh"|"clear_pregame"}`
Viewed in Edge fullscreen on Game-PC's secondary display (1920×1280 native, 100% OS scale → 1920×1280 effective CSS viewport). HTTPS with self-signed cert; either import the cert or set `edge://flags/#unsafely-treat-insecure-origin-as-secure` for `https://192.168.8.230:8888`.

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
   POSTs to `http://192.168.8.230:8889/upload-frame` (auth: `X-RC-Token`).
2. **Vision server** caches the latest frame in memory (`_latest_frame`).
3. **Coaches on Legion** call `modes.shared_vision._capture_screen()`, which
   GETs `http://127.0.0.1:8889/latest-frame` and returns the cached b64.
4. Coaches submit the frame to `/vision` (Sonnet) or `/ocr` (Tesseract).

Tesseract installed at `C:\Program Files\Tesseract-OCR\tesseract.exe`
(via winget; not in PATH — vision server pins explicitly via `_TESSERACT_DEFAULT`).

**Game-PC deploy** (one-line bootstrap, idempotent):
```
iex (iwr https://192.168.8.230:8888/agent/gamepc_boot.ps1).Content
```
Pulls all 4 agents (`gamepc_screen_agent.py`, `gamepc_lcu_agent.py`,
`gamepc_liveclient_relay.py`, `gamepc_mcp_server.py`) from Legion's
`/agent/` allowlist, kills any zombie listeners, ensures the inbound
firewall rule for `:8892` (MCP), starts whatever isn't healthy, and
installs scheduled tasks (`RC-LCU`, `RC-LiveClientRelay`, `RC-MCP-Server`,
plus `RC-ScreenAgent-*` variants) for boot persistence. See `tools/GAMEPC_CLAUDE.md` for the
agent map.

TFT vision (`tft/tft_vision_reader.py`, `tft/tft_ocr_reader.py`) still uses
local `ImageGrab` and is broken post-migration — needs the same relay refactor.

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
modes/                    shared_vision (relay screen-grab client used by coaches)
                          [aram/arena/brawl_overlay archived in T2 #8 C2 — _archive/2026-05-01-audit/modes/]
core/                     game_snapshot, sr_aram_worker, tft_worker, theme, hotkeys, log_setup,
                          moon_proxy (vision client), metrics_cache, lcu integration helpers,
                          prom_metrics (T3 #12 — Prometheus exposition, zero-dep)
tft/                      TFT engine (tft_state_reader, tft_live_analysis, tft_coach_engine, tft_data, tft_pbe_*)
                          [tft_overlay + comp_control archived in T2 #8 C2]
ui/                       (empty — entire package archived in T2 #8 C2; see _archive/2026-05-01-audit/ui/)
ops/                      rc_supervisor, rc_self_monitor, rc_dev_runtime, runtime/health.json
lcu/                      LCU client, auto-accept, rune writer, postgame collector
data/                     coaching artifacts (atomic-written, polled by overlays + dashboard)
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

## Active priorities (2026-04-19)

1. ✅ Web dashboard `:8888` (Edge fullscreen on Game-PC's secondary display)
2. ✅ Tkinter overlays disabled; dashboard is the UI (no overlay-geometry work needed)
3. 🟡 Tiered vision — relay live, Game-PC agent running (RC-ScreenAgent task), Tesseract installed, `core/vision_tesseract.py` module with default 1920×1080 regions in `data/vision_regions.json`. Dashboard exposes `/api/ocr` (run all fields) and `/api/ocr-crop?field=NAME` (PNG preview). Needs: (a) calibration against an in-game frame, (b) coach-side routing that calls Tesseract for cheap fields and only escalates to Sonnet when needed.
4. ✅ This file
