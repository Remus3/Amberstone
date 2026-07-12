# Item 8 - In-Game Stats Panel: Rank-Tier Rework - Implementation Plan

Status: plan grounded against real code (Plan agent, 2026-07-11). Operator intent
captured in memory project_overlay_item8_rank_tier_stats_panel. Open choices below
carry recommended defaults pending operator confirmation. Re-verify cited anchors
at build time (RC verification discipline).

## Goal
The in-game overlay stats panel benchmarks the operator against a SELECTED rank-tier
average (for self-improvement), mode-specific, instead of the operator's own history.
Rank selector synced in-game (DS Settings) <-> out-of-game (PGR/settings). 14/25min
brackets everywhere. Lane/role override relocated from the panel to DS Settings.

## Ground truth (verified)
- Overlay panel today = personal-history cohort: web/js/panels/stats_panel.js renders
  LVL/CS/TF/KDA for a role x bracket, fetching /api/role-bracket-bench;
  core/role_bracket_bench.py scans data/rewind_history.db WHERE game_mode='CLASSIC'
  (SR only). Brackets 1500s/2100s (stats_panel.js:33-34, role_bracket_bench.py:68-69).
- PGR already ships a STATIC rank-tier table: last_match.js _RANK_TIER_AVERAGES
  (10 tiers x {ARAM,SR} x metrics), tagged "estimate / reference - not measured".
  That is the static seed to lift; ARAM rows already zero vision (mode-specific precedent).
- role_bracket_grid() has exactly ONE consumer (routes_bench_role_bracket.py) and the
  route has ONE fetch site (stats_panel.js) - safe to repoint the overlay; nothing in
  PGR/review touches it.
- rewind_history.db has NO rank/tier column -> rank-tier averages MUST come from the
  external source (confirmed).
- External-source pattern to mirror: core/synergy_external_source.py (fetch, TTL,
  _http_get_json seam, fail-soft) + core/smoothed_rates_101qq.py (live-first, static
  seed fallback, RC_*_LIVE kill switch, source()->live|static|none).
- Shared setting rc-pgr-rank-tier ALREADY syncs PGR <-> Settings (last_match.js /
  dev.js). Overlay settings bridge = overlay_settings.js (localStorage rc_overlay_settings
  + rc-shell IPC). DS Settings strip = overlay_ds_controls.js.
- Refresh hooks: RC-PatchRefresh runs scripts/data_pipeline.py all WEEKLY (Wed) AND on
  patch - one hook covers both. RC-UpstreamDriftCheck (daily) trigger_refresh() for
  mid-week patch drift. Gitignored-config idiom: config/*.json gitignored + *.example.json.

## Phases (each shippable, TDD + per-page UI-audit)
1. Data adapter: core/rank_tier_source.py (fetch, mirror synergy_external_source) +
   core/rank_tier_bench.py (live-first, static seed fallback, RC_RANK_TIER_LIVE kill
   switch, rank_tier_grid(tier,mode)). Endpoint/keys in gitignored config/rank_tier_source.json
   (+ .example). Seed data/rank_tiers/rank_tier_averages.seed.json (lift _RANK_TIER_AVERAGES);
   gitignored live data/rank_tiers/rank_tier_averages.json.
2. Ingest+refresh: rank_tiers subcommand in scripts/data_pipeline.py (in `all`); stamp
   live patch. Hook upstream_drift_check.trigger_refresh(). OPERATIONS.md docs.
3. Rank selector + sync: benchmarkRankTier first-class in overlay_settings.js, mirrors
   to rc-pgr-rank-tier both ways; rc-shell IPC carries it across Electron windows;
   storage event for same-origin repaint. DS Settings select in overlay_ds_controls.js.
4. Panel rework (stats_panel.js): new /api/rank-tier-bench route; thread mode in
   (main.js renderStatsPanel(lc,{mode}) or body.dataset.mode); mode-specific metric rows;
   14/25 brackets (change 1500/2100 -> 840/1500 in BOTH stats_panel.js + role_bracket_bench.py
   in lock-step, drop "late"); REMOVE the in-panel role dropdown (.sp-role), keep _detectRole;
   RELOCATE role override to DS Settings; carry the source()/estimate-not-measured badge.
   Keep old route/module alive-but-deprecated so existing tests don't red.
5. Tests + UI audit: full suite; snapshot_panels regen; docs sync.

## Schema (data/rank_tiers/rank_tier_averages.json)
tier -> mode -> role -> bracket(early<840 / mid<1500) -> metric -> {avg}. role="all" for
laneless modes. schema/patch/generated_at/source header.

## Open choices (recommended default - confirm)
(a) Rank set: reuse existing iron->challenger 10-tier list, GLOBAL (not region-scoped).
(b) Per-mode metrics: SR + ARAM = LVL/CS/KDA/KP(bench-only, no live producer); Arena =
    LVL/KDA, DROP CS. NOTE: no Arena seed today -> Arena gates to "no benchmark" until the
    source supplies it. Arena 3rd metric needs live-Arena field confirmed.
(c) Storage: data/rank_tiers/ (committed seed + gitignored live), mirrors data/external/.
(d) Sync: reuse rc-pgr-rank-tier as single source of truth; no new endpoint.
Seed sourcing (operator 2026-07-11): seed from heuristic analysis of a large aggregate
(unnamed, gitignored config). If the source only publishes at a cadence that does not line
up with weekly/patch, flag the operator before wiring.

## Risks
1. Bracket change (1500/2100 -> 840/1500) is breaking: touch stats_panel.js +
   role_bracket_bench.py + asserting tests in one phase.
2. Keep role_bracket_bench route/module deprecated-alive, don't delete in phase 4.
3. Static seed is invented -> the "estimate, not measured" badge + source() must carry
   into the overlay or coaching leans on fiction.
4. Arena has no seed + near-zero CS -> gate Arena to "no benchmark".
5. Mode not passed to the panel today (main.js) -> thread it or read body.dataset.mode.
6. Overlay + companion are separate Electron windows -> rc-shell IPC (not localStorage
   alone) is the authoritative sync channel.
7. ARAM rarely reaches 25min -> MID ARAM cells thin/empty; ensure empty-cell fallback.

## Critical files
web/js/panels/stats_panel.js; core/smoothed_rates_101qq.py + core/synergy_external_source.py
(pattern to mirror); web/js/lib/overlay_settings.js (sync bridge); web/js/panels/last_match.js
(rc-pgr-rank-tier key + _RANK_TIER_AVERAGES seed, lines 185-214); web/js/panels/overlay_ds_controls.js
(DS Settings home for the selector + relocated role override).
