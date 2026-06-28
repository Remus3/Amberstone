# Riot Commander - Overlay + Build Master Plan

Authoritative build spec for the overlay redesign + adaptive build-path module. A looping
multi-agent run executes this over many sessions. Every UI work package gates on the per-page
UI-audit ritual (Section G). All authored text is 7-bit ASCII - no em/en dashes, no smart
quotes; use ' - ' for clause breaks.

## Invariants (apply to EVERY work package)

- 7-bit ASCII only. No em/en dashes, no smart quotes. Spaced hyphen ' - ' for clause breaks.
- Atomic writes only: `tmp.write_text(...); tmp.replace(target)`. Overlays poll mid-write.
- `py_compile` before any restart. Restart via `echo restart > restart_trigger.txt`.
- Per-match build state is IN-MEMORY. Nothing persists to disk except (a) a log line that the
  operator took an action (silence/defer/shift), and (b) an OPTIONAL end-of-match
  "save this build?" snapshot. No build-plan database is written.
- The adaptive module sits ABOVE Daemon Slayer (DS). It NEVER changes DS fundamentals, scoring,
  or ENGINE_VERSION. DS `/api/ds-preview` + `/api/build-order` outputs are read-only ground truth.
- Tier classification per RC R5: Tier-0 cosmetic (Edit + py_compile if .py); Tier-1 local logic
  (py_compile + that module's tests); Tier-2 schema/engine/scorer/ENGINE bump (full dual suite +
  DS :8893 restart + Share mirror). Most overlay JS/CSS is Tier-1 (own module tests + UI-audit).
- TDD: write the failing characterization/regression test FIRST.
- ADR-008 asset hash: editing `web/{js,css}/panels/*` auto-reloads, no RC restart.

---

# SECTION A - OVERLAY FIXES

## WP-A1 - Settings opacity/size slider fix

| Field | Value |
|---|---|
| Goal | Make the `#ovset-opacity` global slider and per-panel op/sz sliders actually move pixels in any context (browser + Electron), and stop the per-panel scale clip. |
| Files | `web/js/lib/overlay_settings.js:99-122` (writeOverlaySettings - add CSS applier); `web/css/overlay.css:66` (body zoom), `:140-160` (widget box/transform); `web/js/panels/overlay_ds_controls.js:258-259,370-379` (global slider); `web/js/lib/overlay_layout.js:208-219` (_setOpacity/_setScale), `:129-146` (_applyPos), `:418-438` (_setMenu reachability); `rc-shell/src/clickthrough_zones.js:30` (ZONE_SELECTOR launcher reg). |
| Break-point (U1) | (1) `#ovset-opacity` has NO page-side CSS consumer - pure no-op outside Electron. (2) Per-panel sliders are correctly wired but the launcher menu may be unreachable (zone/tap) so listeners never bind. (3) `transform: scale` does not change layout box, so scaled panels clip against the 210px slot. |
| TDD test first | `web/js/test/overlay_settings_opacity_applies.test.js`: after `writeOverlaySettings({overlayOpacity:0.5})`, assert `document.body.style.getPropertyValue('--rc-overlay-opacity') === '0.5'` and the overlay root consumes it. `overlay_layout_scale_box.test.js`: assert a scaled widget's effective rendered width shrinks (no neighbor clip) - drive `--ovx-scale` and check `getBoundingClientRect` proxy. |
| Fix | (a) In `writeOverlaySettings`, also set `document.body.style.setProperty('--rc-overlay-opacity', next.overlayOpacity)` and add `overlay.css` consumer on the overlay canvas/`.ovx-widget`. Keep the IPC path for window-level opacity. (b) Confirm `#w-launcher` is in `ZONE_SELECTOR` and `_ensureLauncher` runs (gate `body[data-shell="overlay"]`). (c) For scale clip: switch the widget to size-affecting layout (e.g. drive `width`/zoom on the widget wrapper, or set `transform-origin` + reserve box via `width: calc()`), so scale changes the occupied slot. |
| Tier | Tier-1 (overlay JS/CSS + tests). |
| Acceptance | Global opacity slider visibly dims the overlay in plain Chrome preview AND in rc-shell. Per-panel op slider dims one panel; sz slider resizes its slot without clipping neighbors. Menu opens on launcher tap in PASSIVE. |
| Deps | None (foundational). Touches `overlay_layout.js` (shared - serialize with A4/A5/B). |

## WP-A2 - Drop the legacy enemy-spells surface

| Field | Value |
|---|---|
| Goal | Remove the dead dashboard STATS-panel "Enemy summs" row (the legacy/producerless enemy-summoner surface), leaving the new overlay tap-tracker (`enemy_spells.js`) as the sole surface. |
| Files | `web/index.html:714` (`<span id="st-enemy-summs">`); `web/js/panels/right_now.js:388` (`setv("st-enemy-summs", p.enemy_summs_tracked)`). |
| TDD test first | `web/js/test/right_now_no_enemy_summs.test.js`: render `renderStats` with a payload carrying `enemy_summs_tracked` and assert no `#st-enemy-summs` node exists and no setv call references it. |
| Fix | Delete the `index.html:714` span + the `right_now.js:388` setv line. Confirm `_hideEmptyStatRows` no longer references it. |
| Tier | Tier-1 (right_now.js own tests). |
| Acceptance | No `st-enemy-summs` anywhere in repo grep. Dashboard STATS panel renders without the dead row. `enemy_spells.js` overlay tracker unaffected. |
| Deps | Independent of A4/A5 (different file region in right_now.js than coach sinks). |

## WP-A3 - Coach panel: strip timer tags + fix truncation

| Field | Value |
|---|---|
| Goal | Strip `[t]...[/t]` and sibling bracket-timer tags (`[x]...[/x]`, any `[a-z]...[/a-z]`) at the render sink, and remove the hard truncation on `.immediate`/`.action`. |
| Files | `web/js/lib/helpers.js` (add `stripCoachTags`, fold into `safe()`); `web/js/panels/right_now.js:470-481,532,573-575,599,607,609,610,616,627,630`; `web/js/panels/next.js:105-108,124,139,155,158,169-175,196-198,203`; `web/js/panels/coach_choices.js:63-101` (own call - slices raw fields); CSS `web/css/panels/right_now.css:8-31` (.action clamp), `:83-102` (.immediate fixed height:54px + clamp); `next.css:19,30,49`; `overlay.css:349` (.action overlay clamp). |
| TDD test first | `helpers_strip_coach_tags.test.js`: `stripCoachTags("Back [t]14s[/t] now")` -> `"Back now"` (collapse whitespace); nested/unclosed tags handled; non-tag brackets like item refs preserved if scoped (regex `/\[[a-z]\].*?\[\/[a-z]\]/gi` plus standalone `/\[\/?[a-z]\]/gi`). `right_now_no_timer_tags.test.js`: action/immediate textContent contains no `[t]`. |
| Fix | Add `stripCoachTags(s)` in helpers; call it inside `safe()` so right_now + next inherit it; add explicit call in coach_choices `_chipHtml`. Strip BEFORE `dataset.raw` write (clipboard) and BEFORE the DEAD-state sentence split (right_now.js:470-481). For truncation: drop `height:54px` on `.immediate`, raise/remove `-webkit-line-clamp` (let flex grow to N lines), same for `.action`. |
| Tier | Tier-1. |
| Acceptance | Coach text never shows literal `[t]`/`[/t]`/sibling tags. Multi-line immediate/action render fully (no mid-sentence ellipsis). Clipboard copy is clean. |
| Deps | Touches right_now.js + next.js + helpers.js. Serialize with A2 only if same file regions (A2 is the stats row, A3 is the coach sinks - disjoint within right_now.js, but same file -> assign one agent both or serialize). |

## WP-A4 - Stats panel: vertical you-vs-benchmark redesign

| Field | Value |
|---|---|
| Goal | Remove the panel name; make the panel vertical; new scope = You vs benchmark. Header = rank selector. Rows = LVL / CS / TF / KDA. Columns = You vs Role+game-time-bracket average. |
| Files | `web/js/panels/stats_panel.js:19-34` (scaffold - remove `.sp-head` at :23, rebuild grid as vertical table), `:51-75` (renderStatsPanel - new data feed); `web/css/overlay.css:763` (max-width 190px - widen), `:765-774` (.sp-head style - remove); `web/index.html:2206` (mount); benchmark feed precedent `web/js/panels/champ_benchmarks.js:36-42` (`_COLS`, GET `/api/champ-benchmarks`). NEW backend route needed: Role + game-time-bracket average (current route is per-champion only). |
| TDD test first | `stats_panel_vertical_layout.test.js`: assert no `.sp-head`/"STATS" text; assert vertical structure with a rank-selector header element; assert exactly 4 rows keyed LVL/CS/TF/KDA, each with a You cell and a Benchmark cell. `routes_bench_role_bracket.test.py`: assert `/api/role-bracket-bench?role=&bracket=` returns `{role, bracket, stats:{lvl,cs,tf,kda:{avg}}}`. |
| Fix | Backend: new route (copy `/api/champ-benchmarks` precedent) returning Role x game-time-bracket averages from the operator corpus (`core.benchmarks`). Frontend: rebuild scaffold as a vertical 2-col table, rank-selector `<select>` header (net-new), 4 rows. You side = live `lc.*` (level/cs) + `p.kda`; TF = teamfight metric. Bracket derived from `lc.game_time`. |
| Tier | Tier-2 IF a new backend route + benchmark schema (route + integration tests, full `tests/` dir). Frontend slice alone = Tier-1. Split into WP-A4a (backend route, Tier-2) and WP-A4b (frontend, Tier-1). |
| Acceptance | Panel has no name header, renders vertical, rank selector switches the benchmark column, 4 rows populate live You vs bracket-average. Widened to fit content. UI-audit passed. |
| Deps | A4b depends on A4a (route). A4a is backend-only (parallel-safe with all overlay JS). |

## WP-A5 - Enemy-spells panel: remove name, widen to longest champ name

| Field | Value |
|---|---|
| Goal | Remove the "ENEMY SPELLS" header; widen the champion-name column to the longest champion name (no 9-char slice, no 58px clamp). |
| Files | `web/js/panels/enemy_spells.js:90-93` (`_shortChamp` 9-char slice - remove), `:99-103` (`.es-head` header - remove); `web/css/overlay.css:710` (max-width 230px - lift), `:728-735` (`.es-champ flex:0 0 58px` + ellipsis - widen to `flex:0 0 auto` or computed longest-name basis). |
| TDD test first | `enemy_spells_no_header_full_names.test.js`: render with `enemy_spells=[{champion:"Nunu & Willump",...}]`; assert no `.es-head`/"ENEMY SPELLS"; assert the rendered champ name is NOT truncated (full string present); assert column basis fits the longest name in the set. |
| Fix | Remove `_shortChamp` slice (render full name). Remove `.es-head`. CSS: `.es-champ` to `flex:0 0 auto` (or measure longest name in the live set and set a shared basis so all rows align). Lift panel max-width. |
| Tier | Tier-1. |
| Acceptance | No panel name. Longest champion name renders fully; all rows align to that width. Tap-tracker behavior unchanged. UI-audit passed. |
| Deps | enemy_spells.js + overlay.css. Serialize overlay.css edits with A1/A4/A6 (shared file). |

## WP-A6 - Remove per-panel name headers (specified set)

| Field | Value |
|---|---|
| Goal | Strip the specified per-panel name headers. There is no shared header component - each is per-panel (static `am-pane-head` in index.html, or in-JS `.sp-head`/`.es-head`). |
| Files | Static panes (CALL `index.html:2216`, BUILD `:2226`, FIGHT MODEL `:2271`, MAP `:2275`, CDS `:2282-2284`) styled by `overlay.css:165-175` (`.am-pane-head`); in-JS headers handled by A4 (stats) + A5 (enemy-spells). For BUILD the header removal is folded into Section B. |
| TDD test first | `overlay_pane_headers_removed.test.js`: for each pane slated for removal, assert the `.am-pane-head` node is absent (or hidden via CSS) after render. |
| Fix | Per the operator's per-panel spec: remove the `am-pane-head` div for the named panes OR hide via `overlay.css:165` (`.ovx-widget .am-pane-head { display:none }`) scoped to the panes that lose names. (Keep names only where the operator explicitly retained them.) |
| Tier | Tier-1. |
| Acceptance | Named panes render without their gold uppercase title. Layout reflows without the header band. UI-audit passed. |
| Deps | BUILD header removal -> Section B (WP-B1). Other panes are index.html/overlay.css edits - serialize overlay.css with A1/A5. |

---

# SECTION B - BUILD PANEL REBUILD

Horizontal 3-row module. Row1 + Row2 = items left-to-right in purchase order. Row3 = DS knobs.
Mode + lane + role aware (mode flows today; lane/role is net-new context - see Section C). Remove
the `DS ENGINE - vs 40 armor...5 enemies` header and the "No Draft prior" string.

## WP-B1 - Strip the DS ENGINE caption header + "No Draft prior"

| Field | Value |
|---|---|
| Goal | Remove the `DS ENGINE - vs <armor> - <mr> - <hp> - live - <n> enemies` header and any "No Draft prior" empty-state from the in-game build pane. |
| Files | `web/js/panels/active_match.js:144-161` (`_dsTargetStatsCaption`), `:248-249` (`DS ENGINE - ` prefix), `:197` (`_renderAmBuildBody`); sibling caption `build_order.js:136-140` (`ctxLine`); "No Draft prior" is NOT a literal in repo - confirm via grep of `draft_elo.js` (likely a draft-elo empty-state). |
| TDD test first | `active_match_build_no_ds_header.test.js`: render `_renderAmBuildBody` and assert no string starting with `DS ENGINE` and no `vs ... armor ... enemies` caption appears. Grep test: `no "No Draft prior" anywhere`. |
| Fix | Drop the `label = "DS ENGINE - ..."` line (render the build rows without it). Keep `target_stats` cached for the adaptive module (Section C) - just stop rendering the caption. Locate + remove the "No Draft prior" empty-state in `draft_elo.js` (grep first; cite file:line in the PR). |
| Tier | Tier-1. |
| Acceptance | Build pane shows item rows with no DS-context caption header and no "No Draft prior". `target_stats` still flows to the adaptive module. |
| Deps | Foundational for B2/B3 (same file `active_match.js`). Serialize all of Section B on `active_match.js`. |

## WP-B2 - Horizontal 3-row build module scaffold

| Field | Value |
|---|---|
| Goal | Replace the vertical in-game build list with a horizontal 3-row module: Row1 Live (iterative), Row2 Meta (static standard build), Row3 DS knobs. |
| Files | `web/js/panels/active_match.js:197` (`_renderAmBuildBody` - rebuild), `:242-243` (`_dsIcon`), `:1464-1498` (`_dsIcon`/owned badge), `:1518-1520` (`_defIcon`); knobs precedent `web/js/panels/ds_knobs.js:157-169` + `overlay_ds_controls.js:149-161`; CSS new file `web/css/panels/build_module.css`; data feed `/api/build-order` (`routes_state.py:858`, ordered complete build) + `/api/ds-preview` (`routes_state.py:498`, situational re-rank) + `/api/ds-knobs` (`routes_ds_knobs.py:300`). |
| TDD test first | `build_module_three_rows.test.js`: assert 3 rows (`.bm-live`, `.bm-meta`, `.bm-knobs`); Row1 + Row2 are horizontal item strips ordered left-to-right; Row3 carries the armor/MR/budget/fight-length knobs. |
| Fix | Build the 3-row container. Row1 fed by adaptive module (Section C) live plan; Row2 fed by `/api/build-order` order[] standard build; Row3 reuses ds_knobs strip driving `/api/ds-knobs`. Apply UX doctrine row layout (Section G.8). |
| Tier | Tier-1 (panel + CSS + tests). |
| Acceptance | Module renders 3 horizontal rows. Knobs functional. UI-audit passed. |
| Deps | B1 (header gone). Row1 live content depends on Section C module (WP-C5 data contract). |

## WP-B3 - Live row + Meta row item semantics

| Field | Value |
|---|---|
| Goal | Row1 Live: iterative, owned-aware greying, partial-component aware. Row2 Meta: static standard build, right-click cycles alt metas, owned-aware greying. |
| Files | `active_match.js:206-208` (`ownedSet` id+name), `:1471-1498` (owned membership + badge -> add greying class), `:539,512-523,1400` (item slot reads `itemID||itemId`); owned backend `dashboard/_liveclient.py:135,210` (`owned_item_ids`); meta source `/api/build-order` (full ordered build); alt-meta cycling needs N variant builds from build-order or DS archetype alts. |
| TDD test first | `build_live_row_owned_greying.test.js`: with `owned_item_ids` containing item X, assert X renders greyed (`.bm-owned`) and sorts left; first non-grey icon flagged "next". `build_partial_component.test.js`: owning a component of target item renders a component pip + fractional ring. `build_meta_cycle.test.js`: right-click on meta row cycles `metaIndex` through available alt builds. |
| Fix | Live row: reuse `ownedSet`; apply `.bm-owned` greyed class (per Section G.3) instead of the OWNED badge; sort owned left; detect partial components (item recipe membership) and render pip + ring. Meta row: render `/api/build-order` order[]; right-click cycles alt metas (owned greyed too). Greying is redundant-coded (opacity + check glyph + left-position) per WCAG 1.4.1. |
| Tier | Tier-1. |
| Acceptance | Owned items grey + sort left in both rows; first non-grey = next buy. Partial components show progress. Meta row cycles alts on right-click. UI-audit passed. |
| Deps | B2. Owned-item data already live (`_liveclient.py`). |

## WP-B4 - ADC Miss Fortune SR fixture (acceptance anchor)

| Field | Value |
|---|---|
| Goal | Encode the operator-brief ADC Miss Fortune SR example as a deterministic fixture for the build module + adaptive module, used as a render + scoring acceptance oracle. |
| Files | NEW `web/js/test/fixtures/mf_sr_build.json`; consumed by `build_module_three_rows.test.js` + Section C scoring tests. |
| TDD test first | The fixture IS the test input. Assert the rendered Live row + Meta row match the expected MF SR ordered builds (exact item order rows from the operator brief), owned greying behavior, and DS-knob defaults for an ADC vs the example enemy comp. |
| Fixture content | MF SR: Meta standard build (e.g. boots -> Kraken/Collector -> IE -> LDR/Mortal -> situational) in exact left-to-right purchase order per the operator brief; Live row showing a deviation scenario (e.g. early Executioner's component vs heavy-heal enemy). Encode owned-state snapshots at 1/2/3 items to drive greying tests. |
| Tier | Tier-1 (fixture + tests). |
| Acceptance | Both rows render the MF SR example exactly; greying + partial-component pips behave; scoring model (Section C) ranks the MF example builds as expected. |
| Deps | B2/B3 + C2. Provide fixture early so C/B agents share one oracle. |

---

# SECTION C - ADAPTIVE BUILD-PATH MODULE (the brain)

A planner ABOVE DS. DS answers "which set maxes DPS"; this module answers "best coherent,
situational, ordered PLAN given kit + gold + owned + enemy + clock, and when to deviate". DS
output is read-only ground truth (R1 findings). All per-match state IN-MEMORY.

## WP-C1 - Kit-synergy scaling profiles (theorized expansion)

| Field | Value |
|---|---|
| Goal | Per-champion scaling profile turning DS's raw item ranking into kit-routed value. |
| Files | NEW `core/build_planner/kit_synergy.py`; champion scaling data from existing `champions.json` / archetype data (`core.archetype_picks`); reuse DS stat vectors. |
| TDD test first | `test_kit_synergy_profiles.py`: assert crit-marksman (MF) weights AD/AS/crit high, AH ~0; Yasuo/Yone crit double-valued; AS-cap champ (Kog) overvalues AS until 2.5 then collapses to 0; HP-scaling champ (Ornn/Sion) treats HP as offensive. Synergy score = dot(item_vector, kit_weights) + effect_bonuses - anti_synergy. |
| Fix | Build `{AD,bonusAD,AP,AS,crit,on-hit,AH,HP-scaling,%maxHP,true}` weight vectors per champ/archetype + hard gates (double-crit, AS-cap, spellblade cadence, %maxHP-on-hit). `synergy_score(item, champ) = dot(...) + effect_synergy - anti_synergy_penalty`. |
| Tier | Tier-1 (new module, own tests; does NOT touch DS engine). |
| Acceptance | Synergy scores rank kit-fit correctly for the named champ classes; anti-synergy penalizes crit-on-0-crit, AH-overstack, lifesteal-on-no-auto. |
| Deps | None on overlay. Reads DS preview shape. |

## WP-C2 - Build scoring model + candidate gen + beam search

| Field | Value |
|---|---|
| Goal | The core planner: staged candidate generation, pruning, beam search over ordered partial builds, transparent weighted scoring. |
| Files | NEW `core/build_planner/planner.py`, `core/build_planner/scoring.py`; DS seed from `/api/ds-preview` `ranked[]` (top-K) + `/api/build-order` `order[]`; situational item set (antiheal/resist/%pen/lethality/GA/QSS). |
| TDD test first | `test_planner_beam_search.py`: candidate pool = top-K (12-15) DS items + fixed situational set; beam width 5-8, depth 6; assert dedupe-by-set, relative-threshold prune (tau~0.85), per-parent offspring cap; assert MF SR fixture (B4) produces the expected ordered plan; assert real-time (bounded eval count). |
| Scoring | `Score = w_dps*DS_dps(set,target) + w_cohes*cohesion(set) + w_situ*situational_fit(set,enemy,ally) + w_spike*spike_value(prefix,clock) + w_gold*gold_efficiency(set) - penalties(legality,redundancy,overcap)`. Stage weights shift (early: spike/defense; late: pen-offense/dps). cohesion = pairwise kit-alignment (C1) + named-effect synergies - overcap penalties (crit>100%, AS>2.5, 2nd %pen, redundant antiheal). |
| Fix | Implement candidate gen (DS top-K seed + situational adds + legality filter), beam search over ordered partials with the 3 pruning rules, weighted scorer with stage-dependent weights. Gold values + EHP/pen formulas per R1 (armor EHP = HP*(1+R/100); pen order flat-reduce -> %-reduce -> %pen -> lethality; lethality vs low-armor, %pen vs high-armor crossover ~100-150). |
| Tier | Tier-1 (new modules; no DS engine change, no ENGINE bump). |
| Acceptance | Planner returns an ordered next-purchase + 1-2 lookahead in real time; MF SR fixture matches; pruning keeps eval count bounded; scoring is explainable (per-term breakdown). |
| Deps | C1. DS routes (read-only). |

## WP-C3 - Live adaptation + counter-build layer

| Field | Value |
|---|---|
| Goal | Adapt to enemy comp/items, allies, and the operator's observed deviating build order. |
| Files | `core/build_planner/situational.py`; live enemy items via `core.enemy_aware_stats` + `core.liveclient_cache` (`routes_state.py:741-770`); `compute_threat_profile` / `recommend_defensive_items` (already in ds-preview response); ally items for antiheal coordination. |
| TDD test first | `test_situational_counter_build.py`: enemy damage split (phys/magic/true) from classes+items -> match resist; >=2 heal sources -> antiheal (skip if ally already has Mortal); fed-enemy threat override forces resist now; HP+resist mix vs enemy penetration; pen TYPE from kill-target armor not team avg; tenacity vs CC load. Operator-deviation: if observed purchase order diverges from plan, re-anchor the plan to the operator's actual prefix. |
| Fix | Compute enemy damage profile + threat flags + heal-source count each tick. `situational_fit` rewards matching-resist EHP, correct pen type, antiheal-when-warranted (ally-coordinated), tenacity vs CC. Threat override branch keyed on enemy gold-lead/kill-streak. Defensive-pivot exposed on own gold-lead high OR own deaths spike. |
| Tier | Tier-1. |
| Acceptance | Counter-build picks match enemy profile; antiheal de-duplicates with ally; fed-enemy forces resist; operator deviation re-anchors the plan. |
| Deps | C2. Reads ds-preview threat/defensive fields. |

## WP-C4 - Owned-aware re-plan loop + sell/swap + hysteresis

| Field | Value |
|---|---|
| Goal | Re-plan only remaining slots with owned items as a fixed prefix; deterministic sell/swap rules; anti-flip-flop hysteresis. IN-MEMORY state only. |
| Files | `core/build_planner/replan.py`; owned source `dashboard/_liveclient.py:135,210` (`owned_item_ids`); component-defer logic (recipe membership). |
| TDD test first | `test_replan_hysteresis.py`: owned items fixed-prefix; recommendation stickiness (swap only if challenger > incumbent*1.10); just-bought lock (no sell within N s / same shop unless stage>=mid AND off_build); Schmitt-trigger on counter-build pivots (high add threshold, low drop threshold); component-defer respected; sell rate-limited (<=1 per stage transition, surplus gold required). Trinket->Farsight free upgrade; boots-sell endgame. |
| Fix | On each tick: recompute enemy profile (C3), re-run beam (C2) with owned prefix fixed, emit next purchase + lookahead. Sell/swap: deterministic rules (trinket upgrade, boots-sell at 6-item+surplus, undo within free window, component-defer when effect satisfied, true swap only on matchup-invalidated item). Hysteresis: stickiness margin, just-bought lock, Schmitt-trigger pivots, sell rate-limit. State is in-memory; only log the operator's accepted action + optional end-of-match save. |
| Tier | Tier-1. |
| Acceptance | No whiplash on tick noise; owned items never re-planned; sells gated + rate-limited; component-defer honored; flicker suppressed. |
| Deps | C2, C3. |

## WP-C5 - Data contract: DS -> module -> panel

| Field | Value |
|---|---|
| Goal | Define + implement the data contract from `/api/ds-preview` (+ `/api/build-order`) into the adaptive module into the build panel Row1. |
| Files | NEW route `dashboard/routes_build_plan.py` (`/api/build-plan`, HTTP to module, NOT importing DS engine in-process per split-brain guard `routes_state.py:549`); consumed by `active_match.js` Row1 (B2). |
| TDD test first | `test_build_plan_contract.py`: `/api/build-plan` returns `{ok, live:[{item_id,item_name,state:owned|next|swap|partial|future,order_idx,component_pips,swap_from?}], meta:[{...,alt_index,n_alts}], knobs:{armor,mr,budget,fight_length}, plan_meta:{stage,clock,scorer,target_stats}}`. Assert it composes ds-preview `ranked` + build-order `order` + module output. `build_plan_render_contract.test.js`: Row1 consumes the `live[]` states; greying/partial/swap render from `state`. |
| Contract | Input to module: ds-preview `{ranked[], target_stats, threat, defensive}` + build-order `order[]` + live owned/gold/enemy/ally. Output to panel: ordered `live[]` with per-item `state`, `meta[]` alt-build set, `knobs`, `plan_meta`. |
| Tier | Tier-2 (new route + integration tests; full `tests/` dir). |
| Acceptance | `/api/build-plan` returns the contract; Row1 renders from it; owned/next/swap/partial states drive the visuals; target_stats flows for context. |
| Deps | C2/C3/C4 (module) + B2 (panel). The seam both halves integrate on. |

---

# SECTION D - ITEM INTERACTION LAYER

Hover tooltip + right-click radial 5-action menu modeled on the champ-select lane/trade picker
(`champ_select.js:279-350`). UX doctrine from R2 (Section G). Adjusted positions persist for the
match (in-memory) and are NOT reverted on iterative updates except deferred items.

## WP-D1 - Hover tooltip on item icons

| Field | Value |
|---|---|
| Goal | Native-feel custom tooltip showing item name (+ optional when-to-buy / swap reason) on hover of any item icon. |
| Files | NEW `web/js/lib/overlay_tooltip.js` (no custom tooltip exists today - only `title=` attrs); icons in build module (B2); zone interactivity `clickthrough_zones.js:30` (`[data-rc-zone]`); body-zoom caveat `overlay_layout.js:148`. |
| TDD test first | `overlay_tooltip_timing.test.js`: show delay 300-500ms after settle; hover feedback <=100ms; hide grace ~0.5s; anchors toward HUD edge (away from play area); never shows with no cursor over module; name 16px bold + when-to-buy 13px. |
| Fix | Build a singleton tooltip appended to `<html>` (dodge body zoom). Show on icon hover after 300-500ms; immediate <=100ms highlight; hide grace 0.5s. Anchor on screen-edge side, expand away from minimap/champion. Content: bold name -> when-to-buy -> optional swap reason (only place prose is allowed). |
| Tier | Tier-1. |
| Acceptance | Tooltip timing matches doctrine; never occludes play area; tag-free name + concise meta. UI-audit passed. |
| Deps | B2 (icons exist). Independent of D2. |

## WP-D2 - Right-click radial 5-action menu

| Field | Value |
|---|---|
| Goal | Right-click an item icon opens a 5-wedge radial (modeled on the champ-select trade popup) with the operator-brief actions + semantics. |
| Files | NEW `web/js/lib/overlay_item_radial.js`; visual model `web/js/panels/champ_select.js:279-350` + CSS `champ_select_view.css:864-916` (singleton anchored popup, data-action buttons, render-then-measure, append to `<html>`); existing right-click hook `overlay_layout.js:241-247` (`_installHideMenu`, ACTIVE-gated); zone `clickthrough_zones.js:30`. |
| Action set + semantics | N=Build-Earlier (shift-left, overtakes nearest neighbor); E=Build-Later (shift-right, overtakes nearest neighbor); S=Defer-Once (skip this slot once, re-enters after one full item); W=Keep (lock pick, stop re-ranking it); Center/SW=Silence (stop suggesting changes, logged + reset via settings). 4 cardinal axes for the 4 ordering actions (highest-accuracy zones, Kurtenbach); Silence on diagonal/center so a sloppy flick cannot mute by accident. |
| TDD test first | `overlay_item_radial.test.js`: right-click opens 5-wedge ring; cardinal mapping N/E/S/W + center; data-action routes to handler; outside-click dismisses; append-to-`<html>` + body-zoom-correct positioning. `item_action_semantics.test.js`: Build-Earlier shifts left overtaking nearest neighbor; Build-Later shifts right; Defer-Once re-enters after one full item; Keep locks; Silence logs + suppresses. |
| Fix | Mirror the champ-select singleton anchored popup as a 5-spoke ring (`data-rc-zone` so hover-interactive in PASSIVE, or ACTIVE-gated). Render-then-measure positioning appended to `<html>`. Each wedge a `data-action`; delegated click handler; outside-click dismiss. Wire actions into the planner's per-item position overrides (in-memory). |
| Tier | Tier-1 (UI) + couples with D3 (override semantics). |
| Acceptance | Radial opens on item right-click; 5 actions fire correct semantics; mirrors Smart-Ping muscle memory (hold-drag-release acceptable); UI-audit passed. |
| Deps | B2 (icons). D3 (override state). |

## WP-D3 - Item override state + persistence semantics + reset control

| Field | Value |
|---|---|
| Goal | Adjusted item positions persist for the match (in-memory) and are NOT reverted on iterative updates, EXCEPT deferred items (which re-enter after one full item). Silenced items logged + reset via a settings control. |
| Files | `core/build_planner/replan.py` (apply per-item overrides as constraints in the beam search); NEW in-memory override store (per-match, cleared on game end); settings control in `web/js/panels/overlay_ds_controls.js` (settings strip) - "reset item status"; action log line (disk: action-only log, per invariant). |
| TDD test first | `test_item_overrides_persist.py`: shifted positions held across re-plan ticks; deferred item re-enters after exactly one full item completes; silenced item suppressed until reset; reset clears all overrides. `overlay_reset_item_status.test.js`: settings "reset item status" control clears silence/defer/shift overrides + emits a log line. |
| Fix | Override store: `{item_id: {pin?, shift_offset?, deferred_until_next_item?, silenced?}}` in memory. Beam search (C2/C4) treats pins/shifts as ordering constraints that survive re-plan; deferred items skip one slot then re-enter; silenced items excluded from swap suggestions. Settings "reset item status" clears the store + writes an action-log line. Each operator action writes a single action-log line (no build-state persistence). |
| Tier | Tier-1. |
| Acceptance | Shifts/keeps persist across ticks; defer re-enters after one item; silence persists until reset; reset control works + logs. No build-plan written to disk (only action log + optional end-of-match save). |
| Deps | C4, D2. |

---

# SECTION E - SCREENSHOT REMEDIATION BACKLOG

Disposition legend: REMOVE (delete content), CLOSED (mark item closed / move out of open queue),
PRUNE (slim stale referential header/prose), CLARIFY (resolve ambiguity), DEFER-TFT (redo fresh
later - see grouped block). The `?` mark = same disposition as X (verify-then-prune/remove).

## E.1 - README / landing / docs content (0-11.PNG)

| SS | Text (verbatim-ish) | Mark | Disposition |
|---|---|---|---|
| 0 | `ENGINE_VERSION 1.154.0 - data patch 16.13.1` footer | underline | PRUNE stale engine-header -> live pointer |
| 1 | About: `Live League/TFT coaching overlay + dashboard` (TFT) | strikeout | REMOVE TFT from tagline |
| 1 | Latest-commit row | X | REMOVE / not-needed |
| 2 | intro `League of Legends and Teamfight Tactics` | X over TFT | REMOVE TFT mention |
| 2 | Modes: `ARAM, Arena, Brawl, and Teamfight Tactics` | X over Brawl + TFT | REMOVE both (Brawl retired, TFT dropped) |
| 2 | "How it works": second-monitor framing | strikeout | REMOVE/rewrite (1-PC since ADR-011) |
| 2 | `and the API bill stays small.` | strikeout | REMOVE clause |
| 3 | `About three-quarters of the roster is covered today...` | strikeout | REMOVE stale coverage claim |
| 3 | `(547 items)` + `6,142 tests` | underline + ? | CLARIFY / verify numbers (live: 706 items, 7557 tests) |
| 3 | "Where it runs" two-machine prose | strikeout | REMOVE (1-PC, ADR-011) |
| 3 | third-machine/Peer-bridge para | X | REMOVE (Peer bridge decommissioned) |
| 3 | "in-game coaching loop functionally complete across all five modes" | strikeout | REMOVE |
| 3 | OCR-calibration / build-validation / override-registry / champ-select bullets | strikeout | REMOVE stale active-work bullets |
| 3 | "collapsing the two-machine setup into a single-machine install" | strikeout | CLOSED (1-PC done, ADR-011) |
| 4 | Machines table (Legion/Peer) + two-machine prose | strikeout | REMOVE Peer/two-machine (re-capture for exact words) |
| 5 | `screen_agent` retired clause | X | REMOVE (screen_agent retired) |
| 5 | `mode_router.py - TFT early-exit` | X | DEFER-TFT (TFT path dropped) |
| 5 | `vision_server/_frame.py - GDI in-process self-grab` | X | CLARIFY clause |
| 6 | `coaches/brawl_coach.py` row | strikeout | REMOVE (Brawl retired s214) |
| 6 | `coaches/tft_coach.py` row | strikeout | DEFER-TFT |
| 6 | `routes_ward_heat.py` | ? | CLARIFY (ward-heat keep/retire decision) |
| 7 | `core/ward_events.py` | strikeout + ? | CLARIFY + candidate REMOVE |
| 7 | `core/ward_producer.py` | strikeout + ? | CLARIFY + candidate REMOVE |
| 7 | "RC relocated agents (Legion-local, ADR-011)" header | strikeout | REMOVE parenthetical |
| 8 | DS substrate prose block | left-margin bracket | PRUNE stale DS prose |
| 8 | "Phase journal" heading | underline | CLARIFY |
| 9 | Phase-journal lower rows | strikeout | REMOVE stale rows |
| 9 | "God modules (pending decomposition)" file cells | strikeout | CLOSED (no longer pending) |
| 10 | `assets` folder | ? arrow | CLARIFY what it is |
| 10 | `docs io RC peer` folder | X + ? | REMOVE stray dir (Peer cruft) |
| 10 | God-module file list (game_reader/coach_integrat/champion_profil/moon_vision) | strikeout | CLOSED / mark-resolved |
| 11 | `Status: FUNCTIONALLY COMPLETE - ENGINE_VERSION 1.154.0 - 7557 tests` | engine-header | PRUNE -> live pointer |
| 11 | "Engine substrate & registries" mega-paragraph | left-margin bracket | PRUNE stale narrative |

## E.2 - ROADMAP / history open-vs-closed contradictions (12-25.PNG)

Dominant mark across 13-25 is a left-margin `?` on nearly every item (verify-then-prune) plus
large brackets/squiggles around big mostly-DONE/SHIPPED narrative blocks. Cross-cutting action:
every item tagged CLOSED / SHIPPED / DONE+live-wired / VERIFIED / STALE-SHIPPED still sitting
under an `[open...]` header must move OUT of the open queue.

| SS | Item | Mark | Disposition |
|---|---|---|---|
| 12 | (no actionable marks) | none | - |
| 13 | Dr.Mundo E conditional, Part-2 liveclient HP%, PGR UI-audit carry, Live ARAM Mayhem test, ADR-007 prose-coach | ? | CLARIFY/prune (verify-then-prune) |
| 13 | Phase-3 fixture flow `[CLOSED 2026-06-20]` still listed | ? | CLOSED - prune from open |
| 13 | Active Match view step-5 `[CLOSED]` still listed | ? | CLOSED - prune |
| 13 | `set_augment_intent` Cherry endpoint discovery | strikeout + ? | REMOVE (explicit strikeout) |
| 13 | FU03 clipboard "superseded by FU04" | ? | PRUNE stale open item |
| 13 | Vision regions calibration (live-blocked) | ? | KEEP gated (Section F) |
| 14 | build-ORDER "SHIPPED 2026-06-10" under [open] | ? | CLOSED |
| 14 | KEYSTONE residual "none functional" | ? | PRUNE |
| 14 | opportunity #3 "101.qq DONE + live-wired" under [open] | ? | CLOSED |
| 14 | s242 "SPLIT SHIPPED s243" under [open] | ? | CLOSED |
| 14 | s237/s240/s231/s230/s229 NEXT items | ? | CLARIFY (fold into Section F DS-flag/seed entries) |
| 15 | item-210 page-unify "VERIFIED already converged" under [open] | ? | CLOSED |
| 15 | item-277 101.qq "DONE + live-wired" under [open] | ? | CLOSED |
| 15 | s243-s246 effects.py "reviewed-only-never-autonomous" | ? | KEEP settled (do-not-relitigate) |
| 15 | item-209a/209b carries "none" | ? | PRUNE (none = stale) |
| 16 | item-214 overlay PLAN with many SHIPPED sub-slices | bracket + ? | CLOSED shipped slices; keep only live-gated tails (Section F) |
| 16 | item-277 LIVE VERIFY owed | ? | KEEP gated (Section F) |
| 16 | item-212 "STALE-SHIPPED / verified" under [open] | ? | CLOSED / CLARIFY (RuneWriter once-per-session fix still owed) |
| 17 | DS flag-flip carries (items 228-235), passive_damage, Phase-D | ? | Fold into Section F (DS gated) |
| 18 | Haiku-elimination program (mostly DONE/SHIPPED) | bracket + ? | PRUNE shipped; keep HZ-flip gated tail (Section F) |
| 18 | Dashboard data-wiring gaps (~88 st-* rows, ward-heat empty) | bracket + ? | Section F (deferred low-value) |
| 19 | item-312 refactor-plan triage block | ? + circles | CLOSED shipped portions |
| 19 | ZOI minimap overlay slices 1-3 DONE | check tick | KEEP done; PARK champion-only-isolation (Section F) |
| 19 | items 273/275/276/277 NEXT (visual-capture owed) | ? + circles | Section F (visual-capture gated) |
| 20 | HZ-D4 / Metric DE-BIASED / item-575/614 | ? | KEEP done; HZ re-measurement gated (Section F) |
| 20 | item-312 "need explicit go. Loop note: Gemini reads repo-only" | strikeout | REMOVE clause |
| 21 | HZ-to-ZERO fanout (items 352/362/366/367/370/377 DONE) | bracket + ? | PRUNE shipped narrative |
| 22 | P6 LOLMATH parity (G1/G2/G4/G5 DONE) + "REMAINING" annotation | underline + "REMAINING" | CONDENSE - keep only the Gemini-consult tail |
| 23 | DEEP-AUDIT PROGRAM "SUPERSEDES per-item NEXT queue" | bracket + arrow | REMOVE (superseded/stale) |
| 23 | "NEXT (up for the loop)" framing | bracket | CLOSED/REMOVE stale framing |
| 23 | cdragon Phase-2 "CLOSED 2026-06-17" under NEXT | contradiction | CLOSED - remove from open |
| 23 | numbered SHIPPED items in NEXT list | contradiction | REMOVE done from open queue |
| 24 | DEFERRED item-166 + "Don't-redo" annotation | strikeout + note | REMOVE / do-not-redo |
| 24 | "RC 2.0 PROGRAM IN FLIGHT" overnight directive | bracket + arrow | REMOVE stale directive |
| 24 | "HEADLESS SWARM RUN ARMED" (finished) | bracket + arrow | REMOVE stale |
| 24 | "Swarm progress RF1-RF6/DSP1-DSP11 all DONE" | underline | REMOVE (drained) |
| 24 | Repo-audit follow-up tail (shipped item 490) | underline + arrow | CLOSED |
| 25 | "627-630 objective rows ... do NOT re-write anti-tank/ds-profile radar" | underline + ? + "NOT re-litigate" | CLARIFY / do-not-redo |
| 25 | "PER-PAGE UI/UX DESIGN REVIEW 9 OUT-OF-GAME PAGES" block | bracket + arrow | REMOVE stale program |
| 25 | "CHAMP-SELECT is COMPLETE across SR/ARAM/Arena" | strikeout | CLOSED (done) |
| 25 | "HEADLESS OVERLAY-POLISH RUN ARMED ... TOP PRIORITY THIS RUN" | bracket + arrow | REMOVE stale |
| 25 | "live-gated OWED: E.1 ACTIVE knob press + RC_COMP_IP_LIVE flip" | underline | KEEP gated (Section F) |
| 25 | "Concrete queue: FIGHT MODEL pane RESOLVED/already shipped" | contradiction | REMOVE done from open queue |

## E.3 - Live pre-game lobby UI (26.PNG) - feeds overlay/lobby redesign

| Element | Mark | Disposition |
|---|---|---|
| QUEUE 3340 / FIND MATCH area "DB 30 X" | X | REMOVE lobby element / queue-id not needed here |
| YOUR MAINS / PARTY MAINS -> MY TOP 8 sweep | arrow/lasso | CLARIFY - operator linking mains rows to Top 8 (data-source/layout note) |
| a specific YOUR MAINS row | circle | CLARIFY - calling out that row |
| MY TOP 8 per-row "+ avg / + sec" controls | X | REMOVE those Top 8 columns/controls |

## E.4 - DEFERRED-TFT block (redo fresh later)

Group separately. Do NOT delete the TFT pipeline now; mark these for a fresh TFT pass later:
- `coaches/tft_coach.py` "TFT Set 17 mode coach" (6.PNG)
- `mode_router.py` TFT early-exit (5.PNG)
- README/About + intro + Modes-covered TFT mentions (1.PNG, 2.PNG) - the tagline TFT removal is
  REMOVE-now (cosmetic), but the underlying TFT *feature* surfaces are DEFER-TFT.
- `item_build.js:251` TFT Set 17+ augment TODO (from hygiene sweep).

## WP-E5 - Execute the doc remediation sweep

| Field | Value |
|---|---|
| Goal | Apply E.1 + E.2 dispositions to README / ARCHITECTURE.md / ROADMAP.md / DAEMON_SLAYER.md: remove stale prose, prune engine-headers to live pointers, move CLOSED/SHIPPED items out of open queues, remove Peer/two-machine/screen_agent/Brawl content. |
| Files | `README.md`, `docs/ARCHITECTURE.md` (esp. :172 stale 1.153.0/7537 -> 1.154.0/7557 or live pointer), `ROADMAP.md`, `docs/DAEMON_SLAYER.md:5` (drift-guarded - DO NOT touch), `CLAUDE.md:6` (slim engine-recital to a pointer - CI <60KB). Stray dirs: `docs io RC peer` (remove), `assets` (clarify). |
| TDD test first | This is docs hygiene (Tier-0). No code test. Verification = grep assertions: no "Teamfight Tactics" in tagline, no two-machine prose, no Peer-bridge para, no `screen_agent` reference as live, drift-guard `tests/test_docs_daemon_slayer_drift.py` still green, CLAUDE.md < 60KB. |
| Tier | Tier-0 (doc/comment/string). Edit + size-budget check. |
| Acceptance | All E.1/E.2 REMOVE/PRUNE/CLOSED items applied; do-not-rewrite-history rule honored (AUDIT_*/PHASE_*/dated artifacts NOT rewritten - living docs only); ROADMAP open queue carries only genuinely-open items. |
| Deps | None on code. Run as its own session (large doc edit). Honor `feedback_no_history_rewrite`. |

---

# SECTION F - REMAINING-ITEMS ROUNDUP

Folded from the open/gated/future/deferred/theorized inventory + auditor proposals + inline-TODO /
stale-engine-header hygiene. Each is a work package or explicitly deferred with reason.

## F.1 - Overlay/build-adjacent open items (in-scope, sequenced into A-D)

| ID | Item | Source | Disposition |
|---|---|---|---|
| F1-01 | Overlay redesign live-deploy confirm (Ctrl+Shift+B in-game) | ROADMAP:13 | GATED live deploy - verify at end of each overlay wave |
| F1-02 | Manual ward tracker overlay panel (optional fold into CD ledger) | ROADMAP:13 | DEFER - decide after Section A ships (one-panel-vs-two) |
| F1-03 | In-game build widget on overlay | ROADMAP:14 | RESOLVED-BY Section B |
| F1-04 | L4 capability-gap live SR validation (`RC_CAPGAP_SURFACE=1`) | ROADMAP:16 | GATED live SR game |
| F1-05 | E.1 ACTIVE-knob physical-press round-trip + RC_COMP_HP/IP_LEAN flip | ROADMAP:18, SS25 | GATED physical game |
| F1-06 | Electron packaging (electron-builder) + first GitHub Release | ROADMAP:74 | DEFER - operator/release trigger |
| F1-07 | ZOI champion-only isolation (template-match) | ROADMAP:53, SS19 | PARKED - low value + regression risk (2 Gemini do-not-attempt) |
| F1-08 | LBAND1 live wire-in (live_benchmark_band -> /api/state + overlay) | BACKLOG:144 | GATED - relevant to WP-A4 benchmark feed |

## F.2 - DS build-engine gated items (above-DS module does NOT change these)

All GATED on live re-rank validation + ENGINE bump (Tier-2). The adaptive module reads DS output;
flipping these seams is separate DS-batch work, not part of A-D.
- DS comprehensive per-champion cross-eval (ROADMAP:30) - GATED live re-rank.
- DS sidecar/opt-in flag flips: gate_emms / apply_mode_modifiers / aoe_targets_hit /
  apply_ability_haste / apply_passive_damage (ROADMAP:58,64-72) - GATED live validation.
- DS resist-seam survivability scorer (Anivia P / Orianna E) + percent-of-resist mode (ROADMAP:48,59) - schema-blocked.
- DS live-flip seams R5/DSP2/DSP11/R12/R30/RF1/RF3 default-ON (ROADMAP:14) - GATED.
- DS target-current-HP% flip, enemy-pen-aware EHP flip (BACKLOG:30,32) - GATED product call.
- DS forward-marker LIFT_FOUND queue (LEDGER:344) - OPEN no-consumer accessors; no ENGINE bump.
- DS calibration pipeline (ROADMAP:120) - GATED on 20+ ranked samples (0 SR records).
- Interactive Item Shaper UI (BACKLOG:28) - DEFER until DS 100% + running-coach wire.

## F.3 - Coaching / HZ / precompute gated items

- HZ laning precompute coach FLIP + hold-band recalibration (ROADMAP:44, BACKLOG:143) - GATED real-game agreement.
- Deterministic ARAM coach Stage-4 flip / champ-select brief flip (WAKEUP:31, BACKLOG:34) - GATED shadow-log.
- Antiheal callout membership review (BACKLOG:35) - GATED visual capture.
- Same-state Haiku-skip debounce flips (BACKLOG:60) - GATED fidelity.
- Matchup-engine fidelity lift (ROADMAP:55) - DEFER (coin-flip ceiling, uncertain payoff).

## F.4 - Dashboard / data-wiring deferred

- Dashboard data-wiring gaps: ~88 residual st-* ADAPTATION rows (no live producer), /api/ward-heat
  permanently empty (no WARD_PLACED producer) (ROADMAP:57) - DEFER low-value/retired-panel. NOTE
  this connects to the SS6/7 ward-stack `?` marks - operator uncertain whether ward-heat stays.
  ACTION: one explicit keep-vs-retire decision (WP-F4a below).
- R10/R34 personal-corpus aggregators (lane-counter WR, duo-synergy home, per-opponent matchup
  table, snowball rating) (BACKLOG:41,155-157) - DEFER until Build Insights expansion.
- GPI Player Profile page, Personal-build/rune-write UI, Overlay App F lobby tags (BACKLOG:138-142) - DEFER.

### WP-F4a - Ward-stack keep-vs-retire decision

| Field | Value |
|---|---|
| Goal | Resolve the SS6/7 ward-coverage `?`+strikeout marks: decide keep or retire `core/ward_events.py`, `core/ward_producer.py`, `dashboard/routes_ward_heat.py` + the empty `/api/ward-heat`. |
| Files | `core/ward_events.py`, `core/ward_producer.py`, `dashboard/routes_ward_heat.py`; producerless `/api/ward-heat`. |
| TDD test first | If retire: `test_ward_heat_route_removed.py` (route gone, no import refs). If keep: a producer test wiring WARD_PLACED. |
| Tier | Tier-1 (retire path) / Tier-2 (new producer). |
| Acceptance | Either the ward stack has a live producer + non-empty route, or it is retired with all refs removed (decommission completeness sweep). |
| Deps | Operator keep-vs-retire call (feedback_decisions_not_operator_gated -> act, record in tracker). |

## F.5 - Auditor proposals (agents/agent6_auditor) - STILL OPEN

| ID | Item | Severity | Action | Tier |
|---|---|---|---|---|
| WP-F5-M04 | resolved_decisions.json drift (frozen phase3-1.1, 67 days stale; 5 operator-locked decisions only in CLAUDE.md prose) | MED | Apply d021-d025 verbatim, bump version -> phase3-1.2 + locked_at 2026-06-28, bump EXPECTED_DECISIONS_VERSION in `agents/_supervisor_common.py` | Tier-1 |
| WP-F5-M05 | smb_push.py + gatekeeper UNC guard target retired `\\192.168.8.237\RCClient` | MED | Path A (mirror Brawl s214): deprecate `smb_push.py` (raise from push()), force `share_reachable()->False`, add resolved_decisions phase3-d026, reword charters in agents 2/3/5/6 | Tier-1 (operator: Path A defer vs Path B delete) |
| WP-F5-H02 | task_queue.jsonl state-machine leak (~442/488 filed envelopes never reach dispatched) | HIGH | Agent 2 adds reaper/terminal-state transition for stuck ready/in_progress (verify vs now-5447-event queue) | Tier-1 |
| WP-F5-M01 | body[data-mode] flap regression test missing (commit e4b08ba fixed, no test) | MED | Add `tests/preflip_mode/test_body_data_mode_no_flap.py` (HTTP/WS pre-flip mirror seam) | Tier-1 |
| WP-F5-L03 | p0_inventory_full.csv stale post-deletion paths (rows 16915/20605/20608) | LOW | Regenerate CSV after quiescent point OR add `# inventory frozen at <date>` header | Tier-0 |

Auditor RESOLVED/MOOT (do NOT carry forward): C-01 cron silent-fail, H-04 watcher-freshness,
audit7-h01, audit8-m02, audit5 h01/h02/m01, audit6-m01, L-02 orphan gamepc.json.

## F.6 - Inline-TODO + stale-engine-header hygiene

### WP-F6a - Stale engine-header prune (highest priority)

| Field | Value |
|---|---|
| Goal | Fix the ONE confirmed-drifted decorative engine header + slim drift-prone references to live pointers. |
| Files | `docs/ARCHITECTURE.md:172` (reads 1.153.0/7537 - drifted; live = 1.154.0/7557 -> fix or point to `docs/DAEMON_SLAYER.md` status line); `CLAUDE.md:6` (slim scorer-recital to a pointer). DO NOT touch: `docs/DAEMON_SLAYER.md:5` (drift-guarded), `agents/daemon_slayer/__init__.py:18`, any `assertEqual(ENGINE_VERSION,...)` pin, CHANGELOG/LEDGER/ORCHESTRATION per-version lines (append-only). |
| TDD test first | `test_architecture_no_stale_engine_header.py`: assert ARCHITECTURE.md does not hardcode a version other than the live one (or asserts the live-pointer phrasing). |
| Tier | Tier-0/Tier-1. |
| Acceptance | ARCHITECTURE:172 fixed; CLAUDE.md slimmed (< 60KB held); drift guard green. Also fold the `test_engine_version_is_1_121_0`-style method-rename churn into a `test_engine_version_is_current` rename suggestion. |
| Deps | Coordinate with WP-E5 (same docs). |

### F.6b - Inline TODOs to surface (not all actionable now)

| TODO | File:line | Disposition |
|---|---|---|
| EHP-side enemy-CC consumer aram_tenacity_mult | `agents/daemon_slayer/ability_dps.py:90,694,1015` | DS-batch (Tier-2, gated) |
| Meraki no ability_haste_flat (item-AH data gap) | `ability_dps.py:71` | DS data note |
| Arena Silver augment lethality not modeled | `augments.py:130` | DS-batch |
| ~174/577 ratio blocks need live verify | `docs/DS_COMPLETENESS_GAP.md:79,138` | DS-batch gated |
| subtract owned sub-item values (items_recipes.json) | `web/js/panels/item_build.js:120` | RELEVANT - partial-component logic (WP-B3) needs recipe data; ~200 LOC operator-gated |
| TFT Set 17+ augment support | `item_build.js:251` | DEFER-TFT |
| Home "Tonight's Pick" hardcoded dummy | `web/js/main.js:3080`, `dashboard/builders_home.py:148,105` | DEFER - wire when queue_id ingest ships |
| retrain LR on N>=20 timelines | `core/post_game_score.py:220` | GATED data |
| is_next_opponent / arena dataset gap | `coaches/_arena_item_advisor.py:13,97` | DEFER |
| NSIS/MSIX/Inno installer | `tools/build_installer.py:8` + DISTRIBUTION/DEV/LAUNCH docs | DEFER (release trigger) |
| Auto-ops verb-expansion gate (~550-day ETA) | `tools/AUTO_OPS_VERB_EXPANSION_GATE_PROBE.md:7` | EXPLICIT PARK (close perpetual deferral - WP-F6c) |

### WP-F6c - Park the auto-ops verb-expansion gate

| Field | Value |
|---|---|
| Goal | Stop perpetually deferring the auto-ops verb-expansion gate (blocked on a 95% sample gate with ~zero accrual, ~550-day ETA). Make an explicit park/close decision instead. |
| Files | `tools/AUTO_OPS_VERB_EXPANSION_GATE_PROBE.md:7`; ROADMAP/BACKLOG entries (gated bridge/auto-ops). |
| Tier | Tier-0 (doc decision). |
| Acceptance | One explicit PARKED-with-reason entry (or close) replaces the perpetual-defer; bridge largely Peer-decommissioned context noted. |
| Deps | None. |

## F.7 - Research / theorized (condition-to-act only - do NOT build now)

`.rofl` Layer-1 spike (BACKLOG:64); PyInstaller/OBS publisher (BACKLOG:65-66); Arena S2 augment
Level-Up (trigger 26.09 PBE) (BACKLOG:109); Brawl re-enable (external trigger) (BACKLOG:110);
CommunityDragon broader catalog (trigger PGR S2) (BACKLOG:114); draft-model references (BACKLOG:111-113);
LCU deeper/KebsCS endpoints (BACKLOG:27,71); competitor teardown (BACKLOG:70-71); s220 PGR reframe
tails (ROADMAP:92,94). All THEORIZED/DEFER - keep as reference, no WP.

---

# SECTION G - UX DOCTRINE APPENDIX (R2)

Every UI work package in Sections A, B, D MUST satisfy these. Sources: Kurtenbach/Buxton marking
menus, NN/g + Baymard tooltip timing, WCAG 1.4.1 / AA contrast, HUD glance doctrine, hysteresis.

## G.1 Sizing tokens (px at 1920x1080 baseline)

| Token | Value | Use |
|---|---|---|
| `--ovl-icon-primary` | 48px | build-row item icons |
| `--ovl-icon-component` | 28px | partial-component pips |
| `--ovl-icon-action` | 40px | radial wedge icons |
| `--ovl-font-label` | 14px bold | Sell/Next tags (WCAG large-text bold floor) |
| `--ovl-font-name` | 16px | tooltip item name |
| `--ovl-font-meta` | 13px | DS-knobs row (operator font floor) |
| `--ovl-gap` | 8px | 8px spacing grid |
| `--ovl-row-h` | 64px | icon + label + padding |

MUST: never shrink content to fit - trim items shown instead. Floors ~13/15/18px.

## G.2 Color / state semantics (redundant-coded - WCAG 1.4.1: color never the only signal)

| State | Color | Redundant cue (the real signal) | Contrast |
|---|---|---|---|
| Owned | desaturated/grey | 40-50% opacity + check glyph + sorted row-left | n/a |
| Recommended next | warm gold | bright ring/glow + "-> next" tag + full opacity | >=3:1 |
| Sell/replace | red | red X overlay + dimmed icon | >=3:1 |
| Partial component | neutral | progress pip / fractional ring on target icon | >=3:1 |
| Meta (not yet relevant) | muted | lower row + smaller + no glow | >=3:1 |

Non-text UI >=3:1; tooltip body text >=4.5:1. Name tokens by purpose (`--state-owned`,
`--state-next`, `--state-sell`), not hue. Greying=owned reinforced by left-position so colorblind
read of done-vs-todo survives.

## G.3 SELL/SWAP visual language

One horizontal triplet on one line: `[A](dim, red X)  ->  [B](glow ring)` + optional 14px `swap`
tag. NEVER stack reasoning (defer the "why" to the tooltip). Animate the arrow only on first
appearance of a NEW swap, then hold static.

## G.4 Tooltip spec

Show delay 300-500ms after cursor settles; hover feedback <=100ms; tooltip body renders <=100ms;
hide grace ~0.5s (up to 1.5s if reading). Anchor on the screen-edge/HUD-corner side, expand AWAY
from the play area (never cover minimap/champion). Never appear with no cursor over the module.
Content order: bold name 16px -> one when-to-buy line 13px -> optional swap reason. Tooltip is the
ONLY place prose is allowed.

## G.5 Radial / marking-menu spec

Exactly 5 actions, one ring, depth-1 (keeps error <10% per Kurtenbach <10%-error envelope at
breadth-8/depth-1-2). 4 ordering actions on the 4 CARDINAL axes (highest-accuracy zones); the
destructive/low-frequency Silence on diagonal/center so a sloppy flick cannot mute by accident.
Mirror League Smart-Ping interaction (hold-click -> drag-direction -> release). Novice: pop menu +
select; expert: flick the mark without waiting (faster over a season, no interaction change).
Guide-ring + wedge labels for first N uses, fading to expert.

| Dir | Action | Semantic |
|---|---|---|
| N | Build-Earlier | shift left, overtakes nearest neighbor |
| E | Build-Later | shift right, overtakes nearest neighbor |
| S | Defer-Once | skip slot once, re-enter after one full item |
| W | Keep | lock pick, stop re-ranking it |
| Center/SW | Silence | stop suggesting changes, logged + reset via settings |

## G.6 Anti-flip-flop (stability)

Hysteresis (asymmetric thresholds): promote a new top recommendation only if challenger beats the
incumbent by a margin (>5-10%), not on a hairline lead. Debounce repaints (coalesce, repaint only
after input settles). Schmitt-trigger on counter-build pivots (cross HIGH threshold to add a
defensive item, fall below a LOWER threshold to drop it). Idempotent render: stash a content
signature, skip the DOM wipe if unchanged; atomic-write-then-replace so mid-write polls never see
half-state. Motion restraint: animate only on a genuine state change, once, briefly - never loop
or pulse in peripheral vision.

## G.7 MUST / SHOULD checklist (gate for every UI WP)

MUST: (1) every state = color + non-color cue; (2) non-text >=3:1, tooltip text >=4.5:1; (3) swap
= one horizontal triplet, no prose; (4) radial exactly 5, one ring, depth-1, cardinal ordering +
diagonal Silence; (5) tooltip 300-500ms show / <=100ms feedback / 0.5s hide grace; (6) tooltips
anchor toward HUD edge, away from play area, never cursor-absent; (7) show swap/next only past the
hysteresis margin, debounce, idempotent atomic render; (8) owned grey + sort left, first non-grey =
next buy; (9) animate only on real state change, once; (10) ASCII rule + 13px meta floor, trim not
shrink. SHOULD: mirror Smart-Ping; guide-ring fading novice->expert; operator scales size + picks
corner; optional audio cue for a new swap.

## G.8 Horizontal 3-row layout

```
Row 1 (Live):  [owned][owned] [A X-> B] [NEXT*] [comp-pip] [...]   L->R purchase order, full contrast
Row 2 (Meta):  [item][item][item][item][item]                      muted reference order, right-click cycles alts
Row 3 (Knobs): tier . spike . DS-version . toggles                 13px meta, no glow, never animate
```

Row1 Live vs Row2 Meta contrast IS the "live vs meta" signal (opacity + size, not color alone).
Greying owned left-to-right makes "where am I in the build" a pre-attentive read. Partial
components = sub-component at 28px + fractional ring on the target. Row3 knobs reference-only.

## G.9 Mandatory UI-audit ritual gate

Any UI page change runs the 5-phase visual-hierarchy/fixture audit subagent BEFORE commit+push:
STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY. Every MUST-FIX resolved in the same
slice. No page ships ahead of its audit. Applies to WP-A1,A4,A5,A6,B2,B3,B4,D1,D2,D3.

---

# SECTION H - SEQUENCING + DEPENDENCY GRAPH

Waves run as parallel multi-agent worktree batches on disjoint files. A read-only `verifier`
subagent gates every merge. Shared-file collisions are called out as serialize-constraints.

## Shared-file collision map (must serialize within a file)

| File | WPs touching it | Rule |
|---|---|---|
| `web/js/lib/overlay_layout.js` | A1 | A1 owns it (no other WP edits it) |
| `web/css/overlay.css` | A1, A5, A6 | one agent owns overlay.css OR serialize A1->A5->A6 |
| `web/js/panels/right_now.js` | A2, A3 | one agent owns both (disjoint regions: A2 stats row, A3 coach sinks) |
| `web/js/panels/active_match.js` | B1, B2, B3 | serialize B1 -> B2 -> B3 (one agent owns the build pane) |
| `web/js/lib/helpers.js` | A3 | A3 owns it |
| `core/build_planner/*` | C1-C4 | C1 -> C2 -> {C3,C4} (C3/C4 disjoint files, parallel after C2) |
| README/ARCHITECTURE/ROADMAP/CLAUDE | E5, F6a | serialize E5 then F6a (or one agent owns all docs) |

## Wave plan

| Wave | WPs (agent each) | Files (disjoint across the wave) | Gate |
|---|---|---|---|
| W0 Foundation | A1 (agent-1); A2+A3 (agent-2, owns right_now.js+helpers.js); A4a backend route (agent-3); E5 docs sweep (agent-4); F5-M04 (agent-5); F5-M05 (agent-6); F5-H02 (agent-7); F5-M01 (agent-8); F6a engine-header (agent-9, after E5) | overlay_layout.js+overlay_settings.js / right_now.js+helpers.js / new bench route / docs / auditor files / agents files | verifier per WP |
| W1 Overlay panels | A5 (agent-1, overlay.css+enemy_spells.js); A6 (agent-2, index.html + overlay.css after A5); A4b stats frontend (agent-3, stats_panel.js); B1 build-header strip (agent-4, active_match.js) | enemy_spells.js / index.html / stats_panel.js / active_match.js | verifier; A5 before A6 (overlay.css) |
| W2 Build brain | C1 (agent-1); then C2 (agent-1 cont.); C5 route stub contract (agent-2, after C2 shape) | core/build_planner/* / routes_build_plan.py | verifier; C1->C2 serial |
| W3 Build module + adaptation | B2 (agent-1, active_match.js after B1); C3 (agent-2); C4 (agent-3); B4 MF fixture (agent-4, shared oracle) | active_match.js / situational.py / replan.py / fixtures | verifier; B2 after B1 |
| W4 Live integration | B3 (agent-1, active_match.js after B2); C5 full route (agent-2, after C3/C4); F4a ward decision (agent-3) | active_match.js / routes_build_plan.py / ward files | verifier |
| W5 Interaction layer | D1 tooltip (agent-1); D2 radial (agent-2); D3 overrides+reset (agent-3, couples replan.py + overlay_ds_controls.js) | overlay_tooltip.js / overlay_item_radial.js / replan.py+overlay_ds_controls.js | verifier; D2->D3 |
| W6 Hygiene tail | F6c auto-ops park (agent-1); F5-L03 csv (agent-2); remaining F.4 deferrals recorded | docs / csv | verifier |

## Per-WP agent assignment summary

- W0 maximizes parallelism: 9 disjoint-file agents (3 overlay, 1 backend, 1 docs, 4 auditor/hygiene).
- DS-engine F.2 items are NOT in any wave - they are separate DS-batch sessions (Tier-2, ENGINE
  bump, live-gated), tracked but out of the overlay/build critical path.
- Live-gated items (F1-01, F1-04, F1-05, F1-06, F3.*) verify only when a real game is up; schedule
  a live-deploy confirm pass after W1 (overlay panels) and after W5 (interaction layer).

## Verifier gate (before every merge)

Per RC R7 + Verification Discipline: re-run the WP's own test file FRESH, confirm every cited test
file exists on disk, report exact pass/fail observed THIS run. For Tier-2 WPs (A4a, C5): full dual
suite (DS dir + `tests/`) + DS :8893 restart + Share mirror sync. For overlay JS/CSS WPs: own
module tests + the G.9 UI-audit ritual. Never carry a subagent-reported count forward.

## Critical path

A1/A2/A3 (W0) -> B1 (W1) -> B2 (W3) -> B3 (W4) needs C1->C2->C5 (W2-W4) to feed Row1. The build
brain (C) is the long pole; start C1 in W2 in parallel with the W1 overlay-panel cosmetic work so
the module is ready when B2 needs it. Interaction layer (D) is last (needs icons from B2).

---

# SECTION I - EXECUTION ORCHESTRATION (the loop harness)

This program runs as a self-directing AHK loop that reuses the EXISTING headless harness
(`ops/loop/loop_controller.py` + `ops/loop/claude_gui_bridge.ahk`) in `cycle_command` mode. No
gemini director (the master plan self-directs); the gemini auditor stays on as a per-cycle
regression check. Each cycle is one Opus 4.8 ultracode executor session.

## I.1 Per-cycle contract (one WP per cycle, multi-agent inside)

Each executor cycle:
1. `/remote-control` is active (per I.3 preamble), then runs the continue command.
2. Reads `docs/OVERLAY_BUILD_MASTER_PLAN.md` (this file) + the Section J tracker; picks the next
   OPEN work package whose deps are DONE, honoring the Section H wave + shared-file collision map.
3. Marks it WIP in the Section J tracker (atomic write).
4. Executes it ULTRACODE: spawns worktree-isolated build agents on the WP's disjoint files (one
   merger = the cycle Claude), TDD test first, then implementation. >=3-file or parallel-slice WPs
   use worktrees; trivial single-file WPs inline (R9).
5. Read-only `verifier` subagent gate before merge (re-run the WP test FRESH, confirm cited test
   files exist on disk, report THIS-run pass/fail) per RC R7 + Verification Discipline.
6. UI WPs run the G.9 5-phase UI-audit ritual BEFORE commit (STRUCTURE/TYPOGRAPHY/HIT-TARGETS/
   ASCII/HIERARCHY); every MUST-FIX resolved in the same slice.
7. Tier-2 WPs (A4a, C5): full dual suite (DS dir + `tests/`) + DS :8893 restart + Share mirror.
8. Commit + push + confirm CI; mark the WP DONE in Section J; run `/done` (writes `claude.done`
   sentinel via `ops/loop/done_sentinel.py`).
9. The controller meters budget, runs the gemini auditor on the cycle diff, and re-fires the next
   cycle: `/clear` -> activation -> `/remote-control` -> continue command.

## I.2 Model + token budget

- Executor = Opus 4.8, ultracode, effort high. Claude/executor spend is UNCAPPED (config
  `_ceiling_note`); the `ceiling_usd=200` rail caps GEMINI only, and cycle_command mode calls
  gemini for the auditor ONLY (no director), so gemini spend is minimal.
- Build agents get sufficient budgets: substantive WPs (C2 beam search, B2/B3 module, D2 radial)
  warrant high-effort agents; cosmetic doc/CSS WPs use medium. No per-cycle token cap.

## I.3 AHK typed sequence + /remote-control preamble (NO bridge edit needed)

The bridge types each newline-split line of `control/gemini.ready` (skipping line 1, the CYCLE
header) and handles leading-slash commands. The per-cycle `gemini.ready` body is set so the typed
sequence is:

```
CYCLE=<n>          <- skipped by AHK
/clear             <- resets the session (new session)
go                 <- 1-token activation message (operator requirement; minimal token burn)
/remote-control    <- operator requirement: active every new session
/overlay-build-continue   <- the self-directing continue command (the regenerated next-session prompt)
```

This is achieved purely by setting `cycle_command` in the loop config to the multi-line string
`"go\n/remote-control\n/overlay-build-continue"` - the controller already prefixes `/clear` and
the CYCLE header, and the bridge already types multi-line + slash lines correctly. OPEN QUESTION
for the operator: confirm `/remote-control` is a fire-and-forget slash command (types + Enter, no
modal). If it opens an interactive panel needing a second keypress, the bridge sequence needs a
one-line tweak (add the confirm key); this surfaces on cycle 1 and is a 2-minute fix.

## I.4 Stall / error self-heal (WP-I3 - small controller patch, do pre-launch)

Today the controller HARD-STOPs when `claude.done` is not seen before `cycle_deadline_sec` (90
min). The operator wants the loop to NOT end randomly - to detect a stall and have Claude diagnose
+ recover. WP-I3 adds a one-shot recovery before the hard stop:

| Field | Value |
|---|---|
| Goal | On the FIRST deadline breach of a cycle, inject a recovery directive + extend the deadline ONCE; hard-STOP only on a second consecutive breach. |
| Files | `ops/loop/loop_controller.py` (the `wait_for(claude.done)` branch ~:422) - NOT frozen. |
| TDD test first | `tests/test_loop_stall_recovery.py`: assert `stall_action(1)=="recover"` (one-shot recovery, no STOP) and `stall_action(2+)=="stop"` (second breach = hard hang); plus the `stall_recovery_directive` content (CYCLE header for the AHK skip, `/diagnose`, done_sentinel final step, NO `/clear`, single typed line, ASCII). Pure-function the recovery decision so it is unit-testable headless. |
| Recovery directive | Types: `/diagnose the loop stall: check git status, the last pytest output file, ops/runtime/health.json, and the controller.log tail; recover this cycle and /done, or write a one-line blocker to ops/loop/control/blocker.txt and /done.` |
| Backstops kept | The existing no-progress guard (same sha 2 cycles -> STOP) and AHK-never-typed (120s -> STOP) remain. The `/loop-monitor` dashboard surface (`/api/loop-monitor`) gives the operator a live per-tool-call timeline to watch for stalls. |
| Tier | Tier-1 (loop module + its own test). |
| Acceptance | A single stalled cycle self-recovers; a genuinely wedged run still stops cleanly after one recovery attempt. |

## I.5 Branch + scratch hygiene

- Per-cycle commits land on `main` (RC convention: main tracks origin/main, CI watchdog guards
  red main; each WP is independently shippable + tested + UI-audited so main stays green). Build
  agents work in auto-cleaned git WORKTREES (isolation), merged by the single cycle-Claude.
- Scratch / intermediate files use the session scratchpad dir, never the repo tree.
- Durable continuity across the frequent `/clear` boundaries = git history + `docs/LEDGER.md` +
  THIS plan + the Section J tracker (all committed). Stateless executor per cycle, exactly like
  the proven gemini-headless-upgrade loop.
- `_archive/` quarantine + `feedback_no_history_rewrite` honored (no dated-artifact rewrites).

## I.6 Pre-launch setup checklist (executed after operator go)

1. Create `.claude/commands/overlay-build-continue.md` (gitignored local command): the
   self-directing continue prompt - read this plan + Section J tracker, pick next OPEN WP per the
   wave graph, execute ultracode multi-agent, verifier-gate, UI-audit, commit+push+CI+/done, mark
   DONE. Carries the standing SUBAGENT-FIRST block.
2. Apply WP-I3 (stall-recovery patch + test, green) so cycle 1 already self-heals.
3. Create `ops/loop/config.overlay.json` from `config.json` with:
   `cycle_command="go\n/remote-control\n/overlay-build-continue"`, `clear_each_cycle=true`,
   `max_cycles` sized to the WP count (~30 with headroom), `ignore_no_progress=false`,
   `cycle_deadline_sec` unchanged (5400). Director/fixed unset.
4. Set `ops/loop/control/ahk_mode.txt=live` + `target_pid.txt` = this Claude window PID.
5. Start the AHK bridge (`ops/loop/claude_gui_bridge.ahk`) + launch the controller
   (`ops/loop/launch_loop.ps1 config.overlay.json`), which writes cycle-1 `gemini.ready`.
6. `/done` THIS planning session so the loop takes over a clean context.

## I.7 What I do NOT auto-do

- I do not launch the loop without explicit operator go (it self-`/clear`s this session, commits
  to main repeatedly, and spends across many sessions - hard to reverse).
- I do not invoke gemini headless this run unless it has been updated with these specifics
  (operator directive); cycle_command mode keeps only the read-only gemini AUDITOR, which is fine.

---

# SECTION J - EXECUTION TRACKER (the loop updates this each cycle)

Status legend: OPEN (ready when deps DONE) / WIP (claimed this cycle) / DONE (merged + CI green) /
GATED (needs a live game or operator decision) / DEFER (out of this program).

| WP | Wave | Deps | Tier | Status |
|---|---|---|---|---|
| A1 settings sliders | W0 | - | T1 | OPEN |
| A2 drop legacy enemy-summs | W0 | - | T1 | OPEN |
| A3 coach [t] strip + truncation | W0 | - | T1 | OPEN |
| A4a role-bracket bench route | W0 | - | T2 | OPEN |
| A4b stats vertical frontend | W1 | A4a | T1 | OPEN |
| A5 enemy-spells widen+unname | W1 | - | T1 | OPEN |
| A6 remove pane name headers | W1 | A5 | T1 | OPEN |
| B1 strip DS-ENGINE caption | W1 | - | T1 | OPEN |
| B2 horizontal 3-row scaffold | W3 | B1, C5 | T1 | OPEN |
| B3 Live+Meta item semantics | W4 | B2 | T1 | OPEN |
| B4 MF SR fixture oracle | W3 | B2, C2 | T1 | OPEN |
| C1 kit-synergy profiles | W2 | - | T1 | OPEN |
| C2 scoring + beam search | W2 | C1 | T1 | OPEN |
| C3 live counter-build | W3 | C2 | T1 | OPEN |
| C4 owned re-plan + hysteresis | W3 | C2, C3 | T1 | OPEN |
| C5 /api/build-plan contract | W2/W4 | C2 | T2 | OPEN |
| D1 item tooltip | W5 | B2 | T1 | OPEN |
| D2 right-click radial | W5 | B2, D3 | T1 | OPEN |
| D3 override state + reset | W5 | C4, D2 | T1 | OPEN |
| E5 doc remediation sweep | W0 | - | T0 | OPEN |
| F5-M04 decisions drift | W0 | - | T1 | OPEN |
| F5-M05 smb_push deadcode | W0 | - | T1 | OPEN |
| F5-H02 task_queue leak | W0 | - | T1 | OPEN |
| F5-M01 body-data-mode test | W0 | - | T1 | OPEN |
| F5-L03 inventory csv stale | W6 | - | T0 | OPEN |
| F6a stale engine-header | W0 | E5 | T1 | OPEN |
| F4a ward keep-vs-retire | W4 | operator | T1 | GATED |
| F6c park auto-ops gate | W6 | - | T0 | OPEN |
| I3 loop stall-recovery | pre | - | T1 | DONE 2026-06-28 |

GATED-on-live-game (verify-pass after W1 + W5, not a cycle): F1-01, F1-04, F1-05, F1-06.
DS-batch (separate Tier-2 ENGINE sessions, NOT this loop): all of F.2. DEFER/THEORIZED: F.7.
