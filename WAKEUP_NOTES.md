# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-22 (headless continue 19 / R17) - DS anti-tank level-ramp %max-HP

Item 585, commit `5f308036` (feature, pushed) + this docs-sync. Tier-2 (DS schema / ENGINE_VERSION /
Share mirror): ENGINE 1.150.0 -> 1.151.0, DS :8893 bounced (pid 9340 -> new), Share re-synced.

CONTEXT: gemini+ahk loop executor cycle 6. Directive = ORCHESTRATION_PLAN R17 ds-sweep (antitank
ramp_lo/ramp_hi level-ramp %HP schema lift). Tightly-coupled single-file engine seam -> built inline
(full file context), verifier-gated before commit (no parallel-slice merge to gate).

WHAT: `AntiTankEntry` gains optional `ramp_lo`/`ramp_hi` endpoints (END-appended, default 0.0) +
`compute_antitank` gains optional `level`. Mirrors the P3.2 ap_ratio/ad_ratio default-OFF caster-stat
seam, for champion-LEVEL ramp. The hand-tuned magnitude encodes late-game (max-ramp) reliability; a
ramp-seeded row scales by `_level_ramp_factor` = lerp(ramp_lo,ramp_hi,(level-1)/17)/ramp_hi. DEFAULT-OFF:
level=None (the /anti-tank route default) AND level=18 are byte-identical to item 308/315; every
un-ramped row byte-identical at any level. Seeded 10 verified MAX_HP champion-level ramps (Aatrox 4:8,
Brand 8:12, KSante 1:2, Mordekaiser 1:5, Ornn 10:18, Renata 1:2, Skarner 5:9, Urgot 2:6, Zed 6:10,
Zeri 1:11).

DEVIATION (logged, intent over literal): director said "~16 rows", ground truth is 10 - the rest of the
%HP roster is rank-scaled (per-ability-rank) or flat, not champion-level ramps; Senna P (CURRENT_HP 1:10)
is a real level ramp but out of the %max-HP scope -> deferred sibling. A wrong seed is worse than a
missing one.

VERIFY: RED-first `test_antitank_ramp_r17.py` (25 cases). py_compile + ruff clean. DS suite 7497 passed /
1 skip / 1943 subtests; antitank cluster 94 passed. ENGINE pin sweep 85 files / 96 pins, 0 residual.
ds_share_sync --check green (372 files). Full RC suite 9367 passed - the 6 remaining RC failures are
PRE-EXISTING (reproduced on base `b00c4dc7` via stash: 3x CoachWire ARAM-template, doc_size_budget
ROADMAP-over-budget [FIXED this cycle - relocated 4 shipped bullets to ROADMAP_HISTORY, now under 80KB],
overlay.css sub-floor px, spell_autopush on dirty data/spell_prefs.json) - NONE are R17. Verifier
subagent CONFIRM (byte-identical contract independently reproduced).

CARRY-FORWARD: the 5 still-red pre-existing RC failures (3x CoachWire ARAM-template
`test_aram_user_template_format_with_field`, overlay.css sub-floor px, spell_autopush dirty-data) need a
separate cycle - NOT R17's scope. data/spell_prefs.json is a dirty runtime artifact left uncommitted.

LIVE-GATED: the default-ON flip (a survivability/draft consumer calling compute_antitank with the live
champion level) is EXCLUDED -> docs/LIVE_GAME_GATED_SYNC.md (validate early-vs-late level-discounted
scores vs a real game before flipping).

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
