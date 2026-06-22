# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-22 (headless continue 18 / R16) - Game Flow + Spike Curve fixture audit

Item 584, commit `7ecb5b18` (pushed) + this docs-sync. Tier-0/1 frontend (CSS comment = asset-hash
auto-reload ADR-008, no RC restart). NO engine / DS / Share / ENGINE_VERSION / overlay-render / flip.

CONTEXT: gemini+ahk loop executor cycle. Directive = ORCHESTRATION_PLAN R16 ui-audit (5-phase
fixture audit of the un-audited Game Flow + Spike Curve panels). Overlay-polish lane stays DRAINED.

AUDIT (perf_curve.js / spike_curve.js / spike_markers.js + CSS vs UI_SCALE_SPEC_V2.md): all 3 panels
v2.1-compliant - mode/metric buttons hit `--hit-min` 42px, type on `--fs-sm`/`--fs-xs`, spike_curve
carries its 2 item-184 inline exceptions, spike_markers cells are display-only (no click handler ->
not hit-targets), all 6 files ASCII-clean.

MUST-FIX (in-slice): perf_curve.css `.pf-ylab/.pf-xlab font-size:13px` is a legit scaled-viewBox SVG
chart-glyph user-unit but its rationale lived only in the file header, not INLINE like its sibling
spike_curve.css. Added the inline operator-exception comment (zero pixel delta) + NEW TDD guard
`CssSubFloorFontExceptionTests` (RED->GREEN) failing any sub-16px hardcoded font-size lacking an
inline exception within 6 lines. spike_markers off-grid spacing (1/2/3/6px, radius 4px) deferred
FUTURE (pre-existing, not a NEW value per the spec's "no NEW off-grid" rule).

VERIFY: 136 slice + 13 hygiene tests green; ruff clean; CSS served live on :8888 (asset-hash reload,
index+css 200); verifier subagent CONFIRM 6/6. Live Claude_Preview shot OWED (RC-owned :8888 preview-
attach blocker - same as R4/R8/R13 - + active_match spike panels live-game-gated; mode_key=client).

NEXT: overlay-polish lane still DRAINED; expect the director to pick another off-lane ui-audit /
ds-sweep / lift, or NO_WORK.

---

# 2026-06-22 (headless continue 17 / R15) - OP-Score arc-shape readout (Aggregator A lift)

Item 583, feature commit `b49ef1a7` (pushed) + docs-sync. Tier-1 frontend + core analytics; RC
restarted (pid 3656 -> 9480, last_reload_ok) for the core/op_score_curve.py route change. NO DS /
ENGINE / Share / schema / flip change.

CONTEXT: gemini+ahk loop executor cycle. Directive = ORCHESTRATION_PLAN R15 lift (Section-7b Aggregator A
deep-dive; ship a HIGH-lift LOW-risk presentation finding in-run).

RESEARCH (3 disjoint parallel agents, 6-point checklist -> docs/COMPETITOR_LIFT_2026-06-22.md):
Aggregator A builds / OP-Score+profile / live+overlay. RC already matches-or-exceeds most surfaces
(contextual build planner + antitank > Aggregator A fixed frequency order; rune/spell auto-push, Electron
overlay, role-grade + MVP/SVP, benchmarks, objective callouts all shipped). The one NOW-eligible gap:
Aggregator A's per-line curve "shape keyword".

SHIPPED (TDD red-first): NEW core/op_score_shape.py - pure deterministic classifier labeling each
per-minute wins/losses curve (the OP Score tab already plots them over the local rewind corpus) as
Snowball / Ramping / Front-loaded / Commanding / Behind / Steady / Volatile from start/end/trend/
volatility (RC's own vocabulary). compute_op_score_curve attaches out["arc"]={win,loss}; the route +
cache serve it; op_score.js/css render 2 chips (win-green/loss-red, --fs-xs) + a tooltip read;
op_score.json gains an arc field. No new dep / Riot / Claude / DB schema.

VERIFY: 49 slice tests green; ruff clean; 5-phase UI audit CLEAN; live ui_mock pixel capture (Wins
Snowball / Losses Ramping, 16px); verifier CONFIRM (DS/Share untouched). Full RC suite = 9369 passed
/ 12 PRE-EXISTING failures (item-578 aram_balance template cluster incl. 7 ds_pick_consumption ARAM
subfails + overlay.css px + spell_prefs.json drift) - all independent of this slice, 0 regressions.

NEXT (FUTURE, triaged): single-match per-minute OP-Score line + duo "recently played with" + a 0-10
post-game rollup (presentation, deferrable); live matchup board / enemy-WR / live benchmark delta /
jungle timers (live-game-gated); per-slot frequency + ranked LP trend (new dependency / schema).

---

# 2026-06-22 (headless continue 15 / R14) - cc_conditional durations_floor_s CC floor band (ENGINE 1.150.0)

Item 581, commit `66abc012` (pushed, CI green). Tier-2 DS schema lift: ENGINE 1.149.0 -> 1.150.0,
DS :8893 bounced, Share re-synced in the feature commit; full dual suite (DS-dir 7472 passed).

CONTEXT: gemini+ahk loop, MANUAL single-cycle executor (operator ran /gemini-headless-upgrade with
args = read+execute ops/loop/control/directive.md now). Directive = ORCHESTRATION_PLAN R14 ds-sweep.

BUILT (TDD red-first): optional ConditionalCcEntry.durations_floor_s (None default; loader .get);
default-OFF apply_cc_floor seam on cc_pressure.compute_cc_pressure crediting floor + prob*(max-floor)
instead of max*prob when ON, in both the standalone and coexistence MAX-rule paths
(_conditional_credit_seconds). Byte-identical OFF (parity proven Maokai/Ashe/Hecarim/KSante/Sion/Brand).
Seeded 5 vs Meraki 16.12.1 minimums: Maokai R 0.75 / KSante W 0.5 / Sion R 0.25 / Hecarim R 0.75 (4
existing) + a NEW Ashe R 1.0 coexisting entry (range_gated, durations_s 3.5; Ashe R also unconditional
1.5). Registry regenerated via the canonical generator (durations_floor_s on every record);
externalization guard count 64->65. ENGINE pins bumped across 80 DS test files + 3 consumer pins.

VERIFY: DS-dir 7472 passed; new floor test 13; cc_conditional 1352; externalization 11; Share --check
in sync; ruff clean; DS :8893 live 1.150.0. The verifier subagent hit a transient 529 (0 tool uses) so
the gate was a fresh first-hand re-verification (R7 exempts single-thread edits). ZERO regressions: the
tests/ suite's other failures (3 aram_balance KeyError + overlay.css bare-px + spell_autopush) all
reproduce on clean HEAD 38326ed3 / from the dirty spell_prefs.json - pre-existing, not R14 (logged to
the ORCHESTRATION_PLAN Findings log + LEDGER 581).

NEXT: live default-ON flip + ehp/hybrid propagation are operator-gated -> docs/LIVE_GAME_GATED_SYNC.md.
