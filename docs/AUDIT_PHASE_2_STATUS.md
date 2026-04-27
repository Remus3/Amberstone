# RIOT COMMANDER V3 — PHASE 2 STATUS LEDGER
**Last updated:** 2026-04-18 (Phase 2 sessions 1-5) — **see migration banner below for 2026-04-19 update**
**Updated by:** Claude Sonnet 4.6 (Phase 2 sessions 1-5)
**System state (historical):** PID 11756 on Game-PC, supervisor active, Legion vision server running
**Session count:** 5 sessions (Opus audit sessions 1-3 + Sonnet Phase 2 sessions 4-5)

> **2026-04-19 — RC migrated from Game-PC to Legion.** RC main app, coaches, and
> vision server now all run on Legion (192.168.8.230). Game-PC (192.168.8.237) is
> now only the League client + Riot Live Client API source. Section 1.1's
> "Game-PC RC PID" and Section 6's environment block are superseded — see root
> `AUDIT_PHASE_2_STATUS.md` for the current PID/topology snapshot.

---

## 1. CURRENT SYSTEM STATE

### 1.1 What is live right now

| Subsystem | Status | Notes |
|---|---|---|
| `main.py` entry point | ✅ FROZEN | Clean orchestrator |
| `core/log_setup.py` | ✅ FROZEN | 30-day retention, crash hooks |
| `core/moon_proxy.py` | ✅ FROZEN | Auth token, availability caching |
| `lcu/lcu_client.py` | ✅ FROZEN | Lockfile auth, auto-accept, self-heal |
| `core/game_snapshot.py` | ✅ FROZEN | Dataclasses with __slots__ |
| `ops/rc_supervisor.py` | ✅ PATCHED | restart_trigger.txt watcher live (OPS-001) |
| `ops/rc_dev_runtime.py` | ✅ FROZEN | Atomic health.json writes |
| **Legion vision server** | ✅ NEW | Replaces Moon-PC at 192.168.8.230:8889 |
| `game_reader.py` | ✅ PATCHED | Lockfile LCU (GR-001), runes (RUNE-001), SR-only guards (GR-003) |
| `coaches/aram_coach.py` | ✅ PATCHED | Rune prompt, rune recommendations, _base_coach imports |
| `coaches/arena_coach.py` | ✅ PATCHED | _base_coach helper imports |
| `coaches/brawl_coach.py` | ✅ PATCHED | _base_coach helper imports |
| `coaches/_base_coach.py` | ✅ NEW | Shared utilities: read_api_key, load_json, safe_write, parse_field/s, teardown_overlay |
| `scripts/data_pipeline.py` | ✅ NEW | DDragon download pipeline — patch 16.8.1 downloaded |
| `data/meta_build/rune_recommendations_aram.json` | ✅ NEW | 6 ADC rune recommendations (ARAM) |
| `data/meta_build/rune_recommendations_sr.json` | ✅ NEW | 6 ADC rune recommendations (SR) |
| RC-Supervisor Task Scheduler | ✅ NEW | Auto-starts at logon, adopts RC on boot |
| RC-VisionServer Task Scheduler (Legion) | ✅ NEW | Auto-starts at boot on Legion |

### 1.2 Infrastructure changes

| Change | Detail |
|---|---|
| **Legion-RC provisioned** | Windows 10 Spectre, Python 3.14.4, IP 192.168.8.230 |
| **Moon-PC decommissioned** | VBS autostart removed, IP reassigned to Legion |
| **Python 3.14 in system PATH** | `pythonw.exe` now resolves from any context |
| **restart.bat functional** | Works from Task Scheduler and CLI |
| **restart_trigger.txt live** | Supervisor polls it; write any content to restart RC |

---

## 2. COMPLETED WORK LEDGER (all sessions)

### Sessions 1-3 (Opus audit — pre-Phase 2)
| ID | File | Description |
|---|---|---|
| BUG-1 | app.py | ARAM/Arena/Brawl rating save restored |
| BUG-2 | aram_coach.py | CHAOS-side lane orientation eager write |
| BUG-4 | aram_coach.py | Dead comp_analysis field write removed |
| BUG-5 | shared_vision.py | Moon-PC routing via moon_proxy |
| SEC-001 | logs/, install.bat | API key partial leak scrubbed |
| STR-002 | tft/tft_overlay.bak | Stale backup deleted |
| STR-006 | .gitignore | 12 missing entries added |
| LOG-001 | core/log_setup.py | 30-day retention prune |
| LOG-002 | lan_bridge.py | RotatingFileHandler |
| PERF-001 | modes/aram_overlay.py | Icon cache (5x redraw speedup) |

### Sessions 4-5 (Sonnet Phase 2)
| ID | File | Description |
|---|---|---|
| INFRA | Legion-RC | Full provisioning: OS, Python, vision server, Task Scheduler |
| RUNE-001 | game_reader.py | _read_my_runes(), _read_enemy_runes(), /activeplayerrunes endpoint |
| RUNE-001 | aram_coach.py | Rune fields in _USER_TMPL and _run_coach kwargs |
| RUNE-REC | aram_coach.py | _load_rune_rec() wired into system prompt |
| RUNE-REC | data/meta_build/ | rune_recommendations_aram.json + rune_recommendations_sr.json |
| DATA | scripts/data_pipeline.py | Full DDragon pipeline with version-awareness |
| DATA | data/ | Patch 16.8.1: 172 champion icons, 66 rune icons, 18 spell icons, 4 JSON files |
| GR-001 | game_reader.py | _ensure_lcu() lockfile-first, wmic as fallback |
| GR-002 | game_reader.py | _JUNGLE_CHAMPS refreshed (Rek'Sai, Karthus, Shyvana, etc.) |
| GR-003 | game_reader.py | _ward_hint/_camp_hint guarded to CLASSIC mode only |
| OPS-001 | ops/rc_supervisor.py | restart_trigger.txt watcher in main loop |
| OPS-001 | Task Scheduler | RC-Supervisor scheduled task at logon |
| QUAL-001 | moon_vision_server.py | 5 bare except: → except Exception: on Legion |
| QUAL-002 | coach_integration.py | 2 silent handlers → log.debug |
| QUAL-002 | performance_tracker.py | 1 silent handler → log.debug |
| STR-005 | audit/ | Directory deleted (3MB dev scaffolding) |
| STR-007 | last_game_rating.json | Migrated to data/ratings/ |
| STR-008 | dist/ | Empty directory deleted |
| STR-009 | data/TFT guide author X_* | Archived to backups, removed from data/ |
| STR-010 | ocr_debug.py, write_monitor_b64.py | Moved to tools/ |
| PATH | System | Python 3.14 added to system PATH |
| ARCH-002 (partial) | coaches/_base_coach.py | Shared helper module created; arena + brawl wired |

---

## 3. OUTSTANDING WORK

### 3.1 Architecture
| ID | Severity | Description |
|---|---|---|
| ARCH-001 | HIGH VALUE | Decompose app.py god class into GameLifecycleManager, OverlayManager, etc. |
| ARCH-002 (full) | HIGH VALUE | Full BaseCoach inheritance refactor — helpers extracted (done), class hierarchy deferred. Plan: BaseCoach owns __init__, _poll_loop, _vision_loop, _maybe_coach frame, _teardown_overlay, _ensure_data, _read_game_state. Each mode overrides: _data_filename, _blank_artifact(), _parse_raw_state(), _build_prompt(), _parse_response(), _vision_interval_s, _mode_name, _attach_overlay_windows() |
| ARCH-003 | MEDIUM | Split lan_bridge.py into server-only + delete dead client API |

### 3.2 Game reader
| ID | Severity | Description |
|---|---|---|
| GR-004 | LOW | _map_zone() diagonal "mid" detection heuristic is suspect for edge cases |

### 3.3 Data pipeline
| ID | Severity | Description |
|---|---|---|
| DATA-001 | HIGH | Per-matchup item weighting (matchup_weights.json) — not yet built |
| DATA-002 | MEDIUM | Challenger build data from aggregator D — scraper investigation needed |
| DATA-003 | LOW | Schedule data_pipeline.py to run automatically on patch day |

### 3.4 Riot API coverage
| ID | Endpoint | Priority |
|---|---|---|
| API-001 | /lol-perks/v1/currentpage (LCU) | HIGH — current rune page read |
| API-002 | /liveclientdata/activeplayerabilities | MEDIUM — ability cooldowns |
| API-003 | /lol-gameflow/v1/session (LCU) | MEDIUM — queue phase state |

### 3.5 Quality
| ID | Severity | Description |
|---|---|---|
| QUAL-002 (residual) | LOW | ~84 LOG_DEBUG candidates in live code — mechanical sweep when time permits |

---

## 4. DATA ASSETS

### 4.1 On disk today
```
data/
├── icons/
│   ├── aram_items/     146 PNG  ✅
│   ├── items/           36 PNG  ✅
│   ├── champions/      172 PNG  ✅ (NEW patch 16.8.1)
│   ├── runes/           66 PNG  ✅ (NEW patch 16.8.1)
│   └── spells/          18 PNG  ✅ (NEW patch 16.8.1)
├── meta/
│   ├── ddragon_champions.json        ✅ (NEW 244KB)
│   ├── ddragon_items.json            ✅ (NEW 876KB)
│   ├── ddragon_runes.json            ✅ (NEW 42KB)
│   ├── ddragon_summoner_spells.json  ✅ (NEW 35KB)
│   ├── ddragon_version.json          ✅ (NEW — patch 16.8.1 lock)
│   ├── cdragon_tft_pbe.json          ✅ (24MB TFT)
│   └── tft_set17_meta.json           ✅ (258KB TFT)
├── meta_build/
│   ├── rune_recommendations_aram.json  ✅ (NEW — 6 ADCs)
│   └── rune_recommendations_sr.json    ✅ (NEW — 6 ADCs)
├── match_history.db    104KB
├── decisions.db         52KB
└── ratings/
    ├── last_tft.json    ✅
    └── last_game_rating.json  ✅ (migrated from root)
```

### 4.2 Still missing
```
data/meta_build/
├── sr_challenger_by_champion.json    ❌ (aggregator D scraper needed)
├── aram_winrate_by_champion.json     ❌
└── matchup_weights.json              ❌
```

---

## 5. OPERATING RULES (unchanged from Phase 1)

| Rule | Why |
|---|---|
| Never use Stop-Process | Hangs MCP pipe |
| Always py_compile before restart | Syntax errors crash silently |
| Atomic writes: .tmp → .replace() | Overlay polls can read mid-write |
| Restart via restart_trigger.txt | Supervisor handles graceful restart |
| Hard restart: taskkill /F /PID + restart.bat | When supervisor doesn't restart within 8s |
| Log tail for startup verification | Stale log = watchdog didn't fire |
| Backup before every patch | ops/backups/<timestamp>-<label>/ |

## 6. ENVIRONMENT

```
Game-PC (192.168.8.237):
  Python: C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe
  pythonw: in system PATH ✅
  Root: C:\Riot Commander\
  RC PID: 11756 (as of 2026-04-18T21:00)
  Supervisor: running (Task Scheduler at logon)

Legion-RC (192.168.8.230):
  OS: Windows 10 Spectre
  Python: C:\Users\Administrator\AppData\Local\Python\pythoncore-3.14-64\python.exe
  Vision server: C:\RC\moon_vision_server.py port 8889
  Task: RC-VisionServer (at boot, SYSTEM, restart x5)
```

## 7. NEXT SESSION CHECKLIST

Before starting:
- [ ] Confirm `has_game=false` in health.json (don't patch during active game)
- [ ] Run `python scripts/data_pipeline.py meta` — verify still on patch 16.8.1 or update
- [ ] Check Legion health: `Invoke-WebRequest http://192.168.8.230:8889/health`

Recommended next session priorities:
1. **ARCH-002 full** — BaseCoach class hierarchy (arena + brawl first, then aram)
2. **API-001** — /lol-perks/v1/currentpage LCU rune page read
3. **DATA-002** — aggregator D investigation for challenger build data
4. **ARCH-001** — app.py decomposition plan (propose before executing)
