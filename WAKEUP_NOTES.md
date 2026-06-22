# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

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

---

# 2026-06-21 (headless continue 12) - ARAM "ARAM Modifications" balance line WIRED (BACKLOG F6)

Item 578, commit `b541c923` (pushed). Tier-1; no backend engine / DS schema / Share / ENGINE bump /
overlay render / flip change. Coach-prompt context line only -> ZERO overlay render delta, no electron relaunch.

TRIAGE: live re-probe RC pid=3656, live SR game up (mode_key=sr ~22min full-build carry), DS :8893 ENGINE
1.149.0 / 16.12.1, HEAD 2bfe7113. Candidate set 1/2/A/B/E DRAINED (items 573-577); all remaining named levers
operator-gated. The Gemini director (gemini-3-pro-preview) was UP this cycle (down the prior 2) and surfaced a
FRESH non-gated BACKLOG pick a recency-biased Explore sweep missed: F6 (BACKLOG.md:39). A parallel Explore agent
independently called the hot candidate set drained, confirming F6 was the only fresh lever.

VERIFY-BEFORE-BUILD (grep-confirmed): aram_modifiers IS consumed internally by the DS engine (dps.py:697 dealt,
ehp.py:545 taken, +burst/ability_dps/hps/cc_pressure/engine + aram_tenacity_context.py:73 tenacity) but NO web/
surface renders the dealt/taken deltas (COMPETITOR_LIFT_2026-06-21.md:116 says so literally). core/aram_tenacity_
context.py is the shipped render-side precedent but covers ONLY tenacity (1 of 3 player-facing axes). The Plan
subagent corrected 2 briefing data errors vs live 16.12.1 (Maokai is both-axes not dealt-only; Aatrox/Garen NOT
damage-neutral, so Ahri 1.0/1.0 is the correct test neutral-anchor); re-verified live.

BUILT (subagent-first, TDD red-then-green): NEW sibling core/aram_balance_context.py (load-once map, fail-soft,
per-field fallback, _ARAM_MODES gate) -> aram_balance_line(champion, mode) = signed whole-% clauses
"(mult-1.0)*100", e.g. Akshan "ARAM balance: you deal +5%, take -5% damage"; EMPTY non-ARAM/unknown/neutral
(byte-identical prompt in the 46/172 neutral case). Enemy line a deliberate non-goal (126/172 non-neutral would
render every game; damage delta is a self-tuning signal, unlike tenacity's exploitable CC window). Wired into
coaches/aram_coach.py beside the tenacity line; forced edit added aram_balance="" to the 3 tenacity-test
.format() calls. +new tests/test_aram_balance_context.py; 82/82 pass, ruff clean, ASCII/LF; no frozen file.

VERIFIER GATE + OVERLAY TRACK: read-only verifier independently SHIP (82 passed, lone benign RF5 live-game guard;
4 behaviour outputs exact; scope = 4 files + pre-existing spell_prefs.json dirt). Per-cycle overlay track PASSED
in parallel: render-contract 25/25 + geometry audit overlay_layout.js/overlay.css CLEAN (zero MUST-FIX, baseline
intact). In-game ARAM pixel frame OWED (live game was SR; an ARAM coach line is not SR-verifiable).

NEXT (operator-gated): all 3 player-facing ARAM modifier axes now surfaced (tenacity prior + damage dealt/taken
item 578); residual aram_modifiers fields (healing/shielding/AH/AS) are minor + situational, a future call.
Levers unchanged: overlay S0 shadow->authoritative flip; magnitude-as-bar (Phase-4); HZ Tier-2 partial-combo.
Candidate set drained - next cycle needs a fresh Gemini/operator refill.

---

# 2026-06-21 (headless continue 11) - overlay spec Q2 lethal-incoming S0 predicate WIRED

Item 577, commit `17128058` (pushed). Tier-1 pure-JS; no backend / engine / DS / Share / ENGINE bump /
schema / threshold / flip change. ZERO live render delta (shadow-only) -> no electron relaunch needed.

TRIAGE: live re-probe RC pid=3656 mode flipped client->game mid-cycle (a live SR game came UP), DS :8893
ENGINE 1.149.0 / 16.12.1. Candidate set 1/2/A/B confirmed DRAINED (per the prompt + items 573-576). The
Gemini director was DOWN (gemini-3-pro-preview empty after 150s - quota/RPM), so fell back to spec-first
discipline against the ROADMAP TOP PRIORITY (the overlay-polish run). An Explore agent mapped the live
overlay vs the RC2 condensation spec and surfaced the ONE genuinely-unshipped slice: spec section-9 Q2
lethal-incoming (the priority-100 S0 EMERGENCY cue) had a COMPLETE consumer but NO producer -> the
emergency tier was structurally suppressed.

VERIFY-BEFORE-BUILD (grep-confirmed myself, not trusting the Explore pass): no core/dashboard producer sets
`coach.lethal_incoming` (the "lethal" grep hits are the DS lethality stat / burst target presets,
unrelated); the live coach envelope already carries hp_pct (0-100 scale, =100 at full); signalFromState is
SHADOW-only (`right_now.js:494-516`, the live flip is operator-gated in LIVE_GAME_GATED_SYNC.md) so wiring
it cannot regress the live render; the one shadow output that drives CSS (`body[data-fight]` via isFightCue)
was ALREADY true in both combat bands, so the lethal promotion provably cannot flip it = zero render delta.

BUILT (TDD red-then-green): signalFromState derives `lethal = explicit lethal_incoming flag OR
_isLethalAtFight(band, hp_pct)`, the helper firing iff band in {fight,urgent} AND `0 < hp_pct <= 25`
(LETHAL_HP_PCT named const, conservative emergency floor). Dead/missing HP (0 or absent; dataclass default
0.0) guarded out so a data dropout can never false-fire the reserved lethal-red pop-out (A2). Explicit-flag
passthrough preserved (back-compat). +8 TDD tests (fight/urgent derivation, boundary 25 incl/26 excl,
non-combat no-fire, healthy no-fire, zero/missing/None guard, explicit back-compat, selectPrimary->100);
37/37 pass; node -c clean; ruff clean. Read-only verifier subagent gate: SHIP (scope/frozen/engine clean, 4
sanity booleans correct). Overlay render-contract re-run: 25/25 pass (lone error = the documented live-game
RF5 artifact guard, not a failure).

OVERLAY CADENCE: render-contract GREEN (25/25 + 37/37). Live in-game pixel capture NOT warranted this cycle
- the change is shadow-only (zero rendered-pixel delta; the lethal cue is not yet drawn, that is the
operator-gated flip), and the :8889 frame is token-gated (401). In-game pixel frame OWED only when a
render-affecting overlay slice ships.

NEXT (operator-gated): the lethal cue is now READY for the operator-gated shadow->authoritative S0 flip
(LIVE_GAME_GATED_SYNC.md). Remaining overlay slices vs spec are Phase-4-deferred (magnitude-as-bar) or
already shipped. HZ levers unchanged (C partial-combo Tier-2 operator-gated; flip do-not-flip-blind).
Candidate set drained - next cycle needs a fresh Gemini/operator refill.
