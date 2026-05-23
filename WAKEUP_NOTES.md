# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-146 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---
# 2026-05-22 - item 149 obj_participation 8-col -> 9-col turret add + orphan CSS @import cleanup SHIPPED (commit `7b3d351`, pushed `ced0a9e..7b3d351`; non-engine; non-frozen; RC :8888 restarted pid 7356 alive=True last_reload_ok=True; no DS restart; no ENGINE bump)

Operator AskUserQuestion-picked "Orphan CSS cleanup + obj_participation widen (Recommended)" from 4-option fork (over DS 4-slice drain run 15 / live game smoke + UI audit / headless-upgrade long run). DS 4-slice drain run 15 was the WEAKER option this session: cc_conditional wave 8 with the new COND_FRENZY_STATE/COND_RANGE_GATED tags is DATA-LIMITED per item 148 (Briar W parse-stripped; Renekton/Aatrox/Volibear need real Meraki ability_abilities.json dump with leveling intact); unconditional _PER_SPELL_CC_DURATIONS wave 10 saturated for net-new champs per item 147 (audit walked all 226 unregistered spells). The 3 carries from items 146/147/148 + BACKLOG L14 (c) were the strongest NOW lane.

Closes 3 carries in one slice:
* (a) item 146/147/148 carry: `web/css/dashboard.css:27` orphan `@import './panels/loading_view.css'` (file does NOT exist; browser silently 404'd every cold load + console warning).
* (b) item 147/148 carry: `web/css/panels/build_order.css` (175 LOC live stylesheet for s214 build-order card used by item_build.js + champ_select.js) was MISSING from the @import block - browser never loaded it (inverse orphan: file exists, no @import).
* (c) BACKLOG L14 option (c): obj_participation 8-col -> 9-col adds non-overlapping turret count beyond first_tower binary sentinels via `max(turretTakedowns - ftk - fta, 0)` clamp.

**CSS cleanup (`web/css/dashboard.css`):** Removed orphan loading_view.css @import (1 line). Added build_order.css @import (1 line, alphabetically next to item_build.css per existing block convention). NEW guard test `tests/test_dashboard_css_panel_imports_parity.py` (+4 tests) pins parity BOTH DIRECTIONS via regex scan of dashboard.css `@import './panels/*.css'` entries against the `web/css/panels/*.css` directory listing. Specific pins on build_order.css presence + loading_view.css absence prevent regression of either orphan direction.

**obj_participation 9-col model (`core/obj_participation.py`):** NEW `_TURRET_KEY = "turretTakedowns"` constant. `_challenges_objectives()` widened from 2-tuple (herald, void) to 3-tuple (herald, void, turret). Single parse trip preserved per item-135 single-trip optimization. NEW `_turret_from_challenges()` thin wrapper sibling of `_herald_from_challenges()` + `_void_from_challenges()`. `compute_obj_participation()` SELECT now pulls `COALESCE(first_tower_kill, 0)` + `COALESCE(first_tower_assist, 0)` separately from the 6-col sum so the per-row arithmetic can subtract the binary sentinels: `turret_extra = max(turretTakedowns - ftk - fta, 0.0)`. The `max()` clamp is LOAD-BEARING - prevents NEGATIVE contribution when raw_turret=0 but ftk=1 fires (stale-blob case). Docstring widened 8-col -> 9-col with NON-OVERLAPPING semantic + carry-forward note that the 3 other challenges_json fields (baronTakedowns / dragonTakedowns / epicMonsterSteals) FULLY OVERLAP existing SQL columns and stay deferred per BACKLOG L14 option (a) until operator opts into kills -> takedowns rebaseline. Legacy schema fallback path widened to silently degrade to 6-col when challenges_json column missing.

**+15 tests across 3 existing files + +4 new parity file = +19 net:**
* `tests/test_obj_participation.py` 81 -> 94 (+13): +6 ChallengesObjectivesParseOnceTests rebaselined for 3-tuple shape (incl. NEW only-turret pin) + +1 `_TURRET_KEY` constant pin + +1 9-col docstring pin + +7 NEW TurretTakedownsTests class (operator-lift / first-tower overlap not double-counted / assist overlap / clamp-at-zero with stale ftk / split-credit ally takes more / legacy schema falls back / malformed turret value drops to zero) - 1 deprecated 7-col docstring test reshaped to nine_column model.
* `tests/test_routes_post_game_rubric_obj.py` 16 -> 19 (+3): NEW TurretEnrichmentRouteTests (turret enrichment lifts total_score / first_tower overlap not double-counted / composes with herald+void). Fixture `_seed_obj_db` gains `operator_turret` + `ally_turret` kwargs + populates `turretTakedowns` in challenges_json blob.
* `tests/test_postmortem_analyze.py` 74 -> 77 (+3): NEW TurretEnrichmentWireTests (turret enrichment widens obj_pct / first_tower overlap not double-counted / teammate turret lowers operator share). `_populate_match_a_objectives_blob` helper gains `self_turret` + `ally_turret` kwargs.
* `tests/test_dashboard_css_panel_imports_parity.py` NEW (+4): PanelImportParityTests (every panel CSS file is @imported / every @imported panel file exists / build_order.css IS @imported / loading_view.css NOT @imported).

**Live curl verified end-to-end on operator's NA1_5560540832 (Kai'Sa ADC, May 14 Normal Draft Loss):**
* Pre-restart (8-col): obj_participation=0.331 total_score=37.28 tier=C
* Post-restart (9-col): obj_participation=0.239 total_score=36.37 tier=C

Direction is CORRECT for this specific match: operator did NOT participate in towers 2-11 their teammate destroyed; the team-wide denominator grew faster than the operator's numerator (0.331 inflated baseline because 8-col only credited the first tower, hiding ally's towers 2-11). In matches where operator GOT towers 2-11, the ratio will RISE (per 7 unit tests covering both directions). Aggregate across operator's 624 historic matches will calibrate the true participation score on next RC-PostmortemAnalyze cron run.

**Verified:** RC suite **3219 / 67 subtests / 0 failed**; 191/0 across all 4 touched test files; py_compile + ruff + ASCII clean across all 5 touched source files + 1 new test file. RC :8888 restarted via `restart_trigger.txt` (route module edit triggers reload): pid 7356 alive=True last_reload_ok=True mode=client. No DS restart (non-engine). No ENGINE bump. No frozen-file edits. No worktree agents (single-slice scoped session).

**Don't-redo:**
* The 3 other challenges_json overlap fields (baronTakedowns / dragonTakedowns / epicMonsterSteals) STILL deferred per BACKLOG L14 option (a); only operator can flip the SQL kills -> Match-V5 takedowns semantic (would rebaseline existing 624 historic role-grades). Do NOT pre-ship.
* The `max()` clamp on turret_extra is LOAD-BEARING - prevents a negative contribution when raw_turret=0 but ftk=1 (stale blob case where SQL sentinel fires but challenges_json was not yet populated at match-end). Pinned by `test_clamp_at_zero_when_no_turrets_but_first_tower_set` + `test_first_tower_overlap_does_not_double_count`. Do NOT remove.
* `_challenges_objectives()` 3-tuple shape is the canonical schema as of item 149 (was 2-tuple item 135). Future widenings reshape into 4-tuple etc.; the per-key wrapper helpers (`_herald_from_challenges` / `_void_from_challenges` / `_turret_from_challenges`) stay as thin accessors. Do NOT split into 3 separate JSON parses (would triple-parse per row, defeats the single-trip optimization).
* CSS @import parity test (`test_dashboard_css_panel_imports_parity.py`) is the durable guard - any future panel CSS addition must come with a matching @import OR will fail the orphan-file scan; conversely any @import to a removed file fails the orphan-import scan. Do NOT relax either direction. The 4 specific pins (build_order.css IS @imported / loading_view.css NOT @imported) anchor the item 149 fixes.
* Live curl direction on operator's NA1_5560540832 was DOWN (0.331 -> 0.239) for this match specifically - this is the correct semantic, not a bug. Do NOT re-litigate; in matches where the operator participated in towers 2-11, ratio rises. The aggregate effect calibrates over postmortem cadence.

**Carries forward:**
* Item 148 carries (a) loading_view.css orphan @import + (b) build_order.css inverse orphan FILE NOW CLOSED via this commit.
* BACKLOG L14 (c) NOW CLOSED. BACKLOG L14 (a) (kills -> takedowns semantic flip) STILL operator-gated.
* RC-PostmortemAnalyze first scheduled run 2026-05-24 04:15 - verify LastTaskResult=0 next session; the role_grades JSON will reflect 9-col obj_participation on next aggregation.
* Future cc_conditional wave 8 entries that consume the new COND_FRENZY_STATE / COND_RANGE_GATED tags STILL operator-gated when Meraki-verifiable mechanic surfaces (Renekton W Fury / Aatrox post-R / Volibear R passive).
* `_PER_SPELL_CC_DURATIONS` unconditional registry unchanged at 108/89 (wave 10+ exhausted at 16.10.1 per item 147 audit).
* DD Defy heal-on-takedown STILL deferred (takedown-rate uncertainty).
* Live ARAM/SR smoke STILL pending - operator must play a real game with one of the 89 unconditional CC champs OR 36 conditional CC champs to verify all 5 cc_conditional consumer surfaces reflect signal correctly under real conditions.
* `_MISSING_HP_SHARE_FOR_HEALS = 0.5` + `_CC_EFFECTIVENESS_FACTOR = 0.5` + 12 default condition probability midpoints + per-entry probability values STILL operator-gated.
* Item 133 carry (c) personal calibration via `data/post_game_rubric_weights.json` STILL operator-gated separately.
* UI/UX live-game audit ritual owed once operator plays a real game (including the s214 build-order card that NOW renders correctly with build_order.css loaded).
* Per-page UI audit ritual still owed on the build-order card specifically (the fix landed but visual verification on a live champ-select is owed).
* Frozen-file grant NOT used this run (no frozen-file touches in any slice).

---
# 2026-05-22 - item 148 cc_conditional wave 7 tag schema lift (COND_FRENZY_STATE + COND_RANGE_GATED forward-marker) SHIPPED (commit `2547836`, pushed `0adf131..2547836`; ENGINE 1.43.0 -> 1.44.0; non-frozen; DS :8893 restarted serves 1.44.0; RC :8888 unchanged)

Operator AskUserQuestion-picked "Conditional CC schema lift" from 4-option fork (over DS 4-slice drain run 15 / orphan CSS cleanup / live game smoke). Closes item 147 carry (l) "Briar frenzy + Sylas range REJECTs STILL need new condition tag constants (separate schema lift)".

Ships 2 NEW condition tag constants as a FORWARD-MARKER schema-lift seam (mirror s112 STAT_GRANT_CALC_KEYS pattern at ENGINE 1.22.0 + pre-1.32.0 _PER_SPELL_CC_DURATIONS pattern). NO new registry entries this wave (registry stays at 36/32); the schema lift unblocks future entries without a separate engine bump.

**NEW condition tag constants:**
* `COND_FRENZY_STATE` = "frenzy_state" - champion enters self-empowered state (Briar Blood Frenzy / Renekton Fury / Volibear R passive / Aatrox post-R passive) that gates an empowered variant of another spell with first-order CC.
* `COND_RANGE_GATED` = "range_gated" - CC fires only at specific cast-range band. Distinct from COND_TERRAIN (positioning vs map geometry) and COND_NTH_HIT (stack accumulation).

Both tags registered in `_DEFAULT_CONDITION_PROBABILITY` with calibrated midpoint **0.4** (mid-low - operator-controlled prerequisite but not guaranteed; below COND_DUAL_ENEMY 0.6 + COND_NTH_HIT 0.7, above COND_TERRAIN 0.3 floor). Both exported via `__all__`. Operator-tunable via per-tag JSON override loader.

**Meraki 16.10.1 re-verify** during this run found the item 147 carry-named candidates do NOT cleanly fit:
* Sylas E2 Abduct stuns on hook hit REGARDLESS of cast range (the item 142 REJECT note calling it range-conditional was incorrect per Riot 16.10.1 spec).
* Briar W has 2 forms (Blood Frenzy + Snack Attack) but Meraki extract is parse-stripped to damage_blocks only - the leveling/effects detail needed to verify a frenzy-empowered Q or R CC mechanic is absent at parse-strip level.

The forward-marker schema lift is the deliverable. Future entries populate when a Meraki-verifiable mechanic surfaces (e.g. Renekton W empowered cast during Fury, Aatrox passive-empowered abilities, Volibear R passive form).

**+29 tests NEW** `agents/daemon_slayer/tests/test_cc_conditional_wave7_tags.py` across 7 classes: WaveSevenTagConstantsTests (6) + WaveSevenDefaultProbabilityTests (6) + WaveSevenPublicTaxonomyTests (3) + RegistryUnchangedTests (4) + ConditionalCcEntryAcceptsNewTagsTests (3) + WaveSevenOverrideLoaderCompatibilityTests (3) + EngineVersionCurrentTests (1) + AsciiHygieneTests (2). `test_cc_conditional.py DefaultProbabilityMapCoverageTests` expected_keys gained the 2 new tags. `test_cc_conditional_forward_marker.py _ALLOWED_TEST_FILES` gained `test_cc_conditional_wave7_tags.py`.

**+32 stale ENGINE pin syncs** across 31 DS test files (1.43.0 -> 1.44.0) via bulk regex rewrite.

Consumer math BYTE-IDENTICAL to 1.43.0 for all 5 consumer surfaces (cc_pressure + compute_ehp + compute_hybrid + coach prompt + dashboard UI) since no registry entry consumes either new tag at ship time.

**Verified:** DS suite **3962 -> 3991 / 1 skipped / 1 xfailed / 1666 subtests** (+29). Wider RC **3278 passed / 67 subtests / 0 failed** post-DS-restart. py_compile + ruff + ASCII clean (0 non-ASCII added to source). DS :8893 restarted via taskkill /F /PID 16932 + `schtasks /Run /TN RC-DaemonSlayer` -> /health returns `engine_version=1.44.0 patch=16.10.1 champions=172 items=705`. RC :8888 unchanged (no route module edits; DS engine + tests only).

**Don't-redo:** the 2 new tag constants are CANONICAL forward-marker seam - do NOT remove or rename. Calibration midpoint 0.4 is operator-tunable via JSON override file but the SEED value is the engineered starting calibration; future tuning lives in `data/cc_conditional_calibration.json` not the source. Sylas E2 Abduct stun is NOT range-gated at 16.10.1 - do NOT re-pitch as a wave 8 COND_RANGE_GATED entry. Briar W frenzy-empowered Q/R mechanics cannot be verified at parse-strip Meraki level - any future encoding needs a real Meraki ability dump (champion_abilities.json with leveling intact). The empty-registry-for-new-tags pattern is intentional (mirrors s112 STAT_GRANT_CALC_KEYS + pre-1.32.0 _PER_SPELL_CC_DURATIONS) - do NOT pre-ship speculative entries.

**Carries forward:** (a) `web/css/dashboard.css:27` orphan @import `./panels/loading_view.css` STILL operator-gated (carries from items 146 + 147) - NOW CLOSED via item 149. (b) `web/css/panels/build_order.css` inverse orphan FILE flagged item 147 STILL operator-gated - NOW CLOSED via item 149. (c) cc_conditional wave 8+ entries that consume COND_FRENZY_STATE or COND_RANGE_GATED operator-gated when Meraki-verifiable mechanic surfaces (Renekton W Fury / Aatrox post-R / Volibear R passive). (d) DD Defy heal-on-takedown STILL deferred. (e) Live ARAM/SR smoke STILL pending. (f) RC-PostmortemAnalyze first scheduled run 2026-05-24 04:15 - verify LastTaskResult=0 next session. (g) `_MISSING_HP_SHARE_FOR_HEALS = 0.5` + `_CC_EFFECTIVENESS_FACTOR = 0.5` + 12 default condition probability midpoints + per-entry probability values STILL operator-gated. (h) Item 133 carry (c) personal calibration via `data/post_game_rubric_weights.json` STILL operator-gated. (i) obj_participation widening NOW CLOSED for option (c) via item 149; option (a) STILL operator-gated. (j) UI/UX live-game audit ritual owed. (k) `_PER_SPELL_CC_DURATIONS` unconditional registry unchanged at 108/89 (wave 10+ likely exhausted at 16.10.1 per item 147). (l) Future cc_conditional wave 8 expansion from REJECT pool operator-gated.

---
# 2026-05-22 - item 147 4-slice parallel drain (cc_conditional wave 6 + _PER_SPELL_CC_DURATIONS wave 9 + BACKLOG stale-sweep wave 11 + cost/latency CLEAN) SHIPPED (3 worktree agents merged + orchestrator commit `22c55e8`, pushed `8d50732..22c55e8`; ENGINE 1.42.0 -> 1.43.0; non-frozen; DS :8893 restarted serves 1.43.0; RC :8888 unchanged)

Operator AskUserQuestion-picked "DS 4-slice drain run 14 (Recommended)" from 4-option fork. 14th consecutive long-run using orchestrator-merge template (items 134-147). 4 worktree agents dispatched concurrent on item 146 carries (b) cc_conditional wave 6 + (j) _PER_SPELL_CC_DURATIONS wave 9 (multi-wave coexistence only - saturated for net-new champs).

DS suite **3881 -> 3962 / 1 skipped / 1 xfailed / 1666 subtests passed** (+81: 44 Slice A + 37 Slice B).

Slice A `1dca288` cc_conditional wave 6: 35/32 -> 36/32 (+1 multi-wave coexistence on Brand Q Sear target_debuffed 1.25s coexists with Brand R wave 1; cc_conditional multi-wave coexistence count now 4 champs Aatrox Q+W / Brand Q+R NEW / Briar Q+E / TahmKench R+Q). Used only 10 existing condition tags. +44 tests. 5 prior-wave test files relaxed Brand-pin assertions.

Slice B `3c73c3b` _PER_SPELL_CC_DURATIONS wave 9: 106/89 -> 108/89 (+2 multi-wave coexistence Chogath W silence + Malzahar Q silence; silence joins first-order CC scope per wave 6 stasis precedent; coexistence count 7 -> 9 unconditional champs). +37 tests. Audit walked all 226 unregistered spells of 89 registered champs = data lane exhausted; future expansion requires new schema.

Slice C `fc7219f` BACKLOG L13 stale-sweep wave 11: 1 flip (cc_conditional ecosystem subsection 35/32 + items 141-146; orchestrator commit catches up to 36/108 + items 141-147 post-A merge). Sweep cycle decay 1=2/2=3/3=3/4=1/5=1/6=1/7=2/8=1/9=1/10=1/**11=1**. ROADMAP CLEAN.

Slice D 14th consecutive cost/latency CLEAN no-commit + 2 MINOR PROPOSALS (operator-gated, deferred): (1) loading_view.css orphan @import at web/css/dashboard.css:27 STILL present (carries from item 146) - NOW CLOSED via item 149; (2) NEW: web/css/panels/build_order.css orphan FILE (inverse orphan: exists but NOT @imported) - NOW CLOSED via item 149. Both safe 1-line edits but were operator-gated until item 149.

Orchestrator commit `22c55e8` bumps ENGINE 1.42.0 -> 1.43.0 + syncs 32 stale pin sites across 31 DS test files + BACKLOG L13 catchup + ROADMAP Fleet status DS row appended. Merge order C/A/B. 0 conflicts.

Verified: DS 3962 passed; py_compile + ruff + ASCII clean; DS :8893 restarted serves 1.43.0; RC :8888 unchanged; CI run id 26322208527 in flight at commit time. Worktrees + 3 branches cleaned.

Don't-redo: cc_conditional now 36/32; _PER_SPELL_CC_DURATIONS now 108/89; silence joins first-order CC scope; wave 10+ exhausted for unconditional (need new schema); orchestrator-merge pattern 14 consecutive runs (items 134-147) DURABLE.

Carries forward: (a) loading_view.css orphan @import STILL operator-gated - NOW CLOSED via item 149; (b) NEW build_order.css orphan FILE flagged operator-gated - NOW CLOSED via item 149; (c) Briar frenzy + Sylas range REJECTs need new condition tag constants (separate schema lift, operator-gated) - schema lift SHIPPED item 148 but registry stays at 36/32; (d) DD Defy heal-on-takedown STILL deferred; (e) Live ARAM/SR smoke pending; (f) RC-PostmortemAnalyze 2026-05-24 04:15 first scheduled run - verify LastTaskResult=0 next session; (g) EHP calibrations operator-gated; (h-m) item 146 carries unchanged.
