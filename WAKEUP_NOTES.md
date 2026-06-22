# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

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

---

# 2026-06-22 (headless continue 13) - DS doc-drift reconciled + standing doc-pin GUARD added

Item 579, commit `99f2e72b` (pushed). Tier-0 doc + Tier-1 test; no engine / DS schema / Share /
ENGINE bump / overlay render / flip change. ZERO overlay render delta -> no electron relaunch.

TRIAGE: live re-probe RC pid=3656 mode=client (no game up), DS :8893 ENGINE 1.149.0 / 16.12.1, HEAD
6e7a7afc. Candidate set 1/2/A/B/E/F6 DRAINED (573-578); all named levers operator-gated. A parallel
Explore agent gave up at the docs level (recency-biased-sweep). The Gemini director (gemini-3-pro-preview,
UP) surfaced the fresh non-gated pick: docs/DS_COMPLETENESS_GAP.md f1+f3 (doc drift + no reconciler guard).

VERIFY-BEFORE-BUILD (grep-confirmed): __init__.py:18 ENGINE 1.149.0 vs doc banner stale 1.144.0;
server.py registers 28 routes, doc line 119 listed 15 (missing 13 scored-axis routes); module-map test
row 5931 vs live DS-dir 7362; no existing guard test. DS CHANGELOG.md DOES carry 1.145-1.149 (gap-note,
not backfill).

BUILT (TDD red-then-green): NEW tests/test_docs_daemon_slayer_drift.py (3 tests, sibling-style) pins the
doc banner ENGINE_VERSION->__init__.py + patch->current.txt + endpoint list->server.py routes; does NOT
pin the volatile test counts. RED first (1.144.0!=1.149.0 + 13 missing), then fixed docs/DAEMON_SLAYER.md
(banner 1.149.0/7362; full 28-route list; tests 5931->7362; 1.145-1.149 changelog gap-note) -> GREEN 3/3,
ruff clean, ASCII. Verifier subagent: SHIP (MISSING=[] PHANTOM=[], anti-tautology proven). Overlay track
PARALLEL + PASSED: render-contract 25/25 + geometry CLEAN; in-game ARAM frame OWED (mode=client).

NEXT (operator-gated): guard now fails locally on the next bump/route-add that forgets the doc. Minor
follow-up (NOT done, scope): CLAUDE.md deep-ref line still cites stale ENGINE 1.101.0. Levers unchanged:
overlay S0 flip; magnitude-as-bar (Phase-4); HZ Tier-2 partial-combo. Candidate set drained - next cycle
needs a fresh Gemini/operator refill.
