# Riot Commander — Agent Context

Live League / TFT coaching overlay + dashboard. Reads Riot Live Client API,
calls Claude Haiku for fast coaching and Sonnet for vision, writes JSON to
`data/`, and serves a tkinter overlay + a `:8888` web dashboard for iPad.

## Topology (post-2026-04-19 migration)

| Machine | IP | Role |
|---|---|---|
| **Legion** | 192.168.8.230 | Runs RC (`main.py`), supervisor, vision server, web dashboard |
| **Game-PC** | 192.168.8.237 | Runs League client; exposes Riot Live Client API on `:2999` (read by Legion over LAN) |
| **iPad** | — | Mirrors Game-PC via Duet USB-C; loads `http://192.168.8.230:8888/` as installed PWA |

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
  `app/__init__.py`, `app/_health_monitor.py`, `app/_remediation.py`,
  `app/_state_authority.py`, `app/_overlay_manager.py`, `app/_game_lifecycle.py`.

## Restart workflow

```
echo restart > restart_trigger.txt   # supervisor picks up within 1s, restarts in ~5s
```
Verify after restart: read `ops/runtime/health.json`, confirm new `pid`, `alive=true`,
`last_reload_ok=true`. Hard fallback: `taskkill /F /PID <pid>` then `restart.bat`.

## Scheduled tasks (Legion)

- `RC-Supervisor` — at logon, Administrator, HIGHEST. Runs `pythonw.exe ops/rc_supervisor.py --config ops/rc_config.json`.
- `RC-VisionServer` — at system startup, SYSTEM, HIGHEST. Runs `python.exe moon_vision_server.py`.

Supervisor has a PID lock — duplicate launches abort cleanly.

## Web dashboard (replaces tkinter overlays — RC is headless)

`web_dashboard.py` (root) — daemon thread launched from `main.py` after MetricsCache.
- GET `/`, `/api/state`, `/api/health`, `/manifest.json`, `/icon.svg`
- POST `/api/input` `{text}` — writes to `coaching_data.json.pregame`
- POST `/api/command` `{command: "force_vision"|"refresh"|"clear_pregame"}`
PWA-installable via Edge (after `edge://flags/#unsafely-treat-insecure-origin-as-secure`
adds `http://192.168.8.230:8888`).
Layout: 1180×820 retina (iPad Air via Duet); header 70 / body 670 / input bar 80.

## Headless mode

Tkinter overlays are disabled (`_HEADLESS = True` in `app/_overlay_manager.py`).
Windows are still created (so `client_windows.get('main')` etc don't crash) but
immediately hidden. Set the constant to `False` to restore on-screen overlays.

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

**Game-PC deploy** (one time):
```
1. Copy tools\gamepc_screen_agent.py to Game-PC at C:\RC-Agent\
2. py -m pip install Pillow
3. py C:\RC-Agent\gamepc_screen_agent.py
4. (optional) schtasks /Create /TN "RC-ScreenAgent" /SC ONLOGON /F /TR "py C:\RC-Agent\gamepc_screen_agent.py"
```

TFT vision (`tft/tft_vision_reader.py`, `tft/tft_ocr_reader.py`) still uses
local `ImageGrab` and is broken post-migration — needs the same relay refactor.

## Architecture map

```
main.py                   entry: logging, key, DevRuntime, MetricsCache, web_dashboard, OverlayApp
overlay.py                shim → app/__init__.py
app/                      OverlayApp + decomposed managers (ARCH-001 complete)
  __init__.py             OverlayApp orchestrator (~430L)
  _health_monitor.py      heartbeat
  _remediation.py         restart_game_poll, rebuild_panel_*
  _state_authority.py     envelope + win-pct
  _overlay_manager.py     tk window lifecycle
  _game_lifecycle.py      game start/end, worker dispatch
coaches/                  BaseCoach (ARCH-002) + aram/arena/brawl/sr/tft variants
  _base_coach.py          shared poll/vision loops, debounce, hotkey reg
modes/                    overlay UIs per mode (aram_overlay, arena_overlay, brawl_overlay, shared_vision)
core/                     game_snapshot, sr_aram_worker, tft_worker, theme, hotkeys, log_setup,
                          moon_proxy (vision client), metrics_cache, lcu integration helpers
tft/                      TFT engine + overlay (separate worker)
ui/                       OverlayWindow base + ClientPanel (tabbed lobby panel)
ops/                      rc_supervisor, rc_self_monitor, rc_dev_runtime, runtime/health.json
lcu/                      LCU client, auto-accept, rune writer, postgame collector
data/                     coaching artifacts (atomic-written, polled by overlays + dashboard)
web_dashboard.py          :8888 HTTP read-only dashboard for iPad
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

# Data pipeline (patch day)
cd scripts && python data_pipeline.py meta          # check version
python data_pipeline.py aram_builds                  # ARAM tier refresh
python data_pipeline.py all                          # full refresh
```

## Active priorities (2026-04-19)

1. ✅ Web dashboard `:8888` for iPad (PWA installed)
2. ✅ Tkinter overlays disabled; dashboard is the UI (no overlay-geometry work needed)
3. 🟡 Tiered vision — relay live, Game-PC agent running (RC-ScreenAgent task), Tesseract installed, `core/vision_tesseract.py` module with default 1920×1080 regions in `data/vision_regions.json`. Dashboard exposes `/api/ocr` (run all fields) and `/api/ocr-crop?field=NAME` (PNG preview). Needs: (a) calibration against an in-game frame, (b) coach-side routing that calls Tesseract for cheap fields and only escalates to Sonnet when needed.
4. ✅ This file
