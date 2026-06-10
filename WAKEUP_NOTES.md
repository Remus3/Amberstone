# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-06-10 - gemini loop: HZ-D4 charter sweep - shadow-pipeline root-cause fix + ARAM tables + agreement metric [item 386]

Gemini-headless-upgrade executor cycle. Directive = HZ-D4 (7-lever cost sweep + next HZ increment). Merges `d446ea80` + `b54d040e` (2 PARALLEL worktree agents, verifier-CONFIRMED). NO engine, no Share, no web/ touch; RC restarted pid 14160.

- 7-lever sweep: 7/7 CLEAN, no commit. Scout's lever-6 "orphan tasks" REFUTED by ground truth (all 3 flagged tasks point at on-disk scripts).
- ROOT CAUSE found verifying the table-expand premise: ALL 837 choice + 800 build shadow rows junk - enemy=null 100 percent (champ from PERSISTENT stale coach dict; enemy_team only in live liveclient -> idle ticks logged stale replays) + 290 Champ0 rows (pytest build_state runs appended to REAL data/ jsonls). Flip path could never accrue.
- FIX: live `lc.get("champion")` gate in both shadow_log_precomputed_* + autouse conftest SHADOW_PATH->tmp redirect (hz_choice/hz_build/det_coach); +4 gate tests; polluted jsonls rotated to _scratch/*.pre_item386.jsonl.
- ARAM tables full-roster 172 (every native capture is mode=aram): laning_aram 65.75MB LFS + build_orders_aram 688 + variants_aram 344 @16.12.1. GOTCHA: gen CLIs default to 10-champ seed; pass --champions <172-CSV from SR table scenarios keys>.
- hz_shadow_report v2 (item-369 tail): classify_verdict/record_agreement/summarize_agreement, per-mode agreement + uncovered_with_native; flip hint cites agreement rate; +22 tests.
- Gates: RC 5787p/2sk/94st exit 0; DS 7075p/1sk/1xf exit 0; ruff + ASCII clean.
- OPS: RC-Supervisor task was NOT running (restart_trigger sat unconsumed); schtasks /Run /TN RC-Supervisor restored; watch it next session.
- NEXT (gated): play real ARAM -> covered+native rows accrue -> hz_shadow_report agreement gate -> operator flip decision.

---

# 2026-06-10 - gemini loop cycle 4: Phase 5 stabilization tail - HZ-D1 DONE [item 383, HZ-D1 slice 4]

Gemini-headless-upgrade executor cycle (run 2026-06-10-01 cycle 4). Directive = Phase 5 stabilization tail (electron-updater + stable/dev channels, crash isolation). Merges `96cf5241` + `544cff59` (2 PARALLEL worktree agents, verifier-CONFIRMED) + merger integration `33dc9b3a`. NO engine, no Share, no RC restart, no web/ touch (UI audit n/a).

- Update channels: NEW pure `rc-shell/src/update_channel.js` (resolveChannel env RC_SHELL_CHANNEL > saved > stable; channelConfig dev=allowPrerelease; mergeChannelPatch; checkPlan 15s initial + 4h interval, not-packaged/updater-missing disable). main.js lazy-requires electron-updater in try/catch - bare-node require THROWS inside the autoUpdater getter (app.getVersion on undefined), so the catch is load-bearing (probed). autoInstallOnAppQuit only, console-only events, Shell-menu channel radios + Check-now. NEW electron-builder.yml (nsis, publish github Remus3/riot-commander, all-channels update files; private repo = GH_TOKEN at runtime).
- Crash isolation: NEW pure `rc-shell/src/crash_guard.js` (RESTART_REASONS; killed/clean-exit never resurrect; per-key rolling budget 3/60s -> give-up hides, no strobing). Merger wired attachCrashGuard on BOTH windows: render-process-gone -> reload | hide; unresponsive logs only.
- package.json 0.4.0; npm install restored 258 pkgs (registry reachable). node 109 -> 145/0 (TDD red-first both slices). RC tests/ 5769p/2sk/94st exit 0; DS 7075p/1sk/1xf/1942st exit 0 (canonical Python314 path - bare `py` lacks pytest).
- HZ-D1 flipped DONE in ORCHESTRATION_PLAN (Electron phases 1-5 all shipped code-side; Phase 6 Pengu optional/operator-gated).
- OWED (operator): packaging + first GitHub Release + packaged-app update check; in-match overlay capture (one shell relaunch picks up slices 1-4).

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
