# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-05-24 - item 179 SHIPPED: operator-gated parallel drain #13 (ARAM + Arena build chooser collapse extending item 178's SR pattern; BACKLOG/ROADMAP stale-sweep wave 22 CLEAN; cost/latency CLEAN wave 26) (1 merge `c55fd00` of `worktree-agent-abea64c3e46bbdd24` `d0a66c3` pushed origin/main `2b26f27..c55fd00`; non-frozen; no DS engine change; no DS restart; no RC restart - ADR-008 asset-hash auto-serves data/champion_loadouts.json on next dashboard load)

Operator triggered "in parallel : start all open items in Operator-gated, decision owed : when completed do commit + push and /done for /clear". 32nd consecutive run using orchestrator-merge pattern (items 134-179). 3 worktree/investigative agents dispatched concurrent. AskUserQuestion 3-question scope fork pinned per [[feedback_scope_decision_cadence]]: (Q1) ARAM + Arena variant collapse Full (operator picked the larger scope over ARAM-only or skip); (Q2) cc_conditional wave 20+ Skip / defer (Recommended; schema-blocked saturation continues); (Q3) Housekeeping triple Full (Recommended). Pre-flight: 0 open PRs, 5 green CI runs since item 178, 1 stale remote branch (worktree-agent-a6c0eeb6dcc380e0a = item 178 Slice B fully merged via `9c7a9bb`) deleted via `git push origin --delete`. 22 local worktrees harness-locked (parent owns lifecycle, left in place per pattern). 1 untracked at start: data/aram_coaching_data.json.bak-20260523-135434 (forensic from item 165) left in place per [[feedback_no_history_rewrite]].

**Slice A `d0a66c3` (merge `c55fd00` ort 0 conflicts 3 files +39406 / -31414) feat(loadouts) ARAM + Arena build chooser collapse extending item 178's SR pattern + 43 new tests:**
- Schema ADDITIVE: ARAM + Arena variants collapsed into ONE `aram-collapsed` + `arena-collapsed` per champion carrying `build_paths: list[{key, label, items[], reason?}]`. Variant-level `items` / `runes` / `summoners` populate from primary path for back-compat (loadout_resolver consumers passing just `aram-collapsed` or `arena-collapsed` get primary path's items unchanged). SR `sr-collapsed` from item 178 PRESERVED byte-equivalent.
- Before/after: **ARAM 685 source variants -> 172 aram-collapsed** (one per champion) + **Arena 688 source variants -> 172 arena-collapsed** (one per champion). 0 broken `default_per_mode.aram` or `default_per_mode.arena` pointers. SR 172 sr-collapsed UNCHANGED (item 178 isolation preserved).
- Extended `tools/champion_loadout_collapse_to_paths.py` (+199 / -25 net): NEW `--mode <sr|aram|arena|all>` flag + `--item-tag` flag + `collapsed_key_for(mode)` + `collapse_payload_modes()` helpers + `_AUTO_SLOT_SUFFIX` for Arena slot disambiguation (`(primary)` / `(flavor)` / `(secondary)`). Atomic tmp.write_text + tmp.replace + backup to `data/champion_loadouts.json.bak-item179-20260524-205914` (uncommitted, lives in worktree filesystem per item 178 pattern).
- Label-mapping table extended from 57 (item 178) to **85 entries** covering aram-/arena-`<arch>` standards + legacy ARAM keys (`ap-burst`/`tank-aram`/`ap-bombs`/`ad-bruiser`/`ad-crit`/`adc-scaling`/`berserker`/`bruiser-trinity`/`divetop`/`duelist` etc.) + auto-arena slot disambiguators. SR + ARAM auto-* keys preserve item 178's no-slot-suffix behavior. Only `auto-arena-*` gets the `(sec)` / `(flav)` disambiguator since Arena is the only mode with multi-slot population.
- `coaches/loadout_resolver.py` UNCHANGED: the `<variant>:<path-key>` resolve form already worked for ARAM/Arena via mode-agnostic codepath - no resolver edits needed. Verified end-to-end via Jinx smoke: SR/ARAM/Arena each return ONE entry with 4 build_paths; primary path items + summoners preserved; sub-path resolve form `aram-collapsed:on-hit` returns On-Hit items with distinct `set_uid` `RC-jinx-aram-aramcollapsedonhit`.
- `web/js/panels/champ_select.js::_csvMaybePushBuildsToLCU` UNCHANGED: already handles `build_paths` generically per mode (`set_uid` format `RC-<champion>-<mode>-<uidKey>` was already mode-parameterized) - no JS edits needed.
- LCU `apply_item_sets_batch` LCU contract UNCHANGED at `tools/gamepc_lcu_agent.py:957`; agent takes `sets[]` list; now fed paths-flattened-from-collapsed-variants per mode (up to 4 per mode). Each set's `set_uid` makes paths coexist by-uid.
- NEW `tests/test_champion_loadout_collapse_aram_arena.py` (741 LOC, **43 tests across 8 classes**): migration tool invariants (dry-run + --mode filter + backup + idempotent re-run) + schema-additive per-mode (SR untouched by ARAM run + ARAM untouched by Arena run) + label-mapping (ARAM short labels + Arena primary/flavor/secondary disambiguators) + per-champion collapse correctness + default selection contract + multi-mode isolation + ASCII hygiene.
- Idempotent re-run: re-collapsing an already-collapsed mode with no source variants left preserves the existing path list verbatim (operator hand-edits survive); re-collapsing after operator hand-adds a source variant picks it up + rebuilds deterministically.

**Slice B CLEAN no-commit (BACKLOG/ROADMAP stale-sweep wave 22):** 0 flips. All 4 anchors from item 177 wave 21 grep-verified live at cited lines: ROADMAP L13 `dev.js:361` verdict.team_won + ROADMAP L23 `main.js:3081/3092/4281` LCU 3 sites + ROADMAP L23 `gamepc_lcu_agent.py:246` ARAM Mayhem + ROADMAP L82 `gamepc_lcu_agent.py:1194` augment_intent_unsupported. **Sweep cycle decay:** wave 17=0 / 18=1 / 19=0 / 20=0 / 21=0 / **22=0**. Five consecutive zero-flip waves (17 + 19 + 20 + 21 + 22). Saturation deepening; wave 18 lone flip (`gamepc_lcu_agent.py:1091` -> `:1194` from item 174) remains the most-recent line drift across 5 sweeps.

**Slice C 26th consecutive cost/latency CLEAN no-commit (read-only investigative agent):**
- All 7 levers green. (1) Prompt-cache 8 cache_control sites (7 coaches + coach_integration/_coach.py). (2) Route TTL **16 routes** with `_CACHE` (live grep authoritative; item 177 "12 routes" claim was loose ledger drift not a regression - count fluctuates 12-16 across audits). (3) Polling cadences pollIfStale + pollLcu 2000ms (main.js:6173/6241); no sub-500ms network polls. (4) Log spam top non-suppressed `/api/ward-heat` 0.194/s + `/api/bridge` 0.132/s + `/api/adaptation` 0.122/s + `/api/health/all` 0.068/s - ALL below 1/sec threshold; `/api/bridge` rate matches item 177 baseline exactly. _SUPPRESS_LOG_PATHS = 9 entries unchanged. (5) Model tier coaches all `claude-haiku-4-5-20251001`; agent7 DEFAULT_MODEL = `claude-haiku-4-5` (item 177 correction confirmed); agent6_auditor = Opus only. (6) Scheduled tasks 14 RC-* matching item 177 catalog exactly. (7) Bundle parity 27 panel CSS files = 27 panel @imports in dashboard.css (29 total = 27 panel + 2 non-panel including build_order.css + tokens/base); drift guard `test_dashboard_css_panel_imports_parity.py` 4/4 PASS.
- INFORMATIONAL note: today's `logs/2026-05-24.log` only spans 20:16:18-20:56:52 (40-min window) - the log was rotated/truncated mid-day; pid 5800 continues writing into a freshly-opened handle. Per item 177 closure: `core/log_setup.py` DailyRotatingFileHandler uses `date.today()` local-time so file rotates on local-date boundary not UTC. Mid-day truncation is a separate signal worth verifying next session if it recurs (non-blocking).

**Verified post-merge:**
- DS suite untouched (no engine change; DS :8893 still serves 1.56.0 from item 177; not restarted).
- RC suite `tests/` (excl phase8_smoke) **3367 passed / 67 subtests passed in 56.57s** (+43 over item 178's 3324 baseline = exactly the new test_champion_loadout_collapse_aram_arena.py file).
- Relevant surfaces: `tests/test_champion_loadout_autogen.py` 35/35 + `tests/test_champion_loadouts_no_unique_clash.py` 2/2 + `tests/test_champion_loadout_collapse_to_paths.py` 27/27 + `tests/test_champion_loadout_collapse_aram_arena.py` 43/43 + `tests/phase8_smoke/` 75/75 = **182/182 PASS**.
- `py -m ruff check .` ALL CHECKS PASSED.
- `py -m py_compile tools/champion_loadout_collapse_to_paths.py coaches/loadout_resolver.py` clean.
- ASCII: 0 non-ASCII bytes in tool + test file + data file.
- Resolver smoke verified end-to-end for Jinx: SR/ARAM/Arena each return ONE entry with 4 build_paths; primary path items + summoners preserved; sub-path resolve form `aram-collapsed:on-hit` returns On-Hit items with distinct set_uid.
- Post-collapse counts: SR=172 (collapsed=172) ARAM=172 (collapsed=172) Arena=172 (collapsed=172); 0 non-collapsed source variants remain in any mode; all 172 default_per_mode pointers point to their respective collapsed keys per mode.
- RC :8888 unchanged pid 5800 mode=game aram_mode=true has_game=true (operator entered ARAM game mid-session; never restarted - non-frozen + non-coach-prompt edits; ADR-008 unified asset-hash auto-serves data/champion_loadouts.json on next dashboard load).

**Merge order:** Slice A worktree branch `worktree-agent-abea64c3e46bbdd24` pushed by agent; orchestrator fetched + `git merge --no-ff origin/<branch>` into main as `c55fd00` (ort, 0 conflicts, 3 files). Pushed origin/main `2b26f27..c55fd00`. 0 merge conflicts. 0 docs sync follow-up commit needed (no engine bump, no version pins, no test count refs in living docs - those tier docs sync only on ENGINE bumps per recent ledger pattern).

**Don't-redo:**
- ARAM + Arena variant collapse via `aram-collapsed` + `arena-collapsed` keys with `build_paths: list[{key, label, items[], reason?}]` is now the canonical home for per-champion-multi-archetype build presentations across all 3 modes (SR + ARAM + Arena). The collapse tool is mode-parameterized via `--mode <sr|aram|arena|all>` flag; future mode additions extend `_PATH_ORDER` + `_AUTO_SLOT_SUFFIX` per-mode policies in `tools/champion_loadout_collapse_to_paths.py`.
- The 85-entry label-mapping table covers all 64 ARAM unique variant keys + all 23 Arena unique keys observed in current data; extend it (NOT titlecased fallback) for any future net-new archetype to keep pill labels short + readable.
- The `<variant>:<path-key>` resolve form is mode-agnostic - `coaches/loadout_resolver.py` did NOT need edits this session; the colon-form is the canonical apply-path API across all 3 modes. Legacy callers passing just `<variant>` resolve to the primary path's items (back-compat preserved).
- `apply_item_sets_batch` LCU contract is UNCHANGED at `tools/gamepc_lcu_agent.py:957`; the agent continues to take `sets[]`; the JS `_csvMaybePushBuildsToLCU` already handled the per-mode `set_uid` format (`RC-<champion>-<mode>-<uidKey>`) so distinct paths in distinct modes coexist by-uid.
- Operator hand-edits to collapsed variants survive idempotent re-runs of the tool (verified in test class). Re-collapsing after operator hand-adds a source variant picks it up + rebuilds deterministically; re-running on already-collapsed mode with no source variants is a no-op preserving existing path list verbatim.
- The orchestrator-merge pattern is now 32 consecutive runs (items 134-179). This run had no scope-fork mid-flight + no ENGINE bump + no DS restart + no RC restart - the slim-est-merge variant in the recent ledger (same as item 178). No additional docs-sync follow-up commit needed.
- Operator was mid-game (ARAM) during the merge - the resolver + LCU contract was preserved so live coaching is unaffected. Live UI capture of the new ARAM + Arena multi-path render OWED at next champ select of those modes.

**Carries forward:**
- (a) Item 178 carries ALL unchanged EXCEPT (k) ARAM + Arena variant collapse NO LONGER operator-gated (DONE this session).
- (b) RC-PostmortemAnalyze first scheduled run TODAY 2026-05-25 04:15 (per item 178 carry forward; verify LastTaskResult=0 next session; role_grades JSON will reflect 9-col obj_participation on next aggregation).
- (c) DD Defy heal-on-takedown STILL deferred (operator-gated).
- (d) Live ARAM/SR smoke STILL pending (live-gated; this session's verification was tests + resolver smoke only; live ARAM bench-swap or Arena lobby load with the new collapsed entries owed).
- (e) Calibrations STILL operator-gated.
- (f) UI/UX live-game audit ritual owed once operator plays a real ARAM game with the new collapsed build chooser.
- (g) DS conditional arc operator-CLOSED (s232).
- (h) Legion 1-PC consolidation (s169 option B) STILL operator-gated.
- (i) cc_conditional wave 20+ candidates STILL UNDEFINED - schema-lift-blocked saturation continues (operator-gated; Slice Q2 fork picked Skip / defer this session).
- (j) 542 residual U+2500 chars NO LONGER carry-forward (DONE item 176).
- (k) Live UI capture of new ARAM + Arena multi-path render OWED at next champ select of those modes.
- (l) v2.1 audit pages 9/10 Champ Select ARAM/Arena -> 11/12/13 Active Match SR/ARAM/Arena -> 14/15/16 PGR SR/ARAM/Arena (8 remaining; this session's framing again non-UI per scope fork).
- (m) Frozen-file grant NOT used this session.
- (n) INFORMATIONAL log rotation note: today's `logs/2026-05-24.log` rotated mid-day at ~20:16; if recurring next session, worth investigating (non-blocking).
- (o) Slice C noted route TTL count fluctuates 12-16 across audits; do NOT pin to a specific number in future ledger entries; use live `grep _CACHE dashboard/routes_*.py | wc -l` at audit time.

---

# 2026-05-24 - item 178 SHIPPED: SR champ-select page #8 audit PASS + build chooser multi-path refactor (678 -> 172 SR variants via build_paths[] collapse) (1 merge `9c7a9bb` of `worktree-agent-a6c0eeb6dcc380e0a` `fc269ff` pushed origin/main `21517dc..9c7a9bb`; non-frozen; no DS engine change; no DS restart; no RC restart - ADR-008 asset-hash auto-served CSS+JS+JSON on next dashboard load)

Operator triggered: "lets do the ui agent for the SR champ select page. also i noticed ingame that there was a lot of listed champion builds - either they need to be renamed to follow a convention for selection or reduced down to a manageable amount or refactored to have multiple lines within a build order". 31st consecutive run using orchestrator-merge pattern (items 134-178). AskUserQuestion 2-question scope fork per [[feedback_scope_decision_cadence]]: (Q1) page #8 audit Audit + fix same session (Recommended); (Q2) build chooser refactor Multi-line build orders within ONE variant (operator picked the LARGER CSS+JS+schema refactor over cap-and-rename). 2 agents dispatched concurrent (Slice A Explore read-only + Slice B general-purpose worktree).

**Slice A audit PASS clean (no commit; closes item 168 carry (b) page #8 visual-hierarchy re-run for items 166-168 surface):**
- STRUCTURE PASS: grid 1fr / 1.2fr / 1fr cols + row 2 floor 460px minmax; item 168 3-panel Pick & Ban present (.csv-pb168-picks/bans/expl); DS Build Archetype relocated to #csv-archetype-target with picker UI; SR Build Chooser below; Summoner Spell strip 9 slots between archetype picker + build chooser; Assessment YOUR RECORD pinned top; CC threat balance + conditional CC visible.
- TYPOGRAPHY PASS: all v2.1 token-driven. `.csv-pb168-tag` L1036 `--fs-xs` + `.csv-pb168-name` L1061 `--fs-xs` + `.csv-arch-preview-name` L381 `--fs-xs` + `.csv-summspell-pct` L929 `--fs-sm` all on tokens. Sub-floor operator exceptions documented: `.csv-bench-empty` L1660 13px (s212 v2 across-room legibility floor for interactive surfaces) + `.csv-duo-cell-tag` L2104 11px (s234 Arena cell metadata tolerance). NO new sub-floor violations post-items 166-168.
- HIT-TARGETS PASS: `.csv-archetype-pill` padding 8px 4px + flex container; `.csv-pb168-cell` 38px x 4-col grid w/ 4px gaps ~80px inclusive; `.csv-summspell-cell` L896 `min-height: var(--hit-min)` 42px; `.csv-bench-cell` 48px 10-col grid. All clickables meet --hit-min floor.
- ASCII PASS: CSS 76870 bytes ASCII / CRLF; JS 155129 bytes ASCII / CRLF. Zero non-ASCII bytes both files (post item 170 retro-sweep durable).
- HIERARCHY PASS: 4 distinct visual tiers readable. YOUR RECORD lavender left-accent dominates Assessment; Pick & Ban 3-tier distinct sub-panels with labeled heads + color-coded border-left per source; Build Archetype delegation subordinate w/ 3x2 button grid + top-3 DS preview; Build Chooser 4 rows equal weight border-left color-coded; CC threat balance + conditional CC visible w/o scroll at 1080px baseline.
- BUILD CHOOSER CLUTTER OBSERVED: mock fixture champ_select_sr.json showed 3 variants for Jinx; current UI surface accommodates ~4-6 variant rows before vertical scroll; ~346 total SR variants across 172 champs; Tristana ~4 variants flagged. Current 4-row flex column gap:4px works for typical 3-5 variant clutter. NO CSS BLOCKERS for multi-line refactor - parallel Slice B can proceed without CSS redesign.
- MUST-FIX tier 1: NONE. SHOULD-FIX tier 2: NONE. NICE-TO-HAVE tier 3: 2 operator-exception sub-floor pixel sites (`.csv-bench-empty` 13px + `.csv-duo-cell-tag` 11px) + after multi-line refactor consider responsive row-height collapse for champs with 7+ variants.
- Verdict: page #8 v2.1 audit GREEN. Item 168 carry (b) CLOSED.

**Slice B `fc269ff` (merge `9c7a9bb` ort 0 conflicts 8 files +19009 / -10943) feat(loadouts) SR build chooser multi-path collapse + LCU contract preserved + 27 new tests:**
- Schema ADDITIVE: SR variants collapsed into ONE `sr-collapsed` per champion carrying `build_paths: list[dict]`. Each path = `{key, label, items[], reason?}`. Variant-level `items` / `runes` / `summoners` populate from primary path for back-compat (loadout_resolver consumers passing just `variant` get the primary path's items unchanged).
- Before/after: **678 SR variants -> 172** (one `sr-collapsed` per champion). Path distribution: 3 paths in 10 champs / 4 paths in 162 champs. 0 broken `default_per_mode.sr` pointers. ARAM (685) + Arena (688) variant sets BYTE-IDENTICAL pre/post (operator-scoped SR-only).
- NEW `tools/champion_loadout_collapse_to_paths.py` (473 LOC) migration tool with `--dry-run` / `--champion <name>` / `--no-backup` flags + atomic tmp.write_text + tmp.replace + backup to `data/champion_loadouts.json.bak-item178-20260524-194825` (uncommitted, lives in worktree filesystem per item 165 ARAM pattern).
- `coaches/loadout_resolver.py` extended (+89 / -X): `list_variants()` surfaces `build_paths[]` with resolved item_ids per path; `resolve()` accepts `<variant>:<path-key>` form and overlays the path's items/runes/summoners; bakes path key into LCU `set_uid` + `page_name` so distinct paths produce distinct LCU sets (RC-<champion>-sr-<variant>-<path> UID format coexists by-uid no overwrite).
- `web/js/panels/champ_select.js` (+166 / -X): NEW `_csvBuildPathRowHtml` helper; `_csvBuildVariantRowsHtml` renders ONE champion entry with N labeled build-path rows when `build_paths` non-empty; `_csvWireBuildVariants` wires per-path clicks with `stopPropagation`; `_csvMaybePushBuildsToLCU` flattens `build_paths` into `apply_item_sets_batch` units (up to 4) so each path becomes its own `set_uid`.
- `web/css/panels/champ_select_view.css` (+90): NEW `.csv-build-row-collapsed` + `.csv-build-collapsed-head` + `.csv-build-path-list` + `.csv-build-path-row` (`min-height: var(--hit-min)` 42px) + `.csv-build-path-label` (`--fs-sm`) + `.csv-build-path-items` + `.csv-build-path-item` (32x32). Vertical stack within existing build chooser panel; no width changes; item icons size matches `.csv-arch-preview-icon`.
- `web/data/ui_mock/champ_select_sr.json` updated: Jinx entry now ONE `sr-collapsed` variant with 3 build_paths (Crit primary / On-Hit / Lethality) for dev UI mock multi-path render.
- LCU push contract UNCHANGED: `apply_item_sets_batch` shape preserved at `tools/gamepc_lcu_agent.py:957`; agent takes `sets[]` list; now fed paths-flattened-from-collapsed-variants. Each set gets `RC-<champion>-sr-<variant>-<path>` UID so paths coexist by-uid.
- `tests/test_champion_loadouts_no_unique_clash.py` (+43 / -X) extended to walk `build_paths[].items` so a unique-passive-family clash inside a non-primary path is caught by the drift guard.
- NEW `tests/test_champion_loadout_collapse_to_paths.py` (411 LOC, **27 tests across 5 classes**): migration tool invariants (dry-run / --champion filter / backup behavior) + schema-additive guarantees + label-mapping (`sr-carry` -> `Carry`, `adc-crit` -> `Crit`, `on-hit` -> `On-Hit`, `lethality` -> `Lethality`, `ap-burst` -> `Burst`, `ap-dps` -> `DPS`, `tank-engage` -> `Engage`, `tank-frontline` -> `Frontline`, `bruiser-fighter` -> `Fighter`, `enchanter` -> `Enchanter`, `jg-bruiser` -> `Jungle Bruiser`, `jg-tank` -> `Jungle Tank`, `jg-assassin` -> `Jungle Assassin`; titlecased fallback for unmapped) + per-champ collapse correctness + default selection contract pin + multi-mode isolation (ARAM/Arena untouched assertion) + ASCII hygiene.
- Default selection contract preserved: when champ select fires, FIRST path = historically default variant per `default_per_mode.sr` (now always `sr-collapsed`, stable). Pre-existing `default_per_mode.aram` / `default_per_mode.arena` UNCHANGED.

**Verified post-merge:**
- DS suite untouched (no engine change; DS :8893 still serves 1.56.0 from item 177; not restarted).
- RC suite `tests/` (excl phase8_smoke) **3324 passed / 67 subtests passed in 55.93s** (+27 over item 177's 3297 baseline = exactly the new test_champion_loadout_collapse_to_paths.py file).
- Relevant surfaces: `tests/test_champion_loadout_autogen.py` 35/35 + `tests/test_champion_loadouts_no_unique_clash.py` 2/2 + `tests/test_champion_loadout_collapse_to_paths.py` 27/27 + `tests/phase8_smoke/` 75/75 = **139/139 PASS**.
- `py -m ruff check .` ALL CHECKS PASSED.
- `py -m py_compile coaches/loadout_resolver.py tools/champion_loadout_collapse_to_paths.py` clean.
- JS parse: `node --check web/js/panels/champ_select.js` exit 0 (per Slice B agent's pre-commit verification).
- ASCII: 0 new non-ASCII bytes in all 7 new/touched files (pre-existing 27 bytes in `loadout_resolver.py` left alone per [[feedback_no_em_dashes]]).
- Resolver smoke verified end-to-end for Jinx + Aatrox: SR returns 1 entry with N paths; `resolve('Jinx', 'sr-collapsed', 'sr')` returns primary path items; `resolve('Jinx', 'sr-collapsed:sr-bruiser', 'sr')` overlays sr-bruiser's items with distinct `set_uid`.
- RC :8888 unchanged pid 5800 mode_key=client (never restarted - non-frozen + non-coach-prompt edits; ADR-008 unified asset-hash auto-serves the CSS+JS+JSON on next dashboard load + `coaches/loadout_resolver.py` mtime-cache invalidation on next call).
- 3 untracked at start (`data/aram_coaching_data.json.bak-20260523-135434` + `main_test_err.log` + `main_test_out.log`) left in place after intermediate test runs created + cleaned the 2 main_test_* logs (latter restored on subsequent test runs - non-blocking gitignored noise).

**Merge order:** Slice A audit returned no-commit (read-only Explore). Slice B worktree branch `worktree-agent-a6c0eeb6dcc380e0a` pushed by agent; orchestrator fetched + `git merge --no-ff origin/<branch>` into main as `9c7a9bb` (ort, 0 conflicts, 8 files). Pushed origin/main `21517dc..9c7a9bb`. 0 merge conflicts. 0 docs sync follow-up commit needed (no engine bump, no version pins, no test count refs in living docs - those tier docs sync only on ENGINE bumps per recent ledger pattern).

**Don't-redo:**
- Multi-line build paths `build_paths: list[{key, label, items[], reason?}]` on `sr-collapsed` variant is the canonical home for SR per-champion-multi-archetype build presentations going forward. ARAM + Arena variants are intentionally UNCOLLAPSED this run (operator-scoped to SR; collapsing them would require equivalent per-mode design decisions about which path is "primary" + how to surface them in their non-DS-driven contexts).
- The `<variant>:<path-key>` resolve form is the canonical apply-path API; legacy callers passing just `<variant>` resolve to the primary path's items (back-compat preserved). Future LCU push or coach-recommendation consumers should use the colon-form to address a specific path.
- `apply_item_sets_batch` LCU contract is UNCHANGED - the agent at `tools/gamepc_lcu_agent.py:957` continues to take `sets[]`; we just now flatten `build_paths[:4]` per champion into the list. The `set_uid` discipline `RC-<champion>-sr-<variant>-<path>` makes paths coexist; do NOT collapse the path key out of the uid.
- The label-mapping table in `tools/champion_loadout_collapse_to_paths.py` covers 13 known archetype variant_keys; extend it (NOT a titlecased fallback) for any future net-new archetype to keep pill labels short + readable in the build chooser.
- The migration tool atomically writes back to `data/champion_loadouts.json` + backs up to `data/champion_loadouts.json.bak-item178-<timestamp>`; re-running the tool on already-collapsed data should be a no-op (verify via unit test before re-running on the live data; the tool's behavior on already-collapsed input was not explicitly tested as a re-entrancy guarantee).
- The page #8 audit is GREEN; do not re-run the audit subagent for items 166-168 surface unless new edits land in `.csv-*` namespaces. The next page #8 audit triggers when subsequent UI work touches the surface.
- The orchestrator-merge pattern is now 31 consecutive runs (items 134-178). This run had no scope-fork mid-flight + no ENGINE bump + no DS restart + no RC restart - the slim-est variant of the pattern that's been used in the recent ledger.
- Operator pattern caught by Slice B agent: "ARAM and Arena variants stay UNCOLLAPSED this run - SR mode only" was respected (685 ARAM + 688 Arena BYTE-IDENTICAL pre/post). If operator later asks to collapse ARAM/Arena, the same tool + schema apply; extend label mapping for `arena-<arch>` + `aram-<arch>` variant keys.
- Live UI capture of the new multi-path render is OWED at the next time operator hits a real champ select (or `?ui_mock=1#champ_select` browse) - all backend + JS + CSS + tests verify the contract but the visual proof was not captured this session (the audit subagent's pre-refactor capture from earlier in the session shows the old 4-row variant grid; ADR-008 auto-serves the new code so the next dashboard load picks up the multi-path render automatically).

**Carries forward:**
- (a) Item 177 carries ALL unchanged EXCEPT (a-bis) page #8 audit re-run for items 166-168 surface NOW CLOSED this session via Slice A.
- (b) RC-PostmortemAnalyze first scheduled run TOMORROW 2026-05-25 04:15 (per item 177 carry forward shifted +1 day; verify LastTaskResult=0 next session; role_grades JSON will reflect 9-col obj_participation on next aggregation).
- (c) DD Defy heal-on-takedown STILL deferred (operator-gated).
- (d) Live ARAM/SR smoke STILL pending (live-gated; this session's verification was tests + resolver smoke + audit capture only; live champ select pick + LCU multi-itemset push to in-game shop dropdown owed).
- (e) Calibrations STILL operator-gated.
- (f) UI/UX live-game audit ritual owed once operator plays a real SR game with the new multi-path build chooser.
- (g) DS conditional arc operator-CLOSED (s232).
- (h) Legion 1-PC consolidation (s169 option B) STILL operator-gated.
- (i) cc_conditional wave 20+ candidates STILL UNDEFINED - the current-schema lane + coexistence machinery are both saturated; further growth needs schema lift (operator-gated).
- (j) 542 residual U+2500 chars NO LONGER carry-forward (DONE item 176; item 177 didn't re-introduce).
- (k) ARAM + Arena variant collapse STILL operator-gated (this session scoped to SR mode only per Q2 fork; tool + schema are reusable).
- (l) Live UI capture of new multi-path render OWED at next champ select session.
- (m) v2.1 audit pages 9/10 Champ Select ARAM/Arena -> 11/12/13 Active Match SR/ARAM/Arena -> 14/15/16 PGR SR/ARAM/Arena (8 remaining; this session's framing again non-UI per page #8 audit being a CLOSE-OUT not a new page open).
- (n) Frozen-file grant NOT used this session.

---

# 2026-05-24 - item 177 SHIPPED: operator-gated parallel drain #12 (cc_conditional wave 19 Meraki extractor state-tracking schema lift parent_resource forward-marker ENGINE 1.56.0 + log destination FLAG closure + BACKLOG/ROADMAP stale-sweep wave 21 CLEAN + cost/latency CLEAN wave 25) (2 commits + 1 merge `487981f` (Slice A worktree) + docs sync `bdc70d7` pushed origin/main `01d0970..bdc70d7`; ENGINE 1.55.0 -> 1.56.0; DS :8893 killed pid 8232 + relaunched via schtasks -> serves 1.56.0; RC :8888 unchanged pid 5800 mode_key=client - DS engine + tools + tests + docs only)

Operator triggered "in parallel : start all open items in Operator-gated, decision owed : when completed do commit + push and /done for /clear". 30th consecutive run using orchestrator-merge pattern (items 134-177). 3 worktree/investigative agents dispatched concurrent. AskUserQuestion 3-question scope fork pinned per [[feedback_scope_decision_cadence]]: (Q1) cc_conditional wave 19 STATE-TRACKING extractor schema lift (operator picked the BIG lift over re-audit lane); (Q2) Log destination FLAG investigation (Recommended); (Q3) Housekeeping triple Full (Recommended). Pre-flight: 0 open PRs, all 5 CI runs green since item 176, 0 stale remote branches (only origin/main + origin/HEAD). 21 local worktrees harness-locked (parent owns lifecycle, left in place per pattern). 3 untracked at start: data/aram_coaching_data.json.bak-20260523-135434 (forensic from item 165) + main_test_err.log (0 bytes) + main_test_out.log (182 bytes test output residue) - left in place per [[feedback_no_history_rewrite]].

**Slice A `487981f` (merge into main as part of separate merge commit on worktree-agent-aedeb16395b825ebe) feat(ds) cc_conditional wave 19 Meraki extractor state-tracking schema lift ENGINE 1.55.0 -> 1.56.0 (36 files / +1588 / -39):**
- NEW `parent_resource: str | None` field per spell form record in `tools/daemon_slayer_abilities_extract.py` via NEW `_build_form(parent_resource=...)` signature threaded from champion-level `payload["resource"]` in `_build_champion`. Captures structured state-tracking metadata: FURY (Renekton / Gnar / Tryndamere / Shyvana) / BLOOD_WELL (Aatrox) / FRENZY (Briar) / RAGE (Renekton) / HEAT (Rumble) / ENERGY (Akali / Kennen / LeeSin / Shen / Zed) / GRIT (Sett) / MANA (default). Pure-additive schema extension; downstream consumers ignore the field until they opt in.
- Re-extracted `data/daemon_slayer/16.10.1/champion_abilities.json` at 1.56.0 schema (171 champs / 927 forms / 99.0% ok_rate; +33% file size increase from descriptions+resource). Byte-identical coverage shape vs 1.55.0; the new field surfaces empowered-state resources on Aatrox / Renekton / Gnar / Rumble for first time (per-form `resource` was `null` until this lift).
- 0 net-new registry entries (cc_conditional UNCHANGED at 67/54 across waves 0-18). Schema lift ships as FORWARD-MARKER infrastructure (parallel to wave 7 forward-marker tag pattern at item 148): structured state-tracking metadata is now available so future cc_conditional candidates can pre-filter on `parent_resource` instead of parsing description text or hardcoding champion lists.
- DEVIATION CAUGHT BY AGENT (validated): brief named 6-7 wave-7 schema-lift carries (Renekton W Fury + Aatrox post-R passive + Volibear R + Briar W frenzy + Karma W form 1 + Hwei E form 1+2 + Neeko E) to ship under the lift. Direct verification against LIVE cc_conditional registry + prior audit ledger confirmed **ALL of them were already closed**: Renekton W ALREADY SHIPPED PRIMARY (wave 9 item 153 COND_FRENZY_STATE 1.5s) + Karma W form 1 ALREADY SHIPPED SIDECAR (wave 10 item 154 COND_FRENZY_STATE 2.35-2.75s) + Hwei E form 2 ALREADY SHIPPED SIDECAR (wave 10 item 154 COND_CHANNEL_COMPLETION) + Hwei E form 1 REJECT-verified (item 153 channel mismatch) + Neeko E ALREADY SHIPPED PRIMARY (wave 1 COND_DUAL_ENEMY 1.8-3.0s) + Aatrox post-R passive REJECT-verified (item 153 minion-only fear) + Volibear R REJECT-verified (items 150/153/156 turret-only) + Briar W frenzy REJECT-verified (items 150/153/156 self-buff only). Agent shipped forward-marker infrastructure instead of no-op per brief explicit deviation-welcome clause.
- ENGINE_VERSION 1.55.0 -> 1.56.0 in `__init__.py` with full changelog block + bulk pin sync across 32 DS test files via regex rewrite.
- **+30 tests** in NEW `agents/daemon_slayer/tests/test_cc_conditional_wave19.py` covering Wave19EmpoweredStateStructuralPreFilterTests + extractor schema-lift invariants + parent_resource field shape pins per-champion + ENGINE pin + ASCII hygiene. 4 self-corrections pre-commit: cls.snapshot vs self.snapshot bug + over-eager ASCII hygiene scope picked up U+2500 ASCII-art in extractor source (tightened to docstring paragraph) + `_build_champion` docstring test used escaped newline end-marker truncating docstring mid-block (switched to triple-quote closer).
- Math verification: Default `include_conditional=False` BYTE-IDENTICAL to 1.55.0 for ALL champions. The extractor schema lift is purely additive; consumer math sees `parent_resource` only if it opts in via field access (no current consumer reads it).
- 4 cc_conditional champs (Aatrox / Briar / Gnar / Renekton) now carry empowered-state resources at the form level for the first time in extracted data.

**Slice B VERIFIED OK no-commit (log destination FLAG investigation):**
- Item 176 carry (i) flag was a MEASUREMENT ARTIFACT. The file `logs/2026-05-24.log` IS actively being written by pid 5800 at 1.75 MB / mtime 2026-05-24 18:48:26 -0500 (1 second after probe). Last 3 lines were `rc.lcu lockfile not found - client may not be running` at 18:48:24/25/26 CDT (LCU agent polling, normal idle).
- Item 176 audit ran at ~17:51 local. At that moment, the log spanned 15:52-17:51 because pid 5800 had only just booted at 15:23:23 local (per item 175 verified boot time). The "no log file written since current pid started" claim in carry (i) was a measurement artifact - the auditor compared the file last mtime against a stale rc_facts probe showing pid 5800 boot at "2026-05-20T14:35:48" (4 days ago) and concluded the file was stale. In reality the file was live and being written by pid 5800 the entire time.
- `core/log_setup.py:42-76` DailyRotatingFileHandler uses `date.today()` (local time, not UTC) - file rotates on local-date boundary, NOT UTC. Current system CDT (UTC-5); file will roll at local midnight to `logs/2026-05-25.log`. logs/2026-05-25.log does NOT exist (correct - still 2026-05-24 local).
- **Verdict:** Log destination VERIFIED OK. No drift, no fix needed. Item 176 carry (i) CLOSES this session.

**Slice C 25th consecutive cost/latency CLEAN no-commit (read-only investigative agent) + BACKLOG/ROADMAP stale-sweep wave 21:**
- All 7 levers green. (1) Prompt-cache 7 coaches + 1 coach_integration/_coach.py = 8 cache_control sites. (2) Route TTL 12 routes with `_CACHE` constant (live count fluctuates 12-16 per item 175 don't-redo). (3) Polling cadences pollIfStale + pollLcu 2000ms - no sub-500ms network polls. (4) Log spam top non-suppressed `/api/bridge` at 0.132/s (well below 1/sec hard threshold). _SUPPRESS_LOG_PATHS = 9 entries unchanged. (5) Model tier coaches all `claude-haiku-4-5-20251001`; agent7 DEFAULT_MODEL = `claude-haiku-4-5` (NOT Sonnet - item 175 brief overstated this; Sonnet annotations in coaches are POST-call telemetry stamps only); agent6_auditor charter = Opus only. (6) Scheduled tasks 14 RC-* matching item 176 catalog. (7) Bundle parity 27 panel CSS = 27 dashboard.css @imports (drift guard `test_dashboard_css_panel_imports_parity.py` 4/4 PASS). Cost-trace `test_cost_tracker_response_helper.py` 27/27 PASS (11 wired sites intact).
- BACKLOG/ROADMAP stale-sweep wave 21 = **0 flips**. All 4 anchors from item 176 wave 20 grep-verified live at cited lines: ROADMAP L13 `dev.js:361` verdict.team_won + ROADMAP L23 `main.js:3081/3092/4281` LCU 3 sites + ROADMAP L23 `gamepc_lcu_agent.py:246` ARAM Mayhem + ROADMAP L82 `gamepc_lcu_agent.py:1194` augment_intent_unsupported.
- **Sweep cycle decay:** wave 17=0 / 18=1 / 19=0 / 20=0 / **21=0**. Saturation continues; lane confirmed exhausted absent product-fidelity tradeoffs.
- Model tier correction propagated: item 175 brief claimed Sonnet in agent7_warm_session; actual code shows agent7 DEFAULT_MODEL = `claude-haiku-4-5`. Sonnet stamps in coaches/* are POST-call telemetry annotations (`r._model = "claude-sonnet-4-6"`), NOT call-time model selections. This is CLEANER than ledger lineage claimed.

**Docs sync `bdc70d7` (6 files / 8 ins / 8 del):**
- ENGINE 1.55.0 -> 1.56.0 + 4641 -> 4671 tests + 67/54 waves 0-18 -> 67/54 waves 0-19 + wave 19 closure note across docs/DAEMON_SLAYER.md L5+L32 + README.md L46 + BRIEF.md L20+L26 + docs/ARCHITECTURE.md L161 (2 edits) + BACKLOG.md L13 (2 edits) + ROADMAP.md L165 (2 edits).
- Skipped per [[feedback_no_history_rewrite]]: BRIEF.md L33 milestone narrative + L57 resume-pitch.

**Verified post-merge + DS restart:**
- DS suite **4671 passed / 1 skipped / 1 xfailed / 1764 subtests** (+30 over 4641 baseline = exactly the wave 19 test file).
- RC suite (excl phase8_smoke) **3297 passed** (unchanged from item 176 baseline; extractor schema lift invisible to RC route layer).
- `tests/phase8_smoke/` = **75/75 PASS** post-DS-restart.
- `py -m ruff check .` ALL CHECKS PASSED.
- DS :8893 killed pid 8232 + `schtasks /Run /TN RC-DaemonSlayer` (per [[reference_ds_server_not_supervisor_watched]]) -> /health engine_version=1.56.0 patch=16.10.1 champions=172 items=705.
- RC :8888 unchanged pid 5800 mode_key=client (no route/coach edits this run; DS engine + tools + tests + docs only; never restarted).

**Merge order:** Slice A merged into main FIRST (worktree branch `worktree-agent-aedeb16395b825ebe`, ort, 0 conflicts, 36 files). Slice B + Slice C produced no commits. Docs sync committed direct to main SECOND as `bdc70d7` (6 files / 8 ins / 8 del). 0 merge conflicts.

**Don't-redo:**
- The `parent_resource: str | None` field on spell form records is the canonical home for structured state-tracking metadata; future cc_conditional waves needing Fury / passive-flag / form-empowered state detection should pre-filter on `form.parent_resource` instead of parsing description text or hardcoding champion lists. The 4 cc_conditional champs (Aatrox / Briar / Gnar / Renekton) carrying empowered-state resources at the form level are the first consumers of this lift.
- The 6 brief-named wave-7 schema-lift carries are now CLOSED for re-pitching: Renekton W (wave 9 item 153) + Karma W form 1 (wave 10 item 154) + Hwei E form 2 (wave 10 item 154) + Neeko E (wave 1) are all ALREADY SHIPPED; Aatrox post-R + Volibear R + Briar W are REJECT-VERIFIED. Do NOT re-pitch these as wave 20+ candidates.
- The orchestrator pattern brief-deviation-welcome clause is essential: Slice A agent caught + reported that the brief premise was stale (all 6 carries already shipped) and shipped the forward-marker schema lift instead of a no-op. This is the 3rd consecutive run (items 175 + 176 + 177) where agent self-correction caught spec deviations; the pattern is durable.
- Item 176 carry (i) log destination FLAG was a measurement artifact (stale rc_facts probe boot time vs actual log mtime). The `DailyRotatingFileHandler.date.today()` is local-date NOT UTC; future log audits should use `date.today()` matching system local time as the day-boundary marker. The artifact is NOT a regression - the log destination is fine.
- The model tier audit ledger had drift since item 175: agent7 default is haiku-4-5 (NOT Sonnet); Sonnet only appears as POST-call telemetry stamps (`r._model = "claude-sonnet-4-6"`) in coaches/* coaches. Update ledger lineage going forward.
- The orchestrator-merge pattern is now 30 consecutive runs (items 134-177). Slice A agent independently caught + corrected 4 spec deviations + shipped the schema lift as forward-marker per the brief deviation-welcome clause.

**Carries forward:**
- (a) Item 176 carries unchanged EXCEPT (a)-relaxed: cc_conditional wave 19 state-tracking schema lift DONE; `parent_resource` field on spell form records is now the durable home for state-tracking metadata; the 6 wave-7 schema-lift carries are CLOSED.
- (a-bis) Item 176 carry (i) log destination FLAG CLOSED this session via Slice B verification.
- (b) DD Defy heal-on-takedown STILL deferred (operator-gated).
- (c) Live ARAM/SR smoke STILL pending (live-gated).
- (d) Calibrations STILL operator-gated (13 default condition probability midpoints + 67 per-entry probability values + `_MISSING_HP_SHARE_FOR_HEALS = 0.5` + `_CC_EFFECTIVENESS_FACTOR = 0.5`).
- (e) Legion 1-PC consolidation (s169 option B) STILL operator-gated.
- (f) cc_conditional wave 20+ candidates: registry shape is now fully primitive (primary + sidecar form-gated + coexists_with_unconditional flag + 13 condition tags + parent_resource forward-marker). Future growth needs either NEW Meraki schema field beyond cast_time + effects_descriptions + parent_resource OR re-audit of REJECT carries against the latest Meraki schema for candidates that surface without further schema lift. Operator-gated.
- (g) 542 residual U+2500 box-drawing chars NO LONGER carry-forward (done item 176).
- (h) v2.1 audit pages 9/10 Champ Select ARAM/Arena -> 11/12/13 Active Match SR/ARAM/Arena -> 14/15/16 PGR SR/ARAM/Arena (8 remaining; this session framing again non-UI).
- (i) Frozen-file grant NOT used this session.

# 2026-05-24 - item 176 SHIPPED: operator-gated parallel drain #11 (cc_conditional wave 18 FULL schema lift `coexists_with_unconditional` + Maokai R + Briar R ENGINE 1.55.0 + U+2500 box-drawing sweep on rc_supervisor.py + rc_self_monitor.py via frozen grant 542 -> 0 + BACKLOG/ROADMAP stale-sweep wave 20 CLEAN + cost/latency CLEAN wave 24) (4 commits + 2 merges `c066a8a` (Slice A merge `f5d3ac0`) + `0079f09` (Slice B merge `5a3430e`) + `2fb350f` (docs) pushed origin/main `face325..HEAD`; ENGINE 1.54.0 -> 1.55.0; DS :8893 killed pid 5168 + relaunched via schtasks -> serves 1.55.0; RC :8888 unchanged pid 5800 mode=client - DS engine + tools + tests + frozen byte-edits + docs only)

Operator triggered "in parallel : start all open items in Operator-gated, decision owed : when completed do commit + push and /done for /clear". 29th consecutive run using orchestrator-merge pattern (items 134-176). 3 worktree/investigative agents dispatched concurrent. AskUserQuestion 3-question scope fork pinned per [[feedback_scope_decision_cadence]]: (Q1) cc_conditional wave 18 FULL schema lift (operator picked FULL not Skip not Maokai-only); (Q2) 542 U+2500 box-drawing chars Grant + sweep (operator flipped from item 175's Skip verdict); (Q3) Housekeeping triple Full (Recommended). Pre-flight: 0 open PRs, all 5 CI runs green since item 175, 1 stale remote branch (worktree-agent-a4b1d99b2dc268fe4 = item 175 Slice A) confirmed fully merged via empty `git log origin/main..origin/<branch>` diff -> deleted via `git push origin --delete`. 19 local worktrees harness-locked (parent owns lifecycle, left in place per pattern).

**Slice A `c066a8a` (merge `f5d3ac0`) feat(ds) cc_conditional wave 18 FULL schema lift ENGINE 1.54.0 -> 1.55.0 (45 files / +1161 / -86):**
- NEW `coexists_with_unconditional: bool = False` field on `ConditionalCcEntry` + consumer-side MAX-rule semantics in `compute_cc_pressure()`. When True, declares same-spell-slot coexistence with unconditional entry in `_PER_SPELL_CC_DURATIONS`. Consumer credits MAX(unconditional_post_tenacity, conditional_post_probability_post_tenacity) per slot - never both summed. Backward-compat: wave 0-17 entries default False, byte-identical to ENGINE 1.54.0.
- SHIP **Maokai R Nature's Grasp distance-gated root** PRIMARY registry COND_RANGE_GATED prob 0.4 durations_s=(2.25,) `coexists_with_unconditional=True`. **FIRST consumer of COND_RANGE_GATED forward-marker tag since wave 7 schema lift** (closes wave 7 empty-registry contract for COND_RANGE_GATED). Maokai becomes 2-slot cc_conditional champion (Q wave 2 terrain + R wave 18 range_gated).
- SHIP **Briar R Certain Death Hematomania impact fear** PRIMARY registry COND_TARGET_DEBUFFED prob 0.5 durations_s=(1.5,) flat across 3 R ranks coexists=False (no unconditional Briar R). Briar becomes **SECOND 3-slot cc_conditional champion** after TahmKench (Q wave 4 + E wave 5 + R wave 18; first Briar R first-order CC registration anywhere).
- DEVIATION CAUGHT BY AGENT (validated): the 4 proposed state-tracking tags (COND_FURY_50 / COND_POSTR_PASSIVE / COND_TRANSFORMED / COND_FRENZY_ACTIVE) were REJECTED as redundant with existing COND_FRENZY_STATE which already covers all observed state-tracking-gated CC mechanics. Agent shipped Maokai R + Briar R using EXISTING tags with the new coexists_with_unconditional flag instead of adding 4 new tag constants. Smaller surface + same outcome.
- DEVIATION CAUGHT (validated): the 6 wave-7 schema-lift carries from prior items (Renekton W / Karma W form 1 / Hwei E form 1+2 / Neeko E) were re-audited and confirmed ALREADY SHIPPED in prior waves (9, 10). The orchestrator spec's "schema-lift carries" list was based on stale carries; the agent confirmed via Meraki effects_descriptions that no NEW state-tracking ships were needed. Aatrox R / Volibear R / Briar W REJECT re-verified (minion/monster-only fear / turret-only disable / self-buff frenzy respectively - no champion first-order CC).
- Math verification: Default `include_conditional=False` BYTE-IDENTICAL to 1.54.0 for ALL champions. Maokai SR include_conditional=True: total_cc_seconds = 3.7 (W unconditional 1.4 + R unconditional 2.0 + Q conditional 0.3 + R conditional MAX(unc 2.0, cond 0.9) = 2.0 wins -> R conditional contributes 0). Maokai operator override Maokai:R = 0.95 -> conditional 2.25 * 0.95 = 2.1375 > unconditional 2.0 -> conditional WINS. Total = 1.4 + 0.3 + 2.1375 = 3.8375. Briar SR include_conditional=True: total_cc_seconds = 1.55 (Q 0.3 + E 0.5 + R 0.75; no coexistence).
- Registry growth: 65 entries / 54 champs / 1.54.0 (58 primary + 7 sidecar) -> **67 entries / 54 champs / 1.55.0** (60 primary + 7 sidecar). Per-tag growth: COND_RANGE_GATED +1 (FIRST consumer, closes wave 7 forward-marker contract) + COND_TARGET_DEBUFFED +1. Tag count UNCHANGED at 13.
- ENGINE_VERSION 1.54.0 -> 1.55.0 in `__init__.py` with full changelog block + bulk pin sync across 32 DS test files via regex rewrite.
- **+32 tests** in NEW `agents/daemon_slayer/tests/test_cc_conditional_wave18.py` covering per-entry shape pins + schema-lift invariants + no-double-count MAX-rule math + tag consumer count pins + per-entry override behavior + ENGINE pin.
- Test relaxations required (wave-N tests invalidated by wave 18): test_cc_conditional_wave2.py Maokai aggregator -> assertGreaterEqual / test_cc_conditional_wave5.py Briar aggregator -> assertGreaterEqual / test_cc_conditional_wave7_tags.py COND_RANGE_GATED zero-consumer assertion replaced with proper-shape consumer check / test_cc_conditional_wave12-17.py range_gated_still_zero relaxed assertEqual(0) -> assertLessEqual(1) / test_cc_conditional_wave17.py marker pin restored to "ENGINE 1.54.0" after over-eager bulk rename swept its own narrative.
- `test_cc_conditional_forward_marker.py _ALLOWED_TEST_FILES` extended with `test_cc_conditional_wave18.py`.

**Slice B `0079f09` (merge `5a3430e`) chore(frozen) U+2500 box-drawing sweep on rc_supervisor.py + rc_self_monitor.py via item 176 frozen grant (4 files / +359 / -14):**
- NEW `tools/strip_u2500.py` (208 LOC): reads file as bytes, replaces UTF-8 sequence for U+2500 (`\xe2\x94\x80`) with ASCII `-` (0x2D); atomic write via `tmp.write_bytes()` + `os.replace()`; `--allow-frozen <comma-csv>` flag (mirrors tools/strip_smart_quotes.py + tools/repair_mojibake.py from items 154-156); empty `_HARD_SKIP_FROZEN: frozenset[str] = frozenset()` defense-in-depth constant.
- DEVIATION CAUGHT (validated): spec said "walks repo with same exclusions as tools/strip_em_dashes.py" but a repo-wide walk would corrupt 207+ non-frozen files with ~54k intentional U+2500 ASCII-art chars (U+2500 is NOT a CLAUDE.md hard-rule banned codepoint). Agent changed the tool to REQUIRE `--allow-frozen` as an explicit allowlist (no implicit walk). Matches operator intent (sweep only the 2 granted files) without corrupting intentional art elsewhere.
- Per-file pre/post counts verified: ops/rc_supervisor.py 58 -> 0; ops/rc_self_monitor.py 484 -> 0; total 542 -> 0 (matches probe exactly).
- Tree-drawing semantics preserved 1:1 (each U+2500 -> single ASCII `-`, monospace-equivalent width; section headers like `# -- Section --------` read identically post-sweep).
- NEW drift guard `tests/test_u2500_hygiene.py` (137 LOC, 6 tests): scoped to `_ASSERTED_CLEAN = {ops/rc_supervisor.py, ops/rc_self_monitor.py}` frozenset (matches the spec's secondary "Pin behavior: rc_supervisor.py + rc_self_monitor.py specifically asserted clean" requirement). 6/6 PASS.
- `py -m py_compile ops/rc_supervisor.py ops/rc_self_monitor.py` clean; `py -c "import ops.rc_supervisor"` + `py -c "import ops.rc_self_monitor"` clean.

**Slice C 24th consecutive cost/latency CLEAN no-commit (read-only investigative agent) + BACKLOG/ROADMAP stale-sweep wave 20:**
- All 7 levers green. Prompt-cache 8 sites unchanged. Route TTL 16 routes with `_CACHE` constant (live count fluctuates 12-16 per item 174 don't-redo; loose ledger drift, NOT regression). Polling cadences tightest network 2000ms (pollIfStale + pollLcu); no sub-500ms network polls. Log spam: today's `logs/2026-05-24.log` spans 15:52-17:51 only (pre-pid-5800 boot at 20:23:23) - no log file written since current pid started; FLAG (informational, non-blocking) that log destination may have rotated; `_SUPPRESS_LOG_PATHS` tuple in dashboard/_handler.py:74-83 is 9 entries unchanged. Model tier all active coaches `messages.create()` use claude-haiku-4-5-20251001 (Sonnet POST-call telemetry stamps only; Opus only agents/_supervisor_common.py L46 routing to agent6_auditor). Scheduled tasks 14 RC-* matching item 175 catalog exactly. Bundle parity 27 panel CSS files = 27 dashboard.css panel @imports (drift guard test `tests/test_dashboard_css_panel_imports_parity.py` 4/4 PASSES). 
- BACKLOG/ROADMAP stale-sweep wave 20 = **0 flips**. All 6 file:line citations from item 175's wave 19 audit grep-verified live (dev.js:361 + main.js:3081/3092/4281 + gamepc_lcu_agent.py:246 + :1194).
- Sweep cycle decay: wave 1=2 / 2=3 / 3=3 / 4-12=1 / 13=0 / 14=3 / 15=2 / 16=2 / 17=0 / 18=1 / 19=0 / **20=0**. Saturation confirmed.

**Docs sync `2fb350f` (6 files / 8 ins / 8 del):**
- ENGINE 1.54.0 -> 1.55.0 + 4609 -> 4641 tests + 65/54 waves 0-17 -> 67/54 waves 0-18 + wave 18 closure note across docs/DAEMON_SLAYER.md L5+L32 + README.md L46 + BRIEF.md L20+L26 + docs/ARCHITECTURE.md L161 (2 edits) + BACKLOG.md L13 (3 edits) + ROADMAP.md L165.
- Skipped per [[feedback_no_history_rewrite]]: BRIEF.md L33 milestone narrative + L57 resume-pitch.

**Verified post-merge + DS restart:**
- DS suite **4641 passed / 1 skipped / 1 xfailed / 1764 subtests** (+32 over 4609 baseline = exactly the wave 18 test file).
- RC suite (excl phase8_smoke) **3297 passed / 67 subtests** (+6 over 3291 baseline = exactly the new u2500_hygiene test file).
- `tests/phase8_smoke/` = **75/75 PASS** post-DS-restart.
- `py -m ruff check .` ALL CHECKS PASSED.
- DS :8893 killed pid 5168 + `schtasks /Run /TN RC-DaemonSlayer` (per [[reference_ds_server_not_supervisor_watched]]) -> /health engine_version=1.55.0 patch=16.10.1 champions=172 items=705.
- RC :8888 unchanged pid 5800 mode_key=None alive=True last_reload_ok=True (no route/coach edits this run; DS engine + tools + tests + frozen byte-edits + docs only; supervisor edits take effect on next supervisor restart which operator can choose to do).

**Merge order:** Slice A merged into main FIRST as `f5d3ac0` (worktree branch `worktree-agent-acc267b7cba43b44c`, ort, 0 conflicts, 45 files). Slice B merged into main SECOND as `5a3430e` (worktree branch `worktree-agent-a63db57c34a7322ed`, ort, 0 conflicts, 4 files). Docs sync committed direct to main THIRD as `2fb350f` (6 files / 8 ins / 8 del). 0 merge conflicts across all 3 slices. Slice C produced no commits.

**Don't-redo:**
- The `coexists_with_unconditional: bool = False` flag + consumer-side MAX-rule is the canonical home for same-spell-slot conditional-vs-unconditional coexistence. Future cc_conditional waves needing this pattern should set `coexists_with_unconditional=True` on the entry; the consumer math automatically takes MAX per slot - no double-count. This is the LIGHTEST schema lift possible (one bool field + one if-branch in the aggregator) and preserves wave 0-17 byte-identical behavior.
- Maokai R FIRST consumer of COND_RANGE_GATED closes the wave 7 schema-lift forward-marker contract. The tag had been registered with midpoint 0.4 since wave 7 (item 148) with empty registry; it took until wave 18 to find a candidate that fit the schema + the coexistence machinery. Future distance-gated CC entries can reuse COND_RANGE_GATED + the coexists flag without re-pitching either schema.
- Briar is now the SECOND 3-slot cc_conditional champion after TahmKench (Q wave 4 + E wave 5 + R wave 18). Multi-slot expansions remain unconstrained by registry shape.
- The 4 proposed state-tracking tags (COND_FURY_50 / COND_POSTR_PASSIVE / COND_TRANSFORMED / COND_FRENZY_ACTIVE) were correctly REJECTED as redundant with COND_FRENZY_STATE. Future wave 19+ should NOT re-pitch them without operator approval; the COND_FRENZY_STATE midpoint 0.4 already encodes the time-fraction the empowering state is active.
- The Maokai R duration was sourced from Meraki effects_descriptions; the unconditional Maokai R entry already encodes mid-distance root (1.2, 1.6, 2.0)s; the conditional COND_RANGE_GATED entry encodes additional far-distance behavior at 2.25s + 0.4 probability. The MAX-rule consumer means the unconditional 2.0 wins by default (default operator probability midpoint 0.4 * 2.25s = 0.9 < 2.0); only if operator overrides up (e.g. 0.95) does the conditional contribute more. This is the intended calibration semantic.
- Slice B's `tools/strip_u2500.py` REQUIRES `--allow-frozen <csv-paths>` flag - it does NOT walk the repo. U+2500 is NOT a CLAUDE.md hard-rule banned codepoint; it's intentional ASCII-art in 207+ non-frozen files. The agent's deviation from the spec was correct and validated.
- The `_ASSERTED_CLEAN` frozenset in `tests/test_u2500_hygiene.py` is the canonical home for future frozen-file U+2500 sweeps - extend the set if more files are granted; never assert clean on a file that hasn't been swept.
- The orchestrator-merge pattern is now 29 consecutive runs (items 134-176). Slice A's agent independently caught + corrected 2 spec deviations (rejected the 4 state-tracking tags + confirmed the 6 wave-7 carries already shipped); the "first-attempt success" + "agent self-correction" pattern continues.

**Carries forward:**
- (a) All item 175 carries unchanged EXCEPT (a)-relaxed: cc_conditional wave 18 FULL schema lift DONE; the `coexists_with_unconditional` flag + MAX-rule consumer semantics is now the durable home for same-spell-slot coexistence; Maokai R + Briar R NO LONGER schema-blocked. (b)-relaxed: 542 U+2500 box-drawing chars NO LONGER carry-forward (DONE this session via frozen grant).
- (b) DD Defy heal-on-takedown STILL deferred.
- (c) Live ARAM/SR smoke STILL pending.
- (d) Calibrations STILL operator-gated (13 default condition probability midpoints + 67 per-entry probability values + `_MISSING_HP_SHARE_FOR_HEALS = 0.5` + `_CC_EFFECTIVENESS_FACTOR = 0.5`).
- (e) Legion 1-PC consolidation STILL operator-gated.
- (f) cc_conditional wave 19+ candidates STILL UNDEFINED - the current-schema lane + coexistence machinery are both saturated for what Meraki effects_descriptions exposes; further growth needs either (1) a state-tracking extractor lift (Fury/passive-flag/form-empowered) to register the COND_FRENZY_STATE consumers beyond Renekton W + Karma W form 1 + Gnar W form 1, or (2) re-audit of REJECT carries from waves 11-17 against latest Meraki schema for new candidates that surface without schema lift. Both operator-gated.
- (g) v2.1 audit pages 9/10 Champ Select ARAM/Arena -> 11/12/13 Active Match SR/ARAM/Arena -> 14/15/16 PGR SR/ARAM/Arena (8 remaining; this session's framing again non-UI).
- (h) Frozen-file grant USED this session for ops/rc_supervisor.py + ops/rc_self_monitor.py U+2500 sweep; NOT used for any other frozen file.
- (i) Slice C FLAG: today's `logs/2026-05-24.log` rotated/stopped at 17:51 while current RC pid 5800 started at 20:23:23 - log destination may have moved; worth verifying log file path in a separate audit pass (informational, non-blocking).

---
# 2026-05-24 - item 175 SHIPPED: operator-gated parallel drain #10 (cc_conditional wave 17 COND_TRAVERSE tag schema lift + Taliyah E ENGINE 1.54.0 + BACKLOG stale-sweep wave 19 CLEAN + cost/latency CLEAN wave 23) (3 commits + 1 merge `3fa56a1` (merge) + `a8847f1` (docs) pushed origin/main `92fb056..a8847f1`; ENGINE 1.53.0 -> 1.54.0; DS :8893 restarted pid 12264 -> serves 1.54.0; RC :8888 unchanged pid 5800 mode=client - DS engine + docs only)

Operator triggered "in parallel : start all open items in Operator-gated, decision owed : when completed do commit + push and /done for /clear". 28th consecutive run using orchestrator-merge pattern (items 134-175). 3 worktree/investigative agents dispatched concurrent. AskUserQuestion 3-question scope fork pinned per [[feedback_scope_decision_cadence]]: (Q1) cc_conditional wave 17 small lift COND_TRAVERSE + Taliyah E only (Recommended); (Q2) 542 residual U+2500 box-drawing chars Skip - intentional docstring tree-drawing (Recommended); (Q3) Housekeeping triple Full (Recommended). Pre-flight: 0 open PRs, all 5 CI runs green since item 174, 1 stale remote branch (worktree-agent-ad9b284de92b11e8b = item 174 slice A) confirmed fully merged via empty `git log origin/main..origin/<branch>` diff -> deleted via `git push origin --delete`. 17 local worktrees harness-locked (parent owns lifecycle, left in place per pattern).

**Slice A `3fa56a1` (merge into main) feat(ds) cc_conditional wave 17 COND_TRAVERSE tag schema lift + Taliyah E ENGINE 1.53.0 -> 1.54.0 (36 files / +819 / -33):**
- NEW `COND_TRAVERSE = "cond_traverse"` condition tag constant in `agents/daemon_slayer/cc_conditional.py` alongside existing 12 tag constants (was 12 tags; now 13). Midpoint probability 0.3 in `_DEFAULT_CONDITION_PROBABILITY` (parallel to COND_TERRAIN's 0.3 - both gate on champion behavior near map geometry/spell zones).
- SHIP **Taliyah E Unweaver's Wall** primary registry COND_TRAVERSE prob 0.3: 0.75s knockup when enemy champion crosses through/over the wall (FIRST consumer of new COND_TRAVERSE tag; multi-wave coexistence with Taliyah W wave 1 - Taliyah becomes 2-slot cc_conditional champion).
- Duration verified via Meraki effects_descriptions verbatim: "stunned for 0.75 seconds, increased to 2 seconds if they are a monster" (champion = 0.75s flat across all 5 E ranks; monster value encoded as monster-only - not first-order champion CC).
- DEVIATION FROM SPEC: Slice A worktree agent correctly caught that (a) Taliyah is NOT net-new (already in registry via W wave 1) so REGISTRY_TOTAL_CHAMPIONS stays at 54 NOT 55; (b) duration is 0.75s NOT 1.0s per Meraki source-of-truth. The orchestrator's spec was wrong on both counts; the agent's deviations are validated and correct.
- Registry: 64 entries / 54 champs (57 primary + 7 sidecar) -> 65 entries / 54 champs (58 primary + 7 sidecar). Per-tag growth: COND_TRAVERSE +1 (FIRST consumer of new tag).
- +60 tests in NEW `agents/daemon_slayer/tests/test_cc_conditional_wave17.py`. ENGINE_VERSION 1.53.0 -> 1.54.0 + bulk pin sync across 31 DS test files. `test_cc_conditional_forward_marker.py _ALLOWED_TEST_FILES` extended with `test_cc_conditional_wave17.py`. `test_cc_conditional.py::DefaultProbabilityMapCoverageTests.expected_keys` set extended 12 -> 13 tags (NEW COND_TRAVERSE).
- Default `compute_cc_pressure("Taliyah", include_conditional=False)` BYTE-IDENTICAL to 1.53.0 (base = 0.0 unchanged; True opts in 0.225 = 0.75 * 0.3).

**Slice B CLEAN no-commit (BACKLOG/ROADMAP stale-sweep wave 19):**
- 0 flips. All 6 file:line citations in OPEN items grep-verified live: ROADMAP L13 `dev.js:361` verdict.team_won + L23 `main.js:3081/3092/4281` LCU 3 sites + `gamepc_lcu_agent.py:246` ARAM Mayhem 2400 + L82 `tools/gamepc_lcu_agent.py:1194` augment_intent_unsupported. All other file:line refs (8 hits) were under SHIPPED entries / milestone narrative / shipped-item carry-forwards and intentionally left alone per [[feedback_no_history_rewrite]].
- Sweep cycle decay: 1=2 / 2=3 / 3=3 / 4-12=1 / 13=0 / 14=3 / 15=2 / 16=2 / 17=0 / 18=1 / **19=0**. Item 174 wave 18's lone flip (`gamepc_lcu_agent.py:1091` -> `:1194`) holds; no subsequent line drift.

**Slice C 23rd consecutive cost/latency CLEAN no-commit (read-only investigative agent):**
- All 7 levers green. Prompt-cache 8 sites unchanged. Route TTL 12 routes with module-level `_CACHE` constant (matches item 174 verdict; the 12-16 fluctuation is loose ledger drift, not regression). Polling cadences tightest network 2000ms (pollIfStale + pollLcu); no sub-500ms network polls. Log spam top non-suppressed `/api/bridge` 0.132/sec (identical to item 174 baseline); `/api/minimap-crop` + `/api/activity` confirmed 0/sec post item 171 trailing-space fix; all under 1/sec hard threshold; 9-entry suppression tuple unchanged. Model tier all active coach `messages.create()` callers use claude-haiku-4-5-20251001 + Sonnet only in agents/agent7_context/warm_session.py + Opus only agent6_auditor. Scheduled tasks 14 RC-* matching item 173/174 catalog exactly. Bundle parity 27 panel CSS files = 27 dashboard.css panel @imports (drift guard test `tests/test_dashboard_css_panel_imports_parity.py` 4/4 PASSES per item 174).
- Slice C also confirmed pid 5800 actual boot = 2026-05-24T15:23:23 local (the session-start `rc_facts.py` probe was stale "2026-05-20T14:35:48"; live process started today).

**Docs sync `a8847f1` (6 files / 8 ins / 8 del):**
- ENGINE 1.53.0 -> 1.54.0 + 4549 -> 4609 tests + 64/54 waves 0-16 -> 65/54 waves 0-17 + 12 -> 13 condition tags (COND_TRAVERSE added) + wave 17 closure note across docs/DAEMON_SLAYER.md L5+L32 (4 edits) + README.md L46 + BRIEF.md L20+L26 + docs/ARCHITECTURE.md L161 (3 edits) + BACKLOG.md L13 (3 edits) + ROADMAP.md L165.
- Skipped per [[feedback_no_history_rewrite]]: BRIEF.md L33 milestone narrative + L57 resume-pitch.

**Verified post-merge + DS restart:**
- DS suite **4609 passed / 1 skipped / 1 xfailed / 1762 subtests** (+60 over 4549 baseline = exactly the wave 17 test file).
- RC suite (excl phase8_smoke) **3291 passed / 67 subtests** (unchanged from item 174; engine change invisible to RC route layer until DS restart).
- `tests/phase8_smoke/` = **75/75 PASS** post-DS-restart.
- `py -m ruff check .` ALL CHECKS PASSED.
- `py -m py_compile` clean on all touched files.
- DS :8893 killed pid 12264 + `schtasks /Run /TN RC-DaemonSlayer` (per [[reference_ds_server_not_supervisor_watched]]) -> /health engine_version=1.54.0 patch=16.10.1 champions=172 items=705.
- RC :8888 unchanged pid 5800 mode=client alive=True (no route/coach edits this run; DS engine + docs only).

**Merge order:** Slice A merged into main FIRST as `3fa56a1` (worktree branch `worktree-agent-a4b1d99b2dc268fe4`, ort, 0 conflicts, 36 files). Docs sync committed direct to main SECOND as `a8847f1` (6 files / 8 ins / 8 del). 0 merge conflicts. Slice B + C produced no commits.

**Don't-redo:**
- COND_TRAVERSE midpoint 0.3 is calibrated parallel to COND_TERRAIN's 0.3 - both gate on champion behavior near map geometry/spell zones. Future tag additions for "champion proximity to spell-cast zone" mechanics should reuse COND_TRAVERSE before lifting yet another tag.
- Taliyah is now a 2-slot cc_conditional champion (W wave 1 + E wave 17); previously KSante was the most recent 2-slot champ added (wave 16). TahmKench remains the only 3-slot champ (wave 13 closure).
- The Meraki effects_descriptions field is the authoritative source for CC durations - the orchestrator's spec MUST be verified against the field before claiming a duration value. Slice A's agent correctly caught both spec deviations (Taliyah not net-new + 0.75s not 1.0s) by reading the schema directly.
- The expected_keys set in `test_cc_conditional.py::DefaultProbabilityMapCoverageTests` is now 13 tags; future tag additions MUST extend this set or the schema invariant test fails. Slice A agent caught this pin and extended it correctly.
- The orchestrator-merge pattern is now 28 consecutive runs (items 134-175). The 27-item streak's "first-attempt success" verdict continues; the wave 17 spec had 2 minor inaccuracies but the agent self-corrected without orchestrator intervention.

**Carries forward:**
- (a) All item 174 carries unchanged EXCEPT (a)-relaxed: cc_conditional wave 17 DONE; COND_TRAVERSE no longer "operator-gated tag schema lift"; Taliyah E NO LONGER schema-blocked.
- (b) DD Defy heal-on-takedown STILL deferred.
- (c) Live ARAM/SR smoke STILL pending.
- (d) Calibrations STILL operator-gated (13 default condition probability midpoints + 65 per-entry probability values + `_MISSING_HP_SHARE_FOR_HEALS = 0.5` + `_CC_EFFECTIVENESS_FACTOR = 0.5`).
- (e) Legion 1-PC consolidation STILL operator-gated.
- (f) cc_conditional wave 18+ candidates: Maokai R distance-gated (NEEDS same-spell-slot coexistence schema lift - operator-gated registry schema lift) + 6 wave-7 schema-lift carries (Renekton W Fury / Aatrox post-R passive / Volibear R passive / Briar W frenzy / multi-form Karma+Hwei+Neeko) STILL operator-gated. The current-schema candidate lane is now saturated; further growth needs a registry shape change.
- (g) 542 residual U+2500 box-drawing chars carry forward as operator-gated separate sweep (NEEDS rc_supervisor.py + rc_self_monitor.py frozen-file grant - NOT used this session per Q2 fork).
- (h) v2.1 audit pages 9/10 Champ Select ARAM/Arena -> 11/12/13 Active Match SR/ARAM/Arena -> 14/15/16 PGR SR/ARAM/Arena (8 remaining; this session's framing again non-UI).
- (i) Frozen-file grant NOT used this session.

---
# 2026-05-24 - item 174 SHIPPED: operator-gated parallel drain #9 (cc_conditional wave 16 ENGINE 1.53.0 + BACKLOG stale-sweep wave 18 + L31 round 6 SATURATED + cost/latency CLEAN wave 22 + RC test pin fix for wave 16) (4 commits + 1 merge `9e16584` `45955fc` `66dda6d` `2ac7147` pushed origin/main `9c1cb22..2ac7147`; ENGINE 1.52.0 -> 1.53.0; DS :8893 restarted pid 14312 -> serves 1.53.0; RC :8888 unchanged pid 5800 - DS engine + docs + 1 RC test fix only)

Operator triggered "in parallel : start all open items in Operator-gated, decision owed : when completed do commit + push and /done for /clear". 27th consecutive run using orchestrator-merge pattern (items 134-174). 3 worktree agents dispatched concurrent. No question-fork (carries clearly enumerated in item 173 (a)-(i)). Pre-flight: 0 open PRs, all CI green since item 172, 2 stale remote worktree branches (a515+ae88) confirmed fully merged via empty diff vs origin/main -> deleted.

**Slice A `45955fc` (merge into main) feat(ds) cc_conditional wave 16 ENGINE 1.52.0 -> 1.53.0 (36 files / 1175 ins / 37 del):**
- Re-audit of REJECT carries from prior waves against latest Meraki schema (cast_time + effects_descriptions + damage_blocks). 4 ship candidates surface WITHOUT requiring schema lifts.
- SHIP **Garen Q Decisive Strike** primary registry COND_NTH_HIT prob 0.7: 1.5s silence on empowered-AA (FIRST Garen first-order CC anywhere).
- SHIP **Syndra E Scatter the Weak** primary registry COND_TARGET_DEBUFFED prob 0.5: 1.25s Dark-Sphere knockback stun (FIRST Syndra first-order CC anywhere).
- SHIP **Udyr E Blazing Stampede** primary registry COND_NTH_HIT prob 0.7: 0.75s empowered-AA pounce stun (FIRST Udyr first-order CC anywhere).
- SHIP **KSante W Path Maker** primary registry COND_CHANNEL_COMPLETION prob 0.5: 1.0s recast stun midpoint (0.5-1.75s range; multi-wave coexistence with KSante Q wave 1).
- 7 REJECT verdicts: Ahri W (no W CC), Aphelios R (shipped wave 13 as Q form3 sidecar), Darius E (unconditional pull-displacement), Irelia R (displacement+slow only), LeeSin R (carries from waves 13/14/15), Milio R (cleanse+tenacity only), Taliyah E (needs NEW COND_TRAVERSE tag - operator-gated).
- Registry: 60/51 (53 primary + 7 sidecar) -> 64/54 (57 primary + 7 sidecar). Per-tag growth: COND_NTH_HIT +2, COND_TARGET_DEBUFFED +1, COND_CHANNEL_COMPLETION +1.
- +84 tests in NEW `agents/daemon_slayer/tests/test_cc_conditional_wave16.py`. ENGINE_VERSION 1.52.0 -> 1.53.0 + bulk pin sync across 31 DS test files. `test_cc_conditional_forward_marker.py _ALLOWED_TEST_FILES` extended. `test_cc_conditional_wave1.py` KSante assertions relaxed for multi-wave coexistence (parallel to wave 15 Ornn relaxation).
- Default `compute_cc_pressure(include_conditional=False)` BYTE-IDENTICAL to 1.52.0 for all 4 candidates.

**Slice B `9e16584` (committed direct to main pre-Slice-A) docs(roadmap) BACKLOG/ROADMAP stale-sweep wave 18 (1 file / 1 ins / 1 del):**
- 1 flip: ROADMAP.md L82 `tools/gamepc_lcu_agent.py:1091` -> `:1194` (live grep: `return {"ok": False, "err": "augment_intent_unsupported"` at L1194; drifted +103 from item 156 anchor).
- 5 other open-item paths grep-verified live (main.js:3081/3092/4281 + gamepc_lcu_agent.py:246 + dev.js:361). Per `feedback_no_history_rewrite`: shipped historical paths NOT touched.
- Sweep cycle decay: 1=2 / 2=3 / 3=3 / 4-12=1 / 13=0 / 14=3 / 15=2 / 16=2 / 17=0 / **18=1**.
- Also Slice B did read-only 22nd consecutive cost/latency CLEAN sweep (7 levers green; /api/bridge 0.132/sec top non-suppressed; minimap-crop + activity at 0/sec confirming item 171 trailing-space fix works; 14 RC-* scheduled tasks; 27=27 panel CSS parity).

**Slice C L31 type annotations round 6 SATURATED (no commit):**
- Surfaces checked: tools/ + vision_server/ + ops/_non_frozen + scripts/. tools/ + vision_server/ + ops/_non_frozen = 0 public unannotated defs (rounds 1-5 saturated). scripts/ = ~70 sites across 9 ad-hoc data pipelines (retrofill_match_metrics + rewind_scraper + data_pipeline + discover_champion_codes + probe_missing_codes + team_planner_sync + patch_champion + fetch_cdragon_pbe + audit_ddragon_items) - SKIPPED per item 173 don't-redo "scripts/ ad-hoc data pipelines retrofills skipped per constraint".
- Verdict consistent with item 173 saturation note. No commit.

**RC test pin fix `66dda6d` fix(tests) cc_conditional_pressure - swap Garen for Veigar post-wave-16 (1 file / 6 ins / 4 del):**
- Slice A's wave 16 Garen Q landing invalidated `tests/test_routes_cc_conditional_pressure.py::MathTests::test_zero_cc_both_sides_returns_balanced_warn` which used Garen+Caitlyn as "unconditional-only at patch 16.10.1". Body returned tier=bad instead of warn.
- Fix: swap Garen for Veigar (mage outside cc_conditional registry). Updated docstring with wave-16 invalidation marker mirroring test author's wave-3 Aatrox marker.
- Caitlyn + Veigar + Annie + Galio all confirmed outside 54-champ cc_conditional registry.

**Docs sync `2ac7147` (6 files / 8 ins / 8 del):**
- ENGINE 1.52.0 -> 1.53.0 + 4465 -> 4549 tests + 60/51 waves 0-15 -> 64/54 waves 0-16 + wave 16 closure note across docs/DAEMON_SLAYER.md L5+L32 + README.md L46 + BRIEF.md L20+L26 + docs/ARCHITECTURE.md L161 + BACKLOG.md L13 + ROADMAP.md L165.

**Verified post-merges + DS restart:**
- DS suite **4549 passed / 1 skipped / 1 xfailed / 1761 subtests in 67.43s** (+84 over 4465 baseline = exactly wave 16 test file).
- RC suite (excl phase8_smoke) **3291 passed / 67 subtests in 56.16s** post-test-pin-fix (1 failure pre-fix on Garen + Caitlyn pin).
- tests/phase8_smoke/ = **75/75 PASS** post-DS-restart.
- `py -m ruff check .` ALL CHECKS PASSED.
- DS :8893 killed pid 14312 + `schtasks /Run /TN RC-DaemonSlayer` -> serves engine_version=1.53.0 patch=16.10.1 champions=172 items=705.
- RC :8888 unchanged pid 5800 (no route/coach edits this run).

**Merge order:** Slice B committed direct to main FIRST `9e16584` (pre-Slice-A; 1 file). Slice A merged into main SECOND `45955fc` (worktree branch `worktree-agent-ad9b284de92b11e8b`, ort, 0 conflicts, 36 files). RC test pin fix THIRD `66dda6d` (1 file, direct commit). Docs sync FOURTH `2ac7147` (6 files / 8 ins / 8 del). 0 merge conflicts across all slices.

**Don't-redo:**
- Wave 16 candidates Garen Q + Syndra E + Udyr E + KSante W are first-order CC entries for 3 net-new champs + 1 multi-wave coexistence. Future wave 17+ should target the remaining REJECT carries that DO NOT need schema lift (Taliyah E NEEDS new COND_TRAVERSE tag - operator-gated).
- The RC test pin fix is the CANONICAL gotcha for cc_conditional wave landings: tests/test_routes_cc_conditional_pressure.py uses specific champion examples that go stale when waves land. Future waves landing first-order CC on Annie/Galio/Caitlyn/Veigar/Brand/Mordekaiser/TwistedFate would similarly require test pin updates.
- KSante now has 2-slot cc_conditional coverage (Q wave 1 + W wave 16); previously TahmKench was the only 3-slot champ (wave 13).
- The orchestrator-merge pattern is now 27 consecutive runs (items 134-174).
- L31 type annotations is SATURATED across orchestrator-easy surfaces (rounds 1-5 closed coaches/+dashboard/+core/+tft/+lcu/+coach_integration/+agents/+vision_server/+ops/_non_frozen/+tools/_libraries/+scripts/_entrypoints/). Round 6 confirmed tools/ + vision_server/ + ops/ fully saturated; scripts/ remains operator-gated.
- Slice B's 1-flip BACKLOG sweep on wave 18 shows the lane re-grows by ~1 flip per cc_conditional wave (line drift in `tools/gamepc_lcu_agent.py` across the L31 rounds). Continue periodic sweeps every 2-3 runs.

**Carries forward:**
- (a) All item 173 carries unchanged EXCEPT (a)-relaxed: cc_conditional wave 16 DONE; Garen Q + Syndra E + Udyr E + KSante W NO LONGER schema-blocked.
- (b) DD Defy heal-on-takedown STILL deferred.
- (c) Live ARAM/SR smoke STILL pending.
- (d) Calibrations STILL operator-gated.
- (e) Legion 1-PC consolidation STILL operator-gated.
- (f) cc_conditional wave 17+ candidates: Taliyah E NEEDS new COND_TRAVERSE tag (operator-gated) + Maokai R distance-gated (NEEDS same-spell-slot coexistence schema lift) + 6 wave-7 schema-lift carries (Renekton W Fury / Aatrox post-R passive / Volibear R passive / Briar W frenzy / multi-form Karma+Hwei+Neeko) STILL operator-gated.
- (g) 542 residual U+2500 box-drawing chars carry forward as operator-gated separate sweep (NEEDS rc_supervisor.py + rc_self_monitor.py frozen-file grant).
- (h) v2.1 audit pages 9/10 Champ Select ARAM/Arena -> 11/12/13 Active Match SR/ARAM/Arena -> 14/15/16 PGR SR/ARAM/Arena (8 remaining; this session's framing again non-UI).
- (i) Frozen-file grant NOT used this session.

---
# 2026-05-24 - item 173 SHIPPED: operator-gated parallel drain #8 (cc_conditional wave 15 ENGINE 1.52.0 + L31 type annotations round 5 + cost/latency CLEAN wave 21 + BACKLOG stale-sweep wave 17) (3 commits + 2 merges pushed origin/main; ENGINE 1.51.0 -> 1.52.0; DS :8893 restarted pid 13492 -> serves 1.52.0; RC :8888 unchanged pid 5800 - DS engine + docs only)

Operator triggered "in parallel : start all open items in Operator-gated, decision owed : when completed do commit + push and /done for /clear". 26th consecutive run using orchestrator-merge pattern (items 134-173). 3 worktree agents dispatched concurrent. No question-fork (operator framed scope; carries clearly enumerated in item 172 (a)-(i)). Pre-flight: 0 open PRs, 3 green CI runs since item 172 ruff fix, 13 stale locked worktrees (harness-owned).

**Slice A `2129e6c` (merge into main) feat(ds) cc_conditional wave 15 ENGINE 1.51.0 -> 1.52.0 (36 files / 1198 ins / 35 del):**
- Re-audit of REJECT carries from waves 11-14 with the NEW Meraki `cast_time` field (item 172 schema lift) + targeted effects_descriptions sweep.
- SHIP **Zac Q Stretching Strikes** primary registry COND_NTH_HIT prob 0.7: 0.5s root when 2nd strike lands on DIFFERENT target than 1st (first Zac first-order CC anywhere).
- SHIP **Ornn E Searing Charge** primary registry COND_TERRAIN prob 0.3: 1.25s stun on terrain collision. **FIRST consumer of COND_TERRAIN forward-marker tag (since wave 7 schema lift)**. Multi-wave coexistence with wave 4 Ornn Q.
- SHIP **Rell W form_index=0 Ferromancy Crash Down** sidecar registry COND_CHANNEL_COMPLETION prob 0.5: 0.8s stun after 0.625s leap cast_time (first Rell first-order CC anywhere).
- 22 REJECT verdicts (minion-only / unconditional CC / positional sub-zone / state-tracking schema-blocked / knockback not in schema). Maokai R same-spell-slot coexistence machinery NOT touched (operator-gated separately).
- Registry: 57/49 (51 primary + 6 sidecar) -> 60/51 (53 primary + 7 sidecar). Per-tag growth: COND_NTH_HIT +1, COND_TERRAIN +1 (first consumer), COND_CHANNEL_COMPLETION +1.
- +79 tests in NEW `agents/daemon_slayer/tests/test_cc_conditional_wave15.py`. ENGINE_VERSION 1.51.0 -> 1.52.0 + 31 stale ENGINE pin syncs across DS test files via bulk regex rewrite. test_cc_conditional_forward_marker.py allowlist extended. test_cc_conditional_wave1.py Ornn test relaxed for multi-wave coexistence.
- Default `compute_cc_pressure(include_conditional=False)` BYTE-IDENTICAL to 1.51.0 for all 3 ship-candidates (Zac=2.0 / Ornn=0.5 / Rell=1.0 unchanged).

**Slice B `ef1dfb5` (merge into main) chore(types) L31 type annotations round 5 (5 files / 23 sites / 23 ins / 23 del):**
- 23 surgical sites: tools/gamepc_lcu_agent.py 11 (read_lockfile, ensure_lcu_conn, lcu_request, capture_state, execute_command, auto_features, post, get, post_team_context_refresh, post_last_match_ingest, loop) + tools/dev_cli.py 9 (8 cmd_* + main get -> int CLI exit codes; cmd_perf + cmd_rollback_last param-typed) + tools/run_phase2_perf.py 1 (main -> int) + tools/extract_panels.py 1 (L helper) + tools/ds_cond_inspect.py 1 (show).
- 0 ruff violations / 0 frozen-file touches. Skipped private _FakeX stub classes in run_phase2_perf.py per spec.

**Slice C cost/latency CLEAN wave 21 + BACKLOG stale-sweep wave 17 (read-only, no commit):**
- Slice C initial DRIFT FLAG verdict REJECTED on verification: L6 wmic call was broken (`Get-ScheduledTask RC-*` shows 14 RC-* tasks intact); L4 measured cumulative log including pre-restart pid - post-restart pid 5800 (started 15:23:23) shows 0 minimap-crop + 0 activity + 0 ward-heat hits (item 171 fix works); L2 12 routes with `_CACHE` constant (item 171 ledger pin; item 172's "16" claim was loose drift); L5 top sample shows all haiku in coaches/. Cost-trace 11 wired sites confirmed.
- Effective verdict: **21st consecutive CLEAN** since item 134.
- BACKLOG stale-sweep wave 17 = 0 flips. Sweep cycle decay: wave 1=2 / 2=3 / 3=3 / 4-12=1 / 13=0 / 14=3 / 15=2 / 16=2 / **17=0**. Saturation again at items 134-173 baseline.

**Docs sync `b260a37`:** 4 files / 6 ins / 6 del. ENGINE 1.51.0 -> 1.52.0 + 4386 -> 4465 tests + 57/49 waves 0-14 -> 60/51 waves 0-15 + wave 15 closure note across docs/DAEMON_SLAYER.md L5+L32 + README.md L46 + BRIEF.md L20+L26 + docs/ARCHITECTURE.md L161 (3 edits).

**Verified post-merges + DS restart:**
- DS suite 4465 passed / 1 skipped / 1 xfailed / 1757 subtests in 67.89s (+79 over 4386 baseline = exactly wave 15 test file).
- RC suite (excl phase8_smoke) 3291 passed / 67 subtests in 56.56s (unchanged from item 172).
- tests/phase8_smoke/ = 75/75 PASS post-DS-restart.
- `py -m ruff check .` ALL CHECKS PASSED.
- `py -m py_compile` clean on all touched files.
- DS :8893 killed pid 13492 + `schtasks /Run /TN RC-DaemonSlayer` -> serves engine_version=1.52.0 patch=16.10.1 champions=172 items=705.
- RC :8888 unchanged (pid 5800; non-route-module edits; ADR-008 auto-served if any UI - none this run).

**Merge order:** Slice A FIRST `2129e6c` (worktree branch `worktree-agent-ae88f139dc0053a4b`, ort, 0 conflicts, 36 files). Slice B SECOND `ef1dfb5` (ort, 0 conflicts, 5 files). Docs sync THIRD `b260a37` (4 files / 6 ins / 6 del). 0 merge conflicts across all slices.

**Don't-redo:**
- COND_TERRAIN was a wave-7 forward-marker tag with 0 consumers; wave 15 Ornn E is now the FIRST consumer. Future wave 16+ candidates can use this tag without re-pitching it.
- Zac Q + Ornn E + Rell W form 0 closures are the methodology template for wave 16+: re-audit prior wave REJECT carries against the latest Meraki schema fields (cast_time + effects_descriptions + damage_blocks attribute_kinds).
- Maokai R same-spell-slot conditional-vs-unconditional coexistence machinery STILL operator-gated separately.
- The 6 wave-7 schema-lift carries (Renekton W Fury / Aatrox post-R passive / Volibear R passive / Briar W frenzy / multi-form Karma+Hwei+Neeko) are STILL state-tracking-schema-blocked (need extractor lift beyond cast_time/effects_descriptions). cast_time field doesn't help them.
- The orchestrator-merge pattern is now 26 consecutive runs (items 134-173).
- Slice C's wmic/cumulative-log measurement errors are a recurring pitfall - always grep RC pid start time first then filter log window to post-restart only. The 7-lever audit needs careful filtering not raw tail-N grepping.

**Carries forward:**
- (a) All item 172 carries unchanged EXCEPT (a)-relaxed: cc_conditional wave 15 DONE; Zac Q + Ornn E + Rell W form 0 NO LONGER schema-blocked (NEW: COND_TERRAIN first consumer landed).
- (b) DD Defy heal-on-takedown STILL deferred.
- (c) Live ARAM/SR smoke STILL pending.
- (d) Calibrations STILL operator-gated.
- (e) Legion 1-PC consolidation STILL operator-gated.
- (f) cc_conditional wave 16+ candidates: Maokai R distance-gated (NEEDS same-spell-slot coexistence schema lift - operator-gated registry schema lift) + 6 wave-7 schema-lift carries (Renekton W Fury / Aatrox post-R passive / Volibear R passive / Briar W frenzy / multi-form Karma+Hwei+Neeko) STILL operator-gated.
- (g) 542 residual U+2500 box-drawing chars carry forward as operator-gated separate sweep (NEEDS rc_supervisor.py + rc_self_monitor.py frozen-file grant - NOT used this session).
- (h) v2.1 audit pages 9/10 Champ Select ARAM/Arena -> 11/12/13 Active Match SR/ARAM/Arena -> 14/15/16 PGR SR/ARAM/Arena (8 remaining; this session's "operator gated" framing was again non-UI per item 172 interpretation).
- (i) Frozen-file grant NOT used this session.

---
# 2026-05-24 - item 172 SHIPPED: operator-gated parallel drain #7 (cc_conditional wave 14 Meraki cast_time schema lift ENGINE 1.51.0 + L31 type annotations round 4 + cost/latency CLEAN wave 20 + RC restart applies item 171 log-suppress fix + item 167 tooling ruff fix unblocks CI) (4 commits + 2 merges `9766872` `b5b0ec3` `9a6e697` `528ce82` pushed origin/main `dbf55e6..528ce82`; ENGINE 1.50.0 -> 1.51.0; DS :8893 restarted pid 14632 -> serves 1.51.0; RC :8888 restarted pid 12220 -> 5800 via `restart_trigger.txt` to apply item 171 `_SUPPRESS_LOG_PATHS` query-string fix in production)

Operator triggered "check github for ci checks and branch merge or deletes. then continue next operator gated passes in parallel". **CI was red 10 consecutive runs since item 170** on 3 ruff UP034 errors in `tools/champion_loadout_align.py:342` + `tools/champion_loadout_handcurate.py:315,316` (introduced item 167; items 170+171 deferred as "pre-existing"). Fixed via `py -m ruff check --fix` (3 paren removals). 2 stale remote worktree branches deleted. Then 3 parallel agents (orchestrator-merge pattern items 134-172 = 25 consecutive runs).

**Slice A `b5b0ec3` (merged) feat(ds) cc_conditional wave 14 Meraki cast_time schema lift ENGINE 1.50.0 -> 1.51.0 (37 files / 1685 ins / 34 del):**
- Investigation discovered Meraki source field `castTime` PRESENT but NOT extracted (verified Jayce/Maokai/Karthus/Cassiopeia/Caitlyn/Xerath/Velkoz/Lux).
- Schema lift `tools/daemon_slayer_abilities_extract.py`: NEW `_normalize_cast_time(raw)` helper + `cast_time: float | None` per form. Re-extracted 16.10.1 (171 champs / 927 forms / 99.0% ok_rate).
- SHIP Jayce E form_index=0 Thundering Blow cast-time root sidecar COND_CHANNEL_COMPLETION 0.25s (FIRST Jayce CC registration anywhere; closes item 170 carry).
- REJECT Maokai R distance-gated (same-spell-slot conditional-vs-unconditional coexistence machinery STILL operator-gated). REJECT LeeSin R 0.25s (unconditional belongs in _PER_SPELL_CC_DURATIONS). REJECT KSante R (self-buff immunity not target CC).
- Registry: 56/48 (51 primary + 5 sidecar) -> 57/49 (51 primary + 6 sidecar). +43 tests; default include_conditional=False byte-identical to 1.50.0.

**Slice B `9a6e697` (merged) chore(types) L31 type annotations round 4 (12 files / 30 ins / 30 del):**
- 30 surgical sites: vision_server/_http.py (8) + ops/_ws_probe.py (1) + tools/match_monitor.py (4) + tools/cost_health_watchdog.py (2) + tools/{bridge,ds_matchdb,gamepc}_mcp_server.py (3 each) + tools/run_phase2_smoke.py (1) + scripts/{merge_refresh_builds,parse_external_arena,cache_ddragon_assets,validate_build_data}.py (1 each).
- 0 ruff violations / 0 frozen-file touches. Surface saturation note: orchestrator-easy surfaces now covered; remaining sites are higher-touch (gamepc_lcu_agent.py) or ad-hoc (perf harnesses).

**Slice C cost/latency CLEAN wave 20 read-only (no commit):**
- 20th consecutive CLEAN since item 134. 7 levers green. L4 anomaly: /api/minimap-crop 0.442/sec + /api/activity 0.099/sec - FIX PENDING RC RESTART (commit 0036359 dropped trailing space in _SUPPRESS_LOG_PATHS; RC pid 12220 held pre-fix module image).
- L2 route TTL: 16 routes with `_CACHE` (live count; item 171 audit said 12, item 170 ledger said 14 - additive drift only).
- RC restart applied via `restart_trigger.txt` -> pid 12220 -> 5800 alive=True reload_ok=True mode=client picks up new tuple.

**Docs sync `528ce82`:** 6 files / 8 ins / 8 del. ENGINE 1.50.0 -> 1.51.0 + 4343 -> 4386 tests + 56/48 waves 0-13 -> 57/49 waves 0-14 across docs/DAEMON_SLAYER.md + README.md + docs/ARCHITECTURE.md + BRIEF.md + BACKLOG.md + ROADMAP.md.

**Verified post-merges + DS restart + RC restart:**
- DS suite 4386 passed / 1 skipped / 1 xfailed / 1751 subtests in 66.75s (+43 over 4343 = wave 14 test file).
- RC suite 3291 passed / 67 subtests in 56.46s.
- phase8_smoke 75/75 PASS post-DS-restart.
- ruff ALL CHECKS PASSED (item 167 errors fixed).
- DS :8893: taskkill pid 14632 + `schtasks /Run /TN RC-DaemonSlayer` -> `/health` engine_version=1.51.0 patch=16.10.1.
- RC :8888 restarted via `restart_trigger.txt` -> pid 5800 alive=True reload_ok=True mode=client.
- 2 remote worktree branches deleted (a5d3325f264ac4476 + a1bff00e83a839ac5).
- Pushed origin/main as `528ce82`.

**Don't-redo:**
- Meraki `castTime` field IS in source + IS now captured via `_normalize_cast_time(raw)` helper. Future cc_conditional waves can rely on `form.cast_time` for cast-time-gated CC mechanics.
- Jayce E form_index=0 is ranged (cast-time root); form_index=1 is melee (unconditional knockback, NOT cast-time root).
- Maokai R same-spell-slot conditional-vs-unconditional coexistence machinery is the next BIG schema lift (parallel to _PER_SPELL_CC_CONDITIONAL_FORMS sidecar but for unconditional-vs-conditional pair).
- CI red root cause was item 167 tooling ruff errors that items 170+171 ledger deferred as "pre-existing not this session's scope" - the trivial fix should NOT have been deferred (3-paren removal cheaper than 10 red CI runs).
- L31 type-annotation pass is now SATURATED for orchestrator-easy surfaces.
- Route TTL ledger count is loose (12/14/16 across items 170/171/172); use live grep at audit-time.
- Orchestrator-merge pattern: 25 consecutive runs (items 134-172).

**Carries forward:** (a) Item 171 carries unchanged EXCEPT cc_conditional wave 14 cast_time schema lift DONE; Jayce E NO LONGER schema-blocked. (b) DD Defy STILL deferred. (c) Live ARAM/SR smoke STILL pending. (d) Calibrations STILL operator-gated. (e) Legion 1-PC consolidation STILL operator-gated. (f) cc_conditional wave 15+ candidates: Maokai R distance-gated needs same-spell-slot coexistence schema lift (operator-gated) + 6 wave-7 schema-lift carries STILL operator-gated. (g) 542 residual U+2500 box-drawing chars carry forward as operator-gated separate sweep (NEEDS rc_supervisor.py + rc_self_monitor.py FROZEN grant). (h) v2.1 audit pages 9-16 (8 remaining; UI excluded this session). (i) Frozen-file grant NOT used.
