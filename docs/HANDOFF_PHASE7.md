# HANDOFF_PHASE7.md
# Riot Commander — Phase 7 Continuation Handoff
# Date: 2026-04-15
# Written by: Claude (this session)
# For: Next Claude Desktop chat on Game-PC

---

## CRITICAL FIRST STEPS

1. Restart Claude Desktop on Game-PC (MCP pipe hung from Stop-Process call)
2. Run the pending fix scripts IN ORDER:
   ```
   cd "C:\Riot Commander"
   python fix_p3a.py
   python fix_p3b.py
   python fix_p3c.py
   python fix_p3d.py
   ```
3. Restart the app via trigger file (NEVER use Stop-Process — it hangs the MCP pipe):
   ```python
   # Write this via Filesystem MCP:
   # C:\Riot Commander\restart_trigger.txt  <- any content
   ```
4. Verify: `Get-Process python | Format-Table Id,CPU,StartTime`

---

## CRITICAL OPERATING RULES FOR THIS PROJECT

### NEVER DO THESE — they hang the MCP pipe for 4+ minutes:
- `Stop-Process`
- `Start-Process ... -PassThru` (when waiting on result)
- Any PowerShell command that waits on a new process

### ALWAYS restart the app this way:
```powershell
# Via Filesystem MCP write:
Set-Content "C:\Riot Commander\restart_trigger.txt" "reason_here"
# OR kill via taskkill (non-blocking):
taskkill /F /PID <pid> /T
```

### Python execution on Game-PC:
```powershell
$py = "C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
& $py "C:\Riot Commander\fix_script.py"
```

### Always compile-check before restart:
```powershell
& $py -m py_compile "C:\Riot Commander\tft\comp_control.py"
```

---

## CURRENT SYSTEM STATE (as of this handoff)

**Game-PC:** 192.168.8.237
**Moon-PC:** 192.168.8.230
**LAN Bridge:** http://192.168.8.237:8888/ (PID 11932, always running)
**App entry point:** `python main.py` (NOT app.py)
**Python path:** `C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe`

**App state:** Was running (PIDs ~7404, ~8380) before MCP hang
**Watchdog:** `run_watchdog.bat` / `restart_trigger.txt` mechanism

---

## WHAT WAS COMPLETED THIS SESSION

### P1-A: PBE/Live Data Separation ✅ COMPLETE
**Files changed:**
- `tft/comp_control.py`: `_load_meta(pbe=False)` routes to correct file; toggle reloads comp list
- `tft/tft_coach_engine.py`: trait_augment + double_up loaders read PBE flag from comp_state.json; comp section uses PBE-aware meta path
- `data/meta/tft_set17_pbe_meta.json`: CREATED (copy of live meta + `_data_type: pbe`)
- `data/meta/tft_set17_meta.json`: marked `_data_type: live`

**Behavior:** PBE checkbox CHECKED=PBE data, UNCHECKED=Live data. Toggle reloads comp list. State persists across restarts.

### P2-A: Emblem Toggle Fix ✅ COMPLETE
**Files changed:**
- `tft/tft_coach_engine.py`: reads `ignore_emblems` from comp_state.json; `_ignore_emb` guard on augment section

**Behavior:** When Emblems checkbox is unchecked, emblem advice is suppressed from all coach outputs.

### P2-B: Client Panel Close State ✅ COMPLETE
**Files changed:**
- `app.py`:
  - `__init__`: reads `client_panel_closed` from comp_state.json on startup
  - `_close_client_panel()`: calls `_persist_panel_state(True)`
  - `_reopen_client_panel()`: calls `_persist_panel_state(False)`
  - `_persist_panel_state()`: NEW METHOD — atomic write to comp_state.json
  - `_apply_mode()`: already had `getattr(self, "_client_panel_closed", False)` guard
  - `ROOT_PATH = SCRIPT_DIR` alias added

**Behavior:** Right-click → Close Panel persists across restarts. Panel does NOT reopen automatically.

### P2-C: Augment Reroll Advice ✅ COMPLETE
**Files changed:**
- `tft/tft_live_analysis.py`: `force_scan()` now clears `augment_choices`, `aug_take`, `aug_why` in tft_live_data.json when `augment_select=True`, so the new vision read produces a fresh recommendation

**Behavior:** CTRL+right-click during augment select clears old choices → forces fresh vision → new recommendation for rerolled choices.

---

## WHAT IS PENDING (P3 scripts ready but NOT yet run)

### Fix scripts are at `C:\Riot Commander\fix_p3*.py`
These were written by this session and are ready to run.

### P3-A: Item Selection → Coach Prompt
**Script:** `C:\Riot Commander\fix_p3a.py`
**What it does:**
- `tft/tft_coach_engine.py`: reads `built_items` from comp_state.json, injects into prompt ("BUILT ITEMS: X | Y — Do NOT re-recommend")
- `tft/comp_control.py`: `_toggle_built()` now passes `item_name` and writes `built_items` dict to comp_state.json via `_persist_built_items()`

**Verify after:** Click an item in the Units/Items panel → check comp_state.json has `built_items` → start TFT game → coach output should not recommend that item again.

### P3-B: Right-Click Menus All Mode Overlays
**Script:** `C:\Riot Commander\fix_p3b.py`

**NOTE:** Script was written in Claude container at `/tmp/fix_p3b_rightclick.py` but NOT yet pushed to Game-PC (MCP died before push). Need to recreate it.

**What it needs to do:**
- Add `_rc_menu(event)` method to `modes/aram_overlay.py`, `modes/arena_overlay.py`, `modes/brawl_overlay.py`
- Menu items: Force Refresh, separator, Hide Panel
- Bind `<Button-3>` in each class `__init__`
- TFT already has CTRL+right-click; add standard right-click too pointing at same force scan

**Files to change:** `modes/aram_overlay.py`, `modes/arena_overlay.py`, `modes/brawl_overlay.py`, `tft/tft_overlay.py`

### P3-C: Team Planner Group Name Alignment
**Script:** `C:\Riot Commander\fix_p3c.py`

**NOTE:** Script was in container at `/tmp/fix_p3c_teamplanner.py` — NOT yet on Game-PC.

**What it needs to do:**
- Read all comps from `tft_set17_meta.json`
- Write `team_planner_hex` mapping where group name == comp selector name exactly
- Update `_team_planner_note`

**Files to change:** `data/meta/tft_set17_meta.json`

### P3-D: Set 17 Comp Data Population
**Script:** `C:\Riot Commander\fix_p3d.py`

**NOTE:** Script was in container at `/tmp/fix_p3d_comps.py` — NOT yet on Game-PC.

**What it adds (13 new comps from aggregator C + TFT guide site Y, April 15 2026):**
- S tier: Transformers, Mirror Mayhem (Zed HA required), Capped and Loaded, Astral Meep
- A tier: Slap and Zap, Invader Zed, Anima Cashout, Rogue Diff, Mountain Stargazer, Twin Blades, Stay Groovy, Kindred Lucian
- B tier: Bonk

**After adding:** Total comps will be ~34. Run fix_p3c.py after to align team planner names.

---

## REMAINING PHASE 7 ITEMS (not yet scripted)

### P3-E: Patch/Version Detection
- Auto-detect League client version change
- If version changes and doesn't match meta `_live_launch` date, log warning in overlay
- Computer will be ON CST for patches — auto-detection must fire within one poll cycle
- **Files:** `main.py` or `tft/tft_state_reader.py` — add version check on startup

### OCR Round Counter Calibration
- OCR region for stage_round was widened to `(640, 4, 960, 46)` from `(668, 6, 932, 44)`
- Still needs in-game verification: watch the log for `OCR round=X-Y` during a TFT game
- If still drifting, may need a screenshot comparison during a live game
- **How to test:** Start a TFT game, watch `ops/runtime/logs/` for OCR debug lines

### TFT Client Panel Information Accuracy
- The client panel TFT tab (round, placement, units) pulls from `tft_live_data.json`
- Verify this is reading correctly during a live game
- Round counter fix (OCR widened) should improve this
- If still wrong: check `tft/tft_state_reader.py` `_parse()` return dict field names vs what ClientPanel reads

### Item Images in Units/Items Panel
- `_get_icon()` in `comp_control.py` looks in `data/icons/traits/*.png`
- Verify TFT item PNGs exist at that path
- If not: need to either download from CDragon or remap the icon directory
- **Check:** `dir "C:\Riot Commander\data\icons\traits\" | measure` — if count < 50, images are missing

---

## KEY FILE PATHS

```
C:\Riot Commander\                          — project root
C:\Riot Commander\main.py                   — entry point (use this, NOT app.py)
C:\Riot Commander\app.py                    — OverlayApp (client panel close state patched)
C:\Riot Commander\tft\comp_control.py       — PBE toggle, comp selector (patched P1-A, P3-A)
C:\Riot Commander\tft\tft_coach_engine.py   — TFT coaching (patched P1-A, P2-A, P3-A)
C:\Riot Commander\tft\tft_live_analysis.py  — vision + augment (patched P2-C)
C:\Riot Commander\tft\tft_ocr_reader.py     — OCR regions (region widened P1-B)
C:\Riot Commander\data\meta\tft_set17_meta.json      — LIVE server meta (21 comps, will be 34)
C:\Riot Commander\data\meta\tft_set17_pbe_meta.json  — PBE meta (CREATED this session)
C:\Riot Commander\data\comp_state.json      — selected comp, pbe, ignore_emblems, client_panel_closed, built_items
C:\Riot Commander\PHASE_7_KICKOFF.md        — full Phase 7 scope
C:\Riot Commander\fix_p3a.py               — READY TO RUN (item selection)
C:\Riot Commander\fix_meta.py              — old/stale, ignore
C:\Riot Commander\fix2.py                  — old/stale, ignore
C:\Riot Commander\diag.py                  — old/stale, ignore
```

---

## FROZEN BASELINES — DO NOT TOUCH

```
ops/rc_supervisor.py
ops/rc_self_monitor.py
ops/rc_incident_log.py
ops/rc_league_watcher.ps1
ops/run_self_healing_watchdog.ps1
```

Phase 1-6 authority:
- `app.py` = GameEnvelope authority
- `SrAramWorker` = non-TFT worker
- `TftWorker` = TFT worker
- `MetricsCache` = observability only

---

## COMP STATE AS OF THIS SESSION

```json
{
  "selected": "Brawler Timebreaker Reroll",
  "ignore_emblems": false,
  "pbe": true,
  "client_panel_closed": false,
  "built_items": {}
}
```

**NOTE:** `pbe: true` — Set 17 went live today (April 15). User should uncheck PBE in the comp selector to switch to live server data path.

---

## HOW TO VERIFY EVERYTHING WORKS

1. **PBE/Live routing:** Toggle PBE checkbox → comp list reloads → check log for `meta loaded: tft_set17_pbe_meta.json (pbe=True)` vs `tft_set17_meta.json (pbe=False)`

2. **Emblem toggle:** Uncheck Emblems → start TFT game → coach output should have zero "emblem" or "crest" recommendations

3. **Client panel close state:** Right-click overlay → Close Panel → restart app → panel should stay closed

4. **Augment reroll:** During augment select round, CTRL+right-click → `aug_plan` field should show "Rescanning augment choices..." → new recommendation appears

5. **Item selection (after P3-A):** Click item in Units/Items panel → check `comp_state.json` has `built_items` entry → coach output should say "BUILT ITEMS: X — do not re-recommend"

---

## MCP HANG PREVENTION

The MCP pipe hangs when PowerShell commands block waiting on child processes. Specific triggers:
- `Stop-Process` (hangs for 4+ min)
- `Start-Process ... -PassThru` with wait

**Safe alternatives:**
- `taskkill /F /PID <n>` — non-blocking process kill
- Write `restart_trigger.txt` — watchdog handles restart
- `Start-ScheduledTask` — fire and forget

---

## PHASE 7 COMPLETION STATUS

| Item | Status |
|------|--------|
| P1-A PBE/Live routing | ✅ Complete |
| P1-B Round counter OCR | 🔶 Partial — region widened, needs in-game verify |
| P2-A Emblem toggle | ✅ Complete |
| P2-B Client panel close | ✅ Complete |
| P2-C Augment reroll | ✅ Complete |
| P3-A Item selection | 🟡 Script ready, not run |
| P3-B Right-click menus | 🟡 Script in container, not on Game-PC |
| P3-C Team planner names | 🟡 Script in container, not on Game-PC |
| P3-D Comp data (34 comps) | 🟡 Script in container, not on Game-PC |
| P3-E Patch detection | ⬜ Not scripted yet |
