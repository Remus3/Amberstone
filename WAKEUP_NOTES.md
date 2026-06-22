# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

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

---

# 2026-06-21 (headless continue 7) - candidate triage: a/b/c all drained -> weekly-hygiene (no build)

Overlay-polish red queue + ZOI slices 1-3 came in DONE. Interviewed the Gemini director for the next
priority from the 3 prompt candidates; a GROUND-TRUTH PROBE drained all three, so per the operator's
pre-authorized fallback this became a weekly-hygiene pass. No code/engine/DS/Share change.

CANDIDATES - do NOT re-chase (each verified vs live codebase, like this run's predecessor item 1):
- (b) adaptation st-* "wall of dashes": HEADLINE ALREADY SHIPPED - commit `94f1e07b` wired
  `_hideEmptyStatRows()` (right_now.js:456 <- main.js:1443): hides no-live-producer rows + collapses
  empty group headers, idempotent. `gd_at_15` has a producer ONLY in core/match_metrics.py (post-game)
  so it is NOT live-derivable (Gemini's example was wrong). Residual = wiring a live stat (e.g. KP) into
  the RETIRED Chrome dashboard adaptation panel = low value (the overlay, not that panel, is the surface).
- (c) aggregator G PGR reframe: FULLY SHIPPED S2-S5 (`77c3cc3`/`92c6a0f`/`e6cd350b`/`48bc58c8`/`c162e5bd`;
  ROADMAP_HISTORY flipped to SHIPPED). Explore-agent mapped the surface: no unshipped bounded slice.
- (a) ZOI slice 4 champion-only template matching: the ONLY genuinely-unshipped candidate, but LOW
  value + HIGH risk. core/minimap_blob_detect.py:16-19 author note: "for a ZOI map-control signal, total
  team presence is the right input anyway"; pure-numpy template match on a noisy 312px minimap crop is
  brittle and would REPLACE the just-shipped live-verified presence detector. BOTH Gemini passes said:
  do NOT build it blind. Parked (future, no owner) - needs operator/Gemini sign-off before any attempt.

HYGIENE (relocate-only doc trim committed; memory edits local/uncommitted):
- WAKEUP 6->2 entries: continue 4 / HEXCORE / continue 3 / continue 2 relocated VERBATIM to
  docs/history_notes.md (this entry + continue 6 + continue 5 kept).
- MEMORY.md: 14 longest index lines trimmed (26.2KB -> 25.4KB). STILL ~1KB over the 24.4KB load
  budget (slug-length floor across ~28 medium lines). FLAG: run `/consolidate-memory` to dedupe /
  consolidate the index (incl the 3 retired Game-PC ADR-011 tombstones) - beyond a light pass.
- CLAUDE.md clean (0 leaked ledger items).

ANOMALIES (both EXPECTED, no action): RC-CostHealthWatchdog last_result=1 = a genuine cost breach
(today $2.65 vs $0.655 7-day baseline, flap:false), the expected signature of all-day live SR coaching;
hot lane = `sr_coach` Haiku - the known Haiku-to-ZERO program, NOT a new defect. peer bridge health
publisher stale = the Peer peer not publishing; the Peer bridge probe was deprecated from /done 2026-06-21.

NEXT: the operator-listed candidate set (a/b/c) is EXHAUSTED. The next cycle needs a NEW operator refill
or direction, not another pick from a/b/c. The repeated "already-shipped" hits (item 1, then b + c this
cycle) mean the curated backlog is stale - grep-verify any future pick against the live tree first.

---

# 2026-06-21 (headless continue 6) - overlay-polish queue item (1): already shipped, only a stale comment

Gemini director picked overlay-polish ROADMAP queue item (1) = "FIGHT MODEL pane `#am-pane-ovds` clips
in DEFAULT, gate to build-only." GROUND-TRUTH PROBE FOUND IT ALREADY SHIPPED: the doctrine widget-field
model (commit `7bd7d6a3`, the cfdc9f22 batch) gates `w-ovds` to the build panelset ONLY - overlay.css
section 4d hides it in default/coach/threat (L418/421/437) + shows it only in build (L451); the pane is
a `fit-content` `.ovx-widget` (no height cap, inner `overflow:visible`) so it auto-sizes and no longer
clips. The 25 Playwright overlay snapshot tests already render-assert `#am-pane-ovds`=none in default +
shown in build (all 25 PASS this run; the lone teardown ERROR was the session prod-artifact guard
tripping on the LIVE practice game writing `data/*.jsonl`, NOT an overlay-test failure).

SHIPPED (Tier-0): corrected the one genuinely-stale artifact - the `overlay_ds_controls.css` header
comment said "base subset + the build panelset" / "section 4b" (both wrong); now reads build-ONLY /
"section 4d" + documents the deliberate behavior change. ROADMAP queue item (1) marked RESOLVED with the
evidence + a do-NOT-re-chase-the-662/1305-clip note.

No live rc-shell relaunch: the change is a code comment (zero render delta); the prompt's relaunch
mandate is for NEW overlay JS/CSS that renders differently, and the gating is CSS-structural (proven by
the real-browser snapshot suite + live-CDP-verified last cycle for the ZOI canvas itself).

NEXT: the overlay-polish red queue (items 1-5) is now fully DONE/RESOLVED - only minor w-* default-
position tuning remains, so the "route EVERY cycle here" run is winding down. Re-interview Gemini for the
next priority: candidates = ZOI slice 4 (champion-only isolation via template matching), the ~88 unwired
ADAPTATION st-* rows (item 281), or the aggregator-G-style PGR reframe. WAKEUP is at 6 entries - due for a
weekly-hygiene trim to the last 2-3.
