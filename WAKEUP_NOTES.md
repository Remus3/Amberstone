# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-06-10 - gemini loop cycle 4: false REGRESS audit refuted + gate edge pins [item 387]

Gemini-headless-upgrade executor cycle. Directive = FIX-FIRST regression: audit claimed the
item-386 `lc.get("champion")` gate shipped untested (conftest + gate tests "missing").
REFUTED by ground truth: c7922951 (merged via d446ea80, INSIDE the audited range
9ccc64fa..b5533f85) carries gate + tests/conftest.py + tests/test_hz_shadow_live_gate.py
(4 tests) in the SAME commit. Auditor diffed only tip commit b5533f85 (docs+data only).

- Verified fresh pre-edit: gate+wiring 12 passed at HEAD.
- Shipped `c5cf8b56`: +2 edge pins in test_hz_shadow_live_gate.py (champion="" loading-screen
  edge; non-dict lc isinstance guard). Test-only, no engine, no restart.
- Gates: RC 5789p/2sk/94st exit 0; ruff + hygiene clean; CI run 27315276398 green.
- LOOP IMPROVEMENT (FUTURE): loop auditor should diff prev-done-sha..new-sha, not the tip
  commit - tip-only diffing produced this false REGRESS.
- DON'T REDO: HZ shadow live-gate IS tested (6 tests); do not re-add gate tests.
- NOTE: RC pid drifted 14160 -> 3336 during cycle (supervisor bounce); alive+reload_ok true.

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
