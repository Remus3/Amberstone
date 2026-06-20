# RC 2.0 - Master Orchestration Plan

LIVING DOC. Single source of truth for the RC 2.0 program. `/RC2-Continue`
reads this, finds the first non-DONE stage (top-to-bottom), and resumes.
Continuity = this file + git history + `docs/LEDGER.md` + the directive chain.

ASCII only. No em-dashes, en-dashes, or smart quotes.

---

## PROGRESS

> **Design GREENLIT (Hextech); operator batch E1-E12 added - Stage 35 of 62 - approx 56% complete**
>
> _(% recomputed: 12 approved execution stages E1-E12 added to the 50 base = 62 total. Done: 28 base (+3.1 overlay condensation spec, +3.2 overlay structure/density: arbitration primitive + density clamp, +3.3 overlay shadow-wire S0 arbitration + 44px choice hit-target [LIVE: pulse flip operator-gated], +3.4 dashboard-persist keepCompanion/pin toggles reachable from overlay UI, +3.5 settings-without-hotkeys: no-hotkey Force vision scan control, +3.6 dashboard condensation: collapse empty KV rows in RIGHT NOW + NEXT, +4.1 DPI + resolution-aware overlay sizing, +4.2 non-intrusive overlay: click-through zones + opacity + auto-hide idle recede, +4.3 single-monitor separated-window arrangement, +4.4 settings-UI no-hotkey overlay actions: #ovset panel-set selector + interact-now button) + E3 win-capture + E5 hold-band + E8 design-system + E6 spell-fix + E9 rank/scouting + E4 counter-picks/ban-collapse + E1 persist/pinned/panel-toggles = 35. 35/62 = 56.5% -> ~56%. First non-DONE now Phase 4 stage 4.5.)_

Recompute on every stage flip: `% = DONE_stages / TOTAL_stages * 100`.
If stages are added or removed, update TOTAL and re-derive the percent so the
banner always reflects the live denominator (operator directive: redo the % to
match up or down even as phases/stages grow).

Status legend: `OPEN` (not started) - `WIP` (in flight) - `DONE` (shipped, sha) - `GATE` (operator greenlight pending) - `LIVE` (code done, live-game visual owed).

---

## OPERATOR DIRECTIVE (2026-06-19, verbatim intent)

Exhaustive UI/UX research (League + non-League) -> implement headlessly via
Gemini -> Electron overlay sizing studied against how other apps do it -> deep
research on League apps/utilities/visual-effects/operation/useful-info for every
game surface (home / pregame lobby / champ select / in-match / PGR / history /
timeline) -> multiple UI-agent passes condensing in-game priority info on BOTH
overlay and dashboard -> Haiku-free laning coach tuned for local CV (not Sonnet)
-> ABC choices more specific + condition-change best-path branching -> mid/late
game + objective plays + lost-objective/stagnation response -> faster LCU
champ-select polling (all modes) + UI responsiveness without blowing out ports +
a push/pull-with-League timing map -> dashboard STAYS while overlay active
(currently disappears) -> massive operator-Q/A TODO+future list -> a visual+text
HTML of whole-app design choices (any theme, free of the current layout; if
greenlit it REPLACES the current design) -> single-monitor-friendly, non-intrusive
in-game overlay, every setting changeable WITHOUT hotkeys, separated windows OK ->
ASCII-violation sweep of all old files (kill the warning) -> project-folder cleanup
of files unused >1 week -> DS true-completeness gap analysis -> then a 2nd full
iteration (Gemini-gated to make headless). This becomes RC 2.0.

## POLICY (this program)

- **No budget.** Claude/executor spend uncapped. Gemini spend capped by `ops/loop/config.json` ceiling (runaway backstop only).
- **Gemini-credit fallback:** if Gemini runs out of credits, proceed on best recommended judgment. Do NOT default decisions back to the operator.
- **Frozen-file edits AUTHORIZED** for this program (operator grant 2026-06-19).
- **Full computer usage AUTHORIZED:** download / install / run applications as needed (operator turned off the 2nd monitor to fix default app placement).
- **Swarm:** orchestrate up to 100 parallel agents (worktree-isolated on disjoint file sets, sole merger, verifier-gate before merge). No session cap - report `Phase X of 9, Stage Y of N, ~Z%` each cycle.
- **Per-stage ritual:** TDD (failing test first where logic) -> py_compile before restart -> tiered verification (R5-R7) -> UI stages also run the 5-phase fixture audit + Claude_Preview vs /api/state -> commit + push + CI green -> `/done` ritual (append `docs/LEDGER.md`, sync this file + ROADMAP).
- **DS seams** ship DEFAULT-OFF, Meraki + rewind WIN anchored, ENGINE bump + DS :8893 restart + Share sync in the same commit; live default-ON flip is EXCLUDED -> `docs/LIVE_GAME_GATED_SYNC.md`.
- **Cadence:** use AHK / Gemini / commit+push+CI / `**/done` / `**/clear` / `**/continue` appropriately across cycles.
- **Greenlight gate:** the P2 design HTML is the ONE operator-review artifact. Everything else proceeds without mid-run gating. The full redesign cutover (P3+ replacing the current layout) is gated on that greenlight; if not yet given, P3+ build the NEW design behind a flag and keep the current design live.

## DECISIONS (operator, 2026-06-19)

- **Remote control:** desktop computer-use control ENABLED for app install + window placement (request_access on first desktop task). The operator connects their phone via their own `**/remote-control` command to type into this session mid-match.
- **Theme:** build 3 themes side-by-side into `RC2_DESIGN.html`; operator picks on review.
- **In-game primary surface:** OVERLAY-CENTRIC - a lean glanceable HUD on top of the game; the full dashboard is one toggle / 2nd window away and STAYS available (fixes the disappear bug).
- **League window:** 1920 fullscreen OR borderless default-res both acceptable; the overlay may assume this.
- **Greenlight = HARD PAUSE on redesign code (Phase 3 + Phase 4) after the Phase 2 HTML.** The non-redesign phases CONTINUE meanwhile: P5 coaching, P6 responsiveness, P7 hygiene, P8 TODO/DS-gap (none are "redesign code"). Resume P3/P4 only on operator greenlight of `RC2_DESIGN.html`.

## GREENLIGHT + OPERATOR DECISIONS (2026-06-20)

Design GREENLIT: theme = **Hextech Tactical**. P3/P4 redesign code is UNBLOCKED
(reskin to Hextech). League now runs **borderless @ 2560x1440** (overlay sizing
target). New global ask: **per-panel visibility toggles, separate for in-game vs
out-of-game** (Settings).

TOP-10 answers (from docs/RC2_TODO_QA.md):
1. **Dashboard persists in background while overlay active** + add a **pinned-on-top** setting. [P3.4]
2. **DS 3-game live-flip eyeball pass - APPROVED ("ready to start").** 11 default-OFF seams; needs live games. Prep the flip checklist/harness; flips are operator-played. [P2-DS / docs/LIVE_GAME_GATED_SYNC.md]
3. **End-of-game win capture - APPROVED.** Keystone (tracked_win on disk, not loaded). Operator note: after a match + honor page, re-entering lobby auto-flipped to PGR - verify the win was captured + that PGR auto-show does not clobber a wanted lobby view. [#3 win-capture]
4. **Counter-picks vs live enemy comp - APPROVED** + banned champions display COLLAPSES when the ban phase ends. [champ-select]
5. **Laning off Haiku + hold-band recalibration - APPROVED** (Tier-2 recalibration + regen, not blind). [P5.1]
6. **Responsiveness levers L1/L2/L4 - APPROVED** + FIX the summoner-spell flip-back: stop the poll loop re-pushing the default over a manual change; **% under spells = champion regional WR% for the mode**; on first lock pick the **highest-role-centric-WR spells**; **remember the operator's last-used spells per champion per mode**. [P6 + spell feature]
7. **LCU connection pooling - APPROVED now** (frozen lcu_client.py edit OK) + **ARAM bench-swap must be EXTREMELY responsive** (bench_swap_fast already bypasses the 5s client delay; tighten detection/latency). [P6.4 + bench]
8. **Accessibility/design HIGH-lifts - APPROVED** (reduced-motion-done-right + redundant status glyphs + threshold helper). [P3 design-system]
9. **Rank header + player scouting - PROMOTE BOTH to NOW.** [home rank + Riot scouting]
10. **ASCII retro-sweep - APPROVED: ALL files, frozen INCLUDED, git HISTORY INCLUDED** (history rewrite + force-push, pre-authorized). [P7.1 + history filter]

### Operator-approved execution batch (E-stages, added to TOTAL)
| E | Item | Status | Commit |
|---|------|--------|--------|
| E1 | Dashboard persist-in-bg + pinned-on-top + per-panel in/out-game toggles | DONE | overlay_state.keepCompanion + companionAlwaysOnTop + panel_visibility.js (needs rc-shell relaunch) |
| E2 | DS 3-game live-flip eyeball pass (operator-played, live-gated) | OPEN | |
| E3 | End-of-game win capture (history/home W/L + season WR) | DONE | ad4c9906 |
| E4 | Counter-picks vs live enemy comp + ban-phase collapse | DONE | GET /api/champ-select/counter-picks + _csvBanPhaseComplete collapse |
| E5 | Laning hold-band recalibration (shadow vocabulary) | DONE | 4da01fbe |
| E6 | Spell flip-back fix + WR% under spells + highest-role-WR on lock + remember last-used per champ/mode | DONE | _sync_spells per-lock idempotency + manual-override + WR route |
| E7 | ARAM bench-swap responsiveness + LCU connection pooling (frozen lcu_client.py) | OPEN | |
| E8 | Design system: reduced-motion-done-right + status glyphs + threshold statusFor() | DONE | 19f8116f |
| E9 | Rank/tier/LP header + player scouting (both NOW) | DONE | core/lcu_ranked.py + routes_scouting.py; Riot key = API-Key-Riot.txt via core/riot_api.py |
| E10 | ASCII retro sweep (all files, frozen) + git-history rewrite + force-push | OPEN | |
| E11 | Hextech reskin across surfaces (P3/P4 visual cutover) | OPEN | |
| E12 | Responsiveness levers L1/L2/L4 (SSE/build TTL halve, etc.) | OPEN | |

TOTAL_stages = 62 (50 base + 12 E-batch).

## EXECUTION MODEL

Headless via the Gemini-directed loop (`.claude/commands/gemini-headless-upgrade.md`
+ `ops/loop/`). Each cycle: director picks the first non-DONE stage here, executor
runs the swarm for it, `/done`, `/clear`, `/continue`. Resume after any interrupt
with `/RC2-Continue`. Background-task pane (TaskCreate) carries one chip per phase
so the operator sees gray/blue progress live.

---

## STAGES

### Phase 1 - RESEARCH (exhaustive; output -> docs/research/RC2_*.md)
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 1.1 | Electron/overlay sizing + DPI + click-through: how Overlay App E/Overlay App F/Aggregator C/aggregator A/Aggregator B overlays, OBS, RTSS, Discord overlay size + place an in-game HUD | DONE | docs/research/RC2_RESEARCH_overlay_sizing.md |
| 1.2 | League home/profile dashboard landscape sweep | DONE | docs/research/RC2_RESEARCH_home_profile.md |
| 1.3 | Pregame lobby UX references | DONE | docs/research/RC2_RESEARCH_lobby.md |
| 1.4 | Champ-select UX references (all modes) | DONE | docs/research/RC2_RESEARCH_champ_select.md |
| 1.5 | In-match overlay references: density, glanceability, what-to-show | DONE | docs/research/RC2_RESEARCH_in_match_overlay.md |
| 1.6 | PGR / post-game-review references (aggregator G / league-of-graphs class) | DONE | docs/research/RC2_RESEARCH_pgr.md |
| 1.7 | History / match-list references | DONE | docs/research/RC2_RESEARCH_history.md |
| 1.8 | Timeline-breakdown references (gold graphs, teamfight timelines) | DONE | docs/research/RC2_RESEARCH_timeline.md |
| 1.9 | Non-League UI/UX + visual-effects/design-language refs (glanceable HUDs, dark telemetry dashboards) | DONE | docs/research/RC2_RESEARCH_nonleague_uiux.md |

### Phase 2 - DESIGN SYNTHESIS (the greenlight gate)
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 2.1 | Information architecture: what info lives where across surfaces, single-monitor model | DONE | docs/design/RC2_DESIGN.html |
| 2.2 | Color-theme + design-language options (>=3 themes) | DONE | docs/design/RC2_DESIGN.html |
| 2.3 | Overlay layout mockups (in-game, non-intrusive, glanceable) | DONE | docs/design/RC2_DESIGN.html |
| 2.4 | Dashboard layout mockups (single-monitor, settings-without-hotkeys) | DONE | docs/design/RC2_DESIGN.html |
| 2.5 | DELIVERABLE: docs/design/RC2_DESIGN.html (visual+text, multiple options) | DONE | GREENLIT 2026-06-20: theme=Hextech; replaces current design on P3/P4 |

### Phase 3 - OVERLAY + DASHBOARD QUICK-GLANCE (multi UI-agent)
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 3.1 | In-game priority-info condensation spec (glance test) | DONE | docs/research/RC2_OVERLAY_CONDENSATION_SPEC.md |
| 3.2 | Overlay UI-agent pass 1 (structure/density) | DONE | web/js/lib/overlay_priority.js (`39303acb`) + callout 2-row clamp (`db6f77d4`) |
| 3.3 | Overlay UI-agent pass 2 (typography/hit-targets/hierarchy) + wire right_now.js/overlay_pulse.js to shouldPulse (spec-flagged behavior change; shadow + 5-phase audit + operator eyeball) | LIVE | `87f41baf` shadow-wire (signalFromState + data-s0-* stamp) + 44px choice hit-target; pulse flip owed -> LIVE_GAME_GATED_SYNC.md |
| 3.4 | Dashboard STAYS when overlay active (currently disappears) - fix | DONE | `183f1969` (E1 `a61703ef` shell mechanism + web keepCompanion/pin toggles) |
| 3.5 | Settings-without-hotkeys surface | DONE | `f2bdb2fa` (no-hotkey Force vision scan Settings control; the lone hotkey-only action now keyboard-free; backend /api/command force_vision pre-existed) |
| 3.6 | Dashboard UI-agent condensation passes | DONE | `web/js/lib/condense.js` (`2d347dc0`) - condenseKvRows collapses empty supporting KV rows in RIGHT NOW + NEXT |

### Phase 4 - SINGLE-MONITOR + OVERLAY UX
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 4.1 | Electron overlay sizing/DPI/multi-res correctness | DONE | `4d5d54f0` overlay_state.resolveOverlayMetrics (DPI-guarded, work-area scale) + main.js window-size + ovscale -> web overlay.css `--rc-overlay-scale` zoom |
| 4.2 | Non-intrusive overlay (click-through zones, opacity, auto-hide) | DONE | `85d6b29e` effectiveIgnoreMouse + clickthrough_zones.js hover detector + setOpacity slider + overlay_idle.js idle recede (data-rc-idle) |
| 4.3 | Single-monitor window management (separated windows OK) | DONE | `1a96b764` overlay_state.resolveSeparatedCompanionBounds + rectsOverlap + separateWindows setting; main.js applySingleMonitorLayout (single-display-gated, reposition-only) + #ovset Separate-windows toggle |
| 4.4 | Settings UI: no-hotkey control of everything | DONE | `7de74b2c` overlay-action IPC: #ovset panel-set selector + interact-now (overlay_state.normOverlayAction allow-list; main.js applyPanelSet/setOverlayActive shared with the cycle/active hotkeys); hide stays a hotkey by design |
| 4.5 | Overlay + dashboard coexistence | OPEN | |
| 4.6 | Live-game visual validation (gated) | OPEN | |

### Phase 5 - COACHING ENGINE
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 5.1 | Haiku-free laning coach tuned for local CV (off Sonnet/Haiku in laning) | OPEN | |
| 5.2 | CV signal integration for laning verdicts | OPEN | |
| 5.3 | ABC choices specificity uplift | OPEN | |
| 5.4 | Condition-change branching (best path when conditions change) | OPEN | |
| 5.5 | Mid-game playbook | OPEN | |
| 5.6 | Late-game + objective plays | OPEN | |
| 5.7 | Lost-objective / stagnation response playbook | OPEN | |

### Phase 6 - RESPONSIVENESS (without blowing out ports)
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 6.1 | LCU/LiveClient push/pull function + timing map (document RC<->League I/O cadences) | DONE | docs/research/RC2_RESEARCH_io_timing_map.md |
| 6.2 | Faster champ-select LCU polling (all modes), port-safe | DONE | RuneWriter 2.0s->1.0s env-tunable; tests/test_runewriter_poll_interval_rc2.py |
| 6.3 | UI responsiveness (render cadence, debounce, no-store idempotency) | OPEN | |
| 6.4 | Port-safety audit (connection reuse, no fan-out storms) | OPEN | |
| 6.5 | State-pipeline latency reduction | OPEN | |
| 6.6 | Verify no port/CPU footprint regression | OPEN | |

### Phase 7 - HYGIENE
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 7.1 | ASCII-violation full sweep of old files (kill the startup warning) | OPEN | |
| 7.2 | Stale-file census: .md/scripts unused >1 week of iterations | OPEN | |
| 7.3 | Dead-code / unused-asset removal (safety-verified) | OPEN | |
| 7.4 | Repo folder reorg | OPEN | |
| 7.5 | Verify dual suite green post-cleanup | OPEN | |

### Phase 8 - TODO/FUTURE + DS-COMPLETENESS
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 8.1 | Massive operator-Q/A TODO + future list -> docs/RC2_TODO_QA.md | DONE | docs/RC2_TODO_QA.md (97 items, 9 sections, TOP-10 decisions) |
| 8.2 | DS true-completeness gap analysis -> docs/DS_COMPLETENESS_GAP.md | DONE | docs/DS_COMPLETENESS_GAP.md |
| 8.3 | Operator Q/A consolidation | OPEN | |

### Phase 9 - ITERATION 2 (Gemini-gated to make headless)
| # | Stage | Status | Out |
|---|-------|--------|-----|
| 9.1 | Re-run research sweep (delta-focused) | OPEN | |
| 9.2 | Re-run design synthesis | OPEN | |
| 9.3 | Final consolidation + RC 2.0 banner | OPEN | |

TOTAL_stages = 50.

---

## RESUME PROTOCOL (`/RC2-Continue`)

1. Read this file; find the first stage not `DONE`/`CLOSED` (top-to-bottom).
2. If it is `GATE` and the operator has not greenlit, build behind a flag and move on (do not block).
3. Recompute the PROGRESS banner.
4. Sync the background-task pane (one chip/phase; mark active phase WIP).
5. Run the per-stage ritual for that stage; flip it DONE with the commit sha; loop.
6. On full drain (all stages DONE): run Phase 9 once, then emit the RC 2.0 banner and stop.

## DELIVERABLE INDEX

- Research: `docs/research/RC2_RESEARCH_*.md`
- Design HTML (greenlight): `docs/design/RC2_DESIGN.html`
- Operator Q/A TODO: `docs/RC2_TODO_QA.md`
- DS completeness gap: `docs/DS_COMPLETENESS_GAP.md`
- Per-item ledger: `docs/LEDGER.md` (RC2-* entries)

## FINDINGS LOG (RC2)

- **P4.4 SHIPPED** (`7de74b2c`): Settings UI - no-hotkey control of everything. The overlay's THREE global hotkeys (Alt+Shift+O show/hide, Alt+Shift+A passive<->active, Alt+Shift+C cycle panel set) were the last overlay behaviors reachable ONLY by keyboard (3.5's audit already proved every OTHER action keyboard-free). 4.4 surfaces the two that make sense as on-screen #ovset controls over a NEW one-way renderer->main action channel. (1) PANEL-SET segmented selector (Coach/Build/Threat) - the on-screen twin of the Alt+Shift+C cycle; lights the active segment from `document.body.dataset.panelset` (no shell round-trip - the page already carries `?overlay=1&panelset=NAME`), a pick fires `set-panel` and the shell persists it + reloads the overlay window onto that set. (2) "Interact now" button - the twin of Alt+Shift+A; fires `set-active`, the shell forces ACTIVE (interactive) with the same 20s auto-revert. The hide/show toggle (Alt+Shift+O) STAYS a hotkey BY DESIGN: it clears BOTH surfaces (panic clear-screen, resolveSurface->HIDDEN hides companion AND overlay), so a self-hiding on-screen control would leave no on-screen way back (a 4.5 coexistence concern if an out-of-game overlay-visibility toggle is ever wanted). PURE (`overlay_state.js`): `OVERLAY_ACTIONS` Object.freeze allow-list `["set-panel","set-active"]` + `normOverlayAction(raw)` - the security boundary the main process trusts (only a listed action passes; `set-panel` additionally requires a real `normPanelSet` target, case/whitespace-insensitive on both fields; toggle-hidden + any malformed/array/non-object -> null -> no-op). `main.js` `applyPanelSet(next)` (persist via `mergeOverlayPatch` + reload `overlayUrl`) + `setOverlayActive()` (clickThrough=false + applyClickThrough + scheduleActiveRevert) are the SHARED primitives the Alt+Shift+C/A hotkeys AND the IPC both call - the cycle hotkey was refactored onto `applyPanelSet` so the keyboard + on-screen paths can never drift. `preload.js` exposes `overlayAction(msg)` as a one-way `ipcRenderer.send` (a command needs no reply); `ipcMain.on("rc-shell:overlay-action")` validates through `normOverlayAction` then dispatches. WEB: `overlay_settings.js` `sendOverlayAction(msg)` (bridge-only - these are RUNTIME COMMANDS not persisted settings, so NO localStorage mirror; a plain browser with no `window.rcShell` is a silent no-op). `overlay_ds_controls.js` adds the selector + button to `_settingsHtml`, the delegated-click wiring in `_wireSettings`, `_currentPanelset()` + `_markActivePanelset()` reflection, called once in `_ensureScaffold`. `overlay_ds_controls.css` styles `.ovset-seg`/`.ovset-seg-btn`/`.ovset-act` at the `--hit-min` floor with `--fs-xs` labels + the `.is-active` lit segment (`--signal-info`) - no new hex literals beyond the tokens.css fallbacks. TDD RED-first: rc-shell node 240/240 (`overlay_state.test.js` +5 normOverlayAction/allow-list; `overlay_settings_ipc.test.js` +3 action-channel wiring); `tests/test_overlay_settings_panel_dom.py` 33 (+8 `Rc2Stage44ControlsTests`: control ids, action wiring, helper export, active-reflection, hit-floor + token typography); real-Chromium `test_overlay_view.py` 19 (+2: the selector + button render at the 42px floor with ASCII labels + no segment lit on the full subset; `panelset=build` lights EXACTLY the Build segment via aria-pressed + .is-active) = the durable 5-phase fixture audit. Tier-1 web/shell JS+CSS; NO ENGINE/DS/Share/schema/frozen-Python (rc-shell/* is the Electron shell, not frozen `main.py`); precommit ds_share_sync confirmed no DS source staged -> no Share drift. 5-phase fixture audit PASS (0 MUST-FIX): STRUCTURE two additive `.ovset-row`s in the #ovset flex column (3 equal-flex segments + a full-width button, no reflow); TYPOGRAPHY `--fs-xs` labels; HIT-TARGETS both clear the 42px floor (Chromium-asserted); ASCII 0 banned glyphs (10 files byte-scanned); HIERARCHY supporting chrome, the lit segment shows the current set at a glance. Renderer auto-reloads (ADR-008 asset-hash; live `:8888` serves the updated controls HTTP 200, markers present); the rc-shell Electron MAIN process needs a relaunch for the new IPC handler + applyPanelSet/setOverlayActive (same operator-accepted pattern as E1/P4.1/4.2/4.3). LIVE composited-over-League eyeball at 2560x1440 borderless OWED (operator-gated, NEVER blocks) -> `docs/LIVE_GAME_GATED_SYNC.md`. The Hextech reskin of the new controls rides E11's global token cutover.
- **P4.3 SHIPPED** (`1a96b764`): single-monitor separated-window arrangement. The E1/3.4 keepCompanion fix keeps the full dashboard SHOWN alongside the in-game overlay - but on a SINGLE monitor (the operator's Legion is 1-mon) a companion last left under the right-docked overlay is visible-yet-covered, so "the dashboard stays available" is hollow; you cannot punt it to a 2nd screen. FIX, pure-first: `overlay_state.js` gains `rectsOverlap(a,b)` (strict AABB; touching edges are a clean tile, NOT a collision; garbage rect -> false so the auto-arrange no-ops safely) + `resolveSeparatedCompanionBounds(companion, overlayBounds, workArea)` -> `{x,y,width,height,moved}`: a companion already CLEAR of the overlay (or a garbage overlay) is left exactly where it is (`moved:false` - operator intent wins); an OVERLAPPING companion is docked to the work-area edge on whichever side of the overlay has more free room (`leftRoom >= rightRoom`), top-aligned, KEEPING its size - REPOSITION ONLY, never resize, so the `cfgmod.SIZE_PRESETS` preset is never corrupted by a setBounds-triggered resize-persist. New `separateWindows` operator setting (default ON) threads through `OVERLAY_SETTINGS_DEFAULTS` / `overlaySettingsFrom` / `sanitizeSettingsPatch` (the no-hotkey kill switch). `main.js` `applySingleMonitorLayout()` gates on `screen.getAllDisplays().length === 1` (a >=2-display setup is the operator's to arrange - untouched) + `separateWindows`, reads `mainWindow.getBounds()` + `overlayWindow.getBounds()` + the primary work area, and `setBounds` + `persistWindowState` only when `moved` (called from `applySurface` exactly when BOTH windows show, so once per COMPANION->OVERLAY transition, not per poll). WEB: `overlay_settings.js` carries `separateWindows` through DEFAULTS/_coerce/write; `overlay_ds_controls.js` adds the `#ovset-separate` "Separate windows" `.ovset-row.ovset-toggle` (reuses the audited 42px-floor row). TDD RED-first: rc-shell node 232/232 (+15: rectsOverlap 4, resolveSeparatedCompanionBounds 5, separateWindows defaults/read/merge 3, + 5 pre-existing exact-shape assertions extended with the new field), `test_overlay_settings_rc2` (+7 harness assertions) + `test_overlay_settings_panel_dom` (new Rc2Stage43ControlsTests 4), real-Chromium `test_overlay_view` 44 (the #ovset Separate-windows toggle renders, defaults checked, ASCII label, clears the 42px hit floor = the durable 5-phase audit). Tier-1 web/shell JS; NO ENGINE/DS/Share/schema/frozen-Python (rc-shell/* is the Electron shell, not frozen `main.py`); precommit ds_share_sync confirmed no DS source staged -> no Share drift. 5-phase fixture audit PASS (0 MUST-FIX): STRUCTURE one additive checkbox row in the #ovset flex column (no reflow); TYPOGRAPHY `.ovset-toggle` `--fs-xs`; HIT-TARGETS 42px floor (Chromium-asserted); ASCII 0 banned glyphs (8 files byte-scanned); HIERARCHY supporting chrome, default-checked = dashboard-beside-HUD is the resting state. Renderer auto-reloads (ADR-008 asset-hash, live `:8888` serves both files HTTP 200); the rc-shell Electron MAIN process needs a relaunch for the main.js arrangement logic + the separateWindows authority (same operator-accepted pattern as E1/P3.4/4.1/4.2). LIVE composited-over-League eyeball at 2560x1440 borderless OWED (operator-gated, NEVER blocks) -> `docs/LIVE_GAME_GATED_SYNC.md`. The Hextech reskin of the new toggle rides E11's global token cutover.
- **P4.2 SHIPPED** (`85d6b29e`): non-intrusive overlay - click-through ZONES + opacity + auto-hide idle recede. Stage 4.2 had three named sub-features; all shipped additive + overlay-scoped + default-safe, NO shared dashboard render-path flip (so headless, unlike 3.3's gated pulse flip). (1) CLICK-THROUGH ZONES: `overlay_state.effectiveIgnoreMouse(clickThrough, zoneHover, zonesEnabled)` (pure) is the new EFFECTIVE-ignore decision - it layers a transient `zoneHover` + the `clickThroughZones` setting over the operator/hotkey `clickThrough` INTENT (zones OFF = legacy whole-window; ACTIVE = fully interactive; PASSIVE+zones = click-through EXCEPT over a control). New `rc-shell/src/clickthrough_zones.js` is the PURE injected-string hover detector (mirrors active_indicator/drag_region; sandboxed preload cannot require modules): a pointermove/pointerdown capture listener hit-tests `e.target.closest(ZONE_SELECTOR)` (`#ovset, #rn-choices, #am-pane-ovds, #rc-shell-drag-region, [data-rc-zone]`) and reports cursor-over-a-zone over the preload bridge (new `rcShell.setZoneHover` -> `ipcMain.on rc-shell:overlay-zone-hover`, a one-way send), with a `window.__rcZoneHoverWired` idempotency guard + a no-bridge guard (plain browser no-op). main.js `applyClickThrough` now computes `effectiveIgnoreMouse` and sets both `setIgnoreMouseEvents(ignore,{forward:true})` + `setFocusable(!ignore)`; the ACTIVE glow still tracks the `clickThrough` INTENT (a micro-hover must not light the full frame). Net: the operator clicks the settings strip / A+B choices / DS knobs / drag strip WITHOUT the global Alt+Shift+A. Default ON. (2) OPACITY: `overlay_state.clampOpacity` [0.3,1.0] 2-dp; main.js `applyOverlayOpacity` -> `overlayWindow.setOpacity`; a 30-100% `#ovset` range slider (the HUD recedes into the game without disappearing). Default 1.0 = exact no-op. (3) AUTO-HIDE idle recede: new `web/js/lib/overlay_idle.js` (pure `isIdle`/`planIdle` + DOM `applyIdleAttr` + glue `initOverlayIdle`, dual ESM/CJS like condense.js) - a MutationObserver on the dock mounts (same set as overlay_pulse.js) + pointer listeners reset a `lastActivity`; after ~8s with no coach change AND no pointer activity the body gets `data-rc-idle="1"` and `overlay.css` section 6 dims `#view-active-match` + `main` to 0.35 opacity (opacity-transition only, GPU-light); a coach change / hover snaps it back. OPACITY recede, NOT `display:none` - a hard hide mid-game would remove coaching. All three settings carried through `web/js/lib/overlay_settings.js` (`overlayOpacity` + `clickThroughZones`) + rc-shell `overlaySettingsFrom`/`sanitize`/`merge`, persisted + applied live (`applyOverlaySettings` now also calls opacity + click-through). The renderer half (idle recede + the `#ovset` zones toggle / opacity slider) auto-reloads via ADR-008 asset-hash; the rc-shell Electron MAIN process needs a relaunch for the shell-side opacity/zones (preload `setZoneHover` + main.js), same operator-accepted pattern as E1/P3.4/4.1. TDD RED-first: rc-shell node 220/220 (`overlay_state.test.js` +20: clampOpacity / effectiveIgnoreMouse / overlayOpacity+clickThroughZones settings; new `clickthrough_zones.test.js` 8; `overlay_settings_ipc.test.js` +4 wiring); `tests/test_overlay_idle_rc2.py` 16; extended `test_overlay_settings_panel_dom` for the new `#ovset` controls; real-Chromium `test_overlay_view` 36 unaffected. Tier-1 web/shell JS+CSS; NO engine/DS/Share/schema/frozen-Python (rc-shell/* is the Electron shell, not the frozen `main.py`). CI green (authored-source hygiene + smoke/regression + panel snapshot + mypy). 5-phase fixture audit PASS (0 MUST-FIX): STRUCTURE new `.ovset-toggle`/`.ovset-range` rows reuse the flex column (range caps 140px, no overflow; idle dim is opacity-only, no reflow - snapshot rendered clean); TYPOGRAPHY labels use `--fs-xs`; HIT-TARGETS rows + range carry the `--hit-min` 42px floor; ASCII 0 banned glyphs (new files byte-scanned; main.js residual non-ASCII are pre-existing box-drawing/arrows, NOT banned); HIERARCHY settings stay supporting chrome, the idle recede REINFORCES the glance (a quiet HUD fades so the game shows through). Claude_Preview live-attach OWED (MCP won't attach to the external pythonw `:8888`, same accepted pattern as UIX1/2/3 + P3.4/3.5/3.6 - live `:8888` curl render-proof stands: overlay_idle.js HTTP 200, overlay.css serves data-rc-idle). LIVE composited-over-League eyeball at 2560x1440 borderless OWED (operator-gated, NEVER blocks) -> `docs/LIVE_GAME_GATED_SYNC.md`. The Hextech reskin of the new chrome rides E11's global token cutover.
- **P4.1 SHIPPED** (`4d5d54f0`): DPI + resolution-aware overlay sizing (research LIFT-C, `docs/research/RC2_RESEARCH_overlay_sizing.md`). RC's overlay box (`OVERLAY_DEFAULTS` 460x900) + dock CSS (~460px) were a HARD 1920/100% baseline with ZERO scaleFactor/resolution handling - at the operator's new 2560x1440 borderless the HUD shrank to a tiny corner (the Overlay App F "content too big for the window" failure class, the single biggest documented sizing gap). FIX, pure-first: `rc-shell/src/overlay_state.js` gains `normScaleFactor` (electron#6571 guard - `getPrimaryDisplay().scaleFactor` returns a non-positive/non-number under Windows scaling -> coerce to 1), `resolveOverlayScale(workArea)` (scale = min of the two axis ratios vs the 1920x1080 baseline, preserves aspect + avoids ultrawide over-scale, clamp [0.8,1.6], 2-dp; EXACTLY 1.0 at the baseline = true no-op), `resolveOverlayMetrics(display)` ({scale,scaleFactor,width,height}; height never exceeds the work area so the dock always fits), `resolveOverlayBounds(saved, workArea, metrics?)` honors an optional scaled box (garbage/absent -> default box, backward compatible), and `overlayUrl(origin, panelSet, scale?)` appends `ovscale=N` ONLY when meaningfully != 1 (baseline URL byte-identical). KEY DPI MODEL (research L3): Electron sizes windows in DIPs and Chromium maps CSS px -> DIPs -> device px by deviceScaleFactor, so we size the DIP box against the DIP work area and do NOT multiply by scaleFactor (that would double-apply) - scaleFactor is read only to guard + diagnose. `main.js` `createOverlayWindow` computes metrics from `screen.getPrimaryDisplay()`, sizes the window from them, and passes `metrics.scale` to both `overlayUrl` loadURL sites (create + Alt+Shift+C cycle). RENDERER: `web/js/main.js` overlay-shell stamp parses `ovscale` (re-clamped [0.8,1.6] - never trust a hand-edited URL), sets `--rc-overlay-scale` on body; `web/css/overlay.css` `body[data-shell="overlay"] { zoom: var(--rc-overlay-scale, 1) }` zooms the dock CONTENT to fill the scaled window (zoom not transform so layout + the right-edge dock reflow; default 1 = exact baseline no-op). TDD RED-first: +15 node tests (`overlay_state.test.js` 80->95, full rc-shell suite 194/194) + 3 real-Chromium fixture-audit tests in `tests/snapshot_panels/test_overlay_view.py` (17/17: 1440 ovscale=1.3 zooms the dock to ~598px right-anchored, baseline-absent no-op stays ~460, out-of-band ovscale=2.5 ignored) - the screenshots ARE the 5-phase fixture audit. 5-phase audit PASS (0 MUST-FIX): STRUCTURE right-docked single column scales cleanly (CALL/BUILD/FIGHT panes, no orphan/overflow); TYPOGRAPHY legible + proportional, no clip; HIT-TARGETS the 42/44px floors only enlarge under zoom; ASCII 0 banned glyphs (banned-glyph scan + `test_no_em_dashes` PASS); HIERARCHY glance lands on the CALL headline first. Tier-1 web/shell JS; NO ENGINE/DS/Share/schema/frozen-Python. Renderer auto-reloads (ADR-008 asset-hash, no RC restart); the rc-shell Electron MAIN process needs a relaunch to pick up the window-size change (same operator-accepted pattern as E1/P3.4). OWED (NEVER blocks): the LIVE composited-over-League eyeball at 2560x1440 borderless (stage 4.6, operator-gated) -> `docs/LIVE_GAME_GATED_SYNC.md`. The Hextech color reskin of the panel chrome rides E11's global token cutover; this stage is geometry only.
- **P3.6 SHIPPED** (`2d347dc0`): the dashboard UI-agent condensation pass. 3.6 is the DASHBOARD counterpart to the overlay condensation (3.1-3.3): the full `:8888` view KEEPS its density (it is not the 460px HUD - the spec scoped the 2-row callout clamp to `body[data-shell="overlay"]` and left the dashboard at all 3), but the PRIMARY in-game coaching panels render fixed supporting KV rows (RIGHT NOW: Watch / Fight / Base; NEXT: Objective / Position / Waves and their mode relabels) that paint the `-` no-data sentinel in client / pregame / ARAM / aftergame states - a dead-dash wall under the live headline. FIX: new `web/js/lib/condense.js` (pure + DOM, dual ESM/CJS like `overlay_priority.js`) - `condenseKvRows(root)` hides each `.kv` row whose value cell is a no-data sentinel (`EMPTY_SENTINELS` = ["", "-", "- / -"]; `0` is NOT a sentinel - a zero is a real value) and shows it otherwise; idempotent (toggles `display` only, never rewrites innerHTML, so a row reappears the tick its value latches e.g. Fight rule at the first teamfight). Generalizes the proven inline `right_now.js _hideEmptyStatRows` STATS-panel move (item-precedent, operator-approved dash-wall collapse). Wired at the END of `renderRightNow` (`condenseKvRows(RN.root)`) and `renderNext` (`condenseKvRows(NX.root)`). OVERLAY-INERT by construction: those `.kv` rows are `display:none !important` in the `?overlay=1` shell (`overlay.css #right-now .panel-body > *`), so an inline `display` write can never reveal them there - no shell guard needed, this only reshapes the dashboard surface. TDD RED-first: `tests/test_dashboard_condense_rc2.py` 20 node-driven (require the CJS export; `isEmptyValue`/`planKvCondense` pure-logic + `condenseKvRows` vs a hand-rolled DOM stub since jsdom/playwright are absent on CI; + grep-style wiring + ASCII guards) - 20 RED -> 20 GREEN. Tier-1 web JS, NO ENGINE / 0 frozen / no DS / no Share; ADR-008 asset-hash auto-reload (live `:8888` curl-confirmed serving condense.js HTTP 200, no RC restart). 5-phase fixture audit PASS (0 MUST-FIX): STRUCTURE collapses dead rows with no new elements (flex column, no orphan layout); TYPOGRAPHY/HIT-TARGETS untouched (rows are non-interactive; SCREEN READ button + choices chips unaffected); ASCII 0 banned glyphs across all 4 touched files; HIERARCHY the glance lands on populated coaching rows. Claude_Preview live-attach visual OWED (the MCP won't attach to the live external pythonw `:8888`, same operator-accepted pattern as UIX1/2/3 + P3.4/3.5 - curl render-proof stands in). The Hextech reskin of the panel chrome rides E11's global token cutover. Two-commit pattern: `2d347dc0` feat (code+test) then this docs flip.
- **P3.5 SHIPPED** (`f2bdb2fa`): the Settings-without-hotkeys surface. Audit of the full settings + hotkey surface found exactly ONE hotkey-only action with no live-dashboard UI: the Ctrl+Tab forced coach vision scan (`core/hotkeys.py` `_trigger_force_scan` -> `data/force_scan.json`, polled by `coaches/_base_coach.py:394`). Everything else was already keyboard-free (overlay `#ovset` strip, panel-visibility card, spend gates, voice/PGR/lobby knobs; the Game-PC decision keybinds Ctrl+Shift+1/2 + Alt+1/2/3 already have dashboard banner button equivalents). The backend route ALSO already existed - `POST /api/command {command:"force_vision"}` -> `dashboard/_writers.py force_vision_scan` (`routes_state.py:411`) - the LEGACY dashboard's `btn-scan` used it (`web/legacy_index.html:2953`) but the live `web/js` UI dropped it. FIX: a new COACHING ACTIONS `.settings-card` (`web/index.html`) with a "Force vision scan" `<button>` (`#set-force-scan-btn` + `#set-force-scan-status` aria-describedby + a no-hotkey note), wired in `dev.js _settingsRefresh` to POST `force_vision` (token-header aware, mirrors `screen_read.js`/loop-control; 3s client cooldown matching `CTRL_TAB_COOLDOWN`), styled `.set-action-btn` at the `--hit-min` 42px floor (`header.css`, mirrors `.loop-btn`). TDD: `tests/test_settings_force_scan_dom.py` +10 RED-first grep-DOM guards. Tier-1 web only; NO ENGINE/DS/Share; no RC restart (ADR-008 asset-hash, live `:8888` curl-confirmed serving the card). 5-phase fixture audit PASS (0 MUST-FIX; 1 optional aria SHOULD-FIX applied in-slice). Claude_Preview live-attach visual OWED (the MCP won't attach to the live external pythonw `:8888`, same operator-accepted pattern as UIX1/2/3). The Hextech reskin of the button chrome rides E11's global token cutover.
- **P3.4 SHIPPED** (`183f1969`): dashboard-persist toggles reachable from the overlay UI. The shell-side mechanism shipped under E1 (`a61703ef`): `overlay_state.windowActionsWithPolicy` + `keepCompanion` DEFAULT-TRUE (the disappear-bug fix - the companion window is kept SHOWN alongside the in-game overlay instead of hard-hidden) + `companionAlwaysOnTop` pin, consumed in `main.js` `applySurface` / `applyCompanionAlwaysOnTop`, round-tripped over the `rc-shell:overlay-settings:get/set` ipcMain bridge (81/81 shell node tests, incl. the windowActionsWithPolicy + overlaySettingsFrom keepCompanion/pin coverage in overlay_state.test.js). The RESIDUAL closed this cycle: the web helper `web/js/lib/overlay_settings.js` only carried `pulseNotify`/`activeRevertSec`, so a `keepCompanion`/`companionAlwaysOnTop` write from the dashboard was silently dropped in `_coerce`/`writeOverlaySettings` before it could reach the shell. Fix: (a) carry both booleans (defaults true) through DEFAULTS/_coerce/write; (b) add **Keep dashboard** + **Pin on top** toggles to the `#ovset` overlay settings strip (`overlay_ds_controls.js`, reuse `.ovset-row.ovset-toggle`, 42px hit floor, default checked) = no-hotkey control of persist+pin (operator north star). TDD: `tests/test_overlay_settings_rc2.py` (node ESM, RED-first 6 assertions) + a real-Chromium DOM assertion in `test_overlay_view.py` (controls present, default checked, ASCII labels, hit-target floor = the 5-phase audit as a durable check). Tier-1 web JS; NO ENGINE/DS/Share. Note: the rc-shell Electron main process still needs a relaunch to pick up E1's shell-side default (the web toggles + dashboard auto-reload via asset-hash). The Hextech reskin of the strip is E11.
- **P3.3 SHIPPED (LIVE; shadow slice)** (`87f41baf`): the typography/hit-target half + a SHADOW of the pulse-rationing wire. (a) `overlay_priority.js` gains `signalFromState(p, band)` - the one pure coach-envelope -> selectPrimary-signal mapping (band passthrough + choices detect + Phase-4 crossing-edge predicates `spike_crossed`/`objective_steal_now`/`lethal_incoming` default-false, honored if a producer ever sets them; spec section 9 Q1/Q2 stay deferred, no assumed surface). (b) `right_now.js` SHADOW consumer: each render computes `selectPrimary` + `shouldPulse` and stamps `data-s0-cue` / `data-s0-tier` / `data-s0-pulse` on `#right-now` WITHOUT touching the live `.action` per-band pulse (`right_now.js:490-500`) or `overlay_pulse.js`. (c) `overlay.css` section-7 floor: `#rn-choices .rc-chip` min-height 44px overlay-scoped (dashboard keeps `--hit-min` 42). 29/29 node logic + 13/13 overlay snapshot (real Chromium, screenshots = fixture audit). **OWED LIVE FLIP (operator-gated, NOT headless):** re-point the `.action` per-band pulse + `overlay_pulse.js` MutationObserver at this shadow decision (consume the stamped `data-s0-pulse` instead of firing on every text/content change) - a SHARED dashboard+overlay behavior change -> `docs/LIVE_GAME_GATED_SYNC.md`. The Hextech color-literal swap is E11 (the overlay already uses `--signal-*` tokens, so it inherits E11's global token cutover; pop-out discipline A2 is enforced structurally by the single-winner arbitration, not new literals).
- **P6.2 SHIPPED** (1011f47d): RuneWriter.POLL_INTERVAL 2.0s -> 1.0s (env RC_RUNEWRITER_POLL_SEC), port-safe. Applies on next RC restart. Remaining P6 levers (from io_timing_map): halve SSE+build TTL 1.0->0.5s together (S/LOW, touches state pipeline); pool one keep-alive LCU socket (M/MED, frozen grant). The dashboard champ-select render envelope (champ_select.js ~2s) is the UI-responsiveness lever for 6.3.
- **P7.1 ASCII warning** = `tools/edit_lint_check.py` (PostToolUse) + `tools/precommit_gate.py` scan 6 banned glyphs only: em-dash U+2014, en-dash U+2013, smart quotes U+2018/2019/201C/201D. Box-drawing / arrows / math are NOT banned (functional, leave them). Census: 53 em-dashes total, ALL in `_archive/2026-05-01-audit/**` (dead pre-1PC tkinter code) + `agents/agent6_auditor/reports/*.md` (generated weekly reports); ZERO smart quotes; the live authored tree is CLEAN. These dirs are normally sweep-excluded (immutable). FIX: strip em-dashes in those files (tools/strip_em_dashes.py) AND extend the hook `_FROZEN_SKIP` to root `_archive/` + agent6 reports so it never re-warns; OR delete the dead `_archive/2026-05-01-audit` in P7.2/7.3 (it is the "unused >1wk" target).
- **P3.2 SHIPPED (structure/density pass 1)**: (a) `web/js/lib/overlay_priority.js` (`39303acb`) - the pure-logic S0 arbitration primitive: `selectPrimary(state)` single-winner ladder (lethal 100 / objective_steal 90 / urgent_headline 85 / choices 80 / spike 70 / fight 60 / good 40 / none 0) + `shouldPulse(prevCue, sel)` motion rationing (Emergency tier or one-shot-Urgent {spike,choices} on a CUE CROSS only) + `BAND_TIER` map; dual ESM/CJS export (Node 22 require-of-ESM), 21/21 node-driven tests (`tests/test_overlay_priority_rc2.py`, pre-authored untracked, now GREEN). (b) callout 2-row density clamp (`db6f77d4`) - overlay-scoped CSS `#rn-callouts .rc-co-row:nth-child(n+3){display:none}` so the HUD S1 slot shows the 2 nearest-ETA rows (dashboard keeps all 3); +1 snapshot test. **NOT yet wired:** the primitive is not consumed by a rendered panel - re-pointing `right_now.js` `.action` pulse (currently fires all 3 bands on text change, `right_now.js:490-500`) + `overlay_pulse.js` to `shouldPulse` is the spec-flagged BEHAVIOR change, carried to **3.3** (shared dashboard+overlay render path -> needs shadow + the 5-phase UI audit + operator eyeball, not a blind headless flip). DOM slot reorder deferred (current order audited + close to spec S0>S1>S2>S3).
- **P3.1 SHIPPED**: `docs/research/RC2_OVERLAY_CONDENSATION_SPEC.md`. Reframes the 460px dock as 1 PRIMARY (S0) + 3 SUPPORT (S1-S3) fixed slots with a 3-tier model (Ambient/Urgent/Emergency) mapped onto the existing `classifyAction()` bands (`right_now.js:472`: urgent->Emergency, fight->Urgent, good->Ambient). Adds a deterministic S0 single-winner arbitration (priority 100 lethal -> 0 empty) so exactly ONE pop-out exists at any tick, and NARROWS the pulse channel from every-band-on-text-change to Emergency + one-shot-Urgent-cross only (kills alarm fatigue). 3.2 OWNS new `web/js/lib/overlay_priority.js` (selectPrimary + tier map, TDD fixture table) + callout 2-row clamp; 3.3 OWNS Hextech color-bin bindings (#E84057 lethal reserved for the lone S0 Emergency; gold caution; cyan info; green good) + per-element glance acceptance bars + the 5-phase fixture audit at `?overlay=1`. Open: Q2 lethal-incoming predicate field (grep coach.fight_rule / liveclient hp before wiring), Q1 minimap-anchor projection deferred to P4.1.
- **P5 coaching** spec = `docs/research/RC2_COACHING_SPEC.md`. The laning Haiku-flip is blocked at 39% det-vs-Haiku agreement by CALIBRATION (precompute verdict vocabulary has no hold/farm band, back_off-biased), NOT games-played (`ops/audit/HZ_HAIKU_CALL_INVENTORY.md:49-108`). Top lever: hold-band + `even` relabel in `core/precomputed_laning_coach.py` `_VERDICT_LABELS` (Tier-1, shadow-logged, 39% -> ~53%+). Then CV overrides (new core/laning_cv_overrides.py reading data/vision_state.json) + objective playbook row.
