# PROJECT_STATE.md
# Riot Commander — Single Source of Truth
# Last updated: 2026-04-15 (Phase 7 + Patch 17.1 + TFT guide author X integration)
# Replaces all prior handoff docs
#
# >>> STALE AS OF 2026-04-19 <<<
# RC has since migrated from Game-PC to Legion (192.168.8.230). Vision runs
# locally on Legion at :8889. Game-PC (192.168.8.237) is now only the League
# client / Riot API source. The "TECH STACK" and "CURRENT APP STATE" sections
# below reflect the pre-migration topology and PID.
# Current source of truth: AUDIT_PHASE_2_STATUS.md (root) and ops/runtime/health.json.

---

## APP LAUNCH

```powershell
cd "C:\Riot Commander"
python main.py
```

Restart trigger (watchdog):
```
Write any content to: C:\Riot Commander\restart_trigger.txt
```

NEVER use Stop-Process or Start-Process through windows-mcp — hangs MCP pipe 4+ min.
NEVER launch via `python app.py` — `__file__` undefined in that context.

---

## TECH STACK

- Python 3.14.3 — `C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe`
- tkinter overlay UI (multi-window)
- Riot Live Client Data API (port 2999) — SR/ARAM/Arena/Brawl
- Claude Haiku — live coaching (1.5s poll loop)
- Claude Sonnet — computer vision / screenshots (12–15s vision loop)
- Tesseract OCR — TFT stage/round detection
- LAN bridge: `http://192.168.8.237:8888/`
- Game-PC: 192.168.8.237 | Moon-PC: 192.168.8.230

---

## CURRENT APP STATE

| Component | Status |
|-----------|--------|
| App | RUNNING (main.py, PID 9592, ~140MB) |
| LAN bridge | RUNNING (port 8888) |
| Watchdog | run_watchdog.bat |
| Moon-PC | OFFLINE (expected) |
| Selected comp | Vanguard Karma LeBlanc |
| PBE flag | false (live server) |

---

## PHASE COMPLETION STATUS

| Phase | Status | Notes |
|-------|--------|-------|
| Phase 1–6 | ✅ Frozen | `audit/phase6_kickoff_bundle_v13.zip` |
| P1-A PBE/Live routing | ✅ | PBE checkbox routes to correct meta file |
| P1-B OCR round counter | 🔶 | Region widened — needs in-game verify |
| P2-A Emblem toggle | ✅ | `ignore_emblems` guard in tft_coach_engine.py |
| P2-B Client panel close | ✅ | `_persist_panel_state()` survives restart |
| P2-C Augment reroll | ✅ | `force_scan()` clears stale aug choices |
| P3-A Item → prompt | ✅ | `built_items` injected into coach prompt |
| P3-B Right-click menus | ✅ | ARAM/Arena/Brawl overlays |
| P3-C Team planner names | ✅ | 83 entries aligned |
| P3-D Comp data | ✅ | 34→45 comps after patch 17.1 + BM |
| P3-E Patch detection | ⬜ | Not started — `core/version_check.py` exists |
| P4-A Patch 17.1 meta | ✅ | Names, tiers, items, patch notes in meta |
| P4-B TFT guide author X + hex board | ✅ | 10 new comps, 18 board placements, hex panel |
| VKL comp fix | ✅ | All fields verified, selected in menu |

---

## TFT META STATE (patch 17.1, 2026-04-15)

**Source: aggregator C + TFT guide author X + TFT guide site Y**
Total comps: **45** | S:10 A:16 B:13 C:6

S-tier: Conduit Reroll, N.O.V.A., Transformers, Mirror Mayhem, Astral Meep, Turbo Doomer,
        NOVA YI, Capped & Loaded, Vex Fast 9, Vanguard Karma LeBlanc

Key patch 17.1 changes baked into meta:
- Carousel REMOVED → Realm of the Gods (Stage X-4 = god offering, 4-7 = God Boon)
- Tank items nerfed: Bramble Vest, Dragon's Claw, Gargoyle, Steadfast Heart, Spirit Visage
- Rabadon's buffed: AP 50→55 | Nashor's nerfed: AP 18→15
- 4-star scaling: 1.7x (was 1.33x) | Lv7 3-cost odds: 19% (was 16%)
- Encounters NOT in 17.1 — returning in 17.2
- Keywords: Chill→Slow, Dazzle→Weaken, Precision replaces "spells can crit"

**TFT guide author X tier (bm_tier field):**
S: Vex Fast 9, Vanguard Karma LeBlanc
A: Shepherd Viktor, Space Groove Riven, Mecha, NOVA Marauders, Primordian Reroll,
   Stargazer Xayah, Twisted Fate Reroll, Invader Zed, Big Bang Meepsie
B: 7 Shepherd, Rogue Reroll, Corki Riven, Miss Fortune Reroll, Meeple Veigar, Jhin Fast 9,
   Bonk! Nasus, Contract Killer Pyke, Stellar Combo Aatrox
C: Leona Teemo Reroll, Psionic Yi, Reach For The Stars Jax, Termeepnal Velocity

---

## FILE MAP — MEANINGFUL FILES

### Entry Points
```
main.py                          — Entry point
app.py                           — OverlayApp, GameEnvelope authority
overlay.py                       — Imports OverlayApp
```

### TFT Subsystem
```
tft/comp_control.py              — Comp selector, PBE toggle, item panel,
                                   built_items persist, hex board display (_draw_hex_board)
tft/tft_coach_engine.py          — TFT coaching prompts, emblem guard, built_items inject,
                                   God boon runtime replacement (carousel→god boon)
tft/tft_live_analysis.py         — Vision loop, augment reroll, force_scan()
tft/tft_state_reader.py          — Stage/round state
tft/tft_ocr_reader.py            — Tesseract OCR (region widened to 640,4,960,46)
tft/tft_overlay.py               — TFT overlay window
tft/tft_vision_reader.py         — Screenshot crops for Sonnet vision
```

### Coaches
```
coaches/sr_coach.py              — SR coaching
coaches/aram_coach.py            — ARAM coaching
coaches/arena_coach.py           — Arena coaching
coaches/brawl_coach.py           — Brawl coaching
coaches/tft_coach.py             — TFT coaching wrapper
coaches/tft_hyper_coach.py       — Hyper Roll + Double Up (carousel→God pick fixed)
coaches/tft_pbe_coach.py         — PBE coaching wrapper
```

### Mode Overlays
```
modes/aram_overlay.py            — ARAM (_rc_menu right-click)
modes/arena_overlay.py           — Arena (_rc_menu right-click)
modes/brawl_overlay.py           — Brawl (_rc_menu right-click)
modes/shared_vision.py           — Shared vision utilities
```

### Data Files
```
data/comp_state.json             — selected, pbe, ignore_emblems,
                                   client_panel_closed, built_items
data/meta/tft_set17_meta.json    — LIVE meta (45 comps, patch 17.1, BM data)
data/meta/tft_set17_pbe_meta.json — PBE meta (mirrors live)
data/meta/tft_set17_champion_codes.json — Champion team-planner hex codes
data/meta/tft_set16_meta.json    — Previous set (archived)
data/meta/cdragon_tft_pbe.json   — CDragon raw data
data/TFT guide author X_imgs/          — 27 board placement images (patch 17.1)
data/TFT guide author X_placements.json — Vision-analyzed board placements (24 comps)
data/tft_live_data.json          — Live TFT state (stage, round, augments, HP)
data/tft_coaching_data.json      — TFT coaching output buffer
data/coaching_data.json          — SR coaching output buffer
data/ratings/last_tft.json       — Last TFT game rating
```

### Config
```
config/coach_settings.json       — Coaching behavior settings
config/feature_flags.json        — Feature on/off flags
config/runtime.json              — Runtime tuning
config/settings.json             — General settings
```

### Ops (FROZEN — DO NOT TOUCH)
```
ops/rc_supervisor.py
ops/rc_self_monitor.py
ops/rc_incident_log.py
ops/rc_league_watcher.ps1
ops/run_self_healing_watchdog.ps1
ops/rc_transactional_deploy.py
ops/runtime/                     — health, status, circuit breaker state
ops/backups/                     — timestamped deploy backups (keep all)
ops/staging/                     — staged files for transactional deploy
```

### Launchers
```
run_watchdog.bat     — Start watchdog (required for restart_trigger to fire)
restart.bat          — Manual restart
restart_clean.bat    — Clean restart
run_lan_bridge.bat   — Start LAN bridge
kill.bat             — Emergency kill
```

---

## VANGUARD KARMA LEBLANC — ACTIVE COMP

```
Tier:         S (aggregator C) | S (TFT guide author X)
Level plan:   Fast 8 (4-2)
team_code:    0204402203703b01d01300003900d038TFTSet17

Lv4:  LeBlanc, Karma, Nami, Teemo
Lv7:  LeBlanc, Karma, Nami, Shen, Aatrox, Fiora, Morgana
Lv8:  + Nunu
Lv9:  + Akali, Blitzcrank

BIS Items:
  LeBlanc: Guinsoo (REQUIRED), Nashors Tooth, Last Whisper
  Karma:   Jeweled Gauntlet, Rabadons Deathcap (buffed), Archangels Staff
  Nunu:    Warmogs, Sunfire Cape, Dragon's Claw

Board (hex, rows 2+4 offset right):
  Row 4: Nunu(c2)  Aatrox(c3)  Shen(c4)   Fiora(c5)   [frontline]
  Row 3:           Morgana(c3)                          [CC midline]
  Row 2:           Nami(c3)    Akali(c4)               [flex/support]
  Row 1:           LeBlanc(c3)             Karma(c5)   [carries]

Double Up note:
  Partner: Space Groove vertical
  Shared: Sona, Nami (partner holds — you play without)
  Uncontested: LeBlanc, Karma, Aatrox, Fiora, Morgana, Akali

Key rule: NO GUINSOO = pivot to different comp.
```

---

## KNOWN OPEN ISSUES

| Issue | Priority | Notes |
|-------|----------|-------|
| P1-B OCR round counter | Medium | Needs in-game verify |
| Client panel TFT data | Medium | Verify round/placement during live game |
| TFT item icons | Low | Check data/icons/traits/ count |
| P3-E Patch detection | Low | core/version_check.py exists, not wired |
| Moon-PC offline | None | LAN bridge still running on Game-PC |

---

## CRITICAL OPERATING RULES

1. Restart → write to `restart_trigger.txt`. Never Stop-Process.
2. Kill if needed → `taskkill /F /PID <n>`
3. Compile before restart → `python -m py_compile <file>`
4. Atomic JSON writes → `.tmp` → `.replace(path)`
5. Watchdog → `run_watchdog.bat` must be active for trigger to fire
6. Python path → `C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe`
7. Inline Python via PowerShell → use file-based scripts to avoid quoting issues

---

## FROZEN BASELINES — NEVER MODIFY

```
ops/rc_supervisor.py
ops/rc_self_monitor.py
ops/rc_incident_log.py
ops/rc_league_watcher.ps1
ops/run_self_healing_watchdog.ps1
audit/phase6_kickoff_bundle_v13.zip   — Phase 1-6 canonical record
```
