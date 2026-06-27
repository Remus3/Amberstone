# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-27 (live-flip validation + overlay launcher fix, `2e8abb36`)

Operator-driven live session: Practice Tool games (KSante / Briar / Ezreal) to close the "live half" of the offline-confirmed DS seam flips, tracked via /api/state + game-monitor.

- **KEY FINDING - do NOT re-investigate.** The live-flip DS seams (R5 missing-HP heal-amp, DSP2 off-class exempt, DSP11 kit-axis, and by inference R12/R30/RF1/RF3) are UNWIRED across the DS /rank HTTP boundary. The flags live ONLY in the in-process scorers + tests + offline `live_flip_eyeball.py`; `dispatch_for_coach` (archetype_dispatch.py:232) -> client -> server.py /rank passes NONE of them and /rank does not accept them. The live build-chooser runs every scorer DEFAULT-OFF. PROVEN live: Briar at 7% HP gave byte-identical daemon_slayer_picks to 100% HP. So these are NOT eyeball-able by gameplay - flipping default-ON is multi-file engine wiring (+ self-HP input for R5) + ENGINE bump + Tier-2, not a toggle.
- R12 Evenshroud is Arena-only (map30) on 16.13.1 - SR-untestable. No in-game build widget on the overlay (build-chooser is dashboard-only).
- **Ctrl+Shift+A is NOT a focus/keydown bug.** It is an Electron globalShortcut (rc-shell/src/main.js:1063; overlay_state.js:44 tagged "operator's expected combo 2026-06-27"), focus-independent. Shell IS running (1 instance, requestSingleInstanceLock works - the 5 electron.exe are one instance + helpers). Likely an accelerator collision; register() failure is swallowed (main.js:1081). Diagnostic-first next: log the register() booleans.
- **SHIPPED (`2e8abb36`).** Legion ON/OFF now manage the rc-shell overlay: ON launches it via a cmd-start trampoline (console-detached - closing the launcher terminal no longer kills the overlay; was a coupling bug I introduced) + auto-close window; OFF taskkills rc-shell electron matched by cmdline only (Claude Desktop spared). rc-shell was already idempotent.
- **Operator vision captured -> `docs/NO_LLM_PRECOMPUTE_PLAN.md`.** Drive the WHOLE project to no live LLM via a client-side CV tier + precomputed "expansive DB" (pay-once-build, runtime API-key-free). Budget is idle: Max 20x at 11%/17% used, Sonnet 0%, $418 credits untouched. Findings detail: `ops/audit/ds_perm_swarm/report/live_input_seam_findings_2026-06-27.md`.

NEXT: (1) decide sequencing - wire the DS seams across /rank first vs build the precompute DB first (both feed the build-chooser). (2) Ctrl+Shift+A globalShortcut-collision diagnostic. (3) trace the long coach tick on base-attack (untraced). (4) in-game build widget. Pre-existing anomaly (not mine): RC-LiveFlipWatcher Disabled/result=1.

---

# 2026-06-27 (gemini-headless director CONTINUITY fix + gemini artifacts + overlay-only, `d8445fec`/`8554d2a8`/`f3346b83`)

Operator overnight (Opus 4.8, ultracode): fix the gemini-headless self-handoff redundancy (director re-issues completed work), verify Gemini<->Claude, run /gemini-headless-upgrade. Plus: overlay-only UI, fix gemini tone/style/memory artifacts, commit hexcore.

- **Root cause (3-way confirmed).** docs/LEDGER.md is newest-first (top=newest); `director()` fed `tail('docs/LEDGER.md',90)` = the OLDEST entries (~item 325, 3wk stale), so shipped items 618-633 were INVISIBLE and got re-proposed. Git proves it: `e24410d6`/`b951f985` "R28 CLEAN no-op - directive premises already shipped 618-621".
- **Fix (TDD `d8445fec`).** new `head_lines()` newest-first reader; `build_director_context` now sends an explicit ALREADY-COMPLETED DIGEST (recent commits + LEDGER HEAD + the persisted directive chain `ops/loop/control/directive_history.jsonl`, gitignored, survives restarts) + a BUILD-ON/de-dup HARD RULE. Sibling tail-inversions fixed: loop_controller ROADMAP read + `tools/gemini_audit.ps1` ROADMAP/BACKLOG (Head helper). GEMINI.md gains the continuity/memory model + bans the meta-narration preamble ("last directive was a false positive / stale read" artifact). 7 RED-first tests + 10 existing loop tests green; ruff clean; gemini_audit.ps1 parses.
- **Verified live.** gemini_ask round-trip grounded; REAL 2-cycle director proof PASS (builds on 631-633, no re-issue, chain visible); dry controller<->stub handshake PASS (2 chain records persisted). Independent verifier + repo-wide sibling-sweep workflow CONFIRM (16/16 clean-state).
- **Overlay-only (operator 2026-06-27).** Chrome :8888 dashboard RETIRED as a viewing/audit surface; UI = Electron overlay ONLY. director_prompt.md + skill 3b UI-audit refs retargeted to the overlay (`?overlay=1` / rc-shell). Memory: `feedback_electron_overlay_only`.
- **Opportunistic (`8554d2a8`).** CLAUDE.md DS banner -> live /health 1.151.0 / 706 items / 173 champs (patch 16.13.1).
- **Hexcore (`f3346b83`).** Operator's "accretion disk" rework committed.

NEXT: /gemini-headless-upgrade launched for the overnight (deep audit + lift + UI/overlay audit + DS sweeps); the director now BUILDS ON completed work, no re-issue. Pre-existing anomaly (not mine): RC-LiveFlipWatcher Disabled/result=1.

- **R33 (loop cycle 4, `9eb644c9`)** - Section-3b overlay-cue typography audit. ward_cue.css + objective_chips.css (overlay-only) were sized on the dashboard token var(--fs-xs) 16px, out-shouting the 14px w-call ACTION verb; routed both to overlay var(--fs-ov-chip) 13px (R8 overlay-scoped-token doctrine). RED-first guard added to test_overlay_css_typography_tokens.py. CSS-only asset-hash reload, no restart/ENGINE/Share. **VISUAL OWED:** populated overlay pixel capture of the ward/objective cues - deferred, no live game (mode=client); cues need live data to render. Capture on the next live SR/ARAM game.

- **R34 (loop cycle 5, `a3d38c0e`; ledger 635)** - Section-7b heavyweight Aggregator D deep-dive (`docs/COMPETITOR_LIFT_2026-06-27_AGGREGATOR_D.md`, 12 findings). Signature = delta-vs-baseline + popular-vs-winrate dichotomy. SHIPPED F1 in-run: the personal_build champ-select panel dropped the served `most_common_build`; now renders a "Usual" line + per-row usual pips + a conditional survivorship insight (underused-winner / overused-loser) - pure presentation over the already-served /api/personal-build payload, no new compute/route/dependency. Tier-1 frontend (CSS+JS, asset-hash reload, no restart/ENGINE/Share). TDD RED-first, verifier CONFIRM 24/24, 5-phase UI-audit PASS. F3 matchup delta-stats table (HIGH/new-compute) + F8 snowball/comeback bar (MED) -> BACKLOG. **VISUAL OWED:** populated champ-select pixel capture (no live game; headless snapshot `champ-select_personal-build.png` is the audit-trail proof).

---

# 2026-06-26 (console-flash fix - RC-CIWatchdog subprocess, `0028c8ac`)

Operator reported terminal windows flashing open/closed intermittently on Legion. Diagnosed + fixed in one pass.

- **Root cause.** RC-CIWatchdog fires every 2 min (`PT2M`) under a `pythonw.exe`-hosted task; its `_run` helper at `tools/ci_watchdog.py:316` spawned `git`/`gh` children with no `CREATE_NO_WINDOW`, so each child allocated a console that flashed onscreen. Exact `feedback_avoid_console_flash_legion` mode.
- **Fix.** Added `creationflags = 0x08000000 if os.name == "nt" else 0` to the `_run` subprocess call (repo's cross-platform-safe idiom; no-op off Windows). Tier-1, no restart - the scheduled task re-reads the script on its next fire, so flashing stops within ~2 min.
- **Swept siblings, both clean:** `cost_health_watchdog.py` (no subprocess - in-process HTTP); `ops/rc_supervisor.py` frozen but ALREADY has `CREATE_NO_WINDOW` at :857. CIWatchdog was the only offender.
- **Verified.** `py_compile` OK; `test_ci_watchdog.py` 30/30; hygiene gate 13/13. Pushed `0028c8ac`.

NEXT: nothing pending from this fix. Confirm the flashing is gone over the next few CIWatchdog cycles. Pre-existing anomaly (not mine): RC-LiveFlipWatcher Disabled/result=1.
