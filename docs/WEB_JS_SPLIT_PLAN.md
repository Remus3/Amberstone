# Split plan for web/js/main.js and web/js/panels/champ_select.js

Status: PLAN ONLY. No slice has landed. Row: RM-726 (d), filed 2026-10-09 by
the repo review: "a split plan for main.js and champ_select.js is filed with
the 5-phase UI audit per slice". Written 2026-10-31 by the s144 queue lane,
measured at local main `fc123ec87`.

Guard: `tests/test_web_js_split_plan_rm726.py`. It parses the slice blocks
below and fails when a slice loses a field or names a symbol that is not
defined exactly once across its source file and its target module. It also
fails when a coupled file is missing or no longer names the code, or when a
view is not a real view id. So the plan stays true while it waits and while
slices land. When a slice lands, mark its heading `(LANDED <sha>)`; keep the
block, because the once-defined check is what catches a copy left behind.

## Why split, and what it does not buy

Measured at `fc123ec87`:

- `web/js/main.js`: 375,512 bytes, 7,949 lines.
- `web/js/panels/champ_select.js`: 210,363 bytes, 4,457 lines.

Both files grew on every lane since the row was filed. The filed sizes were
353 KB and 197 KB.

The split is for review and ownership. Today one view's fix means a diff
inside a 7,900-line file that every lane touches, and that is where lane
merges collide. The split does NOT make the page load faster. Both files are
ES modules served from the local dashboard, and ADR-008's asset hash already
reloads them on change. Do not claim a load-time win for any slice.

## Rules for every slice

1. MOVE, never rewrite. A slice cuts the anchors below into the target module
   verbatim, adds `export` / `import`, and changes nothing else. A behaviour
   change is its own row, before or after, never inside a move.
2. One slice per commit, one commit per cycle (the queue lane's one-row rule).
   A slice that turns out to be two is shipped as two. The one exception is a
   pair of slices that share a target module (MJ-1 and CS-1): they land in
   the same commit, because after either one alone the shared symbols are
   defined twice and the guard goes red, by design.
3. Re-point in the same commit. Many Python tests read these files as SOURCE
   TEXT and cut function bodies out by name, for example
   `tests/test_overlay_poller_mode_gate.py` and
   `tests/test_csv_build_chooser_part3_item240.py`. So a moved symbol makes
   those tests read the wrong file. They do not fail: they pass on an empty
   slice or fail with a misleading message. Open every file on the slice's
   Coupled line and, if it reads the source, point it at the target module.
   The Coupled lists were measured by co-mention (the file names the source
   file and at least one anchor). That is a superset: some are browser
   snapshot tests that never read the source, and those need no change.
4. Shared mutable state. A `let` cannot be reassigned through an import. A
   `let` that more than one module writes therefore moves into an object
   (the shape `web/js/lib/state.js` already uses for `state` and `_VIEW`), or
   it gets a setter. Circular calls (champ select's `_csvScheduleRender`
   calls `renderChampSelectView`, and almost every card calls the scheduler)
   are injected with a setter, the way `setDsSkillOrderScheduler` already
   works in `web/js/panels/ds_skill_order.js`.
5. No module-load side effects in a new module. `main.js` boots by running
   code at module scope, in file order. A target module only declares and
   exports; `main.js` still calls it in the same order. That keeps the boot
   order, which several tests pin (the overlay shell stamp must run before
   the router).
6. Tier: Tier-1 web. Before the commit: the slice's coupled tests,
   `tests/test_web_js_esm_parse.py` (a real ES-module parse; `node --check`
   is blind on import-leading files), `tests/test_web_ascii_sweep.py`, and the
   5-phase UI audit below.
7. The 5-phase UI audit runs on a HEADLESS render (the `tests/snapshot_panels`
   harness, `?ui_mock=1#<view>`), by an agent that did not write the slice,
   on every view on the slice's Views line, at 1920x920 and 923x1280. The five
   phases: STRUCTURE, TYPOGRAPHY, HIT-TARGETS, ASCII and HIERARCHY. They are
   defined in `tools/headless-uiux.md` section 5. A pure move must change zero
   computed styles and zero box geometry, so the strongest check is a
   before / after diff of the computed layout on those views. Every MUST-FIX
   is resolved in the same slice.
8. Ownership. These files are hot. Before a slice starts, check that no other
   lane branch has unlanded edits to the source file
   (`git log main..lane/<x> -- <file>` for every lane). If one does, wait for
   it to land.

## Order

Leaf first, hub last. MJ-1 and CS-1 share one new module (the two files carry
copies of `lcuCmd` / `lcuPollResult` whose code is the same apart from
comments), so MJ-1 and CS-1 land together, in the same commit, as the first
cut. Views move before the router that calls them (MJ-9), and the
boot-time pollers move last (MJ-10).

What stays in `main.js` at the end is the boot sequence and its dispatch:
`onState`, `onHealth`, `handleLcuEnvelope`, `connect`, `setMode` and
`renderHeader`, plus the boot wiring. What stays in `champ_select.js` is
`renderChampSelectView`, `handleChampSelect`, `renderChampSelectCoach`, the
team roster (`_csvRenderTeam`), the scheduler and lock button, and the
alignment helpers. That is roughly 1,300 lines.

## web/js/main.js slices

### MJ-1 - LCU command helpers
- File: `web/js/main.js`
- Target: `web/js/lib/lcu_cmd.js`
- Anchors: `lcuCmd`, `lcuPollResult`
- Coupled: `tests/snapshot_panels/test_lobby_view.py`, `tests/test_rm838_reply_scrub_non_ds.py`
- Views: `lobby`, `home`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above, headless, before the commit. Focus: the lobby Find Match / Cancel / queue-change buttons and the Home LCU actions still post and still show their status line (HIT-TARGETS keeps --hit-min and :focus-visible on each).
- Notes: lands in the same commit as CS-1 (rule 2). Pure leaf helpers called by Home, Lobby, Top 8 and auto-accept. The comment above them in `main.js` records why they live there (the champ_select.js copy was unreachable and every lobby click threw). That reason ends once both files import one module.

### MJ-2 - mock fixture resolvers
- File: `web/js/main.js`
- Target: `web/js/lib/mock_fixtures.js`
- Anchors: `_lobbyResolveLcu`, `_csResolveLcu`, `_amIsMock`, `_amMockLoad`, `_amMockUrl`
- Coupled: `tests/test_active_match_mock_fixtures.py`, `tests/snapshot_panels/test_active_match_view.py`, `tests/snapshot_panels/test_aram_balance_view.py`, `tests/snapshot_panels/test_champ_select_view.py`, `tests/snapshot_panels/test_overlay_view.py`, `tests/snapshot_panels/test_tft_ui_mock_active_match.py`, `tests/snapshot_panels/test_ui_mock_active_match_brawl.py`, `tests/test_overlay_minimap_clear_on_exit.py`, `tools/pseudo_screen_overlay.py`
- Views: `lobby`, `champ-select`, `active-match`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above, headless, before the commit. Focus: every ?ui_mock=1 page still paints its mock (STRUCTURE: no empty pane), on each mode fixture.
- Notes: the mock caches (`_amMockData`, `_amMockPromise`, `_csMockData`, `_lobbyMockData`) move with them, and the router, `onState` and `setupMinimapPoller` import the resolvers. Every `?ui_mock=1` snapshot depends on this slice, so run the whole Coupled list.

### MJ-3 - User Builds view and the rune picker
- File: `web/js/main.js`
- Target: `web/js/panels/user_builds.js`
- Anchors: `_UB`, `_RP`, `_userBuildsFetchAndRender`, `_ubRpBuildRow`, `_stripHtml`, `_userBuildsSave`, `_userBuildsWireOnce`
- Coupled: `tests/test_rune_hover_tooltip_dom.py`, `web/js/panels/codeql_js_hardening.test.mjs`, `tests/snapshot_panels/test_user_builds_view.py`, `tests/snapshot_panels/test_user_builds_rune_cells_focus_ring.py`
- Views: `user-builds`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above, headless, before the commit. Focus: the rune picker cells and the save button (HIT-TARGETS, keyboard path), and the rune hover tooltip text (TYPOGRAPHY).
- Notes: the biggest leaf view (about 760 lines), reached only from the router. `codeql_js_hardening.test.mjs` regex-matches the `_stripHtml` body in `../main.js`, so it moves to the new file in the same commit.

### MJ-4 - Session and History views
- File: `web/js/main.js`
- Target: `web/js/panels/session_history.js`
- Anchors: `_sessionFetchAndRender`, `_renderSessionTrend`, `_HISTORY`, `_historyFetchAndRender`, `_historyApplyFilters`, `_historyMatchRowEl`, `_historyResult`, `_sessionWL`, `_wireMatchRowToHistoricalPgr`
- Coupled: `tests/test_historical_pgr_dom.py`, `tests/test_history_resolved_badge.py`, `tests/test_history_session_wl_oq8.py`, `tests/snapshot_panels/test_history_view.py`, `tests/snapshot_panels/test_session_view.py`
- Views: `session`, `history`, `historical-pgr`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above, headless, before the commit. Focus: the history filters and match rows (HIT-TARGETS), the W/L badges (HIERARCHY), and a row click still opening the archive PGR.
- Notes: a leaf, but a match row opens the archive PGR, which needs `applyView`. Inject it (or import it after MJ-9). Never import `main.js` from a panel.

### MJ-5 - Home view
- File: `web/js/main.js`
- Target: `web/js/panels/home_view.js`
- Anchors: `_HOME`, `_homeFetchAndRender`, `renderHomePanel`, `_homeWireStartup`
- Coupled: `tests/snapshot_panels/test_home_view.py`, `tests/snapshot_panels/test_home_companion_view.py`, `tests/snapshot_panels/test_home_mode_tabs.py`, `tests/snapshot_panels/test_home_snapshot_card.py`, `tests/snapshot_panels/test_home_stale_fetch_race_rm508.py`, `tests/snapshot_panels/test_view_profile_radar.py`
- Views: `home`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above, headless, before the commit. Focus: the Home cards and mode tabs (STRUCTURE at both widths), the phase chip (HIERARCHY), and the stale-fetch race guard still holding.
- Notes: about 900 lines. The router reads `_HOME`, so it is exported.

### MJ-6 - Lobby, Mains and Party
- File: `web/js/main.js`
- Target: `web/js/panels/lobby_view.js`
- Anchors: `_LV`, `LANE_LABELS`, `SR_QUEUE_IDS`, `_lvQueueChangeError`, `_mainsFetch`, `_renderMainChamps`, `_renderPartyMembers`, `_setLanePref`, `_lobbyViewWireOnce`, `_lobbyViewRefresh`
- Coupled: `tests/test_web_element_id_resolution_rm339.py`, `tests/snapshot_panels/test_lobby_view.py`, `tests/snapshot_panels/test_lobby_render_stability.py`, `tests/snapshot_panels/test_lobby_duo_synergy_rm881.py`, `tests/phase_b_champ_select/test_lcu_lobby_members.py`, `tools/gated_rm881_duo_lobby.py`, `tools/lcu_agent.py`
- Views: `lobby`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above, headless, before the commit. Focus: the queue picker, lane-pref buttons and party rows (HIT-TARGETS), the mains tabs (STRUCTURE), and the duo synergy card at party size 2.
- Notes: depends on MJ-1 and MJ-2. `tools/gated_rm881_duo_lobby.py` parses the `SR_QUEUE_IDS` literal out of `main.js`, so that tool is re-pointed in the same commit. `_syncAutoAcceptFromConfig` (called from `handleLcuEnvelope`) and `_setAutoAccept` write `_LV` and stay in `main.js` with the auto-accept code, so they import `_LV` (an object, safe to share).

### MJ-7 - Top 8
- File: `web/js/main.js`
- Target: `web/js/panels/lobby_top8.js`
- Anchors: `_TOP8`, `_renderTop8`, `_top8WireSearchOnce`
- Coupled: `tests/snapshot_panels/test_lobby_view.py`, `tests/snapshot_panels/test_lobby_render_stability.py`, `tests/phase_b_champ_select/test_lcu_lobby_members.py`, `tools/lcu_agent.py`
- Views: `lobby`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above, headless, before the commit. Focus: the Top 8 search input and tag control (HIT-TARGETS, keyboard), and the card containment at 923x1280 (STRUCTURE).
- Notes: split from MJ-6 because Lobby plus Top 8 is about 1,730 lines, too big for one reviewable move.

### MJ-8 - Adaptation and trends
- File: `web/js/main.js`
- Target: `web/js/panels/adaptation.js`
- Anchors: `ADAPT`, `TRENDS`, `renderAdaptation`, `fetchAdaptation`, `maybeRefreshAdaptation`
- Coupled: `tests/test_web_js_unimported_calls_s144q43.py`, `tests/snapshot_panels/test_champ_select_adaptation_fetch_s144q43.py`, `web/js/lib/cs_adaptation.test.mjs`
- Views: `active-match`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above, headless, before the commit. Focus: the ADAPTATION panel empty state and its notice line (HIERARCHY: the notice is not brighter than the data).
- Notes: the `#adaptation` panel sits in the in-game grid, outside `#view-content`. `onState` calls `maybeRefreshAdaptation`. The champ-select caller was fixed first (RM-1211): `handleChampSelect` no longer calls `fetchAdaptation` (the bare call threw a ReferenceError); `handleLcuEnvelope` in `main.js` calls it with the arguments from `web/js/lib/cs_adaptation.js` `csAdaptationRequest`. The slice exports `fetchAdaptation`, `main.js` imports it, and that call stays in `handleLcuEnvelope`. Re-point `tests/test_web_js_unimported_calls_s144q43.py`, whose anchor test expects `fetchAdaptation` declared in `web/js/main.js`. `AD` is shared with the footer and `refreshEnv`, so it stays in `main.js` and is passed in. No test covers this region, so the slice adds one first (a node test that `renderAdaptation({ present: false })` paints the empty state).

### MJ-9 - view router
- File: `web/js/main.js`
- Target: `web/js/lib/view_router.js`
- Anchors: `_viewFromHash`, `_viewFromStorage`, `_viewAutoDerive`, `_viewIsUrgent`, `applyView`, `_viewWireOnce`, `_viewResolveAndApply`
- Coupled: `tests/test_view_router_postgame_pgr_arm.py`, `tests/test_view_router_registry_rm341.py`, `tests/test_view_router_state.py`, `tests/test_web_view_registry_rm340.py`, `tests/test_overlay_route_smoke.py`, `tests/test_build_insights_panel_dom.py`, `tests/rc2_l3/test_lcu_phase_sentinels_rm382.py`, `tests/snapshot_panels/test_build_insights_view.py`, `tests/snapshot_panels/test_champ_select_view.py`, `tests/snapshot_panels/test_escape_one_action.py`, `tests/snapshot_panels/test_history_view.py`, `tests/snapshot_panels/test_home_stale_fetch_race_rm508.py`, `tests/snapshot_panels/test_home_view.py`, `tests/snapshot_panels/test_lobby_render_stability.py`, `tests/snapshot_panels/test_lobby_view.py`, `tests/snapshot_panels/test_overlay_view.py`, `tests/snapshot_panels/test_replay_view.py`, `tests/snapshot_panels/test_session_view.py`, `tests/snapshot_panels/test_settings_view.py`, `tests/snapshot_panels/test_user_builds_view.py`, `tools/lcu_agent.py`
- Views: `all`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on every view id in `VIEW_IDS` plus the `?overlay=1` shell, headless, before the commit. Focus: the view menu and hash routing reach every view, the urgent-view banner (HIERARCHY), Escape behaviour, and the overlay shell stamp before first paint.
- Notes: lands only after MJ-3 to MJ-7, because it calls every view's fetch and render. `tests/test_view_router_postgame_pgr_arm.py` cuts the `_viewAutoDerive` body out by name. The falsy-phase branches are LOAD-BEARING (`tools/headless-queue.md` 4d), and `dashboard/view_router_state.py` is a test-only mirror, not the consumer. Move the code byte for byte.

### MJ-10 - background pollers
- File: `web/js/main.js`
- Target: `web/js/lib/pollers.js`
- Anchors: `setupHttpFallback`, `setupStateStream`, `setupLcuPoller`, `setupMinimapPoller`, `setupVoiceToggle`, `refreshMinimap`, `refreshVisionOverlay`
- Coupled: `tests/test_overlay_poller_mode_gate.py`, `tests/test_overlay_minimap_clear_on_exit.py`, `tests/snapshot_panels/conftest.py`, `tests/snapshot_panels/test_tft_active_match_view.py`
- Views: `active-match`, `lobby`, `champ-select`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above and the `?overlay=1` shell, headless, before the commit. Focus: the overlay minimap and vision panes still update and still clear on game exit; no pane flashes at boot (STRUCTURE).
- Notes: last, because these run at boot. Each becomes an exported function that `main.js` calls in the same order, with `onState` and `handleLcuEnvelope` passed in. `tests/test_overlay_poller_mode_gate.py` slices from `function setupMinimapPoller` to `function setupVoiceToggle`, so keep the two adjacent in the new file or re-point the slice.

## web/js/panels/champ_select.js slices

### CS-1 - LCU command helpers (shared with MJ-1)
- File: `web/js/panels/champ_select.js`
- Target: `web/js/lib/lcu_cmd.js`
- Anchors: `lcuCmd`, `lcuPollResult`
- Coupled: `tests/test_csv_push_swap_wipe.py`, `tests/test_rm838_reply_scrub_non_ds.py`, `tools/gated_bench_swap_probe.py`
- Views: `champ-select`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above, headless, before the commit. Focus: the lock button, bench swap and spell picker still POST their LCU command (record the POST on a mocked `/api/lcu-cmd`), and the lock button still handles the reply.
- Notes: lands in the same commit as MJ-1 (rule 2): delete this copy and import the shared module. The two copies match except for comments, so the import changes no behaviour.

### CS-2 - formatters
- File: `web/js/panels/champ_select.js`
- Target: `web/js/lib/cs_format.js`
- Anchors: `_csvOrdinal`, `_csvShortRole`, `_csvQueueLabel`, `_csvTreeIcon`, `_csvKeystoneIcon`, `_csvHumanPhase`, `_csvNormChampName`, `_csvPrTint`
- Coupled: `tests/test_champ_select_rune_follows_build.py`, `tests/test_personal_record_dom.py`, `web/js/panels/codeql_xss_sinks.test.mjs`
- Views: `champ-select`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above, headless, before the commit. Focus: queue labels, role and phase text, and keystone / tree icons (TYPOGRAPHY, ASCII: rendered glyphs unchanged).
- Notes: pure and stateless, so this is the lowest-risk cut.

### CS-3 - mock fixture table
- File: `web/js/panels/champ_select.js`
- Target: `web/js/panels/cs_mock_fixture.js`
- Anchors: `CS_MOCK_FIXTURES`, `csMockFixtureUrl`, `_csvMockFixtureUrl`
- Coupled: `tests/snapshot_panels/test_ui_mock_champ_select_fixture_per_mode.py`
- Views: `champ-select`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above, headless, before the commit. Focus: each mode's mock fixture still loads (STRUCTURE: SR, ARAM and Arena panes all paint).
- Notes: `main.js` imports `csMockFixtureUrl` from `champ_select.js`. Re-export it there, or re-point that import in the same commit.

### CS-4 - saved choices store
- File: `web/js/panels/champ_select.js`
- Target: `web/js/panels/cs_loadout_store.js`
- Anchors: `_csvSaveChoice`, `_csvSavedRuneChoice`, `_csvSavedSelection`, `_csvGetPushFlags`, `_csvSaveRuneDefault`, `_csvStorageKey`
- Coupled: `tests/test_champ_select_rune_follows_build.py`, `tests/test_csv_build_chooser_part3_item240.py`, `tests/test_csv_push_toggles_phase5.py`
- Views: `champ-select`, `settings`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above, headless, before the commit. Focus: a saved rune / build choice survives a reload, and the Settings push toggles still read the same keys.
- Notes: touches only localStorage. Keep every storage key string byte-identical, or saved choices are lost on upgrade. The push toggles are also set from Settings (`web/js/panels/dev.js`), which is why `settings` is audited.

### CS-5 - Arena pane
- File: `web/js/panels/champ_select.js`
- Target: `web/js/panels/cs_arena.js`
- Anchors: `_csvArenaPaneHtml`, `_csvWireArenaAugments`, `_csvRenderEnemiesArena`
- Coupled: `tests/test_rm456_champ_select_shape.py`, `web/js/panels/codeql_xss_sinks.test.mjs`
- Views: `champ-select`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above with the Arena mock fixture, headless, before the commit. Focus: the Arena augment buttons (HIT-TARGETS, keyboard) and the enemy list (STRUCTURE).
- Notes: `codeql_xss_sinks.test.mjs` reads `./champ_select.js` and cuts `_csvArenaPaneHtml` and `_csvRenderEnemiesArena` out by name, so it reads both files after the move.

### CS-6 - counter picks and team damage
- File: `web/js/panels/champ_select.js`
- Target: `web/js/panels/cs_counters.js`
- Anchors: `_csvFetchCounterPicks`, `_csvFetchTeamDamage`, `_csvRenderCounterPicks`, `_csvRenderTeamDamage`, `_csvVariantBadgeClass`
- Coupled: `tests/test_champ_select_e4_counters.py`, `tests/snapshot_panels/test_champ_select_view.py`
- Views: `champ-select`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above, headless, before the commit. Focus: the counter-pick rows and team-damage bars (STRUCTURE), and the variant badges (HIERARCHY).
- Notes: the `?ui_mock=1` window hooks reassign the `_csvCounterFetch` / `_csvTeamDamageFetch` lets. After the move, they go through a setter the new module exports, or the snapshot harness loses its override.

### CS-7 - pick / ban recommendations
- File: `web/js/panels/champ_select.js`
- Target: `web/js/panels/cs_pick_ban.js`
- Anchors: `_PB_PLACEHOLDERS`, `_csvFetchPickBanRecs`, `_csvBanReasonLabel`, `_csvRenderPickBan`
- Coupled: `tests/test_ban_reason_labels_oq9.py`, `tests/test_champ_select_ban_provenance_dom.py`, `tests/test_champ_select_e4_counters.py`, `tests/test_champ_select_pick_placeholder_provenance.py`, `tests/test_champ_select_sr_ui_audit.py`, `tests/test_csv_topleft_picks_layout.py`, `tests/snapshot_panels/test_champ_select_view.py`
- Views: `champ-select`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above, headless, before the commit. Focus: the pick / ban rows, ban reason labels and placeholders (TYPOGRAPHY, HIERARCHY), and the top-left picks layout.
- Notes: needs the scheduler injected (rule 4). The test hooks and the export list at the end of the file stay in `champ_select.js`.

### CS-8 - analysis cards
- File: `web/js/panels/champ_select.js`
- Target: `web/js/panels/cs_analysis_cards.js`
- Anchors: `_CSV_COMPVERDICT`, `_csvFetchCompVerdict`, `_csvCompVerdictKey`, `_csvRenderDraftScore`, `_csvRenderTeamAnalysis`, `_csvRenderCcBlendedEhpThreat`, `_csvFetchCapabilityGap`, `_csvRenderPersonalBuild`, `_csvFetchAdaptiveSummoners`
- Coupled: `tests/test_aram_comp_verdict_variants_rm850.py`, `tests/test_aram_comp_verdict_bench_ui.py`, `tests/test_cc_blended_ehp_threat_panel_dom.py`, `tests/test_personal_build_panel_dom.py`, `tests/snapshot_panels/test_ui_mock_champ_select_fixture_per_mode.py`, `web/js/panels/codeql_xss_sinks.test.mjs`
- Views: `champ-select`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above with the SR, ARAM and Arena mock fixtures, headless, before the commit. Focus: the comp verdict, draft score and team analysis cards (STRUCTURE on all three modes), and the threat panel text (TYPOGRAPHY).
- Notes: its caches (`_CSV_CAPGAP_*`, `_CSV_ADAPT_*`) move with it. `tests/test_aram_comp_verdict_variants_rm850.py` cuts `_csvFetchCompVerdict` out by name.

### CS-9 - build chooser and LCU push
- File: `web/js/panels/champ_select.js`
- Target: `web/js/panels/cs_build_chooser.js`
- Anchors: `_csvResolveArchetype`, `_csvDsModeFor`, `_csvFetchDsBuilds`, `_csvFetchRunePages`, `_csvSelectedRunePageId`, `_csvBuildVariantsFor`, `_csvRuneSidePanelHtml`, `_csvApplyLoadout`, `_csvWireBuildVariants`, `_csvSummSpellSectionHtml`, `_csvWireSummSpells`, `_csvMaybePushBuildsToLCU`, `_csvPushCategory`, `_csvPushFollowedRune`, `_CSV_LAST_PUSH_KEY`, `_CSV_LAST_WIPE_KEY`
- Coupled: `tests/test_champ_select_rune_follows_build.py`, `tests/test_csv_build_chooser_part3_item240.py`, `tests/test_csv_push_swap_wipe.py`, `tests/test_csv_push_toggles_phase5.py`, `tests/test_csv_rune_push_on_selection_change.py`, `tests/test_aram_comp_verdict_variants_rm850.py`, `tests/test_lcu_item_sets_wipe_stale.py`, `tests/test_docs_ds_archetype_picker_s134d14.py`, `tests/snapshot_panels/test_champ_select_view.py`
- Views: `champ-select`
- UI audit: STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY on the views above with the SR, ARAM and Arena mock fixtures, plus the build chooser keyboard path, headless, before the commit. Focus: the build chooser rows and rune side panel (HIT-TARGETS, keyboard, focus kept across a re-render), the summoner spell picker, and the push toggles' effect.
- Notes: the largest and most coupled slice (about 1,350 lines), so it goes last. It holds most of the shared `let` state (`_CSV_RUNE_OVERRIDE`, `_csvSpellPair`, `_csvNextSpellSlot`, `_csvSpellEditOpen`, `_BO_PUSH_INFLIGHT`). That state moves first into a `web/js/panels/cs_state.js` object, in its own commit. The LCU push is an operator-visible write path (item sets and rune pages on the client), so each half (chooser, push) may ship as its own commit, and the push half's tests run on both halves.

## Not in scope

- RM-726 (c), the two panel CSS files over 60 KB (`web/css/panels/header.css`,
  `web/css/panels/champ_select_view.css`), needs its own plan. The CSS is
  styled by class prefix, not by script file, so no JS slice above needs a
  CSS change.
- Any behaviour change, rename or dead-code removal found while moving. File
  it as its own row.

Reverses if: a slice is measured changing a computed style or box on its
views (then the "pure move" premise is wrong for that region and it needs a
design row first), or the operator orders a different module layout.
