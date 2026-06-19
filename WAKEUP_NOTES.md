# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-19 (gemini-loop R4 cycle) - core coaching panels typography-floor UI audit (LEDGER 514)

Gemini DIRECTOR refill R4 (ops/loop/control/directive.md, REFILL PROTOCOL): Section-3b 5-phase UI
audit of three un-audited core coaching panels. Commit `9e56d23d`, CI pending push; Tier-1 CSS-only,
0 ENGINE / 0 frozen / no DS / no Share / ADR-008 asset-hash auto-reload (no RC restart).

- SCOPE: typography floor only (colors already tokenized). Tokenized 14 in-scope sub-floor (<16px)
  font-sizes -> --fs-* (team_context 7x + .tc-slot radius; coach_choices .rc-src + stale fallbacks;
  item_build ds-chip/em + build-label + item-cost + ib-builds-status + cs-build-label + build-value).
  2 documented operator-exceptions kept sub-floor w/ inline rationale (.item-name 14px tile-clamp;
  .cs-build-runes 10px dense column). EXCLUDED the cross-panel .kv/#nx-wave/.minimap-grid blocks in
  item_build.css (already-audited Right Now/Next/Active-Match, C2).
- TDD: tests/test_core_panels_typography_v21_floor.py FIRST (5 fail/2 pass RED) -> fix -> 7/7 GREEN
  (mirrors test_csv_typography_v21_floor.py). Independent 5-phase audit subagent = SHIP, 0 MUST-FIX.
- VISUAL + DISCOVERY: Claude_Preview ATTACHES to https://localhost:8888/ (prior cycles' "cannot
  attach :8888" = the legion-rc hostname cert mismatch; localhost works). Computed-style probe on
  the LIVE stylesheet: every in-scope selector resolves >=16px, the 2 exceptions hold, .rc-chip 42px
  -> confirms the ADR-008 reload served the edits. [[reference_claude_preview_live_8888]]
- VERIFY: RC suite 8642 passed/2 skip/0 fail (incl hygiene + bundle-parity guards); DS N/A (CSS,
  Tier-1); ruff clean. Inline sole orchestrator (R9; verifier = audit subagent + live probe + fresh
  suite). [[feedback_phase3_fixture_ritual]] / [[feedback_execution_efficiency_rules]].

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
