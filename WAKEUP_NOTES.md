# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-06-10 - gemini loop cycle 3: Phase 4 in-overlay DS controls + Phase 5 smoke [item 382, HZ-D1 slice 3]

Gemini-headless-upgrade executor cycle (run 2026-06-10-01 cycle 3). Directive = Phase 4 in-overlay DS controls (weight tweak / build reorder) + dashboard-side web/ slice + UI audit. Merges `85c54ba3` + `141c1333` (2 PARALLEL worktree agents, verifier-CONFIRMED) + audit-fix `bc8c94d3`. NO engine, no Share, no RC restart (ADR-008).

- NEW FIGHT MODEL pane `#am-pane-ovds`: `overlay_ds_controls.js/.css` + overlay.css 4b gates (base+build panelsets; coach/threat narrow it off) + main.js wiring x4 sites; 4 knobs (armor/MR/gold cap/fight len) -> existing GET /api/ds-knobs; top-5 re-ranked rows = build reorder. Zero backend change.
- Live-probed fix 1: coach payload items are NAMES, /api/ds-knobs 503s on names -> bridge via `items_index._resolveItemId` (numeric passthrough, unresolved drop).
- Live-probed fix 2 (UI-audit MUST-FIX): cascade leak - `#view-active-match .am-pane {display:flex}` beat bare-id display:none + [hidden]; fixed with two-id selector (0,2,0,0).
- Phase 5 starter: `tests/test_overlay_route_smoke.py` shell<->web PANEL_SETS drift guard (19 tests + 9 subtests).
- Proof on LIVE :8888 via Claude_Preview (?ui_mock=1&mode=aram&overlay=1): armor 100->300 re-ranked Runaan's-top -> Void-Immolation-top; normal dashboard computed display:none. RC tests/ 5769 passed / 2 skipped / 94 subtests exit 0; ruff clean; DOM suite 26 (TDD red-first x2).
- OWED (live-gated): in-match overlay capture with ACTIVE knob interaction (shell relaunch picks up slices 1-3).
- NEXT in HZ-D1: Phase 5 stabilization tail (electron-updater + channels, crash isolation) or live-capture closeout.

---

# 2026-06-10 - gemini loop cycle 2: rc-shell overlay persistence + ACTIVE indicator [item 381, HZ-D1 slice 2]

Gemini-headless-upgrade executor cycle (run 2026-06-10-01 cycle 2). Directive = overlay position persistence (mirror companion) + advance Phase 4 interactive controls, headless-safe. Merge `8116c6c2` (slice `c9f53543`, 1 worktree agent, verifier-CONFIRMED pre-merge). NO engine, no Share, no RC restart.

- `rc-shell-state.json` gains `overlay: {x, y, panelSet}`: pure `overlayStateFrom` / `resolveOverlayBounds` (clamp via `config.clampPosition`, right-edge dock default) / non-mutating `mergeOverlayPatch` in `overlay_state.js`; main.js debounced overlay move persist + panelSet restore-at-boot / persist-on-cycle + will-quit timer clear.
- Phase 4: NEW `rc-shell/src/active_indicator.js` edge-glow (`pointer-events:none`, `html.rc-shell-active`), injected overlay-only on did-finish-load (re-applies current state), toggled in `applyClickThrough()` - operator can now SEE ACTIVE vs PASSIVE incl. the 20s auto-revert.
- node 85 -> 109/0 (TDD 16 red first); RC tests/ 5724 passed / 2 skipped / 85 subtests exit 0; package.json 0.3.0; DS n/a (zero python touched).
- OWED (live-gated): in-match glow + drag-restore capture; the running shell instance predates slices 1+2 - one relaunch picks up both.
- NEXT in HZ-D1: Phase 4 in-overlay DS controls (dashboard-side web/ slice + UI audit) or Phase 5 stabilization.

---

# 2026-06-10 - gemini loop cycle 1: rc-shell drag region + overlay ACTIVE drag [item 380, HZ-D1 slice 1]

Gemini-headless-upgrade executor cycle (run 2026-06-10-01). Directive minimum = make the frameless companion draggable. Merge `0b2eea62` (slice `bbc8e31e`, 1 worktree agent, verifier-CONFIRMED pre-merge). NO engine, no Share, no RC restart.

- NEW `rc-shell/src/drag_region.js` pure module: `dragRegionCSS()` fixed transparent 24px top strip `-webkit-app-region: drag` + `.rc-shell-no-drag` escape hatch; `dragRegionMountJS()` idempotent IIFE appending to documentElement. Injected by `injectDragRegion(win)` in main.js on `did-finish-load` (insertCSS + executeJavaScript, no-throw) - dashboard untouched.
- Preload route is a DEAD-END: sandbox:true preloads cannot require local modules. Do not re-try.
- Overlay gets the same strip: inert while click-through, grabbable when ACTIVE (Alt+Shift+A) = overlay user-movable (Phase 4 control off the existing gate). Overlay position NOT persisted - named next-slice candidate.
- Gates THIS run: node 85/85 (77 -> 85, TDD red-first); DS 7075p/1sk/1xf/1942st; RC tests/ 5724p/2sk/85st EXIT=0 (file-read summary). `py` launcher resolved to pythoncore-3.14-64 WITHOUT pytest - use the canonical `C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe` for suites.
- OWED: item-379's running shell predates the drag code - relaunch to pick up; live drag-feel + in-game overlay-drag capture.

---

# 2026-06-10 - item-378 overlay tail: ingest regen + panelset rendering + dark-mounts fix + Electron launch [item 379]

Operator queued the 4-part 378 tail; autonomous. Commits `be8a033e` (Share) + `74ba5d31` (overlay/web). NO engine, no RC restart. Full record: docs/LEDGER.md 379.

- **(1) lolmath_ingest regen + guard (`be8a033e`):** subdir restamped 1.108.0/16.11.1 -> 1.120.0/16.12.1 + 13MB dist bundle rebuilt; `ds_share_sync.py` write/--check now cover it (anchors via 2 disjoint token rules + bundle byte-compare; MISSING bundle = skip, it is gitignored `dist/` so CI clean checkouts pass). +9 tests. CRLF gotcha: restamp writer needs `newline=""`. Gist mirror pushed ok.
- **(2) chip task_8a4ebe04 = REAL bug, FIXED:** /api/state top-level `coach`/`lead_projection`/`callouts` never stamped onto `state.latest` -> renderCoachChoices/renderLead/renderCallouts (fed `state.latest`) dark since W3E, dashboard AND overlay. Stamped at all 3 ingest sites (item-201 pattern); +3 contract tests.
- **(3) panelset rendering (`74ba5d31`):** `body[data-panelset]` stamp (canonical names only) + overlay.css 4b: coach=CALL+mounts, build=BUILD only, threat=CDS ledger+lead/callouts. UI audit pre-commit: 1 MUST-FIX fixed in-slice (cd_ledger 10/9/11px sub-floor at game distance -> threat-scoped 13px/18px lift) + NICE (collapse suppressed; persisted `cdLedgerCollapsed` ignored - shared-origin localStorage would blank the HUD). +4 Playwright tests, overlay suite 10/10.
- **(4) Electron launch:** rc-shell node_modules was EMPTY (electron gone; npm start failed) -> `npm install` restored; companion window up rendering live dashboard, WS connected, capture taken; node 77/77. **Shell LEFT RUNNING** - overlay auto-flips on game start (Alt+Shift+O toggle, Alt+Shift+C panelset cycle).
- Ground truth this run: tests/ `5601 passed / 2 skipped / 0 FAILED EXIT=0` (file, not pipe).
- **Post-tail (`359a131a`):** operator re-reported the dark-mounts bug with forensics asks -> behavioral SSE characterization test `tests/snapshot_panels/test_deterministic_mounts_sse.py` (real EventSource drive; proven RED on `74ba5d31~1`, GREEN current; snapshot suite 123). FORENSICS: dead since DAY ONE (`ee5323b7` 2026-05-20 - `git -S` shows `74ba5d31` is the first-ever `state.latest.coach` assignment); NOT an item-314 regression; the May decisions_log rows are smoke-test synthetics. Don't re-investigate.
- Owed next: live-game overlay capture (League client was at PLAY screen); Phase 4 interactive controls; Phase 5.

---

# 2026-06-09 - orchestrated Electron-overlay session: HZ-D1 route + shell P4 + prune + sidequest [item 378]

Operator: continue Electron overlay autonomously, multi-agent orchestrated, self-audit, prune files/branches, no operator gating. 4-agent Workflow (wf_51d1c597) -> merge -> 5-phase UI audit -> verifier -> fix -> push. Commits `b58a1550`/`47b9e5d6`/`c97f5fcc`/`6e8989ec`/`0522ceab`. NO engine, no Share delta, no RC restart.

- **S1 (`b58a1550`):** `?overlay=1` overlay route - `body[data-shell=overlay]` + active-match pin; NEW `web/css/overlay.css` (460px right-dock, transparent page, CALL+BUILD+lead/choices/callouts only) + `web/js/overlay_pulse.js` (one-shot 1.2s edge-glow on content change); asset-hash covers both; +6 snapshot tests.
- **UI audit:** 4 MUST-FIX fixed in-slice (`0522ceab`): flex 0 1 auto/overflow hidden (1080 clip), mount display:flex (gap restore), rn-lead accent re-assert, .rc-src 13px. 3 NICE deferred (active_match.js 9-10px inline fonts, eyebrow contrast, boot-pulse burst).
- **S2 (`47b9e5d6`):** rc-shell P4 partial - ACTIVE 20s auto-revert + poll backoff 2-15s + Alt+Shift+C `panelset=` cycle; node 77/77. Dashboard-side panelset rendering = next slice.
- **S3:** 3 orphan worktree-agent branches DELETED (patch-equivalent to main `9d2e85ea`/`df78b090`/`7e8e47fa`); ROADMAP item-280/281 stale NEXT lines corrected.
- **Prune (`c97f5fcc`):** 10 dated docs -> `_archive/` + 7 refs rewritten; rc-shell/.pytest_cache deleted.
- **Verifier catch:** pre-existing `test_ledger_holds_relocated_items` red (LEDGER split-home) - re-scoped; full suite 5706/0 fail fresh.
- **Sidequest (no naming):** Share core in sync (1.120.0/16.12.1) BUT Share's calculator-ingest subdir pins 1.108.0/16.11.1 + the external site's deployed chunks embed 16.11.1 with no DS markers = bundle offered-not-consumed. OWED: regen ingest bundle at next Share sync; extend `ds_share_sync.py --check` to cover that subdir.
- **S1 agent flag (chip task_8a4ebe04):** renderLead/renderCallouts/renderCoachChoices read `state.latest` keys (lead_projection/callouts/coach) no ingest path assigns - overlay mounts may stay dark until wired; verify on a live game.
- Owed next: Electron visual launch (`npm start`) + live-game overlay capture; dashboard panelset rendering; Phase 4 controls; Phase 5.

---

# 2026-06-09 - HZ precompute regen at live patch 16.12.1 (unblock shadow coverage) [item 377]

Operator "start what is up next that is open" -> diagnosed the Haiku-to-ZERO HZ shadow gate. `hz_shadow_report` showed 0/512 laning + 0/475 build covered. ROOT CAUSE: HZ-A/B precompute dirs existed ONLY at 16.11.1 but live patch is 16.12.1 (item 372 patch-refresh deferred the HZ regen; item 374 S4 re-deferred). The patch-keyed reader found no 16.12.1 dir -> every new-game shadow record logged covered=false. Data-only, NO engine, ENGINE 1.120.0 untouched, no Share (HZ tables not Share-mirrored). Commit `cc35d5ed`, CI green (run 27249973771).

- Regenerated all 3 SR tables at 16.12.1 from the full 172-champ roster (`data/daemon_slayer/16.12.1/champions.json` keys; item-370 baseline +1 patch-added champ):
  - laning_scenarios/16.12.1/laning_scenarios_sr.json  355008 cells / 66MB (LFS)
  - build_orders/16.12.1/build_orders_sr.json          172 champs / 688 orders
  - build_orders/16.12.1/build_order_variants_sr.json  344 orders
- Generators: `core/{laning_scenario_precompute,build_order_precompute,build_order_variants}.py --mode sr --champions <172-csv>`; laning needs `PYTHONPATH=repo` (top-level `agents` import) + 187s for the 172x172x3 sweep.
- Read path live-verified at 16.12.1: `lookup` + `precomputed_choices` Ahri vs Darius L6 -> back_off / "Recall now".
- `hz_shadow_report` 0-coverage is HISTORICAL only - `covered` is baked into each record at log time (report line 81 reads the record, never the live table). Accrues covered=true on NEW games now the dir exists.
- HZ tests 165 passed; ruff/hygiene green; clean tree pushed.
- Don't-redo: SR HZ precompute now current at 16.12.1; ARAM/Arena `--mode all` expand STILL deferred (item 374 S4); owed = confirm covered=true on the next live SR game.
