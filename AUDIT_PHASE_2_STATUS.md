# RIOT COMMANDER — PHASE 2 STATUS LEDGER
**Last updated:** 2026-04-19
**Current PID:** 4440 (started 2026-04-19T23:16:36 UTC, alive=true)
**ARCH-001 status:** ALL PHASES COMPLETE
**Host:** Legion (192.168.8.230) — RC migrated from Game-PC, transition complete

## TOPOLOGY (post-migration)

| Machine | IP | Role |
|---|---|---|
| Legion | 192.168.8.230 | Runs RC (`main.py`, coaches, overlays) + vision server on :8889 (local) |
| Game-PC | 192.168.8.237 | League client; exposes Riot Live Client API on :2999 (read over LAN) |

Vision is now in-process on the same host as RC — no Moon-PC, no LAN hop for vision.

---

## 1. app/ PACKAGE STRUCTURE (ARCH-001 COMPLETE)

```
C:\Riot Commander\
├── app.py                       ← shim (Python package takes precedence)
└── app\
    ├── __init__.py              ← OverlayApp orchestrator (428 lines)
    ├── _health_monitor.py       ← HealthMonitor (81 lines)
    ├── _remediation.py          ← RemediationService (132 lines)
    ├── _state_authority.py      ← StateAuthority + calc_win_pct (95 lines)
    ├── _overlay_manager.py      ← OverlayManager (238 lines)
    └── _game_lifecycle.py       ← GameLifecycleManager (494 lines)
```

**Original app.py: 1228 lines → app/__init__.py: 428 lines (−65%)**
**Key path rule:** `SCRIPT_DIR = Path(__file__).parent.parent`

---

## 2. ALL COMPLETED PATCHES

| ID | File(s) | Change |
|---|---|---|
| BUG-1 | `app/__init__.py` | ARAM/Arena/Brawl rating save restored |
| BUG-2 | `coaches/aram_coach.py` | CHAOS-side lane orientation eager write |
| BUG-3 | `modes/aram_overlay.py` | AramBottomStrip y=920→900 |
| BUG-4 | `coaches/aram_coach.py` | Dead comp_analysis write removed |
| BUG-5 | `modes/shared_vision.py` | Moon-PC routing via moon_proxy |
| SEC-001a/b | `logs/`, `install.bat` | API key leak scrubbed |
| STR-002/006 | `tft/`, `.gitignore` | .bak deleted, 12 entries added |
| LOG-001/002 | `core/log_setup.py`, `lan_bridge.py` | Log retention + rotation |
| PERF-001 | `modes/aram_overlay.py` | Icon cache (5× redraw speedup) |
| QUAL-002 ×6 | Various | Silent handler → log.warning/debug |
| DATA-001 | `item_advisor.py`, `aram_coach.py`, `matchup_weights.json` | Matchup-aware item coaching |
| ARCH-001 P1-4 | `app/` (5 files) | God class decomposed, −65% lines |
| API-002 | `game_reader.py`, `coaches/aram_coach.py` | Ability cooldowns in ARAM coaching |
| DATA-003 | `scripts/data_pipeline.py` | `cmd_aram_builds` — ARAM tier auto-update |

---

## 3. OUTSTANDING WORK

| ID | Priority | Description |
|---|---|---|
| API-003 | LOW | `/lol-gameflow/v1/session` — LCU already has queue_state(); minimal gain |
| GR-002 | DONE | `_JUNGLE_CHAMPS` set refreshed (Rek'Sai, Karthus, Briar, Bel'Veth, Aurora, Naafiri, etc.) — verified 2026-04-25 |
| GR-003 | DONE | `_ward_hint`/`_camp_hint` gated on `game_mode == "CLASSIC"` — verified 2026-04-25 |
| ARCH-002 | DONE | BaseCoach already exists (426L), coaches inherit from it, ~1484 total lines |
| DATA-003 | DONE | `cmd_aram_builds` added (graceful fallback when sources blocked) |
| BUG-6 | DONE | `item_advisor.py` print → logger.debug — only 2 prints remain, both in `if __name__=="__main__"` smoke-test block (correct) |
| STRUCT (Moon-PC dual routing) | DONE | `modes/shared_vision.py` already routes through `core.moon_proxy` (BUG-5 fix). `lan_bridge.py` dead-code path (`add_vision_job` / `get_job_result`) removed (ARCH-003) |
| CLEANUP (debug artifacts) | DONE 2026-04-25 | `data/debug_crops/` (6 MB, 85 files), `data/debug_frame*.jpg` (670 KB) deleted. Regenerated on demand by `tools/calibrate_vision.py`. |
| STRUCT (`last_game_rating.json`) | PARTIAL | Stale duplicate at `data/ratings/last_game_rating.json` deleted. Root file kept (still actively read by supervisor + performance_tracker). Architectural unification deferred. |
| STRUCT (`lan_bridge.py`) | DONE 2026-04-25 | Moved to `legacy/` — not imported, not running anywhere, never deployed to Game-PC |
| STRUCT (`core/moon_sync.py`) | DONE 2026-04-25 | Moved to `legacy/` — Moon-PC retired post-migration, no production importers |

---

## 4. OPERATING RULES

- **windows-mcp is UNRELIABLE** — assume dead, prefer Filesystem + Python scripts
- Never Stop-Process → `taskkill /F /PID`
- Always `py_compile.compile()` before restart
- Restart via `restart_trigger.txt`
- `SCRIPT_DIR` in `app/__init__.py` MUST be `Path(__file__).parent.parent`

## 5. USEFUL COMMANDS

```powershell
# Run data pipeline (patch day)
cd 'C:\Riot Commander\scripts'
python.exe data_pipeline.py aram_builds   # update ARAM tiers
python.exe data_pipeline.py all           # full refresh
python.exe data_pipeline.py meta          # check version status

# Health check
Get-Content 'C:\Riot Commander\ops\runtime\health.json' | ConvertFrom-Json

# Restart RC
Set-Content 'C:\Riot Commander\restart_trigger.txt' -Value 'manual'
```
