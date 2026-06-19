# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-19 (gemini-loop R3 cycle) - DS passive_damage caster bonus-armor/MR scaling (LEDGER 513)

Gemini DIRECTOR refill R3 (ops/loop/control/directive.md, REFILL PROTOCOL): DS schema lift -
passive_damage caster-defensive-stat (bonus armor / bonus MR) scaling. Commit `ab23c32c`, CI
pending push; Tier-2, ENGINE 1.144.0 -> 1.145.0, DS :8893 restarted -> 1.145.0 live, Share
re-synced SAME commit, 0 frozen.

- SCOPE (verify-before-build): the eval chain ALREADY existed end-to-end - DamageBlock
  bonus_armor_pct/bonus_mr_pct + _SCALING_TARGETS (-> caster_bonus_armor/caster_bonus_mr) +
  AbilityContext.from_build. The ONLY gap = the hand-authored passive_damage REGISTRY did not
  carry the two %-fields. Thin bridge, not a new evaluator.
- IMPL (_passive_damage_overrides.py, default-OFF byte-identical): added bonus_armor_pct/
  bonus_mr_pct to PassiveDamageEntry + PerStackTerm; to_damage_block copies them -> evaluator
  applies via existing _SCALING_TARGETS loop, ZERO new math. Seeded Taric P (25:93 + 15% bonus
  armor) + Galio P (15:115 + 100% AD + 45% AP + 60% bonus MR; crit omitted -> AA-crit seam).
  Both no_damage/empty-blocks (no double-count), both metadata-only (NOT AA-routed: Taric
  post-spell-2-hit + Galio periodic gates).
- SWEEP (172 champs): ONLY these 2 clean linear cases. FUTURE residual (not built blind):
  K'Sante P (bilinear caster-resist x target-HP, All Out gated) + Rammus W (TOTAL-resist reflect,
  needs a caster-total-MR field) - see ORCHESTRATION Findings.
- TDD: test FIRST 10 fail/8 pass RED -> impl -> 18/18 GREEN (hand-computed: Taric L1@100armor=40,
  L18=108; Galio L1 ad200/ap100/mr50=290, L18=390). ENGINE pins quoted-literal only (79 DS test
  files byte-bumped, 0 residual). Share/docs/02 PassiveDamageEntry field list updated.
- VERIFY: DS 7379 pass/1 skip/1942 subtests; RC 8634 pass/2 skip with 1 EXPECTED transient
  (test_live_three_profiles caught the mid-suite DS-restart window at stale 1.144.0) -> re-ran
  fresh = 1 passed, /health 1.145.0. ruff + Share --check green. Inline sole orchestrator (R9
  single-file lift; verifier skip R7). [[reference_ds_bump_run_tests_dir]] /
  [[feedback_engine_bump_quoted_literal_only]] / [[feedback_verify_before_declare_broken]].

---

# 2026-06-19 (gemini-loop R2 cycle) - Build Insights UI audit + doc-size unblock (LEDGER 512)

Gemini DIRECTOR refill R2 (ops/loop/control/directive.md): Section-3b 5-phase UI audit of the
Build Insights surface + recent tabs + the item-511 GPI drilldown. Commit `9b55615d`, CI green;
Tier-0/1 CSS-only, 0 ENGINE / 0 frozen / no DS / no Share / ADR-008 auto-reload (no RC restart).

- AUDIT: build_insights / duration_winrate / op_score / player_gpi (JS+CSS) vs UI_SCALE_SPEC_V2.
  STRUCTURE/TYPOGRAPHY/ASCII/HIERARCHY PASS. Directive premise corrected: op_score_curve.js ->
  real file op_score.js (the curve is the backend module). 1 MUST-FIX: `.bi-table th.bi-sortable`
  used `min-height` (a no-op on a display:table-cell) so the 42px sort-header hit target was never
  applied -> switched to `height`. Deferred NICE-TO-HAVE: gpi-tip radius token; Min-buys inert on
  chart/curve tabs (R1-logged).
- VISUAL: Claude_Preview cannot attach to :8888 (per R1) -> Playwright harness
  test_player_gpi_view.py 5/5 PASS incl. the item-511 drilldown interaction + regen radar PNG.
- RED-FIRST UNBLOCK: full suite surfaced a PRE-EXISTING doc-size fail (ROADMAP.md 82355 > 81920
  after the 510/511 commits; CI runs no pytest). Relocated the 2026-06-01 items-241-259 shipped
  epic to ROADMAP_HISTORY.md (breadcrumb keeps Phase-D + #7/#8). ROADMAP 76587, doc-size green.
- VERIFY: full RC suite 8634 passed / 2 skip (CSS fix + 5 GPI snapshots in it) + doc-size 2 + 47
  ROADMAP-ref tests. Inline sole orchestrator (1 CSS line < worktree threshold; verifier skip R7).
- NEXT: headless surface saturated (per LEDGER 511 completeness scan); remaining = live-gated /
  operator-product / outward-gated.

---

# 2026-06-19 (re-run orchestrated Q&A swarm) - GPI drilldown swarm-found + shipped + D1 slice-3 (LEDGER 510/511)

Operator re-fired the IDENTICAL "multi agent orchestrator Q&A swarm complete the open items" prompt
(same as LEDGER 508/509, same day). Scope pre-resolved to full-autonomy ship-all (the identical prior
run + overnight headless) - no re-ask. Repo unchanged since 508/509 so the disposition was nearly
drained; shipped the one named headless follow-up + a swarm-discovered miss.

- SHIPPED 2 (Tier-1, 0 ENGINE / 0 frozen / no DS / no Share): (510) D1 slice-3 `.pytest_cache` rglob
  leak in `tools/ds_share_sync.py` (`_is_pyc` -> `_is_transient`, leak 5->0; cleaned the on-disk
  working-tree pollution; commit `f4b8e0ee`); (511) GPI per-champion DRILLDOWN end-to-end (backend
  `51b9e957` + UI selector `d050523b`, ADR-008 auto-reload). The re-run swarm's adversarial verifier
  proved the prior swarm's "gpi-drilldown needs a Tier-2 champ-pool source" gate GROUND-TRUTH FALSE -
  the source (`list_champions` = the join `compute_gpi` already runs) + the `?champion=` drilldown
  backend already existed; only the UI selector was missing (BACKLOG L137 had it right). UI Fixture
  Ritual: 5-phase PASS, 0 MUST-FIX (1 SHOULD-FIX `color-scheme: dark` applied in-slice); 5 snapshot
  tests pass incl. a new drilldown interaction test.
- DISCOVERY SWARM (`wf_afa19bf2`, 7 agents / 240s, read-only scan+verify over 6 open areas): 1 SHIP
  (gpi-drill, shipped) + 1 GATED (carry-eff re-confirmed: the non-flip wiring is a provable no-op
  under the DEFAULT-OFF read-gate; only lever = the operator product flip) + 4 CLOSED (d1-untrack
  verb-redundant + un-track outward-coupled; universal-files out-of-repo; cdragon/p6 gated-or-done;
  missed-scan found CLAUDE.md:6 ENGINE prose drift 1.101.0 vs 1.144.0 but correctly GATED on the
  CLAUDE.md <60KB edit-discipline rule).
- NEXT: the headless open surface is genuinely SATURATED - remaining work is live-game-gated
  (`LIVE_GAME_GATED_SYNC.md`), operator-product (carry-eff flip; the CLAUDE.md ENGINE prose drift),
  or outward/Gemini-gated (D1 un-track slices 2-4; p6 g3/g6/g7). No headless-safe slice remains per
  the completeness scan.

---

# 2026-06-19 (orchestrated Q&A swarm) - complete the non-live open items (LEDGER 508/509)

Operator: "multi agent orchestrator Q&A swarm complete the open items" + a scope
AskUserQuestion -> "Full autonomy, ship all". Read-only Workflow (20 agents = 10 items x
Draft+Verify; 1.69M tok / 414s), all 10 CONFIRM; supervisor applied the safe slices serially.
Commits `4623edd7` + `186a9165` + `a78fe657`, CI green (27847530746); Tier-1, NO ENGINE /
0 frozen / no DS / no Share.

- SHIPPED 2: 508 hz laning report `even` bucket + even<->hold map (`tools/hz_shadow_report.py`,
  report-only, +57 ticks 39%->53%); 509 D1 slice-1 `test_ds_share_sync_determinism.py` lock.
- ALREADY-SHIPPED 3 (do NOT redo): aram-override (467 `97920f56`), ci-watchdog (204 `391191be`
  built-not-armed, ROADMAP fixed), weekly-hygiene red (444; stale, self-heals 06-21).
- GATED-NOT-LIVE 5 (unblocks in LEDGER 509): carry-eff default-ON = operator A/B/C call (the
  `_ROLE_BASELINES` lever is WRONG, collides w/ sum-5.0 invariant; literal flip = silent no-op);
  gpi-drilldown needs a Tier-2 champ-pool source; universal-files out-of-repo; cdragon PGR-S2-gated;
  p6-g6 FORBIDDEN_BLIND, g3/g7 Gemini-down.
- NEXT (gated): hz engine threshold + LFS regen + live flip (`matchup.py`); D1 slices 2-4 (un-track
  + CI flip + gist re-key, outward; + the `.pytest_cache` rglob leak).
