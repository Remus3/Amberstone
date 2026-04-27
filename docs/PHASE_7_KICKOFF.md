# PHASE_7_KICKOFF.md
# Riot Commander -- Phase 7 Kickoff
# Date: 2026-04-15
# Baseline: Phase 6 complete (Fix Pack 1 + Fix Pack 2A/2B + all doc alignment passes v7-v13)
# Author: Claude (implementation) + ChatGPT (doc audit)

---

## Phase 7 Mission

Phase 6 delivered a stable, truthful coaching overlay.
Phase 7 delivers a CORRECT and COMPLETE one.

The gap: game data routing is wrong (PBE data leaks into live, live data leaks into PBE),
the TFT client panel shows stale/wrong information constantly, comp data is incomplete,
and several UI interaction promises (emblem toggle, right-click menu, item selection,
augment reroll advice) do not work as described.

Phase 7 fixes all of this. No architecture redesigns — targeted, verifiable fixes.

---

## Section 1: PBE / Live Server Data Separation

### Problem
PBE data is being pulled into live-server matches and live data into PBE matches.
Incorrect units, items, and comps appear in coach outputs and the client panel.
Set 17 goes live today (April 15, 2026 CST). Data routing must be correct immediately.

### Required behavior
- PBE checkbox in TFT comp selector:
    CHECKED   = force PBE data path for all coach outputs and comp lookups
    UNCHECKED = force Live server data path (override, not just preference)
    Last state persists across restarts (already implemented — preserve this)
- When PBE=OFF: all coach outputs, comp lookups, unit names, item names, and
  tier lists must come exclusively from the live server meta file
- When PBE=ON: all of the above must come exclusively from the PBE meta file
- No cross-contamination: a unit that exists only in PBE must never appear in
  live coaching output, and vice versa
- Patch version detection: when League/TFT patches (Riot client version changes),
  auto-detect the new version and log it. If the detected version does not match
  the active meta file's declared version, surface a warning in the UI.
  Computer will be on CST when the patch goes live — auto-detection must fire.

### Files to audit and fix
- tft/comp_control.py: _load_meta() path selection logic
- tft/tft_coach_engine.py: all meta references
- tft/tft_pbe_data.py / tft/tft_pbe_engine.py: verify they are correctly isolated
- data/meta/tft_set17_meta.json: verify _live_launch date and set name
- data/meta/cdragon_tft_pbe.json: verify PBE-only units are not in live meta

---

## Section 2: TFT Round Counter and Client Panel Correctness

### Problem
- Round counter is wrong 99% of the time
- Right-now advice always says "level 6" or "x9 XP rolls to level" regardless of
  actual stage — this is downstream of a bad round/stage value
- Client panel (tabbed UI) shows incorrect units, incorrect placement rank,
  incorrect round for many matches

### Root cause hypothesis
- Stage/round parsing from OCR or API is drifting — needs to be verified against
  the actual Riot Live Client API response structure for Set 17
- The stage map used for tempo advice (_TEMPO dict) may have wrong round keys
  for Set 17 now that Carousel is replaced by Realm of Gods

### Required fixes
- Audit tft_state_reader.py OCR round parsing vs Riot API round field
- Audit tft_coach_engine.py _build_prompt() stage/round values passed to model
- Audit _tempo_context() round keys against Set 17 actual stage structure
  (Set 17 removed Carousel rounds 2-4, 3-4, 4-4 — these are now God Boon rounds)
- Fix client panel TFT tab to show correct stage, round, and alive count
- Verify placement rank display uses the same truthful logic as the overlay

---

## Section 3: Emblem Toggle Fix

### Problem
The "Emblems" checkbox in the TFT comp selector does not affect coach outputs.
Coach still outputs "get Brawler emblem" / "Brawler crest worth" type advice even
when the checkbox is unchecked (no emblem available).

### Required behavior
- UNCHECKED: coaching prompt and comp selector must treat all emblem-dependent
  comp variations as unavailable. No emblem advice in any output field.
- CHECKED: emblem advice enabled as today.
- The toggle must propagate to:
    - tft/comp_control.py: comp row highlighting (already exists, may be broken)
    - tft/tft_coach_engine.py: _build_prompt() must suppress emblem lines when
      ignore_emblems=True
    - data/comp_state.json: ignore_emblems field must be read by coach engine

### Files to fix
- tft/comp_control.py: verify _save_state() writes ignore_emblems correctly
- tft/tft_coach_engine.py: verify _build_prompt() reads comp_state.json and
  suppresses emblem advice when ignore_emblems=True
- tft/tft_overlay.py: if any emblem advice surface exists, add the same guard

---

## Section 4: Augment Reroll Advice

### Required behavior
When the augment selection screen appears:
1. First vision scan fires immediately on augment_select=True
2. Coach outputs one-time "TAKE X — reason" recommendation based on selected comp
3. Player can press the refresh/force-scan button to reroll augment options
4. Second scan fires and produces updated recommendation for the new choices
5. Coach does NOT repeat the same recommendation on subsequent refreshes —
   it re-evaluates the new choices every time

### Files to audit
- coaches/aram_coach.py: augment_select path (reference implementation)
- tft/tft_coach_engine.py: augment select prompt construction
- tft/tft_live_analysis.py: augment_select detection + choices parsing
- tft/tft_overlay.py: force-scan binding (CTRL+right-click)

---

## Section 5: Item Selection Integration

### Problem
Selecting items as "built" in the Units/Items panel does nothing to coach outputs.
Item images are also not displaying — only text names show.

### Required behavior
- When a player marks an item as built on a unit, the coaching prompt must reflect
  this: "Ezreal has Guinsoo's — next priority is IE or LW"
- Item images must load from the correct asset path
- Built items must be written to comp_state.json and read by tft_coach_engine.py

### Files to audit
- tft/comp_control.py: item selection state write path
- tft/tft_coach_engine.py: item state read in _build_prompt()
- tft/tft_overlay.py: item image asset loading
- assets/: verify TFT item images exist and paths are correct

---

## Section 6: Right-Click Menu and Always-On Client Panel

### Problem 1: No right-click game mode menu
SR/ARAM/Arena/Brawl overlays have no right-click context menu.
TFT has limited right-click. All game modes should have a consistent right-click
menu matching the options available in client mode.

### Problem 2: Client panel always reopens
After right-clicking and closing a panel, Riot Commander reopens the client mode
panel on every restart and on every game-end transition.

### Required behavior
- Right-click menu on all overlay panels:
    - Force refresh / scan
    - Toggle mode (SR/ARAM/Arena/Brawl/TFT)
    - Hide panel
    - Settings
- Client panel close state must persist. If the user right-clicks and closes it,
  it must not reopen until explicitly reopened or the user starts a new game.
- Even when League of Legends / TFT are NOT running, the client panel should
  respect its last closed/open state.

### Files to audit
- overlay.py: panel lifecycle and close/reopen logic
- ui/client_panel.py: close state persistence
- app.py: mode transitions and panel rebuild triggers

---

## Section 7: Comp Data Quality and Team Planner Group Names

### Required
- Evaluate at minimum: TFT guide site W, TFT guide site Y.com, aggregator C/tft, TFT aggregator T
  for Set 17 comp data. Cross-reference for tier, units, items, augments.
- Populate tft_set17_meta.json with accurate, cross-referenced comp data.
  Current comp list has 21 entries — should have 30-40 for full coverage.
- Team planner group names must match the comp list names exactly so the
  in-client team planner import finds the right comp immediately.
- Each comp entry must have: tier, core_units, lv4/lv7/lv8, items (all core
  units), target_stars, gameplan, stage_plan, augments_best, team_code.

---

## Section 8: All-Modes Information Audit

Every mode coach and overlay must be verified for correctness against Set 17 /
current live data. Specific items:

### TFT
- God Boon rounds replace Carousel at 2-4, 3-4, 4-4
- Realm of Gods mechanic at 2-4: choose a God for boons/blessings
- Stage tempo advice must reflect these new round structures
- Unit pool verified against Set 17 champions list
- Trait list verified against Set 17 trait list
- Item names verified (no Set 16 item names in Set 17 outputs)

### SR / ARAM / Arena / Brawl
- No PBE-only unit names in coach outputs
- No stale Set 16 / old patch references in system prompts
- Arena round and rank display verified still correct post-Set-17-launch

---

## Section 9: Phase 7 Execution Order

Priority 1 (day-1 critical — Set 17 live today):
  P1-A: PBE/Live data separation and routing fix
  P1-B: Round counter and stage/tempo fix
  P1-C: Comp data population for Set 17 live

Priority 2 (this week):
  P2-A: Emblem toggle propagation to coach engine
  P2-B: Client panel close state persistence
  P2-C: Augment reroll advice flow

Priority 3 (next week):
  P3-A: Item selection integration
  P3-B: Right-click menu all modes
  P3-C: Team planner group name alignment
  P3-D: Full all-modes information audit

Architecture-exception (deferred, explicit reopen required):
  B3: Arena team HP via ArenaVisionReader

---

## Section 10: Phase 7 Frozen Baselines

These files must NOT be touched in Phase 7:
  ops/rc_supervisor.py
  ops/rc_self_monitor.py
  ops/rc_incident_log.py
  ops/rc_league_watcher.ps1
  ops/run_self_healing_watchdog.ps1

Phase 1-6 authority boundaries remain in force:
  app.py = GameEnvelope authority
  SrAramWorker = non-TFT worker
  TftWorker = TFT worker
  MetricsCache = derived observability only
  feature_policy = advisory/gating only

---

## Section 11: Phase 6 Completion Record

All Phase 6 safe-on-frozen-baseline work is complete.

  Fix Pack 1 (Steps 2, 2.1, 3): 8 items complete
  Fix Pack 2A (Steps 4, 4.1):   4 items complete
  Fix Pack 2B (Step 5):          1 item complete
  Doc alignment (v7-v13):        complete

  Active kickoff bundle: audit/phase6_kickoff_bundle_v13.zip
  Open architecture item: B3 (Arena HP vision) — deferred to Phase 7 P3 or later

---

## Patch Version Watch

Set 17 (Space Gods) goes live April 15, 2026.
Computer will be ON in CST when the patch deploys.
Target: auto-detect version change and switch Live meta to Set 17 within
one polling cycle of the patch going live. No manual intervention required.
