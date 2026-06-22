# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

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

---

# 2026-06-21 (headless continue 10) - HZ rewind-db ground-truth cross-ref + memory hygiene cleared

Item 576, commit `fc520407` (pushed). Tier-1 tooling; no engine / DS / Share / ENGINE bump / threshold /
precompute-table / flip change. PLUS the 3-cycle-owed memory hygiene pass.

HYGIENE FIRST (operator-mandated, owed 3 cycles - done BEFORE the build pick): ran /consolidate-memory.
MEMORY.md 25457 -> 24700 bytes (now ~24.1KB, 286B under the 24.4KB load budget it had been failing to
fully load). Folded the 3 retired Game-PC ADR-011 tombstones into one `reference_gamepc_retired_adr011.md`
(132 -> 130 files), repointed 2 dangling [[links]], ASCII-fixed the whole index (arrows/x/~/!=/<=/ellipsis
+ smart-quotes), trimmed ~24 long hooks. Memory dir is outside the repo = local/uncommitted (on disk).

TRIAGE: live re-probe RC pid=3656 (mode client->game mid-cycle, operator started a practice match), DS
:8893 ENGINE 1.149.0 / 16.12.1. Candidates 1 (DS cross-eval) + 2 (HZ blind flip) + A (item-575 diagnosis)
all drained/done. Gemini director (gemini-3-pro-preview) picked candidate B (the rewind-db cross-ref, the
item-575 stubbed follow-up) over C (Tier-2 partial-combo) - grounding the calibration in REAL outcomes
breaks the circular Haiku-vs-precompute dependency before any heavy engine change.

PROCESS (subagent-first, parallel): Explore agent mapped ground truth + surfaced the KEY CONSTRAINT (the
945 genuine mismatches are 483 ARAM / 460 SR / 2 client; ARAM has no laning phase -> lane-outcome ground
truth is SR-ONLY). Parallel overlay-verify agent: 25/25 overlay snapshot tests pass, all widget defaults
CLEAN, no overlay code change needed this cycle. Plan subagent emitted the file:line-verified spec
(corrected several Explore line numbers; confirmed the standalone import is safe - rv's agents imports are
LAZY). Build agent TDD-first; independent verifier gate SHIP before commit.

BUILT: `tools/hz_mismatch_diagnose.py --rewind` = an SR-only MATCHUP-AGGREGATE cross-ref over
rewind_history.db (no match_id linkage in the records, so it aggregates per (my_champ, enemy) matchup
across rewind SR games), reusing select_sr_match_ids / extract_lane_pairs / extract_kill_counts.
Order-independent match + my-perspective gold@10min + solo-kill orientation; conservative
agree/disagree/insufficient_data rule with a <3-lane-game low-sample guard; ARAM+client excluded+COUNTED;
honest sparsity. Additive (schema v1->v2 tool-local, default-OFF flag, v1 output byte-identical,
fail-soft on missing DB); agreement REPORTED-ONLY (anti-circularity, never a threshold trigger). +19
hermetic in-memory-sqlite TDD tests (no real-DB dep), 42/42 pass, ruff clean, ASCII/LF. CLI smoke on the
real DB: available=True, 654 SR matches, excluded {aram:483, client:2} (exactly matching the Explore mode
breakdown), 12 classes, coverage SPARSE (mostly-self-games DB -> most classes insufficient_data = honest).

NEXT (operator-gated): richer rewind SR coverage per matchup turns insufficient_data into a real
agree/disagree per CALIBRATION class -> THEN a justified threshold look. Remaining item-575 levers: (C)
Tier-2 partial-enemy-combo model for back_off->trade MODEL-ERROR (ENGINE bump + table regen, confirm
scope first; do NOT chase the metric); back_off->hold per-pair inspection. Flip stays do-not-flip-blind.
Hygiene debt CLEARED. Candidate set is again drained - next cycle needs a fresh Gemini/operator refill.

---

# 2026-06-21 (headless continue 9) - HZ laning-combat mismatch DIAGNOSED + overlay live-verified clean

Item 575, commit `367297b6` (pushed). Standalone Tier-1 diagnosis tool; no engine / DS / Share / ENGINE
bump / flip.

TRIAGE (candidates 1+2 verified DRAINED/GATED again - 5th cycle, grep-verify mandatory): live re-probe
RC pid=3656 mode=game (live SR game UP), DS :8893 ENGINE 1.149.0 / 16.12.1. (1) DS cross-eval + (2) HZ
blind flip confirmed drained/operator-gated per items 573/574. Gemini director (gemini-3-pro-preview)
picked candidate (A) - root-cause the now-GENUINE laning combat mismatches - and KEPT IT LANING-ONLY (NOT
the build-axis anti_squishy->anti_tank skew; mixing axes breaks scope).

PROCESS (subagent-first, parallel): an Explore agent mapped the combat-verdict pipeline -> a Plan subagent
emitted the file:line spec (KEY FINDING: the shadow log does not store net_swing, but
choices[0].expected_outcome embeds it - parse the LOG-TIME scalar, zero engine drift) -> a background
build agent implemented TDD-first -> an independent verifier gate PASS (22/22, ruff, partition invariant)
before commit.

THE DIAGNOSIS (real log, 17409 records, 945 genuine laning mismatches; `ops/audit/HZ_MISMATCH_DIAGNOSE.md`):
the over-caution is MOSTLY CALIBRATION, NOT Haiku noise. hold->all_in (151, med -0.02), even->trade (126,
med -0.06), hold->trade (91, med +0.06) all cluster at the hold/trade boundary (368 ticks, defensible).
ONE structural MODEL-ERROR pocket: back_off->trade (138, med -0.30) = the enemy sequence_b=_FULL_COMBO
over-kill (`core/laning_scenario_precompute.py:355`) - a threshold tune cannot fix a structural-input
error. The largest class back_off->hold (351, med -0.24) is per-pair ambiguous. Partition invariant
945==945==(2103-1158). +22 TDD, ruff clean, verifier-confirmed.

PARALLEL OVERLAY (operator directive, live SR Caitlyn game UP): 25/25 overlay snapshot tests pass (lone
teardown ERROR = the live game writing data/*.jsonl, documented env guard). w-spike(20,580) /
w-trinket(20,520) default positions (`web/js/lib/overlay_layout.js:50-51`) = clean left-edge column, NO
collision (Gemini's tune is a non-issue). Live composite screenshot: CALL + WARD-UP render in clean
doctrine positions, click-through, no HUD/play collision. Process-vs-mtime check: the RUNNING overlay
(electron 9736 @ 19:32:51) post-dates the ZOI render files (minimap_zoi.js @ 19:30:33) -> operator on
FRESH ZOI code, not stale. No overlay code change needed.

NEXT: the diagnosis converts the "54.6%" gate into 3 operator-gated levers - (i) a realistic partial-
enemy-combo model is the principled MODEL-ERROR fix for back_off->trade (NOT a threshold tune); (ii)
CALIBRATION classes need ground-truth (rewind-db / live side-by-side) before any _BACK_OFF/_HOLD_LOW nudge
(anti-circularity); (iii) back_off->hold needs per-pair inspection. Flip stays do-not-flip-blind. HYGIENE
STILL OWED (3 cycles): MEMORY.md ~1KB over the 24.4KB load budget - run /consolidate-memory next idle
cycle (a bounded build was picked this cycle, so deferred again per the operator rule).

---

# 2026-06-21 (headless continue 8) - HZ shadow agreement metric DE-BIASED (recall category error)

Item 574, commit `79a7906a` (pushed; restored upstream tracking the item-569 rewrite had dropped). Tier-1
tooling; no engine / DS / Share / ENGINE bump.

TRIAGE (the prompt's candidates 1+2 verified DRAINED before building - the curated backlog had 3 already-
shipped picks in a row, so grep-verify was mandatory): (1) DS cross-eval Aphelios dps zero-output BUG = ALREADY
FIXED (ENGINE 1.128.0; `ds_cross_eval/SYSTEMIC_FINDINGS.md:74-84,112`) and LIVE-CONFIRMED this session (re-probed
at live 1.149.0 -> dps ranks Yun Tal 103 / IE 96 / Stormrazor 82, not Doran's). B1 melee-gate + F2 gold-top
shipped default-OFF (items 496/497); Cluster A ARAM-override = operator off-meta call, not a bounded build. So
(1) has no bounded slice left. (2) HZ flip = NOT ready (laning 29.3% / build 48.9%, operator-gated). The 5-day
memory `project_ds_comprehensive_cross_eval` (Aphelios "clearest defect") predated the 1.128.0 fix - same stale-
backlog trap as items 1/b/c.

GEMINI DIRECTOR consult -> priority = de-bias the HZ shadow agreement metric. SUBAGENT-FIRST: Plan subagent
emitted the file:line-grounded spec -> impl TDD-inline (2 coupled files, worktree fan-out inappropriate per R9)
-> read-only verifier gate (117/117, fix confirmed in-impl, no production importer) BEFORE commit.

ROOT CAUSE + FIX: `tools/hz_shadow_report.py` scored the precompute choice-A laning-COMBAT verdict against the
native Haiku action even when that action was "recall" - an ECONOMY decision the combat-A can STRUCTURALLY never
be (the precompute's recall signal is choice B: "Recall now"/"Back soon"). ~1794 guaranteed mismatches were in
the laning denominator. Fix: native=recall excluded from the laning-combat comparable; routed to a NEW `economy`
sub-block {native_recall, precompute_also_recall} (`_is_recall_directive_label` catches BOTH "Recall now" AND
"Back soon" - classify_verdict MISSES the latter; labels HARDCODED not core-imported because a top-level core
import breaks the standalone `python tools/hz_shadow_report.py` CLI, verified live). Build (lean) + even<->hold
untouched.

RESULT: laning agreement 29.3% -> 54.6% (1133/2076); 1794 native-recall now in the economy block (all 1794 with
precompute also recalling); flip hint 31% -> 54%; remaining laning mismatches are now GENUINE combat disagreements
(back_off->hold x351, hold->all_in x151 = the actionable gate). TDD +6 / 3-updated, 41/41 pass; ruff clean.
DON'T redo: this de-bias; do NOT re-add native-recall to the combat denominator (it is cross-axis by design).

NEXT: the HZ flip stays operator-gated (do-not-flip-blind) - the honest gate now reads ~54% combat agreement;
the genuine combat mismatches (back_off->hold, hold->all_in) are the next signal to investigate IF a flip is
pursued. MEMORY.md still ~1KB over the 24.4KB load budget (a higher-priority build item was picked this cycle,
so `/consolidate-memory` is still owed - run it next idle cycle). Candidate set 1+2 now both drained/gated; a
fresh operator refill or a new Gemini-bounded slice is needed next cycle.
