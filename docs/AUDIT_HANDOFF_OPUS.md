# RIOT COMMANDER V3 — OPUS AUDIT HANDOFF
**Date:** 2026-04-18 (audit prep) — **superseded sections updated 2026-04-19 post-migration**
**Prepared by:** Sonnet 4.6 (active dev session)
**For:** Claude Opus 4 — full professional codebase audit
**Project root:** `C:\Riot Commander\`
**Python:** `C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe`

> **2026-04-19 — RC migration complete.** RC now runs on **Legion (192.168.8.230)**.
> Game-PC (192.168.8.237) is now only the League client / Riot API source.
> Vision is in-process on Legion at `:8889` (no Moon-PC). Outdated topology
> references in this doc have been corrected below; the audit findings themselves
> remain valid.

---

## MISSION

You are being handed a mature, actively-running Windows overlay coaching application for League of Legends and TFT. This is a production system — it runs live during games. Your job is a **professional-grade audit sweep** covering:

1. File/directory structure and organisation
2. Code quality, duplication, dead code, and naming consistency
3. Architecture and coupling concerns
4. Safety: exception handling, data integrity, secret management
5. Functionality gaps and known bugs (list follows)
6. Performance and resource usage
7. Logging and observability quality
8. Concrete, prioritised recommendations with diffs or patch scripts where applicable

Do not summarise what you see. Produce a **working audit report with actionable findings**. Where you identify a fixable issue, fix it or write the patch. Where you identify a structural concern, recommend a concrete remediation path.

---

## SYSTEM OVERVIEW

### Two-machine setup (post-migration, 2026-04-19)
| Machine | IP | Role |
|---|---|---|
| Legion | 192.168.8.230 | Runs RC overlay app, tkinter UI, coaches, vision server (`:8889` local) |
| Game-PC | 192.168.8.237 | League client + Riot Live Client API on `:2999` (read by Legion over LAN) |

**Historical:** Pre-2026-04-19, RC ran on Game-PC and offloaded vision to a Moon-PC at .230. Moon-PC was decommissioned and Legion was assigned its IP.

### What the app does
Real-time overlay coaching for:
- **SR** (Summoner's Rift) — standard LoL
- **ARAM / ARAM Mayhem** — Howling Abyss (most active dev focus)
- **Arena** — 2v2 rotating mode
- **Brawl** (NEXUSBLITZ / URF / ONEFORALL)
- **TFT** (all variants: standard, Hyper Roll, Double Up)

Data flow: `Riot Live Client API (192.168.8.237:2999, over LAN)` → `game_reader.py` (on Legion) → `sr_aram_worker.py / tft_worker.py` → coach engines → `data/*.json` → `tkinter overlays` (polled at 500ms)

---

## DIRECTORY MAP

```
C:\Riot Commander\
├── app.py                    # 1,223 lines — master app, mode orchestration, game lifecycle
├── main.py                   # entry point, supervisor wiring
├── game_reader.py            # 1,293 lines — Riot API reader, all game modes
├── champion_profiles.py      # 902 lines — ADC/TFT champion coaching profiles
├── coach_integration.py      # 785 lines — coach dispatcher, shared logic
├── composition_advisor.py    # TFT composition analysis
├── item_advisor.py           # item recommendation engine (has print() debug statements)
├── performance_tracker.py    # per-mode ratings (SR/ARAM/Arena/Brawl/TFT)
├── lan_bridge.py             # Moon-PC job queue bridge (HTTP)
├── moon_vision_server.py     # Moon-PC server (runs on Moon-PC)
│
├── coaches/
│   ├── __init__.py
│   ├── aram_coach.py         # 631 lines — ARAM/Mayhem coach (v2, challenger prompt)
│   ├── arena_coach.py        # 725 lines — Arena coach
│   ├── brawl_coach.py        # 639 lines — Brawl coach
│   ├── sr_coach.py           # 1,209b — SR stub (thin wrapper)
│   ├── tft_coach.py          # TFT standard coach
│   ├── tft_hyper_coach.py    # TFT Hyper Roll variant
│   └── tft_pbe_coach.py      # TFT PBE variant
│
├── modes/
│   ├── aram_overlay.py       # 822 lines — ARAM overlay (v2.8, most complex)
│   ├── arena_overlay.py      # Arena overlay
│   ├── brawl_overlay.py      # Brawl overlay
│   └── shared_vision.py      # Vision base class + Moon-PC routing
│
├── core/
│   ├── coaching_timestamps.py
│   ├── config_validator.py
│   ├── data_store.py
│   ├── feature_policy.py     # 18,726b — coaching enable/disable per mode
│   ├── game_snapshot.py      # 25,104b — RiftSnapshot/AramSnapshot dataclasses
│   ├── hotkeys.py            # Ctrl+Tab forced vision scan (Win32 GetAsyncKeyState)
│   ├── log_setup.py
│   ├── match_db.py           # SQLite match history
│   ├── metrics_cache.py      # 21,351b — runtime observability
│   ├── moon_proxy.py         # MoonProxy singleton (HTTP to Moon-PC)
│   ├── moon_sync.py          # Moon-PC sync utility
│   ├── ops_ui_actions.py     # Preflight/snapshot/rollback actions
│   ├── resource_manager.py
│   ├── sr_aram_worker.py     # 18,501b — SR/ARAM/Arena/Brawl poll worker
│   ├── theme.py              # tkinter colour/font constants
│   ├── tft_worker.py         # 15,759b — TFT dedicated worker
│   ├── tk_ai_bar_proxy.py
│   └── version_check.py
│
├── tft/
│   ├── comp_control.py       # 798 lines — TFT comp UI control
│   ├── tft_coach_engine.py   # 791 lines — TFT coaching engine
│   ├── tft_live_analysis.py  # TFT live board analysis
│   ├── tft_overlay.py        # 1,343 lines — TFT overlay (largest single file)
│   ├── tft_placement_aggregator.py
│   ├── tft_state_reader.py   # state parsing
│   └── tft_vision_reader.py  # vision extraction
│
├── ui/
│   ├── base.py               # OverlayWindow base class
│   └── client_panel.py       # tabbed lobby panel (ARAM|SR|ARENA|BRAWL|TFT|OPS)
│
├── ops/
│   ├── rc_supervisor.py      # 1,189 lines — process supervisor + circuit breaker
│   ├── rc_self_monitor.py    # 1,062 lines — health + ops observability
│   ├── rc_dev_runtime.py     # 632 lines — dev runtime shim
│   ├── runtime/health.json   # live health state
│   ├── backups/              # rolling deployment snapshots
│   └── staging/              # staged code before deploy
│
├── config/
│   ├── settings.json         # user-facing settings
│   ├── runtime.json
│   ├── feature_flags.json    # per-mode feature toggles
│   ├── coach_settings.json
│   ├── self_monitor_profile.json
│   └── schema/               # JSON schemas for all configs
│
├── data/
│   ├── aram_coaching_data.json    # live ARAM coach output (polled by overlay)
│   ├── arena_coaching_data.json
│   ├── brawl_coaching_data.json
│   ├── tft_coaching_data.json
│   ├── tft_live_data.json
│   ├── unit_presence.json         # TFT board unit tracking
│   ├── force_scan.json            # Ctrl+Tab forced vision trigger
│   ├── match_history.db           # SQLite
│   ├── decisions.db               # SQLite
│   ├── ratings/last_tft.json      # post-game ratings (last_aram.json MISSING)
│   ├── icons/aram_items/          # 146 DDragon item icons (final items only)
│   ├── icons/items/               # TFT item icons
│   ├── meta/                      # DDragon/CDragon meta JSON (TFT set data)
│   └── ocr_debug/                 # debug screenshots
│
├── scripts/
│   └── download_aram_icons.py     # DDragon icon downloader
│
├── lcu/
│   └── lcu_client.py              # LCU auto-accept client
│
├── assets/wards/                  # ward placement suggestion assets
├── monitor.html                   # Moon-PC web monitor (fetches from port 8888/8889)
├── moon_monitor.html              # Moon-PC focused monitor
├── restart_trigger.txt            # write anything here → watchdog restarts app
├── API-Key-Claude.txt             # API key (gitignored)
└── .gitignore
```

---

## CURRENT GIT STATE

```
e7eb2a2  v2.8: lane canvas layout rework
6e5db23  v2.7: bottom strip y=900 w=1600
cbfa8bf  v2.6: hotkeys Ctrl+Tab forced scan
b0d20b5  v2.5: ARAM overhaul
527a435  style: ruff baseline
d4b1311  baseline: 2026-04-11
```

---

## KEY ARCHITECTURAL PATTERNS

### File-poll overlay system
- Coaches write JSON to `data/*.json` using `.tmp → .replace()` atomic writes
- Overlays poll their data file at 500ms intervals via `root.after()`
- No direct coach→overlay coupling — fully decoupled through filesystem

### Restart / watchdog
- Write any content to `restart_trigger.txt` → watchdog fires within ~8s
- Watchdog implemented in `ops/rc_supervisor.py`
- Hard kill: `taskkill /F /PID <pid>` then `Start-Process restart.bat`
- **NEVER use `Stop-Process`** — hangs the MCP pipe

### Atomic JSON writes
```python
tmp = path.with_suffix(".tmp")
tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
tmp.replace(path)
```

### Mode detection
`game_reader.py._process_game()` → `core/game_snapshot.py` → `app.py._process_game_state()`  
ARAM Mayhem: Riot internal string `"KIWI"` → mapped to `MODE_ARAM` in `core/game_snapshot.py`

### Vision routing (post-migration)
Vision server now runs in-process on Legion at `:8889`. `shared_vision.GameVisionReader._extract()` historically tried `lan_bridge.add_vision_job()` (20s timeout) and fell back to direct Anthropic. With vision local, the LAN hop is gone but `core/moon_proxy.py` (`MOON_HOST=192.168.8.230`) and `core/moon_sync.py` still address the vision server by its old LAN IP — works because that IP is now Legion itself, but should be migrated to `127.0.0.1` for clarity.

### Coach cadence (ARAM)
- Poll loop: 1.5s (reads Riot API)
- Vision loop: 15s (Sonnet screenshot analysis, or Ctrl+Tab forced)
- Coach call: debounced 8s, fast-path at 20% HP drop or new kill (5s min)

---

## KNOWN BUGS (confirmed, not yet fixed)

### BUG-1: `last_aram.json` never written (HIGH)
**Location:** `app.py._on_game_end()`  
**Symptom:** After ARAM games end, `data/ratings/last_aram.json` is never created. The `save_rating()` call exists and the code path is correct, but the rating is not appearing on disk.  
**Root cause to verify:** `self._game_state` may be `None` at game-end for ARAM mode since `_on_game_end()` checks `elif self._game_state:` — if state was cleared before this check runs, the block is skipped entirely.  
**Fix direction:** Cache a copy of final game state before clearing it in the game-end handler, or move the rating save before the state clear.

### BUG-2: `my_team` not in blank artifact on game start (MEDIUM)  
**Location:** `coaches/aram_coach.py._write_blank_artifact()`  
**Symptom:** For CHAOS-side players, lane canvas shows ORDER orientation for the first ~8 seconds (until first coach call completes).  
**Fix:** Write `my_team` from first `_poll_loop` read to `aram_coaching_data.json` immediately, before the first full coach call.

### BUG-3: `bottom strip y=920` may still overlap on non-1280px League installs (LOW)  
**Location:** `modes/aram_overlay.py AramBottomStrip GEO`  
**Context:** League window was observed at 1280×720 during testing. The GEO is hardcoded at `y=920, h=160`. If the League window is at 1600×900 (expected), the strip should be `y=900`. Need dynamic detection or a config value.

### BUG-4: `comp_analysis` field still referenced in `aram_coach._run_coach()` (LOW)  
**Location:** `coaches/aram_coach.py` line with `"comp_analysis": ""`  
**Context:** The COMP column was removed from the overlay but the field is still being written as empty string on every coaching update. Not harmful but wasteful and misleading.

### BUG-5: Moon-PC vision fallback always fires (MEDIUM)  
**Location:** `modes/shared_vision.py._extract()`  
**Symptom:** Logs show `Moon-PC vision routing failed, falling back` on every vision cycle. `lan_bridge` import is succeeding but `add_vision_job` is failing silently.  
**Root cause to verify:** `lan_bridge.py` may not have a registered Moon-PC connection or the job queue isn't being consumed. Contrast with `core/moon_proxy.py` which works correctly — there are two separate Moon-PC routing systems and they are not unified.

### BUG-6: `item_advisor.py` has ~121 `print()` debug statements (LOW)  
**Location:** `item_advisor.py` lines 565–574+  
**Fix:** Replace all `print()` with `logger.debug()` calls.

---

## KNOWN STRUCTURAL CONCERNS

### Dual Moon-PC routing (ARCHITECTURE)
There are **two separate Moon-PC routing implementations**:
1. `core/moon_proxy.py` — `MoonProxy` singleton, clean HTTP client with auth, retry, fallback
2. `modes/shared_vision.py` — imports `lan_bridge.py` job queue, completely different mechanism

These should be unified. `shared_vision._extract()` should call `moon_proxy.extract_vision()` instead of `lan_bridge`.

### `app.py` god class (ARCHITECTURE)
`app.py` is 1,223 lines and handles: mode orchestration, game lifecycle, overlay management, rating saves, LCU auto-accept, TFT worker lifecycle, SR worker, hotkey wiring, metrics cache wiring, and the tkinter main loop. Should be decomposed into a `GameLifecycleManager` and an `OverlayManager`.

### 123 bare `except:` clauses (SAFETY)
Scanning found 123 instances of `except:` or `except Exception: pass` across the codebase. Many are intentional (overlay callbacks can't crash the app), but several suppress real errors silently. Each should be audited — at minimum, silent suppressions should log at `DEBUG` level.

### Phase markers as inline comments (MAINTAINABILITY)
72 `# Phase N Step M` comments remain in `app.py` and coaches. These were dev-time scaffolding. They should either be converted to proper docstrings/section headers or removed.

### Staging directory duplication (STRUCTURE)
`ops/staging/` and `ops/backups/` contain copies of `tft/`, `coaches/`, etc. at various versions. These are ~15 Python files duplicated 8+ times. Git already handles versioning — the staging/backup directories should be audited and cleared of anything git handles.

### `data/debug_screen.png` and `ocr_debug/` in production (CLEANUP)
`data/debug_screen.png` (1MB), `data/ocr_debug/*.png` (2MB+) are debug artifacts. These shouldn't be committed or accumulating in the data directory.

### `last_game_rating.json` at root (STRUCTURE)
Both `data/ratings/last_{mode}.json` AND a root-level `last_game_rating.json` exist. The root file is from an older single-mode rating system. If unused, it should be removed; if still read anywhere, it should be migrated to `data/ratings/`.

---

## AUDIT SCOPE — WHAT TO DO

### 1. Structure audit
- Map every file, identify dead/orphaned files not imported anywhere
- Identify files that should be moved (e.g., `item_advisor.py`, `composition_advisor.py` → `tft/`)
- Verify `ops/staging/` and `ops/backups/` are safe to prune (git has it all)
- Check `.gitignore` covers `data/debug_screen.png`, `data/ocr_debug/`, `data/*.db`

### 2. Code quality pass
- Audit all 123 bare `except` clauses — label each as intentional/fixable
- Replace `print()` debug statements with proper logging
- Remove Phase marker comments or convert to section docstrings
- Check for duplicate logic between `aram_coach.py` / `arena_coach.py` / `brawl_coach.py` — these share ~60% structure and may benefit from a shared `BaseNonTftCoach`

### 3. Architecture review
- **Unify Moon-PC routing**: `shared_vision._extract()` should call `moon_proxy.extract_vision()` not `lan_bridge`
- **`app.py` decomposition plan**: identify which responsibilities can be cleanly extracted
- **Coach base class**: `aram_coach`, `arena_coach`, `brawl_coach` share poll loop, vision loop, force_scan, hotkey reg/unreg, overlay file polling — extract `BaseCoach`
- Review `game_snapshot.py` (25KB) — is `AramSnapshot` vs `RiftSnapshot` distinction still earning its complexity?

### 4. Bug fixes
Fix all 6 bugs listed above. Patches should be written as Python scripts using the `.tmp → .replace()` pattern, compile-checked before restart.

### 5. Safety review
- Verify `API-Key-Claude.txt` path is never logged
- Verify no API keys in any config JSON committed to git
- Audit `data/*.json` schema — do coaching files have unbounded growth risk?
- Check `match_history.db` and `decisions.db` — do they have cleanup/size caps?
- Verify `hotkeys.py` Win32 thread is properly daemon and doesn't leak on shutdown

### 6. Performance review
- `aram_overlay.py._ItemBuildCanvas._load_icon()` opens and closes a PIL image on every redraw — icons should be cached per-slug
- `AramLaneCanvas._redraw()` redraws every 500ms even when state hasn't changed — add dirty-flag check
- `champion_profiles.py` (55KB/902 lines) is imported on every coach call — verify it's not re-read from disk each time

### 7. Logging review
- Confirm all coaches use `logger.error()` for real failures (not `logger.warning()` or silent pass)
- Verify log rotation is configured and old logs don't accumulate unboundedly
- Check that `ops/runtime/health.json` is always written atomically

---

## OPERATING CONSTRAINTS (never violate these)

| Rule | Why |
|---|---|
| Never use `Stop-Process` | Hangs the MCP pipe |
| Always `py_compile.compile()` before restart | Syntax errors crash silently |
| Atomic writes: `.tmp → .replace()` | Overlay polls can read mid-write |
| Restart via `restart_trigger.txt` write | Supervisor handles graceful restart |
| Hard restart: `taskkill /F /PID` + `Start-Process restart.bat` | When watchdog doesn't fire |
| Log tail for startup verification | Stale log + no new timestamp = watchdog didn't fire |

---

## ENVIRONMENT (post-migration, 2026-04-19)

```
Legion (192.168.8.230) — RC host:
  Python: C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe
  Root:   C:\Riot Commander\
  Ports:  8888 (RC HTTP / planned web dashboard for iPad)
          8889 (vision server, local)
  Auth:   X-RC-Token: 8e8f131e212b329438218eca27372dde

Game-PC (192.168.8.237) — League client only:
  Riot Live Client API: https://192.168.8.237:2999/liveclientdata/
  LCU API:              https://192.168.8.237:{port}/  (lockfile-discovered)
```

---

## AUDIT DELIVERABLE FORMAT

Produce your findings as a structured report with:

```
## FINDING-NNN: [Title]
Severity: CRITICAL | HIGH | MEDIUM | LOW | INFO
Category: Structure | Quality | Architecture | Safety | Performance | Logging | Bug
File(s): path/to/file.py (line numbers if applicable)
Description: [what the problem is]
Evidence: [code excerpt or log evidence]
Recommendation: [concrete fix]
Patch: [Python patch script or diff, if fixable]
```

After all findings, produce a **prioritised fix queue** — what to tackle first for maximum safety/stability gain.

---

## QUICK REFERENCE — HOW TO READ AND PATCH FILES

```python
# Read a file
from pathlib import Path
c = Path(r'C:\Riot Commander\coaches\aram_coach.py').read_text(encoding='utf-8', errors='replace')

# Patch and compile-check
c = c.replace(old_str, new_str, 1)
Path(r'C:\Riot Commander\coaches\aram_coach.py').write_text(c, encoding='utf-8')
import py_compile
py_compile.compile(r'C:\Riot Commander\coaches\aram_coach.py', doraise=True)

# Trigger restart
Path(r'C:\Riot Commander\restart_trigger.txt').write_text('audit_patch', encoding='utf-8')
```

All patch scripts should be written to disk, executed, then deleted in a single operation.

---

*This document was generated from a live session on 2026-04-18 by Claude Sonnet 4.6. The system was running PID 14684 at time of writing with 0 errors in the Moon-PC monitor.*
