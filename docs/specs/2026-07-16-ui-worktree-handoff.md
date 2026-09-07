# LANE U (UI/UX no-game) worktree handoff - 2026-07-16 night run

Branch: `ui/overlay-item4-item8-20260716` (headless, autonomous). NO merge to
main tonight; NO RC/DS restart; NO 5-phase visual fixture audit (Electron
windows would fight the AHK bridge for focus) - the audit + merge run in the
next interactive session, per the audit-before-ship ritual.

## Scope pinned (verify-premise-first)

- **Item 8 (rank-tier stats backend) was ALREADY SHIPPED + merged to main**
  before this run (LEDGER 869/870/873 - "item-8 = DONE"). Re-building it would
  be a defect, so this lane did NOT touch it. Confirmed live this run: the
  backend files exist tracked (`core/rank_tier_bench.py`,
  `core/rank_tier_source.py`, `data/rank_tiers/rank_tier_averages.seed.json`,
  `config/rank_tier_source.example.json`, the `rank_tiers` data-pipeline
  subcommand, the `GET /api/rank-tier-bench` route in
  `dashboard/routes_bench_rank_tier.py`) and its 6 test files pass:
  **73 passed** (`test_rank_tier_bench`, `test_rank_tier_source`,
  `test_routes_bench_rank_tier`, `test_data_pipeline_rank_tiers`,
  `test_overlay_item8_rank_tier_selector`, `test_upstream_drift_rank_tier_refresh`).
  NOTE: the lane brief said "from data/rewind_history.db" but the resolved
  design (spec + shipped code) sources rank-tier averages from the external
  seed/aggregate - `rewind_history.db` has NO rank/tier column. Nothing to do.

- **Item 4 (Client Settings reorg)** was the real open work (LEDGER 872 STILL
  OPEN: "item-4 DS Settings"). Only the out-of-game Settings menu portion is
  safely buildable headless; the in-game overlay portions (D/E/F below) are
  visual/interactive and are deferred to the audit session.

## SHIPPED this run - item 4 Slice 1 (commit `ee2db2ff`)

Out-of-game Settings menu (`web/index.html` `#settings-body`), Sections A/B/C
of `docs/specs/2026-07-11-overlay-item4-client-settings-reorg-design.md`:

- **A** CHAMP SELECT card renamed **CLIENT SETTINGS**; consolidates Champ
  Select / Pre-Game Lobby / Post Game Review / Voice as labelled
  `.settings-subgroup` sub-heads in one card. **All control ids unchanged**
  (dev.js/main.js wiring intact - verified: zero JS pageerrors). PGR
  sub-renames: "Rank-tier comparison" -> "Rank-Tier"; "Baseline window (prior
  games)" -> "Baseline Games".
- **B** removed COACHING ACTIONS / HEADLESS LOOP / DATA-METRICS cards. Visual
  removal only - the `/api/command force_vision` route + dev.js binders stay
  (null-guarded), so no backend rip-out.
- **C** API SPEND GATES kept (comment flags it for later removal). DISPLAY kept.
- CSS: new `.settings-subgroup` / `.settings-subhead` in
  `web/css/panels/header.css` (secondary sub-head + hairline group rule).

Tests observed THIS run (headless Playwright/DOM, Tier-1):
- NEW `tests/snapshot_panels/test_settings_client_reorg.py` - 6 pass.
- Combined settings + push-toggle regression re-run: settings-view (4) +
  reorg (6) + r30 (2) + force-scan (6) + push-toggles (14) = all green;
  broader grep-hit sweep run = **1 failed then fixed -> re-run green**
  (`test_csv_push_toggles_phase5` re-anchored on the Champ Select sub-group;
  `test_settings_review_r30` filter re-pointed at CLIENT SETTINGS;
  `test_settings_force_scan_dom` IndexHtmlTests inverted to guard the removal).
- `ruff check` clean on all 4 touched/new `.py` files; ASCII-only diff.

## THE AUDIT SESSION MUST DO (tomorrow, interactive, before merge)

1. **5-phase UI fixture audit** on the new CLIENT SETTINGS card
   (STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY). The sub-head
   styling (`.settings-subhead`) is a first cut - confirm the sub-groups read
   one tier under the gold card head and the hairline rule spacing is right at
   1920x1080. Resolve any MUST-FIX in-slice, then merge branch -> main.
2. Confirm the settings quick-filter still feels right at card granularity now
   that 4 groups live in one card (matching "voice" reveals the whole CLIENT
   SETTINGS card - acceptable; sub-group-level filtering is out of scope).

## DEFERRED item-4 work (visual/interactive - NOT done tonight)

Grounded anchors for the next build session:

- **D. Panel Visibility rework** - per-mode show/hide + bidirectional in-game
  <-> settings sync; REMOVE the "Out-of-Game" category.
  Anchors: `web/js/main.js:6469` (RC2 E1 builds the Panel Visibility card),
  `web/js/panels/panel_visibility.js:7` (the mode-context list incl.
  out-of-game), the per-widget hide path `overlay_layout.js`
  `_setHidden`/`_toggleHidden`, sync bridge `web/js/lib/overlay_settings.js`.
- **E. Opacity split** - flagged `[item-7 territory]` in the spec, NOT item 4.
  Split the single `overlayOpacity` into panel-background vs content layers,
  two sliders. Anchors: `web/js/lib/overlay_settings.js:72,160,210`
  (`overlayOpacity` + `--rc-overlay-opacity` apply), `web/css/overlay.css:79`
  (`opacity: var(--rc-overlay-opacity,1)`). Genuinely visual - do with an
  in-game eyeball. Track under item 7.
- **F. In-game DS Controls strip-down + Overlay Options hub + lock model.**
  `web/js/panels/overlay_ds_controls.js` `_settingsHtml()` (lines ~259-322)
  today renders keep/pin/separate/pulse/zones(Hover-to-interact)/opacity/
  revert(Auto-passive)/panelset/interact/rearrange/raise/reset-items PLUS the
  item-8 rank-tier + role selects PLUS the 4 knobs (`_stripHtml`, ~190-216).
  Spec F wants DS Controls = 4 knobs + rank-tier + role + the DMG/SURV/UTIL
  shaper (`web/js/panels/ds_shaper.js` -> `GET /api/ds-shape`, and fix its
  dead-stepper bug) ONLY. The window-mgmt controls MOVE to a new **Overlay
  Options hub** (`overlay_layout.js` launcher menu `_setHidden`/`_setOpacity`/
  `_setScale`), which also gains per-panel opacity split + the rank-tier
  selector. A **lock model** replaces Hover-to-interact (panels
  movement-locked unless Overlay Options is open).
  ORDER MATTERS: build the Overlay Options hub FIRST (new home) before
  stripping controls out of DS Controls, or the operator loses access. This is
  why F was NOT attempted headless - it needs the hub + an in-game eyeball.

## Merge

`git checkout main && git merge --ff-only ui/overlay-item4-item8-20260716`
AFTER the audit passes. Assets auto-reload via the ADR-008 asset-hash (no RC
restart for web/css/js-only changes).

## 5-phase audit results (2026-07-17, pre-push gate on merge 090fc62d)

Ran headless code-side; live :8888 DOM-verified (4 sub-heads present, 3 removed
cards absent); pixel capture OWED (browser screenshot pipe stuck 2x - carry to
the next live overlay session per ritual rule 3).

- MUST-FIX (resolved in-slice, same push): .settings-body lacked align-items -
  the 1-row DISPLAY card stretched to the consolidated card's row height.
  Fix = align-items: start (header.css). Plus the .settings-subhead size
  inversion (--fs-sm 18 ABOVE the card head's --fs-xs 16, contradicting the
  slice's "one tier under" claim) -> --fs-xs.
- SHOULD-FIX (FUTURE): (1) set-voice-name select has zero JS consumers
  repo-wide (the working picker is #voice-picker, main.js:6903) - populate it
  from speechSynthesis sharing the rc-voice-name key, or drop the row.
- NICE (FUTURE): dev.js:81-86 /api/diagnostics fetch fires before its
  removed-consumer guard (hoist the id-check); index.html:1507-1518 moved PGR
  option block keeps stale indent; set-voice-on shows persisted checked state
  while TTS deliberately starts OFF each load (pre-existing).
- ID-wiring verdict: INTACT (every moved id resolves once; removed-card ids
  null-guarded at their binders). STRUCTURE/TYPOGRAPHY/HIT-TARGETS/ASCII/
  HIERARCHY all PASS post-fix; no scroll regression.
