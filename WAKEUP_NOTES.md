# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

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

---

# 2026-06-20 (RC 2.0 /RC2-Continue - Phase 3.1 + 3.2 overlay condensation)

Resumed the RC 2.0 program (P3/P4 unblocked by the Hextech greenlight). Accidental computer
restart mid-session between 3.1 and 3.2 - git was clean, P3.1 already pushed, recovered cleanly.

- P3.1 (75a2c10b): docs/research/RC2_OVERLAY_CONDENSATION_SPEC.md - the in-match glance-test spec.
  3-tier model (Ambient/Urgent/Emergency) on classifyAction bands, S0 single-winner arbitration
  ladder (lethal 100 -> none 0), motion rationing, Hextech color bins, 3.2/3.3 handoff. Tier-0 doc.
- P3.2 (39303acb + db6f77d4): web/js/lib/overlay_priority.js (selectPrimary + shouldPulse, dual
  ESM/CJS, 21/21 node TDD - the test was pre-authored+untracked from a prior cycle) + overlay
  callout 2-row density clamp (CSS #rn-callouts nth-child(n+3) + snapshot). Tier-1, no ENGINE/DS/frozen.
- NOT wired (DELIBERATE, do NOT flip headlessly): the pulse-rationing consumer re-point
  (right_now.js .action pulse :490-500 + overlay_pulse.js -> shouldPulse) is a SHARED dashboard+overlay
  BEHAVIOR change -> carried to 3.3; needs shadow + 5-phase UI audit + operator eyeball on the live headline.
- Banner 27/62 = ~44%. Task pane: 9 phase chips (P1/P2 completed, P3 in_progress).

NEXT via /RC2-Continue: P3.3 (typography/hit-targets/hierarchy + Hextech bins + the pulse wiring above),
then 3.4 dashboard-stays-when-overlay-active, 3.5 settings-without-hotkeys, 3.6 dashboard condensation.
Then Phase 4 (Electron sizing/DPI), Phase 5 coaching, E10/E11/E12/E7/E2. Memory: project_rc2_build.
