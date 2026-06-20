# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-20 (RC 2.0 /RC2-Continue - Phase 7.5 verify-suite; Phase 7 HYGIENE COMPLETE)

P7.5 "verify dual suite green post-cleanup" DONE. Work `afa07330` + docs flip `a7c59635`.
Banner 52 -> 53 / 62 = ~85%. Phase 7 HYGIENE COMPLETE (7.1-7.5). Pushed, CI green.

- The verify stage was NOT a rubber stamp - found 5 REAL reds, one root cause: the prior
  `74cca91d` ASCII glyph sweep + prod hardening made coaches/adaptation_hint_champion.py +
  _cli.py emit ASCII arrows ^/v and ` | ` separator, but 6 stale agent3 round-test asserts
  still expected unicode (up/down/mid-dot). Production is correct per the ASCII rule; the
  tests were the defect. Fixed all 6 in round16/24/25/28/29 (4 failing + 2 tautology/dead).
- Cluster B: ROADMAP.md 88772 B > 80KB doc-size guard -> relocated 3 shipped mega-bullets
  (RC2 enumeration, swarm-progress, 2026-06-15 refill) to docs/ROADMAP_HISTORY.md
  (### Relocated 2026-06-20); ROADMAP now 65096 B (~16.8KB headroom); line 11 kept in-flight
  head + OPEN tail. Full dual suite 17151 passed / 0 failed. LEDGER #549. Sentinel written.
- EFFICIENCY (operator flagged live): ran the full 14.5min suite TWICE (~29min). Recorded in
  feedback_execution_efficiency_rules R6 - for test-string+doc-only fixes the targeted slice
  + deduction is enough; do NOT re-run the whole 17k suite for a count.
- LEFT UNTOUCHED (concurrent process, NOT this session): dashboard/_dispatch.py (M) +
  dashboard/routes_loop_monitor.py + tests/test_loop_monitor_route.py (new loop-monitor
  route). Do NOT auto-commit these in an RC2 session - they belong to whatever added them.

NEXT /RC2-Continue: Phase 8 stage 8.3 operator Q/A consolidation; then E10/E11/E12/E7/E2.
[[project_rc2_build]] [[feedback_execution_efficiency_rules]].

---

# 2026-06-20 (RC 2.0 /RC2-Continue - Phase 7.1 ASCII-sweep close + Subagent-First protocol)

P7.1 ASCII-violation sweep CLOSED (Phase 7 HYGIENE begins). Commits `dbbd7a8d` (feat) +
`52c63336` (flip). Banner 48 -> 49 / 62 = ~79%. Then operator Subagent-First directive ->
`d9580d21`. All pushed, CI green.

- P7.1: tree ALREADY banned-glyph clean (prior P2/P3 cycles); only immutable `_archive/` keeps
  em-dashes -> VERIFICATION + ENFORCEMENT, not mass-rewrite. Census: banned set 0 tree-wide +
  per-frozen 0; `p3_ascii_sweep --dry-run`/`--doc-dry` 0 subs / 546 .py. Tightened
  `tests/test_smart_quote_hygiene.py`: dropped the frozen skip (operator "frozen INCLUDED") + new
  `test_frozen_files_clean_of_banned_glyphs` lock. Doc `RC2_ASCII_SWEEP_VERIFICATION.md`. 15 green.
- Subagent-First (operator 2026-06-20): always subagents for substantive work; design spec THEN
  act; new session interviews Gemini/operator + verifies before build; refines R9. CLAUDE.md
  "## Subagent-First Protocol" + memory `feedback_subagent_first_protocol` + block into 14
  `.claude/commands/*.md` (gitignored; applied BY 3 subagents). Excluded sleep/wake/game-monitor.
- NOTE: command files GITIGNORED (local) - durable levers = CLAUDE.md + memory. done.md has 19
  em-dashes but is untracked = not a tracked violation.

NEXT /RC2-Continue: P7.2 stale-file census (.md/scripts unused >1 week); then 7.3/7.4/7.5, Phase 8
(8.3), E10/E11/E12/E7/E2. [[project_rc2_build]] [[feedback_subagent_first_protocol]].

---

# 2026-06-20 (RC 2.0 /RC2-Continue - Phase 3.3 overlay shadow-wire + hit-target)

P3.3 (typography/hit-targets/hierarchy + pulse-rationing wire), headless-safe slice. Commit
`87f41baf`. Tier-1 JS-logic + overlay CSS. NO ENGINE / 0 frozen / no DS / no Share. Stage = LIVE
(code done; pulse flip operator-eyeball-owed). Banner 27 -> 28 / 62 = ~45%.

- overlay_priority.js: NEW `signalFromState(p, band)` - the one pure coach-envelope -> selectPrimary
  signal map (band passthrough, choices detect, Phase-4 crossing-edge predicates
  spike_crossed/objective_steal_now/lethal_incoming default-false + honored-if-set). Dual ESM/CJS.
- right_now.js: SHADOW consumer - each render stamps data-s0-cue/-tier/-pulse on #right-now via
  signalFromState->selectPrimary->shouldPulse, try-guarded, ZERO live pulse change. Eyeball-able at ?overlay=1.
- overlay.css: section-7 floor - #rn-choices .rc-chip min-height 44px (overlay-scoped; dashboard keeps 42).
- TDD: +8 signalFromState node tests (RED 8f/21p -> GREEN 29/29) + 1 overlay snapshot hit-target (test_overlay_view 13/13).
- OWED LIVE FLIP (NOT headless): re-point .action per-band pulse (right_now.js:490-500) + overlay_pulse.js
  MutationObserver to consume data-s0-pulse (fire only Emergency + one-shot-Urgent cross). SHARED
  dashboard+overlay behavior -> docs/LIVE_GAME_GATED_SYNC.md; eyeball a real game first. Hextech literal
  swap = E11 (overlay uses --signal-* tokens, inherits the global cutover).

NEXT via /RC2-Continue: P3.4 dashboard-stays-when-overlay-active (E1 keepCompanion shipped; verify +
any residual), 3.5 settings-without-hotkeys, 3.6 dashboard condensation. Then Phase 4 (Electron
sizing/DPI), Phase 5 coaching, E10/E11/E12/E7/E2. Memory: project_rc2_build.
