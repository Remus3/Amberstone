# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) + R47 UI-audit cycle 16 (2026-06-30, full in LEDGER 702) + E11 sweep (2026-07-04, LEDGER 773-774) archived + /live-gated-drain (2026-07-04, LEDGER 780) archived 2026-07-05. Only the last 3 sessions kept here.

---

# 2026-07-05 (R80 - item-keyed basic-attack-DR EHP seam, the R77 sibling lane; LEDGER 791)

Gemini-loop executor cycle 9 (DIRECTOR REFILL rotation 2). Directive: premise-check ORUN3 + ORUN4, then rotate to the REFILL DS-sweep. Commit `bd397d36` (feat) + docs-sync commit. ENGINE 1.180.0 -> 1.181.0, DS :8893 bounced, Share synced.
- PREMISE: ORUN3 (Aggregator B per-stat PGR strip) + ORUN4 (Aggregator D game-flow strip) are BOTH CLEAN duplicates (verified vs LIVE code) -> flipped DONE-CLEAN. ORUN3 == OQ12 (CS/min lm-rank-cspm last_match.js:520 + KP%/gold-share/dmg-share sub-lines last_match.js:1048 + champ_benchmarks.js); ORUN4 == R16 perf_curve.js + ORUN2 899b5f24 snowball-elasticity.
- BUILD (R80): fresh Meraki-vs-registry refute -> Plated Steelcaps 3047/223047 Plating 10% basic-attack DR was defensive_only NOTE-only (ZERO EHP credit). NEW ItemEffect.basic_attack_damage_reduction (0.10) + ehp.item_aa_dr_multiplier + physical-only compute_ehp fold behind default-OFF assume_item_aa_dr; mirror of R77 crit-DR, never cross-credits; byte-identical OFF; +5.3% phys EHP armed at the 0.5 midpoint.
GATE: TDD 17 + DSV9 end-append guard co-fix; DS 8032 pass; verifier CONFIRM 7/7; 123 ENGINE_VERSION pins bumped. CO-FIX (R77 a8302f01 pattern): the ENGINE bump re-fired 6 HZ-B stamp guards + 1 DAEMON_SLAYER doc-drift -> re-stamped HZ-B tables byte-exact 1.181.0 (173 roster preserved; the item-388 --static 10-champ seed footgun caught + reverted per the R78 warning) + the doc banner; RC 293 affected-class re-verify -> 10746 / 0 fail. Share --check green 410 files.
DO NOT redo: ORUN3 + ORUN4 are CLEAN duplicates (do NOT re-pitch a Aggregator B per-stat strip or a Aggregator D game-flow strip); Steelcaps AA-DR is SHIPPED (do NOT re-pick 3047/223047); Frozen Heart 3110 enemy-AS aura is the next OPEN sibling candidate; the live default-ON flip -> LIVE_GATED B46 (do-not-flip-blind, the 0.5 AA-share midpoint calibration is the accrual tail).

---

# 2026-07-05 (ORUN2 slice 2 - snowball-elasticity Build Insights UI panel; LEDGER 788)

Gemini-loop executor cycle. The deferred UI half of ORUN2 (backend was 9cd38c13). Commit `899b5f24`, pushed. ENGINE-IMPACT NONE (frontend; ADR-008 asset-hash reload, no RC restart / no Share / no DS).
- NEW web/js/panels/snowball_elasticity.js (mount bi-snowball-mount, export renderSnowballElasticity) + .css (se- prefix) + web/data/ui_mock/snowball_elasticity.json + tests/test_snowball_elasticity_panel_dom.py; wired via build_insights.js import+dispatch + a "Snowball" tab/pane in index.html + a dashboard.css @import (panel-import parity).
- Faithful mirror of duration_winrate.js but SR-ONLY (no mode bar / champ picker): 2 checkpoint blocks (10min/20min) x 5 signed gold-lead buckets behind_big..ahead_big; bar fill = Laplace-smoothed win%, value = raw win% (or ~smoothed% thin / "-" below min_bucket_n); per-checkpoint elasticity chip (snowball-prone/comeback-prone/elastic) = games-weighted ahead-vs-behind smoothed lean, DESCRIPTIVE not a win probability.
GATE: 1 build subagent + verifier CONFIRM (targeted 74/74 + full RC suite 10725 passed/0 failed/2 skipped exit 0) + independent 5-phase UI-audit PASS 0 MUST-FIX + ui_recon visual proof clean (companion+desktop, 2 blocks x 5 bars, 0 page errors, no overflow). Live curl shape matched the fixture.
DO NOT redo: ORUN2 FULLY SHIPPED (backend 9cd38c13 + UI 899b5f24); SR-only by design; next OPEN = ORUN3 (Aggregator B per-stat PGR strip) / ORUN4 (Aggregator D game-flow strip), then REFILL.

---

# 2026-07-05 (FIX-FIRST test red-state recovery - 3 residual clusters; LEDGER 787)

Gemini-loop out-of-band executor cycle. Cleared the 3 residual red tests that LEDGER 786 / the ORUN2 finding deferred, before the ORUN2 UI panel slice proceeds. ENGINE-IMPACT NONE (test + doc only). Commit `4aac77de`, pushed.
- S1 doc_size_budget: ROADMAP.md 88794 -> 81024B (< 81920) - relocated 3 fully-shipped bullets verbatim to docs/ROADMAP_HISTORY.md (player-snapshot 782 / HOME-E11 768-774 / DS cross-eval 495-497). No rewrite.
- S2 motion_reduce_sweep_oq4: directive undercounted - TWO failures. `.lobby-status.searching` purged repo-wide by E11 (`1cf122e2`), not just an 8->7 drift. Removed dead home.css SITES entry + assertion 8->7 + docstrings (7 loops: item_build x2 + map_state x2 + header x3).
- S3 lcu_loop_resilience x5: ROOT CAUSE = snapshot_panels Playwright fixtures leave a ProactorEventLoop running on the main thread -> a later bare asyncio.run() raises "cannot be called from a running event loop". Fix = _run_coro daemon-thread pattern (already used by test_p2w1_core_f.py / test_p2w2_ds_h.py). Test-only.
GATE: full RC suite 10701 passed / 2 skipped / 192 subtests, exit 0. Orchestrator: slice 3 worktree subagent (verifier-gated) + slices 1+2 inline.
DO NOT redo: the 3 clusters are FIXED; `.lobby-status.searching` is gone by design (E11 purge - do not re-add to SITES); the lcu asyncio-suite immunity is _run_coro (do not revert to bare asyncio.run).
