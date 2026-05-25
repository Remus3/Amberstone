# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 archived to docs/history_notes.md. Only the last 3 sessions kept here.

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

---

# 2026-05-24 - item 171 SHIPPED: non-UI open-items parallel drain #6 (cc_conditional wave 13 ENGINE 1.50.0 + BACKLOG stale-sweep wave 16 + cost/latency DRIFT FLAG `_SUPPRESS_LOG_PATHS` query-string fix + docs sync) (4 commits + 2 merges `8611ff3` `a66210b` `0036359` pushed origin/main `27c4dba..0036359`; ENGINE 1.49.0 -> 1.50.0; DS :8893 restarted pid 4432 -> serves 1.50.0; RC :8888 unchanged mode=client - DS engine + dashboard log-suppress + docs only)

Operator triggered "continue on any open items not operator ui" - sixth consecutive parallel drain. Orchestrator-merge pattern items 134-170 extended to 24 consecutive runs. 3 worktree/investigative agents on disjoint slices.

**Slice A `8611ff3` (merged) feat(ds) cc_conditional wave 13 ENGINE 1.49.0 -> 1.50.0 (37 files / 1452 ins / 57 del):**
- Re-audit of effects_descriptions across all 171 champs surfaced 7 new candidates verifiable WITHOUT schema lift.
- SHIP Sejuani E Permafrost 4-Frost-stack stun nth_hit 1.0s (prob 0.7).
- SHIP Renata Q Handshake recast bystander stun channel_completion 0.5s.
- SHIP Shaco R Hallucinate clone-death AoE fear channel_completion 1.0s.
- SHIP Fizz R Chum the Waters lure-on-champion knockup target_debuffed 1.0s.
- SHIP Warwick E Primal Howl recast fear channel_completion 1.0s (joins wave 0 Warwick R).
- SHIP TahmKench W Abyssal Dive emerge stun channel_completion 1.0s - FIRST 3-slot cc_conditional champ (W + Q wave 5 + R wave 0).
- SHIP Aphelios Q form_index=3 Gravitum Binding Eclipse expunge root target_debuffed 1.0s sidecar (first Aphelios first-order CC anywhere).
- REJECT LeeSin R + Poppy R + RekSai W form 1 (all UNCONDITIONAL belong in `_PER_SPELL_CC_DURATIONS` not cc_conditional). Jayce E cast-time + Maokai R distance-gated CARRY (still schema-blocked / would double-count).
- Registry growth: 49/43 -> 56/48 (45 primary + 4 sidecar -> 51 primary + 5 sidecar). ENGINE 1.49.0 -> 1.50.0 with changelog block + 31 stale ENGINE pin syncs.
- NEW `agents/daemon_slayer/tests/test_cc_conditional_wave13.py` ~848 LOC; +109 tests; default include_conditional=False byte-identical to 1.49.0 for all 7 candidates.

**Slice B `a66210b` (merged) docs(backlog) stale-sweep wave 16 (1 file / 2 ins / 2 del):**
- 2 flips. ROADMAP.md L13 `dev.js:337` -> `dev.js:361` (line drifted +24 from item 162 carry).
- ROADMAP.md L165 Fleet status DS row header bumped (later re-bumped to 1.50.0 + 4343 + wave 13 by docs sync commit `0036359`).
- Sweep cycle: 1=2 / 2=3 / 3=3 / 4-12=1 / 13=0 / 14=3 / 15=2 / **16=2**.

**Slice C drift flag + fix (committed as part of `0036359`):**
- Cost/latency 19th consecutive sweep. 6/7 levers CLEAN.
- **DRIFT on lever 4 (log spam):** `_SUPPRESS_LOG_PATHS` needles in `dashboard/_handler.py:74-83` were trailing-space terminated. Substring match silently failed against actual log lines with query strings. `/api/minimap-crop?mode=sr&_=ts` ran unsuppressed at **0.490/sec** (3720 hits / 7599s window) since item 156 despite being in the tuple; item 156 ledger's "0.000/sec after suppression" claim was a misread. `/api/activity?limit=6` same silent failure at 0.099/sec.
- Fix: drop trailing space from all 9 needles. Bare prefix match handles both bare-path AND query-string variants. Defense-in-depth test added: `test_constant_contains_high_frequency_paths` asserts no needle ends with space. 2 new positive tests for query-string variants.
- Other 6 levers CLEAN: prompt-cache 8 sites + route TTL 12 routes + polling cadences (tightest network 2000ms) + model tier (haiku active, sonnet only agent7_warm) + scheduled tasks (14 RC-*) + bundle parity (27=27).

**Docs sync (committed in `0036359`):** 6 files / 7 edits. docs/DAEMON_SLAYER.md L5+L32 / README.md L46 / docs/ARCHITECTURE.md L161 + wave lineage / BRIEF.md L20+L26 / BACKLOG.md L13 / ROADMAP.md L165 wave-13 lineage append.

**Verified post-merges + DS restart:**
- DS suite 4343 passed / 1 skipped / 1 xfailed / 1747 subtests in 67.01s (+109 over 4234 baseline = exactly wave 13 test file).
- RC suite 3291 passed / 67 subtests in 57.05s (+2 over 3289 = exactly the 2 new query-string log-suppress tests).
- phase8_smoke 75/75 PASS post-DS-restart.
- ruff 3 errors confirmed pre-existing item 167 tooling - NOT this session's scope.
- DS :8893: taskkill pid 4432 + `schtasks /Run /TN RC-DaemonSlayer` -> `/health` engine_version=1.50.0 patch=16.10.1 champions=172 items=705.
- RC :8888 mode=client throughout (never restarted - non-route-module change; `_SUPPRESS_LOG_PATHS` tuple is module-level immutable so existing handlers won't suppress until supervisor relaunch).
- Pushed origin/main as `0036359`.

**Don't-redo:**
- The `_SUPPRESS_LOG_PATHS` trailing-space silent failure is a CANONICAL regression. `test_constant_contains_high_frequency_paths` now asserts no needle ends with space + 2 new positive tests cover the query-string variant. CI catches any future regression.
- The item 156 ledger's "0.000/sec after suppression" claim was a misread. The actual fix never took effect because the needle never matched.
- cc_conditional wave 13's 7 closures are all candidates verifiable WITHOUT schema lift (methodology template per item 151 wave 8 precedent).
- TahmKench is now the FIRST 3-slot cc_conditional champion (W + Q + R) - future multi-slot expansions are not constrained by the registry shape.
- Aphelios Q form_index=3 (Gravitum) is the first Aphelios first-order CC anywhere; other 4 Aphelios Q forms remain damage-only.
- Orchestrator-merge pattern now 24 consecutive runs (items 134-171).
- Route TTL ledger count (12 vs item 170's "14") is loose. Actual count fluctuates around 12-16 with consumer routes added/removed.

**Carries forward:** (a) All item 170 carries unchanged EXCEPT (f)-relaxed: cc_conditional wave 13 DONE; Jayce E + Maokai R STILL schema-blocked / would-double-count. (b) DD Defy heal-on-takedown STILL deferred. (c) Live ARAM/SR smoke STILL pending. (d) Calibrations STILL operator-gated. (e) Legion 1-PC consolidation STILL operator-gated. (f) cc_conditional wave 14+ candidates: 2 schema-blocked + 6 wave-7 schema-lift carries all operator-gated. (g) 542 residual U+2500 box-drawing chars carry forward. (h) v2.1 audit pages 9-16 (8 remaining in audit order). (i) Frozen-file grant NOT used.

---

# 2026-05-24 - item 170 SHIPPED: parallel drain (page #8 typography + champ_select ASCII sweep + cc_conditional wave 12 ENGINE 1.49.0 + BACKLOG sweep wave 15 + cost/latency CLEAN wave 18 + docs sync) (5 commits + 2 merges `f8fa9f1` `8f63409` `cb834a6` `36f6172` `a8b8164` `3e6e34b` pushed origin/main `a80dd6b..3e6e34b`; ENGINE 1.48.0 -> 1.49.0; DS :8893 restarted pid 7344 -> serves 1.49.0; RC :8888 unchanged pid 12220 mode=game alive=True - operator in active game during drain so no UI capture)

Operator triggered the "in parallel: start all open items in Operator-gated, decision owed" drain. Orchestrator-merge pattern items 134-169 streak extended to 23 consecutive runs. 3 worktree agents on disjoint slices.

**Slice A `f8fa9f1` (merge `36f6172`) page #8 typography migration + champ_select ASCII retro-sweep (2 files / 94 ins / 94 del):**
- 9 CSS rules in `web/css/panels/champ_select_view.css` swapped: `.csv-arch-preview-head/name` (11px) + `.csv-pb168-head/tag/name/pct/expl-empty/expl-cc/expl-pick` (9/11/12/13px) -> `var(--fs-xs)` (16px floor). 0 sub-floor px declarations remain inside both namespaces post-sweep.
- ASCII retro-sweep: `web/js/panels/champ_select.js` 399 -> 0 non-ASCII bytes; `web/css/panels/champ_select_view.css` 728 -> 0 bytes. 21 catalogued codepoints handled; 1 uncatalogued surfaced (U+2212 minus in CSS comment) and manually restored as ASCII `-`. Phase8 75/75 PASS. JS brace-balance clean (3305 lines).

**Slice B `cb834a6` (merge `a8b8164`) cc_conditional wave 12 ENGINE 1.49.0 (35 files / 916 ins / 33 del):**
- 4 explicit candidates audited + ~30 from broader effects_descriptions cc-keyword scan.
- SHIP **Singed E Fling Mega-Adhesive overlap root** primary COND_TARGET_DEBUFFED 0.5 prob, Meraki damage_blocks per-rank Root Duration [1.0/1.25/1.5/1.75/2.0]s (item 156 wave 11 audit dismissed as "for a duration" text-only but the structured block was overlooked). Coexists with Singed E unconditional 1.0s knockback in `_PER_SPELL_CC_DURATIONS`.
- SHIP **Alistar E Trample 5-stack stun** primary COND_NTH_HIT 0.5 prob, 1.0s flat (named in ability_dps.py:1225-1228 carryover comment; closes the conditional-CC note).
- SHIP **Sylas E form_index=1 Abduct** sidecar COND_CHANNEL_COMPLETION 0.5 prob, 0.5s flat (first Sylas first-order CC anywhere; closes item 148 wave 7 schema-lift REJECT note).
- REJECT Jayce E Thundering Blow: effects_descriptions "0.4 seconds" refers to Q/Q1 lockout AFTER cast, NOT cast-time root. Carry to wave 13+.
- REJECT Maokai R Sapling Showcase distance-gated root: unconditional Maokai R already encodes mid-distance root (1.2/1.6/2.0)s at `_PER_SPELL_CC_DURATIONS`; adding cc_conditional COND_RANGE_GATED would double-count.
- Registry growth: 46/40 -> **49/43** (45 primary + 4 sidecar). ENGINE_VERSION 1.48.0 -> 1.49.0 with full changelog block + 32 stale ENGINE pin syncs across DS test files via bulk regex rewrite.
- NEW `agents/daemon_slayer/tests/test_cc_conditional_wave12.py` (~533 LOC) covering per-entry shape pins + registry growth + multi-wave coexistence + COND_TARGET_DEBUFFED/COND_NTH_HIT/COND_CHANNEL_COMPLETION consumer counts + per-form override + ASCII hygiene. `test_cc_conditional_forward_marker.py _ALLOWED_TEST_FILES` extended.
- Default `compute_cc_pressure(include_conditional=False)` BYTE-IDENTICAL to 1.48.0 for all 3 ship candidates (Singed=1.0 / Alistar=1.5 / Sylas=0.0).

**Slice C `8f63409` housekeeping triple (committed direct to main):**
- Sub-task 1 BACKLOG stale-sweep wave 15: 2 flips. BACKLOG.md L13 cc_conditional ecosystem header version bumped + wave count refreshed. ROADMAP.md L23 lobby change_queue_type item: stale `main.js:2614-2629` -> `:3081`; `:3713-3723` -> `:3092 + :4281`; `gamepc_lcu_agent.py:229` (Poro King 920) -> `:246` (ARAM Mayhem 2400, actual stale-on-920 location).
- Sub-task 2 cost/latency CLEAN wave 18 - **18th consecutive CLEAN sweep since item 134**. All 7 levers green. Top non-suppressed `/api/ward-heat` 0.109/sec (below item 156 baseline 0.149); `_SUPPRESS_LOG_PATHS` unchanged at 9; 27=27 CSS @import parity guard test 4/4 PASS.
- Sub-task 3 living docs sync (synced to ENGINE 1.48.0 + 4178 baseline; Slice B's 1.49.0 + 4234 caught in follow-up commit `3e6e34b`).

**Verified post-merges + DS restart:**
- DS suite 4234 passed / 1 skipped / 1 xfailed / 1737 subtests in 67.31s (+58 vs item 156 baseline 4176).
- RC suite 3289 passed / 67 subtests in 55.83s.
- phase8_smoke 75/75 PASS post-DS-restart.
- ruff 3 errors confirmed pre-existing item 167 tooling (`tools/champion_loadout_*.py` UP034 extraneous parens) - NOT this session's scope.
- DS :8893: taskkill pid 7344 + `schtasks /Run /TN RC-DaemonSlayer` -> `/health` engine_version=1.49.0 patch=16.10.1 champions=172 items=705.
- RC :8888 alive=True last_reload_ok=True mode=game throughout (operator in active SR game during drain - ADR-008 asset-hash auto-served Slice A's CSS+JS edits without restart).

**Don't-redo:**
- The Singed E re-audit lesson: re-check schema-lifted damage_blocks per-form for explicit duration attributes before dismissing as "for a duration" text-only. Wave 11's miss on Singed E was a parse-strip oversight, not a schema gap.
- Jayce E cast-time root requires patch data with an explicit cast_time field; effects_descriptions "0.4 seconds" is Q/Q1 lockout AFTER cast, not the root duration. Schema-blocked at the parse-strip level.
- Maokai R distance-gated root double-counts with existing unconditional `_PER_SPELL_CC_DURATIONS` entry; would need that registry deleted first.
- Sub-floor pixel typography on `.csv-pb168-*` + `.csv-arch-preview-*` is now CLOSED via v2.1 token migration; do NOT re-introduce hardcoded px values below --fs-xs (16px) in these namespaces.
- champ_select.js + champ_select_view.css are now 0 non-ASCII bytes; the sweep map covers 21 catalogued codepoints + U+2212 minus discovered this run. Drift guard pattern: pre-existing drift guards in tests/snapshot_panels/ cover most surfaces.

**Carries forward:**
- All item 169 carries unchanged EXCEPT (c) page #8 typography migration NOW CLOSED + (d) ASCII retro-sweep on champ_select.js + champ_select_view.css NOW CLOSED.
- DD Defy heal-on-takedown STILL deferred.
- Live ARAM/SR smoke STILL pending (operator was in active game during drain; visual UI capture of Slice A typography deferred to next non-game window).
- Calibrations STILL operator-gated.
- Legion 1-PC consolidation STILL operator-gated.
- cc_conditional wave 13+ candidates: Jayce E (cast_time schema-blocked) + Maokai R distance-gated (would double-count). 6 wave-7 schema-lift carries (Renekton W Fury / Aatrox post-R passive / Volibear R passive / Briar W frenzy / multi-form Karma+Hwei+Neeko) still operator-gated separately.
- 542 residual U+2500 box-drawing chars carry forward as operator-gated separate sweep (NOT trivial - intentional docstring tree-drawing).
- v2.1 audit pages 9/10 Champ Select ARAM/Arena -> 11/12/13 Active Match SR/ARAM/Arena -> 14/15/16 PGR SR/ARAM/Arena (8 remaining in audit order).
- Frozen-file grant NOT used this session.

---
# 2026-05-24 - item 169 SHIPPED: SR carry summoner default Flash+Heal -> Flash+Barrier + page #8 audit re-run + PostmortemAnalyze verification (1 feature commit `102886c` merged `1d83f96` + 1 docs sync `969b337` pushed origin/main `12c604b..969b337`; non-frozen; no DS restart; no RC restart - data-only + dashboard route docstring sync via ADR-008 auto-serve)

Operator triggered the "in parallel: start all open items in Operator-gated, decision owed" drain with a specific ADC summoner-spell fix spec. Orchestrator-merge pattern items 134-156 streak extended to 22 consecutive runs.

**(a) Slice A `102886c` (merge `1d83f96`) SR carry [4,7] -> [4,21]**: `tools/champion_loadout_autogen.py:102` `SR_SUMM_BY_ARCH["carry"]` flipped Flash+Heal -> Flash+Barrier (solo ADC norm 16.10.x). `tests/test_champion_loadout_autogen.py` renamed `test_sr_carry_is_flash_heal` -> `test_sr_carry_is_flash_barrier` asserting [4,21]. NEW `tools/migrate_carry_summoners_flash_barrier.py` (147 LOC) iterates SR carry-coded variants (match `sr-carry`, `adc-*`, `ad-crit`, `on-hit`, contains `carry`, OR `_archetype=carry`, OR keystone in {Lethal Tempo, Press the Attack, Fleet Footwork}); flips [4,7] -> [4,21] except `BOT_DUO_HEAL_KEEP={Senna, Kalista, Yuumi}` denylist. Ran once: 61 flips / 5 denylist kept. `dashboard/routes_adaptive_summoners.py:181` docstring synced. Verification probe: 14 SR [4,7] survivors = 5 denylist + 9 enchanter/support variants (Janna/Lux/Milio/Nami/Sona/Soraka/Seraphine/Zilean) correctly skipped (NOT solo-ADC).

**(b) Slice B (read-only audit) page #8 items 166-168 visual-hierarchy re-run per `feedback_phase3_fixture_ritual` (no commit)**: structure PASS (3-sub-panel TOP/MIDDLE/BOTTOM at champ_select.js:3252-3263 matches item 168 spec). DS-preview PASS (.csv-arch-preview-* renders top-3 DS items per archetype). Typography FAIL = pre-existing carry (.csv-pb168-* + .csv-arch-preview-* hardcoded 9/11/12/13px below v2.1 floor --fs-xs 16px) - page #8 v2.1 typography token migration STILL OWED. ASCII FAIL = pre-existing operator-gated retro-sweep carry (champ_select.js 399 non-ASCII bytes + champ_select_view.css 728 bytes). Not introduced by items 166-168.

**(c) Item 156 carry (b) RC-PostmortemAnalyze first scheduled run CLOSED**: ran today 2026-05-24 04:15:15 with LastTaskResult=0, State=Ready, NumberOfMissedRuns=0, NextRunTime=2026-05-31 04:15:15 (weekly cadence confirmed).

**Verified**: `py -m pytest tests/test_champion_loadout_autogen.py tests/test_champion_loadouts_no_unique_clash.py tests/phase8_smoke/ -q` = 112 passed in 2.48s post-merge. Spot-checks across 5 ADC variants flipped correctly. Adaptive route `_recommend()` swap logic (CC -> Cleanse, burst -> Barrier) still applies on top of new baseline at routes_adaptive_summoners.py:192-197 unchanged.

**Don't-redo:**
- SR carry default is now [4, 21] - do NOT revert without a meta shift. Bot duo coordinated Heal pick is the EXCEPTION, codified in BOT_DUO_HEAL_KEEP denylist.
- Arena keeps [4, 7] (revive frame shorter than Barrier window). ARAM keeps [4, 32] (Mark/Snowball mode-mandatory).
- The 9 enchanter/support [4, 7] survivors (Janna/Lux/Milio/Nami/Sona/Soraka/Seraphine/Zilean) are correct as-is (support sustain picks; NOT solo-ADC; carry-coded heuristic correctly skipped them).
- `tools/migrate_carry_summoners_flash_barrier.py` is the durable migration template - re-run after a future patch's autogen regeneration if archetype mappings drift.

**Carries forward:**
- All items 165-168 carries unchanged EXCEPT item 156 carry (b) RC-PostmortemAnalyze first scheduled run NOW CLOSED + page #8 items 166-168 visual audit subagent re-run CLOSED.
- Page #8 v2.1 typography token migration on .csv-pb168-* + .csv-arch-preview-* hardcoded 9/11/12/13px sites STILL OWED.
- ASCII retro-sweep on champ_select.js (399 bytes) + champ_select_view.css (728 bytes) STILL operator-gated.
- DD Defy heal-on-takedown STILL deferred.
- Live ARAM/SR smoke STILL pending.
- Calibrations STILL operator-gated.
- Legion 1-PC consolidation STILL operator-gated.
- cc_conditional wave 12+ has 2 deferred candidates (Jayce E + Singed E) needing schema lifts beyond effects_descriptions.
- 542 residual U+2500 box-drawing chars carry forward as operator-gated separate sweep (NOT trivial - intentional docstring tree-drawing).
- v2.1 audit pages 9/10 Champ Select ARAM/Arena -> 11/12/13 Active Match SR/ARAM/Arena -> 14/15/16 PGR SR/ARAM/Arena (8 remaining in audit order).

---
# 2026-05-24 - items 165b-168 SHIPPED: ARAM bench 10-cell + loadout roster + SR DS-align + P&B 3-panel + archetype preview (4 feature commits `15bafed` `dbcf9f2` `1750425` `81925a6` pushed origin/main `3b3f9d8..81925a6`; non-frozen; RC pid 14464 -> 12220 via schtasks /Run /TN RC-Supervisor; ADR-008 asset hash auto-served all UI edits)

Four operator-directed asks executed end-to-end.

**(a) ARAM bench 10-cell + drop champ name (`15bafed`)**: `_csvBenchHtml` slice 5 -> 10; dropped `.csv-bench-cell-name` div + CSS rule; CSS grid 5fr -> 10fr; mock fixture bench 5 -> 10 ids.

**(b) Item 166 hand-curate Arena/SR/ARAM roster + boots (`dbcf9f2`)**: NEW `tools/champion_loadout_handcurate.py` + `tools/champion_loadout_handcurate_merge.py`. 4 worktree agents A-D on disjoint champ slices produced 4 patches; merged 172 / 503 / 172. Arena went from 0/172 hand to 172/172 hand. SR 162 champs at 1 hand variant got a 2nd archetype variant with boots; ARAM 169 champs at 2 hand variants got a 3rd archetype variant with boots. Yuumi + Cassiopeia bootsless preserved. Coverage gaps (no auto seed available): SR Caitlyn/Ezreal/Kai'Sa/Kayn/Lux/MasterYi/Pantheon/Twitch/Varus/Vayne; ARAM Kai'Sa/Lulu/Vayne.

**(c) Item 167 align SR curated to DS engine + dedupe ARAM/Arena (`1750425`)**: 1421 unique-passive-family clashes pre-fix (Trinity Force + Essence Reaver, Lich Bane + Trinity Force, etc.). NEW `tools/champion_loadout_align.py`: SR variants regenerated via `core.build_order.plan_build_order` at typical enemy stats (armor=80, mr=60, hp=2000, bonus_hp=600, level=14, inject_boots=True) - same engine as DS-vs-enemy-comp build so curated + dynamic share components. ARAM + Arena variants deduped in-place per operator directive ("keep role standard for ARAM since enemy unknown"). Boots integral for SR/ARAM, excluded for Arena (no shop boots). 4 worktree agents A-D + follow-up all-slice rerun with improved 24-token legacy detector (ap-burst, adc-crit, tank-engage, etc.). Post-merge: 0 clashes anywhere; SR hand 346 (342 with boots). NEW `tests/test_champion_loadouts_no_unique_clash.py` drift guard.

**(d) Item 168 P&B 3-panel + DS-archetype top-3 preview (`81925a6`)**: Operator reframed Pick & Ban panel as 3 stacked sub-panels in same row-2 floor (460px). TOP = 4 picks (3 role-matching from comfort + 1 last_in_queue). MIDDLE = 4 bans (3 counter + 1 struggle). BOTTOM = dynamic explanation (per-pick reason lines + CC-cleanse advisory). Backend: NEW `_query_last_in_queue` + `_query_struggle_ban` + `_compose_cleanse_advisory` helpers + 3 response fields (`last_in_queue`, `struggle_ban`, `cleanse_advisory`) + 2 query params (`enemies`, `my_summoners`). Frontend: full rewrite of `_csvRenderPickBan` with new `.csv-pb168-*` classes + source-color tags. Mood toggle dropped from UI (kept in cache key default=comfort). DS Archetype empty-space fill: top-3 DS picks render in a 3-cell row below the 6 archetype buttons via `_csvArchetypePickerHtml` extension + `.csv-arch-preview-*` CSS. Live probe BOT: `last_in_queue=Tristana`, `struggle_ban=Nilah 5/5`. 10 new pickban tests (53/53). Phase8 75/75. RC suite 3289/3289.

**Don't-redo:**
- `tools/champion_loadout_handcurate.py` + `tools/champion_loadout_handcurate_merge.py` + `tools/champion_loadout_align.py` are durable patch-pipeline tools. To regenerate after a patch bump: 4 parallel agents on A-D slices, then merge with the merge tool. Drift guard `test_champion_loadouts_no_unique_clash` LOCKS the no-double-family invariant for all 678 curated variants.
- The Arena hand-curate is intentionally NOT bespoke per-champ-meta - it's a promotion of the auto-arena-primary-<arch> variant via the DS engine's archetype scorer. Hand-tuning per champ is operator-gated separately.
- SR plan_build_order baseline (armor=80, mr=60, hp=2000, lvl=14) is the neutral pivot; the live DS-vs-enemy-comp path runs the SAME engine at the SAME baseline + current enemy stats, so curated + dynamic share components by construction.
- `.csv-pb-pick-row` / `.csv-pb-pick-icon` / `.csv-pb-mood-row` CSS rules are now DEAD post-item-168 (new layout uses `.csv-pb168-*`); leave them in place for now (CSS-only, no JS still references them). Mood-toggle wiring code in JS is also no-op (querySelectorAll returns empty list).
- `_compose_cleanse_advisory` HEAVY_THRESHOLD=1.0s + 3-champs-with-heavy-CC + cleanse-not-equipped triple gate is operator-tunable but currently calibrated for "actionable not spam".

**Carries forward:**
- All item 165 carries unchanged EXCEPT bench-10 part done this session.
- Item 164 LCU multi-itemset push verification via Practice Tool match + Game-PC monitor 0 capture STILL operator-gated.
- v2.1 audit pages 9/10 Champ Select ARAM/Arena -> 11/12/13 Active Match SR/ARAM/Arena -> 14/15/16 PGR SR/ARAM/Arena (8 remaining in audit order).
- RC-PostmortemAnalyze first scheduled run was 2026-05-24 04:15 - verify LastTaskResult=0 next session.
- 13 SR/ARAM coverage gaps in champion_loadouts (above (b)) - operator-gated whether to backfill with curated picks for the no-auto-seed champs.
- New P&B panel layout per-pick reasons are short backend strings; if operator wants RICHER prose, swap `_compose_cleanse_advisory` for a Haiku call (opt 2/3 from item 168 fork; operator picked opt 1 lite for this round).
- Page #8 visual-hierarchy audit subagent re-run per [[feedback_phase3_fixture_ritual]] STILL OWED for items 166-168 surface (P&B 3-panel + archetype preview need a live visual capture before /done locks the page).
- DD Defy / Live ARAM/SR smoke / calibrations / cc_conditional wave 9+ / 542 U+2500 chars / Legion 1-PC consolidation - all operator-gated carries.

---
# 2026-05-23 - item 165 ARAM bench-swap + summoner-spell D/F slot rotation SHIPPED (commit `1fa39de`, pushed origin/main `02fef4b..1fa39de`; non-frozen; agent redeployed Game-PC; no DS restart; no RC restart - ADR-008 asset-hash auto-served)

Operator-reported 4 live champ-select bugs, all fixed end-to-end:

1. **ARAM bench-swap silent no-op**: JS sent `champion_id` (snake) but agent at `tools/gamepc_lcu_agent.py:1052` read `championId` -> `cid=0` -> early return "no champ". Fixed `champ_select.js:1283` to send `championId`; agent now accepts both for back-compat. Pre-fix the bench-swap pre-cooldown bypass was completely dead.
2. **Summoner-spell single-select instead of D-then-F**: rewrote click handler with module-level `_csvSpellPair[2]` + `_csvNextSpellSlot` state. First click = D slot, next = F, then wraps. Skips no-op when clicked spell matches the other slot.
3. **Push to client unwired**: `set_summoner_spell` was in `_LCU_ALLOWED_CMDS` (item 164) but had NO agent handler. Added `set_summoner_spell` handler: `{slot:1|2, spellId:N}` -> GET session, splice the targeted slot, PATCH `/lol-champ-select/v1/session/my-selection` with the new pair so the partner slot survives rapid clicks.
4. **Strip spell name text removed**: dropped `.csv-summspell-name` divs + CSS rules. Cells now carry icon + green D/F pill + pct only. New `.csv-summspell-slot` CSS class for the pill.
5. **Snowball in ARAM listing**: NEW `_CSV_SUMM_STRIP_ARAM` constant (Flash/Mark/Heal/Cleanse/Barrier/Exhaust/Ignite/Clarity/Ghost) swapped in by `_csvSummSpellListFor(mode)`. Mark = Snowball id 32 visible in cell 2 of the ARAM strip per visual capture.

**Mock + verification**:
- NEW `web/data/ui_mock/champ_select_aram.json` (queue_id=450, is_aram=true, bench=[22,18,76,81,51], spell defaults [4,32]).
- `web/js/main.js:3254` `_csMockLoad` picks `champ_select_{sr,aram}.json` off `?mode=aram` URL flag.
- Visual proof captured Game-PC monitor 1: SR variant (Flash D 95% / Heal F 60% / 7 other cells, no names) + ARAM variant (BENCH·CLICK TO SWAP with 5 champ cells: Ashe/Tristana/Nidalee/Ezreal/Caitlyn; spell strip Flash D 95% / Mark 88% / Heal F 35% / 6 other cells incl. Clarity).

**Agent redeploy**: pushed updated `tools/gamepc_lcu_agent.py` to Game-PC `C:\RC-Agent\gamepc_lcu_agent.py` via HTTP-pull (legacy 92755 -> 94875 bytes, py-parse OK, backup retained `bak-item165-20260523-211601`). RC-LCU scheduled task is DISABLED and no LCU agent process was running at ship time (operator was in client mode, not champ-select); the new code is in place for next champ-select entry.

**Verified**: Phase 8 smoke 75/75 PASS post-edit. py_compile + JS Function-constructor parse OK. ASCII clean (0 new non-ASCII bytes added across all 5 touched files). RC :8888 mode_key=client alive=True reload_ok=True throughout. Asset hash flow: 6773054739 (pre) -> 6773054739 (post-JS+CSS, mtimes incorporated) -> 5f58ce3f3c (post-main.js+aram.json).

**Don't-redo**:
- bench_swap payload uses `championId` (canonical); agent accepts both forms for forward compat - do NOT remove the `champion_id` legacy fallback.
- `set_summoner_spell` handler is per-slot atomic: caller sends one spell id + slot number, agent reads session for the other slot so client/server stays in sync across rapid D/F clicks. Do NOT switch to a full-pair payload here (would require the JS to know the partner slot, racing the LCU).
- `_csvSpellPair[2]` + `_csvNextSpellSlot` are MODULE-level state; resets when render() is called with new champion (the spell pair init reads the variant's summoners array, not the session's spell1Id/spell2Id - this is intentional per the existing "Selection mirrors the current default variant's summoners" rule).
- The `.csv-summspell-name` CSS class is now DEAD - if a future audit reintroduces name text, give it a fresh class.
- ARAM strip list is hand-curated (Flash/Mark/Heal/Cleanse/Barrier/Exhaust/Ignite/Clarity/Ghost). Mark and Clarity are ARAM-only; do NOT add to SR list.
- `champ_select_aram.json` mock fixture is now canonical for ARAM page #8 audit. Mirror the shape for any Arena variant.
- Game-PC RC-LCU scheduled task is DISABLED - operator must launch the LCU agent manually before champ-select (via the `RC-Agent` desktop shortcut or by re-enabling the task). The disabled-task carryover is pre-existing; this session did NOT change it.

**Carries forward**:
- All items 158/162/163/164 carries unchanged except item 158 (a)-relaxed: page #8 Champ Select SR is now functionally complete (operator-gated audit ritual visual-hierarchy subagent re-run STILL OWED).
- LCU multi-itemset push verification via Practice Tool match + Game-PC monitor 0 capture of mid-match item-shop dropdown STILL operator-gated.
- 8 remaining pages in v2.1 audit order: #9/10 Champ Select ARAM/Arena -> #11/12/13 Active Match SR/ARAM/Arena -> #14/15/16 PGR SR/ARAM/Arena.
- RC-PostmortemAnalyze first scheduled run TOMORROW 2026-05-24 04:15 - verify LastTaskResult=0 next session.
- Game-PC RC-LCU task re-enable decision pending (operator must opt back in or keep manual launch).

---
# 2026-05-23 - items 163-164 page #8 Champ Select SR rounds 1-3 + boots-engine + LCU multi-itemset push SHIPPED (5 commits `15a2202` `562e992` `42e0c96` `0554ce7` `3d02d94` `fba6b72`, pushed origin/main `8c54682..fba6b72`; non-frozen; DS engine extended via core/build_order.py non-frozen; no DS restart needed since engine_version unchanged; RC :8888 ADR-008 asset-hash auto-served throughout)

Item 158's v2.1 audit order continued: page #4 History visual proof closed (item 162 carry-forward (b)) + page #7 Pre-Game Lobby SHIPPED + page #8 Champ Select SR end-to-end + 3 rounds of operator-driven deltas + boots-engine injection.

**Pages shipped:**
- **#4 History visual** (commit `15a2202`): captured Game-PC monitor 1 with 5-session 14-day grid + 4-scope tabs + SEASON STATS card. Closes item 162's owed visual.
- **#7 Pre-Game Lobby** (commits `15a2202` `562e992`): header.css L681-1766 ~22 v2.1 token swaps on .lobby-view-* / .lq-* / .lv-* (preserves s162 v2/v4/v5/v8/v10/v11/v13/v14/v15 fit-without-scroll discipline). NEW web/data/ui_mock/lobby.json (3-member Ranked Solo party + mains + top8). NEW main.js _csResolveLcu helpers + restorePrefs sticky-clear hook (PWA hash-restore fallback). Mid-iteration delta: PRIMARY/SECONDARY labels stripped from lane buttons; icon area 28x28 -> 44x44.
- **#8 Champ Select SR** (commits `42e0c96` `0554ce7` `3d02d94` `fba6b72`):
  - Round 1: ~17 v2.1 token swaps on champ_select_view.css. NEW champ_select_sr.json mock fixture. NEW main.js _csResolveLcu helpers + 3 call-site wires.
  - Audit MUST FIX: 13 sub-floor declarations bumped to --fs-xs (YOUR RECORD lines / PICK&BAN labels / champ names / trade popup / SUGGESTIONS).
  - Round 1.5: shrunk YOUR RECORD pills, removed games count from chips, populated SR BUILD CHOOSER with 3 Jinx mock variants + Experimental row, fixed _csvScheduleRender rAF re-fire to handle mock lcu (post-fetch re-render now lands).
  - Round 1.75: hide ALLY/ENEMY ban grids + tips 1/2/3 from Assessment panel + .csv-card-mypick overflow:hidden so bo-chain ellipsis engages.
  - Round 2 (4 deltas): Allies panel removed -> DS BUILD ARCHETYPE relocated to that grid slot via #csv-archetype-target. SR Build Chooser label widened 130 -> 200px. YOUR RECORD pinned to top of Assessment panel above CC threat cards. Pick & Ban restored to 3 rows (Performance/Mastery/Meta) + ban candidates 3 -> 2 per row (dropped terror).
  - Round 3 (7 deltas): inner DS BUILD ARCHETYPE duplicate label hidden; HOVERING + Jinx vertically aligned (dropped 92px min-height, align-self center); LOCK IN button reduced (--fs-md -> --fs-sm, padding tightened, min-height 42 -> 32); summoner spell strip typography bumped (icons 28->36, fonts -> --fs-sm); Build order label renamed "Build Order" -> "DS vs Enemy Comp"; YOUR RECORD chips: icons replace names + WITH row dropped + VS row kept; CC threat balance + Conditional CC card fonts 11/10 -> --fs-sm/--fs-xs.

**LCU multi-itemset push (item 164 - separate spawn task closed inline):**
- `gamepc_lcu_agent.py` apply_item_set: replace-by-uid (NOT wipe-all-RC) so 4 build variants + boots-set coexist as RC- entries in the in-game item-shop dropdown.
- gamepc_lcu_agent.py NEW `apply_item_sets_batch` command: PUTs N sets in 1 LCU call.
- `dashboard/routes_loadout.py` _LCU_ALLOWED_CMDS: added apply_item_sets_batch + set_summoner_spell.
- `champ_select.js` NEW _csvMaybePushBuildsToLCU helper: fires on every central-pane render, debounced via last-push key, pushes up to 4 variants. Operator-gated verification step: redeploy agent to Game-PC C:/RC-Agent/ + Practice Tool match + mid-match item shop dropdown capture.

**League settings audit (item 164 sibling spawn closed inline):**
- 7 `Riot Games` path refs in RC code, ALL `lockfile` READS. ZERO writes to PersistedSettings.json / input.ini / game.cfg.
- RC NOT the culprit for the operator's settings-default-after-match issue. Likely actual causes: Vanguard / League patch / cloud-sync / per-resolution settings dir / GPU driver reset.

**Boots-engine injection (item 164b - core/build_order.py):**
- NEW _BOOTS_IDS frozenset (8 families) + _BOOTS_NAMES + _DEFAULT_BOOTS_BY_ARCHETYPE + _BOOTSLESS_CHAMPS{Yuumi, Cassiopeia}.
- NEW _select_boots(arch, target_armor, target_mr) keyed on: MR >= 60 + non-dps -> Mercury's (3111); armor >= 100 + non-caster -> Steelcaps (3047); fallback by archetype.
- plan_build_order: NEW inject_boots: bool = True parameter; loop refactored to insert boots step AFTER engine_call_i == 1 so subsequent engine calls see boots in item_ids when scoring slots 3+; engine_picks_count decremented to keep total length == slots; boots step scorer="boots" + unit="boots" for downstream filter.
- 20 NEW tests in `tests/test_build_order_boots.py` (10 _select_boots + 10 plan_build_order integration). 26 existing plan_build_order test calls patched with `inject_boots=False` to test engine semantics in isolation. test_opt_in_populates_ordered_build + ScorerContractTests updated to filter scorer="boots". test_personal_record_dom updated for Assessment-panel relocation. test_replay_events_panel_dom widths updated for item 162 page #3 work.

**Verified:** 7528 tests + DS tests pass (3277 RC + 4251 DS). Phase 8 smoke 75/75. RC pid=14464 alive=True reload_ok=True throughout. DS engine_version unchanged (engine code untouched, only orchestration in core/build_order.py). Asset hash flow: 5c6b5a4247 -> 3d4b452ea3 -> b3e5a7234a -> a1324c2a8a -> fd52ce4f4e -> a4b25e196d -> 4bea6a1b10 -> 5eaee8b26f -> dc95d0676b -> 0786e7f5ec -> 2d7f796c1f -> 2cd7868018 -> 7b16e25196 -> b8b917c1c1 -> (final).

**Don't-redo:**
- `apply_item_set` agent replace-by-uid is the canonical multi-set push; legacy wipe-all-RC available via `replace_all_rc=True`.
- `apply_item_sets_batch` is the bulk-push command; use for >1 RC- set in one LCU call.
- `_csvMaybePushBuildsToLCU` is debounced via `_CSV_LAST_PUSH_KEY` - safe to fire on every render.
- Boots scorer="boots" + unit="boots" - downstream consumers MUST filter by `scorer != "boots"` when computing engine-driven aggregates (the ScorerContractTests pattern + DispatchIntegrationTests pattern in tests).
- `_BOOTSLESS_CHAMPS` exception set lives in core/build_order.py; sanity-pinned in tests. Add to set if more bootsless champs surface (operator-flagged).
- The PWA hash-restore fallback (`restorePrefs` extension when ?ui_mock=1) is BROADLY USEFUL - future audit captures with `?ui_mock=1#<view>` auto-clear prior manual sticky.
- DS engine SHARED with all callers: archetype_dispatch invokes plan_build_order with default `inject_boots=True` so live coaching now includes boots. Tests of engine semantics use `inject_boots=False` to isolate.
- The page #8 audit ritual (visual-hierarchy audit subagent per [[feedback_phase3_fixture_ritual]]) is STILL OWED before /done locks the page. Operator signaled /done + /clear before the next-session audit ritual - next session continues SR variant tweaks per operator's request.

**Carries forward:**
- Item 162 carries (a)-(g) unchanged EXCEPT (a)-relaxed: pages #7 + #4 visual closed; #8 SR shipped. 8 remaining pages in v2.1 audit order: #9/10 Champ Select ARAM/Arena -> #11/12/13 Active Match SR/ARAM/Arena -> #14/15/16 PGR SR/ARAM/Arena.
- Page #8 audit ritual (visual-hierarchy subagent re-run) STILL OWED. Operator continues SR variant tweaks next session.
- Operator-gated verification: LCU multi-itemset push verification via Practice Tool match + Game-PC monitor 0 capture of mid-match item-shop dropdown.
- RC-PostmortemAnalyze first scheduled run TOMORROW 2026-05-24 04:15.
- Page #6 Home dev.js:337 verdict.team_won null bug, page #4 history mock-vs-render field-name mismatch, page #3 Replay flex-allocation re-tune, Active Match stale-detection fix - all operator-gated.
- DD Defy / Live ARAM-SR smoke / calibrations / cc_conditional wave 12+ deferred / 542 U+2500 chars / Legion 1-PC consolidation - all operator-gated.

---
# 2026-05-23 - items 159-162 UI scale v2.1 pages #3 Replay + #4 History + #5 Session + #6 Home SHIPPED (6 commits `0d77e05` `69249f0` `6d55f63` `d677daf` `b3e14c1` `84b99a8`, pushed origin/main `2dfe8ac..84b99a8`; non-engine; non-frozen; no DS restart; no RC restart - ADR-008 asset-hash auto-served throughout)

Item 158's 16-page v2.1 audit order continued. 4 consecutive pages migrated end-to-end (CSS to v2.1 tokens + per-page mock fixture at `web/data/ui_mock/<page>.json` + dev-toggle mock-fetch branch consulting `body.dataset.uiMock`). 7-step audit ritual GREEN on all 4 pages; visual proof captured on Game-PC monitor 1 except page #4 History (operator entered ARAM Mayhem mid-edit -> dashboard auto-routed away).

**Per-page deltas:**
- **#3 Replay** (`69249f0` CSS + `6d55f63` mock+wire + `0d77e05` item-158 fixture flip Eyeball Collection -> Sixth Sense): primitives.css L144-288 (.replay-* list/main/grid) + replay_events.css ribbon all token-migrated; champ-icon 28->38, item-icon 22->30, match-row min-height: var(--hit-min). 4-match fixture (full Normal Draft 10p + Arena overflow + ARAM empty + 2p ranked-solo). 3 fetch sites wired (`_replayViewRefresh` + `_replayLoadMatch` + `loadReplayEvents`).
- **#4 Replay** (`d677daf`): header.css L585-599 (.view-tab shared rule) + L1794-1830 .history-grid/card/session/match-row. 4-scope fixture (14d / season / prior_season / all-empty-edge) keyed by `payload.scopes[scope]` with 14d fallback. **VISUAL DEFERRED** to next non-active-game window.
- **#5 Session** (`b3e14c1`): header.css L1772-1797 .session-grid/card/row/champ-list/match-list. 6-game session fixture (32/14/47 KDA + S/A/B grades + 5 champs + 5 matches). Visual GREEN after Ctrl+Shift+R hard-reload (mock not fired on first nav due to service-worker cache).
- **#6 Home** (`84b99a8`): home.css .home-* migrated (.lobby-* + .cs-* INTENTIONALLY preserved on v1 - pages #7 + #8-10 in audit order). Full Home payload fixture (today.games=4 + streaks 5-day/3-S-A-row + recent[5] + this_week[5] with full kills/deaths/assists/cs_total breakdown + services[6] + trends 14-day sparkline series with null gap + tonight_pick Jinx + last_build 6-item). Visual GREEN: hero + 3 chips with sparklines + 7 action tiles + Tonight's Pick card + LAST BUILD strip + RECENT 5 + THIS WEEK.

**Mid-session BUG SURFACED + MITIGATED:** operator reported "active match does not match" - dashboard rendered 14-hour-old Kai'Sa snapshot during Senna ARAM loading screen. Root cause: liveclient :2999 not exposing active_player during loading; coaches haven't refreshed; dashboard fell through to stale `data/aram_coaching_data.json`. Force-cleared the file (backup `data/aram_coaching_data.json.bak-20260523-135434` preserved). View auto-routed to PRE-GAME LOBBY post-clear.

**Verified:** Phase 8 smoke 75/75 PASS throughout. 0 new non-ASCII bytes per file-by-file diff scan. RC :8888 mode=client/aram alive=True reload_ok=True pid=14464 stable. DS :8893 untouched. Asset hash flow: fc4ff80c8b -> 682a4518c8 -> 3994d709da -> 48a31749d7 -> b805d11ec3 -> 67d175f339 -> 5c6b5a4247. Live UI hash = HEAD post-push.

**Don't-redo:**
- Mock-fixture pattern is canonical: module-level `_<page>MockPromise` + `_<page>IsMock()` + `body.dataset.uiMock` + `?ui_mock=1` URL flag. Mirror for pages #7-#16; each fixture MUST match render code field names (page #6 surfaced kda vs avg_kda + grade vs best_grade renaming).
- `.lobby-*` + `.cs-*` CSS in home.css stays on v1 tokens until their pages (#7 Pre-Game Lobby + #8-10 Champ Select) hit the audit order.
- The Eyeball Collection -> Sixth Sense fixture flip closes item 158's owed visual capture; don't re-investigate.
- Active Match stale-detection bug: when `liveclient.champ=null + coaching_data.mtime > N min`, render should show empty "waiting for game start" state instead of stale snapshot. Separate fix needed (operator-gated).

**Carries forward:**
- Page #4 History visual proof owed at next non-active-game window.
- Page #3 Replay finding: 10-row participant table collapses to ~0 visible rows when 15-event timeline saturates `max-height: 480`. Pre-existing flex allocation edge made visible by v2.1 +44% row height. Worth re-tuning `.replay-grid-wrap` min-height in follow-up.
- Page #6 Home pre-existing bug: meta-line verdict at dev.js:337 `verdict.team_won ? "(W)" : "(L)"` treats null win as "(L)". ARAM neutral mock surfaces it.
- 10 remaining pages in v2.1 order: #7 Pre-Game Lobby -> #8/9/10 Champ Select SR/ARAM/Arena -> #11/12/13 Active Match SR/ARAM/Arena -> #14/15/16 PGR SR/ARAM/Arena.

---
# 2026-05-23 - item 158 UI scale v2.1 page #2 User Builds + rune-page builder + spell chooser SHIPPED (2 commits `a82d8f3` `5452e9e`, pushed origin/main `dffea08..5452e9e`; non-engine; non-frozen; no DS restart; RC pid drifted 7356 -> 14464 mid-session via supervisor auto-relaunch picking up coaches/sr_user_builds.py edit - reload_ok=True)

Operator-driven continuation of item 157's 16-page UI scale v2.1 audit order. Page #2 (User Builds) shipped end-to-end + mid-round augmentation: form pane gained a tabbed 5-tree rune-page builder + 11-icon summoner-spell chooser.

**Commit `a82d8f3` (page #2 base, 4 files / +292 / -48):**
- `web/css/panels/header.css` `.ub-*` classes migrated to v2.1 tokens (--fs-xs/sm/md, --space-1..5, --panel-padding, --panel-radius, --panel-radius-sm, --hit-min). 30+ surgical replacements; per-class deltas tabulated in spec.
- `web/js/main.js::_userBuildsFetchAndRender` consults `body.dataset.uiMock`; loads `/data/ui_mock/user_builds.json` when live is empty + mock is on. Renders `(MOCK)` suffix on label + count + hint.
- `web/data/ui_mock/user_builds.json` NEW 5-build Tristana fixture (populated + role-variant + overflow + minimal edge cases).
- `web/js/main.js` boot restorePrefs adds `?ui_mock=1` URL-search override so headless captures hit mock state without touching interactive Chrome localStorage.
- `docs/UI_SCALE_SPEC_V2.md` per-component-class table for User Builds + mock fixture doc + audit ritual additions.
- Asset hash `e9dad0bf6b -> 87ddde541c`. 7/7 audit ritual checks GREEN via 2 headless Game-PC captures.

**Commit `5452e9e` (rune-builder + spell-chooser, 6 files / +629 / -29):**
- `web/index.html` form-pane: Keystone / Primary tree / Secondary tree inputs marked `readonly` with `(driven by builder)` em hint. Summoner-spell numeric inputs become hidden + driven by chooser. NEW `.ub-sp-chooser` + `.ub-rp-builder` blocks.
- `web/js/main.js` +355 LOC: `_UB_SPELLS` 11-spell catalog, `_RP_DDRAGON_BASE` constant, `_RP` + `_SP` state objects. Spell chooser: 2 slot buttons + 11-cell grid; click slot D/F to activate, click spell to assign, auto-flips active slot. Rune builder: lazy fetch `/api/dictionary/runes`, render 5 tabs (Domination/Inspiration/Precision/Resolve/Sorcery), PRIMARY pane shows keystone row + 3 minor rows (1 pick per row), SECONDARY pane shows pill row of 4 other trees + 3 minor rows (up to 2 picks total). `.ub-rp-summary` one-line preview of current picks. `_ubRpSyncTextFields` keeps readonly Keystone/Primary/Secondary text inputs aligned with builder state. `?ub_form=mock` URL flag auto-opens form with first mock build pre-loaded.
- `web/js/main.js::_ubReadForm` extended to write `runes.minor_primary[]` + `runes.minor_secondary[]` on save.
- `coaches/sr_user_builds.py::_normalize_record` extended additively to persist + sanitize minor_primary + minor_secondary (list[str], default empty). `format_for_display` unchanged - downstream chooser surface untouched. 22/22 phase8_smoke/test_sr_user_builds PASS post-edit; python smoke (minor runes round-trip through add->list) PASS. ruff PASS.
- `web/css/panels/header.css` +178 LOC: `.ub-sp-*` + `.ub-rp-*` classes, all token-driven, --hit-min on all interactive cells, --panel-radius-sm on icons.
- `web/data/ui_mock/user_builds.json` first build extended with minor_primary/secondary lists.
- `docs/UI_SCALE_SPEC_V2.md` "User Builds form-pane augmentation" section: component-class table + DDragon image base + schema extension + round-trip notes.
- Asset hash `87ddde541c -> fc4ff80c8b`.

**Verified:**
- RC dashboard https://127.0.0.1:8888/api/state HTTP 200; mode_key=client throughout.
- `/api/ui-version` shows `fc4ff80c8b` post-commit (ADR-008 auto-reload).
- RC health: pid drifted 7356 -> 14464 mid-session (RC-Supervisor auto-relaunch picked up the coaches/sr_user_builds.py edit). alive=True reload_ok=True post-relaunch.
- Backend persistence: Python smoke test asserts minor_primary/secondary round-trip through `add()` -> `list_for()` cleanly. format_for_display unchanged.
- Phase 8 smoke 75/75 PASS post-edit. ruff clean.
- Headless captures: empty state + populated mock list both render correctly at v2.1 sizing. Form-pane visual capture (showing builder tabs + spell grid) NOT captured this session - headless Chrome session isolation from non-interactive PowerShell hung repeatedly. Form HTML/CSS/JS is mechanical extension of working code; visual verification owed at operator's next interactive Chrome session.

**Don't-redo:**
- `?ub_form=mock` is the canonical dev URL flag for auto-opening the form with the first mock build pre-loaded; requires `?ui_mock=1` to be set. Don't add another flag for the same purpose.
- Rune-builder schema is `runes.minor_primary[]` + `runes.minor_secondary[]` (additive; empty lists when absent). Don't rename or restructure; downstream `format_for_display` ignores them today (champ-select chooser surface unchanged).
- `_RP` + `_SP` are module-level state singletons (one form open at a time). Don't refactor into per-instance state - the form pane is single-instance + single-mode.
- DDragon image base in JS is HARDCODED to `/data/ddragon/16.10.1/img/` (matches what `routes_dictionary.py` serves from `data/meta/ddragon_runes.json`). Both update in lockstep on the operator-triggered patch refresh; don't add a `/api/ddragon/current` indirection just to dynamically resolve.
- Rune-page minor-rune row enforcement is INTENTIONALLY soft: primary side restricts to 1 pick per row (single-select toggle), secondary side allows up to 2 picks total with no per-row check. Game rules enforce stricter constraints client-side at the Riot client; RC's user-builds store is operator-curated additive, NOT pushed to LCU.
- Headless Chrome screenshot of the form-pane via `mcp__gamepc__run_powershell` is FRAGILE: virtual-time-budget + setTimeout(_userBuildsOpenForm, 100) race + chrome lifecycle in non-interactive session hung 3 attempts. Form-pane visual verification owed at operator's next interactive session. Pattern for future: drive via the existing Chrome on Game-PC monitor 1 if SendKeys-from-service-session can be made to land (item 158 attempts failed at AppActivate / SetForegroundWindow due to session 0 vs interactive session isolation).

**Carries forward:**
(a) Item 157 carries (a)-(l) ALL unchanged EXCEPT (k)-relaxed: User Builds (page #2) is NO LONGER pending - SHIPPED this session.
(b) 14 remaining pages in the UI scale v2.1 audit order: Replay (#3) -> History (#4) -> Session (#5) -> Home (#6) -> Pre-Game Lobby (#7) -> Champ Select SR/ARAM/Arena (#8/9/10) -> Active Match SR/ARAM/Arena (#11/12/13) -> Post Game Review SR/ARAM/Arena (#14/15/16). Per-page mock fixture owed at `web/data/ui_mock/<page>.json`.
(c) Form-pane visual verification for the new rune builder + spell chooser owed at operator's next interactive Chrome session (headless capture race hung 3 attempts; backend + ruff + 75/75 smoke PASS).
(d) RC-PostmortemAnalyze first scheduled run TOMORROW 2026-05-24 04:15 - verify LastTaskResult=0 next session.
(e) DD Defy heal-on-takedown STILL deferred. Live ARAM/SR smoke STILL pending. Calibrations operator-gated. cc_conditional wave 12+ 2 deferred candidates. 542 residual U+2500 box-drawing chars operator-gated. Legion 1-PC consolidation operator-gated.

---
# 2026-05-23 - item 157 UI scale v2.1 - per-element ~44% bump (25% + 15%) + zoom feature retired - Settings worked example SHIPPED (1 commit `09eddeb`, pushed origin/main `1d5ef99..09eddeb`; non-engine; non-frozen; no DS restart; no RC restart - asset-hash auto-reload per ADR-008)

Operator triggered global UI density refactor across 16 pages (Settings -> User Builds -> Replay -> History -> Session -> Home -> Pre-Game Lobby -> Champ Select SR/ARAM/Arena -> Active Match SR/ARAM/Arena -> Post Game Review SR/ARAM/Arena). One framed AskUserQuestion 4-question scope fork pinned per [[feedback_scope_decision_cadence]]: (Q1) Spec doc + tokens.css draft + Settings rendered preview reviewed together (Recommended); (Q2) Density modes - single Comfortable/Broadcast target now, multi-mode primitive deferred (Recommended); (Q3) Page order - operator's verbatim list (Recommended); (Q4) Dummy data - dev-only Settings toggle default OFF.

**Shipped (7 files / +457 / -96):**
- `docs/UI_SCALE_SPEC_V2.md` NEW - typography matrix (v1 / v2 25% / v2.1 +15% columns) + 8-px spacing matrix + panel rules + interaction rules + dummy-data architecture + UI audit ritual v2 checklist + per-page execution order + per-component-class Settings targets + cleanup deltas.
- `web/css/tokens.css` extended additively. Font scale v1 11/13/15/20/27 -> v2.1 16/18/22/29/37 + NEW tiers --fs-stat 26 + --fs-display 46. Panel tokens: --panel-padding 20, --panel-padding-comp 14, --panel-padding-loose 28, --panel-gap 14, --panel-gap-tight 10, --panel-radius 18, --panel-radius-sm 10. Interact tokens: --hit-min 42, --hover-pad 8, --tooltip-offset 12, --tooltip-delay 250ms, --focus-ring. NEW --space-7 40 + --space-8 48. v1 --space-1..6 unchanged (audit-wave-1 contract preserved).
- `web/css/panels/header.css` settings-card / settings-card-head / settings-row / settings-row inputs token-driven; .view-section-head h2 -> --fs-lg 29px (affects all view-sections via single selector). Checkbox 14x14 -> 24x24, card padding 12-14 -> 20, card border-radius 8 -> 18, inter-card gap 14 -> 32.
- `web/css/panels/base.css` `body { zoom: 1.0 }` declaration REMOVED + comment block updated to document zoom feature retired.
- `web/index.html` Zen mode `<label class="settings-row">` row REMOVED + zoom slider row REMOVED + Dev UI mock data toggle ADDED in DISPLAY card.
- `web/js/panels/dev.js` zoom slider wiring removed; cb("set-ui-mock", "rc-ui-mock", v => body.dataset.uiMock = v ? "1" : "") added.
- `web/js/main.js` boot zoom-restore removed; Shift+R + prefs-chip-click no longer touch rc-zoom; tooltip place() function no longer divides by getComputedStyle(body).zoom; prefs-chip footer pill is ui-mock:on (was zoom).

**Verified:**
- RC dashboard https://127.0.0.1:8888/api/state HTTP 200, mode_key=client throughout (never restarted - ADR-008 unified asset-hash auto-reloaded CSS+JS edits, asset hash 8d3c7bcb7d -> 2579468dff between captures).
- Game-PC monitor 1 captured 2x (pre-bump baseline + post-+15% delta). Settings page reads at comfortable viewing distance; zoom slider gone, mock toggle wired + functional (UI-MOCK:ON pill visible when checked); checkboxes 24x24 read fingertip-scale; section heads 29px (was 17px) clearly prominent.
- RC health pid=7356 alive=True reload_ok=True throughout.
- No tests touched (pure UI refactor, no logic change).

**Don't-redo:**
- Zoom feature is FULLY RETIRED. Do NOT reintroduce `body { zoom: N }`, the `#set-zoom` slider, or the `localStorage.rc-zoom` key. The 4 lazy mechanisms (transform: scale, body zoom, browser zoom, root font-size hack) are documented in docs/UI_SCALE_SPEC_V2.md as OFF-LIMITS for this refactor.
- The +15% second-pass values (16/18/22/26/29/37/46) ARE the v2.1 baseline. If operator asks for "another 15%" treat that as v2.2 explicitly.
- The tooltip `place()` function in `main.js:6113` is now in plain viewport CSS pixels - the prior zoom-divisor was specific to the old 1.33 body-zoom era and is dead-weight removed.
- The `champ_select.js:268-274` popup workaround appends to `<html>` to bypass body-zoom; the workaround is HARMLESS now that body-zoom is gone but its reasoning is stale. Audit-ritual step 7 covers this when Champ Select pages (#8/9/10) hit the order.
- Settings is the WORKED EXAMPLE not the locked ship-state. Operator approved (issued /done) so v2.1 token values + Settings layout are LOCKED for subsequent pages.
- 27 panel CSS files + 27 panel JS files + 583 hardcoded font-size declarations across 29 CSS files - the page-by-page audit pass sweeps its OWN panels only. Do NOT do a bulk font-size sweep.

**Carries forward:**
(a) Item 156 carries ALL unchanged - this session was NON-engine, NON-frozen, NON-test (zoom feature retirement was the only "code-deletion" lever; everything else was additive token + selector tuning).
(b) RC-PostmortemAnalyze first scheduled run TOMORROW 2026-05-24 04:15 - verify LastTaskResult=0 next session.
(c) DD Defy heal-on-takedown STILL deferred.
(d) Live ARAM/SR smoke STILL pending.
(e) Calibrations STILL operator-gated.
(f) UI/UX live-game audit owed.
(g) DS conditional arc operator-CLOSED (s232).
(h) Legion 1-PC consolidation STILL operator-gated.
(i) cc_conditional wave 12+ has 2 deferred candidates (Jayce E + Singed E) needing further schema lifts.
(j) 542 residual U+2500 box-drawing chars carry forward as operator-gated separate sweep.
(k) **NEW carry from item 157**: 15 remaining pages in the UI scale v2.1 audit order (User Builds -> Replay -> History -> Session -> Home -> Pre-Game Lobby -> Champ Select SR/ARAM/Arena -> Active Match SR/ARAM/Arena -> Post Game Review SR/ARAM/Arena). Each page consumes v2.1 tokens during its own audit pass per the UI audit ritual v2 checklist in `docs/UI_SCALE_SPEC_V2.md`. Per-page mock fixtures owed at `web/data/ui_mock/*.json` for the dev UI mock data toggle to render anything; no fixtures shipped this session.
(l) **NEW carry from item 157**: 583 hardcoded font-size declarations across 29 CSS files will be swept incrementally per page-audit pass; no bulk sweep authorized.

---
# 2026-05-23 - item 156 operator-gated decision-owed parallel drain #4: rc_supervisor FROZEN mojibake byte-repair + Variant B em-dash mojibake closure + cc_conditional wave 11 Sion R + Gnar W form 1 + housekeeping triple SHIPPED (4 commits + 3 merges + docs sync follow-up, pushed origin/main; ENGINE 1.47.0 -> 1.48.0; DS :8893 restarted serves 1.48.0; RC :8888 unchanged)

Operator triggered fourth consecutive "in parallel : start all open items in Operator-gated, decision owed" drain. AskUserQuestion 4-question scope fork pinned: (Q1) rc_supervisor.py 1368 mojibake byte-repair Grant + repair; (Q2) cc_conditional wave 11 Full pass (Recommended); (Q3) DD Defy Defer (Recommended); (Q4) Add housekeeping CLEAN slices explicitly. 3 worktree agents dispatched concurrent (orchestrator pattern items 134-155 extended to 21 consecutive runs).

**Slice A `8ab3822` (merge `3fe431b`) chore(frozen) rc_supervisor.py mojibake byte-repair + Variant B em-dash mojibake closure (8 files / +246 / -136):**
- Critical discovery: item 155's signature `c3 a2 e2 80 9d e2 82 ac` is actually U+2500 box-drawing mojibake (bytes e2 94 80 = UTF-8(U+2500) -> CP-1252 mis-decode -> re-encode UTF-8 `c3 a2 e2 80 9d e2 82 ac`). The canonical em-dash mojibake (Variant B) signature is `c3 a2 e2 82 ac e2 80 9d` (bytes e2 80 94 = UTF-8(U+2014) -> CP-1252 mis-decode -> re-encode UTF-8 `c3 a2 e2 82 ac e2 80 9d`).
- `tools/repair_mojibake.py` extended to detect both variants + add `--allow-frozen <comma-csv>` flag (mirrors item 155 strip_smart_quotes pattern) + empty `_HARD_SKIP_FROZEN: frozenset[str] = frozenset()` defense-in-depth constant.
- Per-file pre/post: ops/rc_supervisor.py Variant A 1368 -> 0 + Variant B 12 -> 0 (operator-granted frozen-file write); tft/tft_coach_engine.py Variant B 22 -> 0; ops/rc_self_monitor.py Variant B 5 -> 0; ops/rc_state_validator.py Variant B 3 -> 0.
- Smart-quote follow-through: 1410 U+2014 em-dashes normalized to ASCII ` - `.
- `tools/strip_smart_quotes.py` emptied `_HARD_SKIP_FROZEN` (was `{ops/rc_supervisor.py}`; post-repair the corruption-risk rationale no longer applies).
- Drift guards `tests/test_mojibake_hygiene.py` + `tests/test_smart_quote_hygiene.py` extended to cover both variants + remove rc_supervisor from frozen exclusion list.

**Slice B `5ec3d65` (merge `9c5cba1`) feat(ds) cc_conditional wave 11 - Sion R + Gnar W form 1 (35 files / +788 / -33):**
- Re-audit of REJECT carries from item 153 against item 154's `effects_descriptions` + sidecar registry produced 2 new entries / 2 net-new champs.
- **Sion R Unstoppable Onslaught** PRIMARY: stun 1.0s representative midpoint, COND_CHANNEL_COMPLETION 0.5; effects_descriptions evidence "stunned after a brief delay for 0.25 : 1.75 (based on channel time) seconds". Coexists with Sion Q unconditional 1.25-2.25s stun (different spell slot).
- **Gnar W form_index=1 Wallop** SIDECAR Mega-rage-form-gated: stun 1.25s flat, COND_FRENZY_STATE 0.4; THIRD consumer of COND_FRENZY_STATE after Renekton W wave 9 + Karma W form 1 wave 10. Coexists with Gnar R unconditional 0.75s terrain-collision stun (different spell slot).
- REJECT-confirmed (effects_descriptions evidence): Aatrox R minion-only fear / Volibear R turret-disable + slow only / Briar W self-buff frenzy no CC payload / Sion E minion-only stun / Lillia W damage only / Ekko R self-stasis + damage only / Smolder R damage + heal only / Karma E shield + MS both forms / Vladimir R damage amp + delayed burst + heal / Akshan Q+R damage + buffs only / Tristana E damage stacking only / Kayle E+R no CC / Nidalee R/Q/W/E transform + no champion CC.
- Deferred wave 12+: Jayce E (cast_time value missing from schema) + Singed E Mega-Adhesive overlap root (2-spell-overlap target-debuffed encoding not supported).
- ENGINE 1.47.0 -> 1.48.0 + 32 stale ENGINE pin syncs across DS test files.
- NEW `agents/daemon_slayer/tests/test_cc_conditional_wave11.py` 46 tests across 11 classes.
- REGISTRY_TOTAL_CHAMPIONS=38 -> 40 / REGISTRY_TOTAL_ENTRIES=44 -> 46 (43 primary + 3 sidecar). Default include_conditional=False math BYTE-IDENTICAL to 1.47.0.

**Slice C `bdb0043` + `60c8d37` (merge `c1a88b5`) housekeeping triple (6 files / +8 / -8):**
- Sub-task 1 stale-sweep wave 14: 3 flips (BACKLOG L13 cc_conditional ecosystem stale counts; ROADMAP L22 stale dashboard.js:5055 ref removed; ROADMAP L80 gamepc_lcu_agent.py:777 -> :1091).
- Sub-task 2 cost/latency CLEAN wave 17 no-commit: 17th consecutive CLEAN sweep since item 134. All 7 levers + cost-trace 11 wires intact.
- Sub-task 3 living docs sync: DAEMON_SLAYER.md/ARCHITECTURE.md/README.md/BRIEF.md test count 4130 -> 4132 (pre-Slice-B baseline; post-Slice-B sync via this item's follow-up commit).
- Sweep cycle decay: 1=2 / 2=3 / 3=3 / 4-12=1 / 13=0 / **14=3** (rebound from items 149-155 churn).

**Merge order:** A `3fe431b` -> B `9c5cba1` -> C `c1a88b5`. 0 merge conflicts (disjoint file sets). One mid-flight recovery: initial Slice A merge accidentally landed on Slice B's worktree branch due to persisted shell cwd; recovered via `git reset --hard 5ec3d65` on Slice B worktree + re-merging from C:\Riot Commander cwd.

**Verified:**
- DS suite `agents/daemon_slayer/tests/` = **4176 passed / 1 skipped / 1 xfailed / 1731 subtests in 67.88s** (+46 over 4130 baseline = exactly the wave 11 test file).
- RC suite `tests/` (excl phase8_smoke) = **3257 passed / 67 subtests in 56.17s** (unchanged from item 155 baseline).
- `tests/phase8_smoke/` = 75/75 PASS post-DS-restart.
- `py -m ruff check .` ALL CHECKS PASSED.
- DS :8893 killed pid 10516 + `schtasks /Run /TN RC-DaemonSlayer` (per [[reference_ds_server_not_supervisor_watched]]) -> serves engine_version=1.48.0 / patch=16.10.1 / 172 champs / 705 items.
- RC :8888 responsive throughout (mode_key=client; never restarted - DS engine + tools + tests + docs only; supervisor edits take effect on next supervisor restart which operator can choose).

**Don't-redo:**
- Mojibake Variant identification is now definitive: Variant A `c3 a2 e2 80 9d e2 82 ac` = U+2500 box-drawing mojibake (NOT em-dash as items 154+155 ledger claimed); Variant B `c3 a2 e2 82 ac e2 80 9d` = canonical em-dash mojibake. Both repaired across non-frozen + rc_supervisor.py.
- 542 residual U+2500 box-drawing chars (rc_supervisor 58 + rc_self_monitor 484) are INTENTIONAL docstring tree-drawing chars - operator-gated separate sweep needed if desired.
- cc_conditional wave 11 methodology (re-audit prior REJECT carries against LATEST schema-lift + sidecar registry) is durable for future waves; the 14 REJECT-confirmed verdicts with effects_descriptions evidence are CONFIRMED NEGATIVES.
- Shell-cwd persistence between Bash calls is a HAZARD: use `git -C "<path>"` for explicit-cwd or verify pwd before destructive ops.
- Orchestrator-merge pattern now 21 consecutive runs (items 134-156).

**Carries forward:** (a) Item 155 carries ALL unchanged EXCEPT (a)-relaxed: rc_supervisor.py mojibake byte-repair NO LONGER operator-gated (DONE this session). (b) RC-PostmortemAnalyze first scheduled run TOMORROW 2026-05-24 04:15. (c) DD Defy heal-on-takedown STILL deferred. (d) Live ARAM/SR smoke STILL pending. (e) Calibrations STILL operator-gated. (f) UI/UX live-game audit owed. (g) DS conditional arc operator-CLOSED (s232). (h) Legion 1-PC consolidation STILL operator-gated. (i) cc_conditional wave 12+ has 2 deferred candidates (Jayce E + Singed E) needing further schema lifts. (j) 542 residual U+2500 box-drawing chars carry forward as operator-gated separate sweep. (k) Operator-gated decision-owed lane EXHAUSTED for actionable headless items at item 156 ship time. Frozen-file grant USED for ops/rc_supervisor.py; NOT used for any other frozen file.

---
# 2026-05-23 - item 155 operator-gated decision-owed parallel drain #3: mojibake byte-repair + frozen smart-quote sweep + L31 round 3 lcu/+coach_integration/+agents/ SHIPPED (3 commits + 3 merges, pushed origin/main `22a56bd`; non-engine; no DS restart; RC :8888 unchanged - non-frozen + frozen-grant scoped)

Operator triggered third consecutive "in parallel : start all open items in Operator-gated, decision owed" drain. AskUserQuestion 4-question scope fork pinned: (Q1) Mojibake UTF-8 byte-repair on 4 flagged files Repair (Recommended); (Q2) Frozen smart-quote sweep Grant + sweep 3 trivial only - rc_supervisor NOT granted (Recommended); (Q3) L31 round 3 All three surfaces lcu/+coach_integration/+agents/ (Recommended); (Q4) cc_conditional wave 11 Skip / defer (Recommended - no clear candidate). 3 worktree agents dispatched concurrent (orchestrator pattern items 134-154 extended to 20 consecutive runs).

**Slice A `4122d41` (merge `bd2d861`) tools mojibake UTF-8 byte-repair on 3 non-frozen files + drift guard (5 files / +430 / -21):**
- NEW `tools/repair_mojibake.py` reads bytes, detects 8-byte signature `c3 a2 e2 80 9d e2 82 ac` (latin-1-misdecoded UTF-8 em-dash), replaces with proper 3-byte UTF-8 em-dash `e2 80 94`. Atomic `tmp.write_bytes + os.replace`. Frozen-file hard-skip allowlist mirrors `strip_em_dashes.py` + `strip_smart_quotes.py`. `--dry-run` default + `--apply` flag.
- Per-file pre/post mojibake counts: `ops/rc_self_monitor.py` 534 -> 0; `ops/rc_state_validator.py` 256 -> 0; `tft/tft_coach_engine.py` 75 -> 0. (Carry-forward stated 539/259/97 = PRE-item-154 totals incl. clean U+201D; item 154 smart-quote sweep cleaned 5/3/22 clean-context bytes leaving 534/256/75 mojibake. Math reconciles.)
- `ops/rc_supervisor.py` 1368 hits UNTOUCHED (FROZEN-NO-GRANT this session; defense-in-depth hard-skip even if tool's argv accidentally targets it).
- Byte deltas (8B sig -> 3B em -> 3B ` - ` follow-through = -5B/sig): rc_self_monitor 52003 -> 49333 (-2670); rc_state_validator 10542 -> 9262 (-1280); tft_coach_engine 36356 -> 35981 (-375).
- Smart-quote sweep follow-through ran after byte-repair: 865 U+2014 -> ` - ` across the 3 files.
- NEW `tests/test_mojibake_hygiene.py` drift guard (3/3 PASS) walks repo with same exclusions + asserts no `c3 a2 e2 80 9d e2 82 ac` signature in tracked byte streams.

**Slice B `6024ccc` (merge `fd91117`) chore(frozen) smart-quote sweep on 3 trivial frozen-file hits via item 155 operator grant (4 files / +51 / -5):**
- Added `--allow-frozen <csv-paths>` argv flag to `tools/strip_smart_quotes.py` + `_HARD_SKIP_FROZEN={ops/rc_supervisor.py}` defense-in-depth constant. Rewrite-branch gates on `allow_override = (rel_posix in _allow_frozen) and not is_hard_skip`. Report prints overridden + hard-skipped-from-override lists.
- 3 grant-targeted single-codepoint hits swept: `ops/rc_dev_runtime.py` U+2026 1 -> 0 (DailyRotatingFileHandler backup-suffix docstring); `core/moon_proxy.py` U+2026 1 -> 0 (Moon vision dedupe debug); `core/log_setup.py` U+2026 1 -> 0 (Popen verify-window AUDIT docstring).
- `ops/rc_supervisor.py` UNTOUCHED confirmed via git status + file size 79885 unchanged + hard-skip listed in report. NOT in modified set.
- Drift guard `tests/test_smart_quote_hygiene.py` 3/3 PASS post-sweep. Combined `test_smart_quote_hygiene + test_frozen_files_sync` 6/6 PASS.

**Slice C `3fd9f4a` (merge `22a56bd`) chore(types) L31 round 3 - type annotations on lcu/+coach_integration/+agents/ public APIs (5 files / +23 / -23):**
- 19 surgical sites total: lcu 9 + coach_integration 9 + agents 1 (+2 stub return types) + 1 import.
- Files: `lcu/lcu_postgame_collector.py` + `coach_integration/_coach.py` + `coach_integration/_sr_prompt.py` + `coach_integration/_profiles.py` + `agents/agent7_context/warm_session.py`.
- 0 ruff violations / 0 reverts / 0 frozen-file touches (`lcu/lcu_client.py` hard-skipped per CLAUDE.md).
- Surface saturation: `lcu/lcu_pregame.py` + `lcu/lcu_rune_writer.py` + `coach_integration/{enemy_stats,archetype_dispatch}.py` + `agents/{_supervisor_*, supervisor, agent6_auditor/*, agent7_context/{input_parser,ui_feedback}}.py` ALREADY FULLY ANNOTATED (use `__future__ annotations` or pre-typed). Branch name `worktree-slice-c-l31-r3` (agent self-named; non-standard but functional).

**Merge order:** A `bd2d861` -> B `fd91117` -> C `22a56bd`. All 3 ort merges 0 conflicts (disjoint file sets across all 3 slices).

**Verified:**
- RC suite `tests/` (excluding phase8_smoke) = **3257 passed / 67 subtests passed in 56.17s** (+3 over 3254 baseline = exactly new test_mojibake_hygiene.py tests).
- `tests/phase8_smoke/` = 75/75 PASS (no engine change; DS :8893 untouched serves 1.47.0 from item 154 restart).
- `py -m ruff check .` ALL CHECKS PASSED.
- `py -m py_compile` clean on all 13 touched files (5 mojibake + 4 smart-quote + 5 L31, 1 overlap on tft_coach_engine.py).
- RC :8888 responsive throughout (rc.pid=7356 alive=True mode=client; never restarted - non-frozen byte-edits + frozen-grant scoped to 3 trivial files + no coach prompt changes).
- DS :8893 untouched (non-engine session); /health still serves engine_version=1.47.0 from item 154.
- Pushed main as `22a56bd` to origin/main.

**Don't-redo:** The mojibake signature `c3 a2 e2 80 9d e2 82 ac` (8 bytes = U+00E2 U+20AC U+009D U+20AC followed by U+20AC; result of latin-1 misinterpretation of UTF-8 em-dash `e2 80 94` re-encoded UTF-8) is the canonical fingerprint - the `tools/repair_mojibake.py` is the durable tool for any future drift. The drift guard `tests/test_mojibake_hygiene.py` LOCKS the invariant going forward; any future commit that introduces this byte sequence fails CI. The `--allow-frozen` flag on `tools/strip_smart_quotes.py` is the durable mechanism for operator-granted frozen-file sweeps; `_HARD_SKIP_FROZEN={ops/rc_supervisor.py}` is the defense-in-depth constant that prevents accidental sweep of rc_supervisor even if a future grant targets it - bump that constant only with explicit operator authorization. The L31 extension is now CLOSED for lcu/+coach_integration/+agents/ public APIs; the remaining surfaces (`ops/` + `tools/` + `app/` + `tft/` ALREADY DONE in item 154) have nothing significant to annotate. The orchestrator-merge pattern (3-4 worktree agents on disjoint slices + tests gate + RC unchanged + docs sync follow-up commit) is now 20 consecutive runs (items 134-155).

**Carries forward:** (a) Item 154 carries ALL unchanged EXCEPT (a)-relaxed: mojibake byte-repair on 3 non-frozen files NO LONGER operator-gated (DONE this session); 3 trivial frozen-file smart-quote sweeps NO LONGER operator-gated (DONE); L31 extension to lcu/+coach_integration/+agents/ NO LONGER operator-gated (DONE). (b) RC-PostmortemAnalyze first scheduled run TOMORROW 2026-05-24 04:15 - verify LastTaskResult=0 next session. (c) DD Defy heal-on-takedown STILL deferred. (d) Live ARAM/SR smoke STILL pending. (e) Calibrations STILL operator-gated. (f) UI/UX live-game audit ritual owed once operator plays a real game. (g) DS conditional arc operator-CLOSED (s232). (h) Legion 1-PC consolidation (s169 option B) STILL operator-gated. (i) **STILL CARRY**: `ops/rc_supervisor.py` 1368 mojibake U+201D byte-repair pass (FROZEN - needs explicit grant for that specific file beyond this session's grant). (j) cc_conditional wave 11+ should consume sidecar registry shape directly - skipped this session per no-clear-candidate verdict. (k) Operator-gated decision-owed lane EXHAUSTED for actionable headless items at item 155 ship time (remaining carries are all live-gated, hardware-migration, or frozen-rc_supervisor-only). Frozen-file grant USED this session for 3 trivial files; NOT used for rc_supervisor.

---
# 2026-05-23 - item 154 operator-gated decision-owed parallel drain #2: cc_conditional wave 10 sidecar registry schema lift + smart-quote retro-sweep + L31 extension dashboard/+core/+tft/ SHIPPED (3 commits + 2 merges, pushed origin/main `df50ca9`; ENGINE 1.46.0 -> 1.47.0; DS :8893 restarted serves 1.47.0; RC :8888 unchanged)

Operator triggered "review github branches and close or merge as needed, then in parallel : start all open items in Operator-gated, decision owed". 5 stale remote worktree branches + wave9-cc-conditional-schema-lift all confirmed fully merged into main via `git log origin/main..origin/<branch>` empty diff; deleted via `git push origin --delete` x5. No open PRs. AskUserQuestion 4-question scope fork pinned: (Q1) cc_conditional wave 10 full pass (Recommended); (Q2) Smart-quote retro-sweep (Recommended); (Q3) L31 extension all three surfaces dashboard/+core/+tft/ (Recommended); (Q4) DD Defy SKIP (Recommended - still deferred). 3 worktree agents dispatched concurrent (orchestrator pattern items 134-153 extended to 19 consecutive runs).

**Slice A `20b3afa` (merge `90e3462`) feat(ds) cc_conditional wave 10 closure - same-spell-slot sidecar registry schema lift (36 files / +1097 / -40):**
- Parallel sidecar registry `_PER_SPELL_CC_CONDITIONAL_FORMS: Dict[champion, Dict[(spell, form_index), ConditionalCcEntry]]` in `agents/daemon_slayer/cc_conditional.py` preserves backward compat with ~244 test access lines pinning the primary registry shape `_PER_SPELL_CC_CONDITIONAL[champion][spell]`.
- `ConditionalCcEntry` gains optional `form_index: Optional[int] = None`. `get_conditional_entries()` merges both registries default-first then form_index ASC. New `_apply_per_form_entry_overrides()` extends JSON override key shape with 3-segment `Champion:Spell:FormIndex`.
- Wave 10 closures (+2 entries / 0 net-new champs both multi-form coexistence; 42/38 primary -> 44/38 total):
  - Karma W form_index=1 Mantra-empowered Renewal - root - durations (2.35, 2.45, 2.55, 2.65, 2.75)s at mid Mantra rank 2 (+0.75 bonus) - COND_FRENZY_STATE prob 0.4 (SECOND consumer; closes single-consumer state on wave 7 forward-marker tag) - verified via effects_descriptions[0] "Mantra Bonus: Focused Resolve's root duration is increased ... Renewal scales with Mantra's rank".
  - Hwei E form_index=2 Gaze of the Abyss - root - durations (1.2, 1.4, 1.6, 1.8, 2.0)s across 5 E ranks per Meraki Root Duration block - COND_CHANNEL_COMPLETION prob 0.4.
- NO new condition tag (reuses pre-existing COND_FRENZY_STATE + COND_CHANNEL_COMPLETION).
- ENGINE_VERSION 1.46.0 -> 1.47.0 + 31 DS test files bulk-rewrite of ENGINE pin (assertEqual contexts only).
- +56 tests in NEW `agents/daemon_slayer/tests/test_cc_conditional_wave10.py`: per-entry shape pins + multi-form coexistence + sidecar registry shape + form_index field defaults + REGISTRY_TOTAL growth + COND_FRENZY_STATE 2nd consumer + per-form override parsing + builder idempotence + wired-site grep pins + engine version pin + ASCII hygiene.
- `compute_cc_pressure("Karma", "sr", include_conditional=False) = 0.0` BYTE-IDENTICAL to 1.46.0; True = 1.9 (wave 1 + wave 10 sidecar both contribute).

**Slice B `b045618` tools smart-quote retro-sweep + drift guard test (40+ files via sweep, mojibake-aware byte-level rewrites):**
- NEW `tools/strip_smart_quotes.py` mirrors `tools/strip_em_dashes.py` precedent. Atomic `tmp.write_bytes + os.replace`. Codepoints in source via `chr()` to keep tool ASCII-clean.
- Per-codepoint rewrite counts (pre / post): U+2026 ellipsis 175 -> 0; U+2019 right-quote 12 -> 0 (4 still in frozen-skipped/mojibake); U+201C left-dquote 4 -> 0; U+2018 left-quote 4 -> 0; U+2013 en-dash 4 -> 0; U+2014 em-dash 4 -> 0; U+00A0 NBSP 1 -> 0. U+201D right-dquote 2279 -> 2275 (4 clean replaced; 2275 mojibake-preserved via byte-context detection of latin-1-misdecoded em-dash signature `c3 a2 e2 80 9d e2 82 ac`).
- Frozen-file hits SKIPPED + listed (NOT rewritten): `ops/rc_supervisor.py` (1380 mojibake U+201D), `ops/rc_dev_runtime.py` (1 U+2026), `core/moon_proxy.py` (1 U+2026), `core/log_setup.py` (1 U+2026).
- Mojibake-tainted REFUSED (non-frozen, separate UTF-8 byte-repair pass needed): `ops/rc_self_monitor.py` (539 mojibake U+201D), `ops/rc_state_validator.py` (259), `tft/tft_coach_engine.py` (97 mojibake + 5 clean replacements).
- NEW `tests/test_smart_quote_hygiene.py` drift guard walks repo with same exclusions + asserts no U+201C/U+201D/U+2018/U+2019/U+2013/U+2014 in tracked source (3/3 passes).
- 4 pre-existing drift-guard tests (`tests/snapshot_panels/test_{cd_ledger,spike_curve,ward_heat,draft_elo_panel}.py`) self-violating with literal smart quotes -> refactored to `chr(0x2014)` form.
- Direct push to main (not worktree branch; bash cwd-default behavior; matches item 150 Slice D precedent).

**Slice C `84aadde` (merge `df50ca9`) chore(types) L31 extension - type annotations on dashboard/+core/+tft/ public APIs (14 files / +49 / -45):**
- 44 surgical sites total: dashboard 6 + core 14 + tft 24. Typical patterns: `-> None` for mutators, `-> dict | None` / `Optional[T]` for readers, `-> "TftSnapshot | None"` via TYPE_CHECKING forward-ref in `tft/tft_state_reader.py`.
- Files: `core/coaching_data_lock.py` + `core/decision_detector.py` + `core/match_db.py` + `core/resource_manager.py` + `core/vision_tracker.py` + `dashboard/_context.py` + `dashboard/_handler.py` + `dashboard/server.py` + `tft/tft_coach_engine.py` + `tft/tft_live_analysis.py` + `tft/tft_ocr_reader.py` + `tft/tft_pbe_engine.py` + `tft/tft_state_reader.py` + `tft/tft_vision_reader.py`.
- 0 ruff violations / 0 reverts / 0 frozen-file touches.
- SKIPPED deliberate: `compute_cc_pressure` fallback stubs already `# type: ignore[misc]`, inner closures, dashboard route inner matchers already typed.

**Merge order:** Slice B pushed directly to main first `b045618`; Slice A worktree merged into main second as `90e3462` (ort, 0 conflicts, 36 files); Slice C worktree merged into main third as `df50ca9` (ort, auto-merged dashboard/_handler.py + tft/tft_coach_engine.py without conflict, 14 files). 0 merge conflicts across all 3 slices.

**Verified:**
- DS suite `agents/daemon_slayer/tests/` = **4130 passed / 1 skipped / 1 xfailed / 1726 subtests passed in 68.23s** (+56 vs 4074 baseline = exactly the wave 10 test file).
- RC suite `tests/` (excluding phase8_smoke) = **3254 passed / 67 subtests passed in 55.51s**.
- `tests/phase8_smoke/` = 74 passed / 1 failed pre-DS-restart; resolved post-restart to 75/75 (the 1 was the documented `test_live_three_profiles` engine pin mismatch per [[reference_ds_server_not_supervisor_watched]]).
- DS :8893 killed pid 9936 -> 10516 + `schtasks /Run /TN RC-DaemonSlayer` -> `/health` serves `engine_version=1.47.0 patch=16.10.1 champions=172 items=705`. HTTP not HTTPS at :8893 (DS server scheme reaffirmed).
- `py -m ruff check .` ALL CHECKS PASSED.
- `py -m py_compile` clean on all 15 touched files.
- RC :8888 responsive throughout (rc.pid=7356 alive=True mode=client; never restarted - non-frozen + non-coach-prompt edits).
- Pushed main as `df50ca9` to origin/main.

**Don't-redo:** The same-spell-slot sidecar registry pattern `_PER_SPELL_CC_CONDITIONAL_FORMS` is the canonical home for multi-form champion CC mechanics where the form_index differentiates two distinct CC behaviors on the same spell slot (e.g. Karma W default vs Mantra-empowered, Hwei E form 1 Disable vs form 2 Root). Future cc_conditional wave 11+ should consume this sidecar SHAPE directly without re-pitching the registry lift. The `ConditionalCcEntry.form_index` field defaults to None for backward compat - do NOT add it as a required field. The 4 mojibake-tainted files (`ops/rc_self_monitor.py` + `ops/rc_state_validator.py` + `tft/tft_coach_engine.py`) need a separate UTF-8 byte-repair pass (signature: latin-1-misdecoded em-dash `c3 a2 e2 80 9d e2 82 ac`) - the smart-quote tool deliberately REFUSES to rewrite mojibake context to avoid corrupting source. The 4 frozen files with smart quotes (`ops/rc_supervisor.py` + `ops/rc_dev_runtime.py` + `core/moon_proxy.py` + `core/log_setup.py`) need explicit frozen-file grant before sweep. The L31 extension is now CLOSED for dashboard/+core/+tft/ public APIs; future surface coverage would be `lcu/` + `coach_integration/` + `agents/` (operator-gated separately). The orchestrator-merge pattern (3-4 worktree agents on disjoint slices + tests gate + DS restart if ENGINE bumped + RC unchanged unless coach prompts touched + docs sync follow-up commit) is now 19 consecutive runs (items 134-154). Direct-to-main push by a worktree agent (Slice B this run, Slice D item 150) is acceptable for pure tool/docs/sweep work with zero conflict risk vs other slices touching disjoint files.

**Carries forward:** (a) Item 153 carries ALL unchanged EXCEPT (a)-relaxed: cc_conditional wave 10 is NO LONGER operator-gated (DONE this session); smart-quote retro-sweep is NO LONGER operator-gated (DONE - drift guard test now locks invariant going forward); BACKLOG L31 extension to dashboard/+core/+tft/ is NO LONGER operator-gated (DONE). (b) RC-PostmortemAnalyze first scheduled run TOMORROW 2026-05-24 04:15 - verify LastTaskResult=0 next session. (c) DD Defy heal-on-takedown STILL deferred. (d) Live ARAM/SR smoke STILL pending. (e) Calibrations STILL operator-gated. (f) UI/UX live-game audit ritual owed once operator plays a real game. (g) DS conditional arc operator-CLOSED (s232). (h) Legion 1-PC consolidation (s169 option B) STILL operator-gated. (i) **NEW carry**: 4 mojibake-tainted files (`ops/rc_self_monitor.py` + `ops/rc_state_validator.py` + `tft/tft_coach_engine.py`) need separate UTF-8 byte-repair pass (operator-gated). (j) **NEW carry**: 4 frozen files with smart quotes (`ops/rc_supervisor.py` + `ops/rc_dev_runtime.py` + `core/moon_proxy.py` + `core/log_setup.py`) need explicit frozen-file grant before sweep (operator-gated). (k) **NEW carry**: L31 extension to `lcu/` + `coach_integration/` + `agents/` surfaces (operator-gated separately - this session closed dashboard/+core/+tft/). (l) Wave 11+ cc_conditional should consume sidecar registry shape directly. Frozen-file grant NOT used this session.

---
# 2026-05-23 - operator-gated decision-owed parallel drain: Meraki schema lift + cc_conditional wave 9 + BACKLOG L14 closure + minimap-crop log suppression + type hints on public coach API SHIPPED (4 commits + 2 merges, pushed origin/main `100c9c9`; ENGINE 1.45.0 -> 1.46.0; DS :8893 restarted serves 1.46.0; RC :8888 unchanged)

Operator "in parallel : start all open items in Operator-gated, decision owed" -> AskUserQuestion 4-question scope fork pinned: (Q1) Meraki extractor schema lift FULL + cc_conditional wave 9 (Recommended); (Q2) BACKLOG L14(a) kills->takedowns Option B keep 9-col additive (Recommended); (Q3) minimap-crop log suppression (Recommended; smart-quote sweep + .mcp.json wiring SKIPPED); (Q4) BACKLOG L31 type hints + ruff on public coach API. 4 worktree agents dispatched concurrent (orchestrator pattern items 134-151 extended to 18 consecutive runs).

**Slice A `051e606` (merge `9383a31`) feat(ds) cc_conditional wave 9 + Meraki extractor schema lift (39 files / +5435 / -106):**
- `tools/daemon_slayer_abilities_extract.py` schema-lifted to add `effects_descriptions: list[str]` per form record (purely additive; damage_blocks + parse_status math byte-identical).
- Re-extracted `data/daemon_slayer/16.10.1/champion_abilities.json` at 1.46.0 schema (+33% size, descriptions added; 171 champs / 705 items / 16.10.1).
- Wave 9 closures (+3 entries / +3 net-new champs; registry 39/35 -> 42/38): Renekton W Ruthless Predator Reign-of-Anger empowered stun 1.5s (first consumer of wave 7 forward-marker COND_FRENZY_STATE), Hwei E form_index=1 Grim Visage Disable 1.0-1.5s, Neeko E Empowered Root 1.8-3.0s.
- REJECT verdicts (4 candidates schema-lift-verified NEGATIVES): Karma W form 1 (registry schema needs same-spell-slot lift), Aatrox R (post-R fear is minion-only per description), Volibear R (Disable Duration is turret-only), Briar W (frenzy is self-buff-only).
- +58 tests (test_cc_conditional_wave9.py 36 + test_abilities_extract_descriptions.py 22) + 31 DS test files bulk-rewrite of ENGINE pin 1.45 -> 1.46 + 2 test pin relaxations.

**Slice B+C `62eb8b2` chore: minimap-crop log suppression + BACKLOG L14 obj_participation closure (3 files / +20 / -3):**
- `dashboard/_handler.py::_SUPPRESS_LOG_PATHS` tuple +1 entry `"GET /api/minimap-crop "` (was top non-suppressed contributor at 0.417/sec per item 151 Slice C audit; ~1500 log lines/hr saved). +1 test pin in `tests/test_handler_log_spam_suppress.py`.
- `BACKLOG.md` L14 obj_participation flipped from operator-gated to operator-decided Option (b) keep 9-col additive (avoids rebaselining 624 historic role-grades). CLOSED.

**Slice D `97bdbb4` (merge `100c9c9`) chore(coaches) type annotations on public coach API (6 files / +17 / -9):**
- 6 surgical annotation sites: ArenaVisionReader.read / BrawlVisionReader.read return types; coaches/feedback.py TYPE_CHECKING + apply_grade.cache; sr_coach Coach.shutdown -> None; tft_coach Coach.set_worker.worker via TYPE_CHECKING; tft_pbe_coach Coach.{submit_state,reset_state,shutdown} -> None.
- 0 ruff violations net (coaches/ already clean pre-edit; agent's 1 self-introduced F821 resolved in-pass via TYPE_CHECKING guard).
- Coach prompts UNCHANGED.

**Merge order:** Slice B+C committed directly to main first as `62eb8b2`; Slice A worktree agent rebased + landed `051e606` -> merged into main as `9383a31`; Slice D worktree agent rebased + landed `97bdbb4` -> merged as `100c9c9`. 0 merge conflicts (all 4 slices touched disjoint files).

**Verified:**
- full pytest `tests/` + `agents/daemon_slayer/tests/` = **7399 passed / 1 skipped / 1 xfailed**. The 1 expected `test_sr_draft_profile_engine.py::test_live_three_profiles` pre-DS-restart engine_version pin mismatch RESOLVED post-restart.
- DS :8893 killed pid 14292 + `schtasks /Run /TN RC-DaemonSlayer` (per [[reference_ds_server_not_supervisor_watched]]) -> serves engine_version=1.46.0 / patch 16.10.1 / 172 champs / 705 items; live test now passes 18/18.
- `ruff check .` ALL CHECKS PASSED.
- RC :8888 responsive throughout (mode_key=client idle; never restarted - non-frozen + non-coach-prompt edits).
- Pushed main as `100c9c9` to origin/main.

**Don't-redo:** Meraki schema lift is now DONE - the `effects_descriptions` field is the canonical home for description-text mechanics that don't fit the structured leveling[]/damage_blocks pipeline; future cc_conditional wave 10+ should consume this field DIRECTLY before re-pitching candidates. The 4 wave 9 REJECT verdicts are now schema-lift-verified NEGATIVES - do NOT re-pitch Karma W form 1 / Aatrox R / Volibear R / Briar W without new evidence. The wave 7 COND_FRENZY_STATE forward-marker tag is now ACTIVE (1 consumer); COND_RANGE_GATED remains forward-marker (0 consumers). The `_SUPPRESS_LOG_PATHS` tuple is now 9 entries; ward-heat at 0.149/sec becomes top non-suppressed but still below 1/sec threshold. The 6-site type annotation pass DELIBERATELY scoped to coaches/ only (operator-gated to public coach API); dashboard/+core/+tft/ surfaces NOT in this session's scope.

**Carries forward:** (a) Item 152 carries ALL unchanged EXCEPT Meraki schema lift is NO LONGER operator-gated (DONE this session). (b) RC-PostmortemAnalyze first scheduled run TOMORROW 2026-05-24 04:15 - verify LastTaskResult=0 next session. (c) DD Defy heal-on-takedown STILL deferred. (d) Live ARAM/SR smoke STILL pending. (e) Calibrations STILL operator-gated. (f) BACKLOG L14 NOW CLOSED. (g) BACKLOG L31 type hints NOW CLOSED for public coach API; dashboard/+core/+tft/ still open separately. (h) UI/UX live-game audit owed. (i) Smart-quote retro-sweep STILL operator-gated (skipped this session). (j) DS conditional arc operator-CLOSED (s232). (k) Legion 1-PC consolidation (s169 option B) STILL operator-gated. (l) Wave 10+ cc_conditional should consume `effects_descriptions` field directly - the schema lift this session is the durable substrate for description-text mechanic capture. Frozen-file grant NOT used this session.

---
# 2026-05-23 - living-docs cleanup pass: archive completed items + list open/pending (1 commit pending; docs-only; no DS restart; no RC restart; no ENGINE bump)

Operator "cleanup the .md's of completed items if not necessary to be present for future use & list to me all items that are still open or pending operator". Pure housekeeping pass per session-workflow last-3 rule.

**Archived (verbatim, zero rewrite):**
* CLAUDE.md items 94-149 (56 ledger entries spanning 2026-05-19/22 = DS audit iter chain + cc_blended_ehp ecosystem + cc_conditional ecosystem + obj_participation 9-col + s220 PGR S2-S5 + headless-upgrade runs + Fleet OAuth) -> `docs/history_notes.md` new section at top. Items 150-152 stay inline at full fidelity. Settled-section pointer flipped "items 1-93" -> "items 1-149".
* WAKEUP_NOTES items 148+149 -> already in `docs/history_notes.md` via the CLAUDE archive (single archive section covers both); cost-trace + item 151 + item 150 + this session entry inline.

**Compressed in place:**
* BACKLOG.md L13: cc_blended_ehp + cc_conditional 10-consumer chain (~5500 chars) -> one-paragraph SHIPPED summary pointing at CLAUDE archive (items 126-148).
* BACKLOG.md L80: cdragon-arena formula evaluator entry -> 1-liner SHIPPED.
* ROADMAP.md lines 11-72: shipped items 94-149 SHIPPED entries -> single pointer block; older s218-s246 SHIPPED entries kept inline for AUTONOMOUS_AUDIT chain context per ROADMAP-95 "Now + Next only".

**Byte deltas:**
* CLAUDE.md 483801 -> 43518 (-440K). Reloaded every turn so this is the biggest latency lever.
* ROADMAP.md 294689 -> 174953 (-120K).
* BACKLOG.md 33638 -> 23337 (-10K).
* WAKEUP_NOTES.md 32741 -> 17528 (-15K) (already trimmed to 3 sessions per s222 sync-all-md skill).
* history_notes.md +590K (verbatim absorption).

**Open/pending operator list surfaced inline.** Full list in chat output above; not duplicated here.

**Don't-redo:** items 94-149 are in `docs/history_notes.md` verbatim - do NOT restore them inline or treat their absence as drift; the Settled-section pointer at CLAUDE.md is the inline marker. The session-workflow last-3 rule is now strictly enforced in CLAUDE / WAKEUP. The ROADMAP pointer at line 11 covers May 19-22 sessions; older s218-s246 entries are intentionally kept for AUTONOMOUS_AUDIT chain context. The 27 panel CSS = 27 dashboard.css @imports parity guard (item 149 `test_dashboard_css_panel_imports_parity.py`) was unchanged; do NOT re-litigate.

**Carries forward:** ALL item 150/151/152 carries-forward unchanged (RC-PostmortemAnalyze 2026-05-24 04:15 first run = verify LastTaskResult=0 NEXT SESSION, the immediate-tomorrow check; DD Defy deferred; live ARAM/SR smoke pending; Meraki extractor schema lift operator-gated for cc_conditional wave 9+; BACKLOG L14 (a) kills -> takedowns flip operator-gated; UI/UX live-game audit owed; calibrations operator-gated; Slice C MINOR PROPOSAL `/api/minimap-crop` to `_SUPPRESS_LOG_PATHS` operator-gated). Frozen-file grant NOT used this session.

---
# 2026-05-23 - cost-trace gap C closure: wire 11 untracked messages.create + construction-layer shim SHIPPED (1 commit `7ad4056`, pushed; CI green 1m23s; non-engine; non-frozen; no DS/RC restart)

Operator triggered docs/cost_trace.md "Recommended follow-ups (not auto-applied; tracked here)" -> AskUserQuestion-picked "Both: wire 11 sites + add construction-layer shim (Recommended)" -> full vertical slice executed end-to-end.

**Shipped (`7ad4056` 14 files / +643 / -35):** NEW `core/cost_tracker.py::record_anthropic_response(resp, *, model, purpose) -> dict | None` shared module-level helper (sibling of `_BaseCoach._record_coach_call` private + `vision_server._record_to_cost_tracker` private) so all 11 sites funnel through ONE pricing-table + Prometheus path. NEW `core/anthropic_client.py::tracked_anthropic(api_key, *, purpose, default_model="")` construction-layer shim returning a real `anthropic.Anthropic` client with `messages.create` rebound to a wrapper that auto-records - defense-in-depth so a future 12th call site is tracked by default if the caller forgets the helper.

**11 wired sites (purpose= label is the by_purpose key in data/spend/YYYY-MM-DD.json):**
- 6 coach-side: aram_team_analyzer / experimental_builder / champ_select_coach / replay_coach / champ_select_brief (dashboard/_champ_select.py) / agent7_warm
- 5 TFT (highest priority polling/warm cadence per audit): tft_coach / tft_pbe / tft_live_analysis / tft_live_aug_select / tft_vision (SONNET - the most expensive untracked lane)

**+27 tests in NEW `tests/test_cost_tracker_response_helper.py`** across 5 classes: RecordAnthropicResponseTests 8 (usage extraction defensive on None/missing/blank, fallback to resp.model, swallows ledger exceptions, blank purpose -> _unspecified) / TrackedAnthropicShimTests 4 (wrapper applied, real API errors propagate, recording failures caught, default_model fallback) / WiredSitesImportSmokeTests 2 (public symbols) / WiredSitesGrepTests 11 (one per audit site pins import + purpose= label so a future regression rip fails CI before live cadence hits) / AsciiHygieneTests 2 (new code blocks ASCII-clean).

**docs/COST_TRACE.md updated:** follow-ups 1+2 flipped "tracked here" -> "SHIPPED 2026-05-23"; call-site matrix all 11 sites YES with per-site purpose label; reconciliation section reframed (gap is closed; pricing-table drift only, no untracked surface).

**Verified:** full RC suite **3250 passed / 0 failed** (+27 over 3223 baseline = exactly the new test file); py_compile + ruff clean across all 14 touched/new files; 0 non-ASCII bytes added by this diff (pre-existing carryover in tft/* + coaches/* left in place per operator-gated retro-sweep policy); CI green 1m23s on first push. No DS restart. No RC restart. No ENGINE bump. No frozen-file edits.

**Don't-redo:** The shared helper `core.cost_tracker.record_anthropic_response` is the canonical chokepoint for any non-`_BaseCoach` site - do NOT duplicate the usage-extraction logic in a new caller. The `tracked_anthropic` shim is INTENT defense-in-depth, NOT replacement for the helper - sites with per-call purpose granularity (e.g. vision_server vision_relay vs coach_relay from same client) should keep calling the helper directly. `WiredSitesGrepTests` pins the wire-in at each of the 11 sites by grep-matching `record_anthropic_response` + `purpose="<label>"` - if a future refactor renames the helper or rips the wire, these 11 tests fail before any live cadence hits the missing telemetry. The 3rd cost-trace audit (2026-04-29 gap A + gap B + this gap C) has CLOSED the recurring "new coach forgot to wire telemetry" pattern.

**Carries forward:** Item 151 carries-forward (a)-(k) ALL unchanged (Meraki parse-strip standing constraint, schema lift operator-gated, RC-PostmortemAnalyze first scheduled run 2026-05-24 04:15 = verify LastTaskResult=0 next session, DD Defy deferred, live ARAM/SR smoke pending, calibrations operator-gated, BACKLOG L14 kills->takedowns flip operator-gated, UI/UX live-game audit owed, Slice C MINOR PROPOSAL `/api/minimap-crop` to `_SUPPRESS_LOG_PATHS` operator-gated, wave 9+ should target REJECT carries without Meraki schema lift). Frozen-file grant NOT used this session.

---
# 2026-05-23 - item 151 4-slice parallel housekeeping drain (cc_conditional wave 8 SHIPPED + BACKLOG stale-sweep wave 13 CLEAN + cost/latency CLEAN wave 16 + living docs sync post-wave-8) SHIPPED (2 commits + 1 merge `656c4f5` `d2711ba`, pushed; ENGINE 1.44.0 -> 1.45.0; non-frozen; DS :8893 restarted serves 1.45.0; RC :8888 unchanged - DS engine + docs only)

Operator "continue what is left as open items in parallel commit + push & /done for /clear, use as many agents as needed" -> 17th consecutive run using orchestrator-merge template (items 134-150 streak extended). 4 worktree agents dispatched concurrent.

**Slice A SHIPPED `656c4f5` feat(ds) cc_conditional wave 8 (36/32 -> 39/35; +3 entries / +3 net-new champs closing prior-wave REJECT carries):** Via setdefault builder + `_p()` helper. NEW: **Morgana R Soul Shackles** (channel_completion 0.5 stun 1.5/1.75/2.0s across 3 ranks - per items 146 + 147 REJECT carries "belongs in cc_conditional parallel to Karma W"); **Seraphine E Beat Drop** (target_debuffed 0.5 stun 1.5s all 5 ranks - per items 138 + 146 + 147 "target-state-conditional: stun fires only when target debuffed by slow/airborne/immobilize"); **Evelynn W Allure** (target_debuffed 0.5 charm 1.5-2.5s across 5 ranks - per items 138 + 146 "detonation-on-Eve-attack conditional charm"). All 3 had been EXPLICITLY flagged in prior wave REJECT notes as belonging in cc_conditional, NOT new pitches. Uses ONLY existing 12 condition tags (COND_CHANNEL_COMPLETION + COND_TARGET_DEBUFFED). +25 tests NEW `test_cc_conditional_wave8.py`. ENGINE 1.44.0 -> 1.45.0 + 32 stale ENGINE pin syncs across DS test files. The Meraki parse-strip STILL BINDS for OTHER candidates (Renekton W / Aatrox post-R / Volibear R / Briar W frenzy / multi-form same-spell-slot Karma+Hwei+Neeko); wave 8 closes ONLY candidates whose duration values + mechanic descriptions are verifiable WITHOUT the extractor schema lift.

**Slice B CLEAN no-commit (wave 13 stale-sweep saturation):** Agent grep-verified every open BACKLOG.md + ROADMAP.md entry against live source. BACKLOG L13 cc_conditional ecosystem subsection ALREADY current. BACKLOG L14/L15 SHIPPED. L16-L106 legitimately operator-gated. ROADMAP L223 + L82/L83/L111/L129/L130/L133/L140 all legitimately operator/live-gated. **Sweep cycle decay:** wave 1=2/2=3/3=3/4=1/5=1/6=1/7=2/8=1/9=1/10=1/11=1/12=1/**13=0**. Saturation at item 150 post-housekeeping baseline.

**Slice C 16th consecutive cost/latency CLEAN no-commit (read-only investigative agent):** 7 levers surveyed. Prompt-cache 8 cache_control sites + Route TTL 14 routes + Polling cadences sane + Model tier haiku-4-5 + Scheduled tasks 14 RC-* + Bundle size 27=27 parity ALL CLEAN. **MINOR PROPOSAL (operator-gated):** `/api/minimap-crop` at **0.417 hits/sec** (1786 hits over 71min) above item 150 baseline ward-heat 0.149/sec. UI-local poller (250ms fast / 2000ms slow gated on MINIMAP_MODES + document.hidden short-circuit). STILL below 1/sec threshold (0.417 < 1.0) but now top non-suppressed path; 1-line tuple addition to `_SUPPRESS_LOG_PATHS` in `_handler.py:74-83` would save ~1500 log lines/hr.

**Slice D `d2711ba` (committed directly to main post-Slice-A) docs sync to post-item-151 state (ENGINE 1.45.0 + cc_conditional 39/35 + DS 4016):** Initial Slice D returned CLEAN no-commit confirming item 150 docs durable; Slice A merge required follow-up flip. 6 surgical edits across 4 files: DAEMON_SLAYER.md L5+L32 / README.md L46 / BRIEF.md L20+L26 / ARCHITECTURE.md L161. Skipped per [[feedback_no_history_rewrite]]: BRIEF.md L33 (2,822 s174-s181 anchor) + L57 (2,703 resume-pitch). Live source-of-truth: ENGINE=1.45.0 entries=39 champs=35 tags=12 DS tests 4016.

**Merge order:** Slice A merged into main FIRST `656c4f5` (worktree branch `worktree-agent-a522d5e7b46c1f89e`, ort strategy, 0 conflicts, 36 files changed); Slice D follow-up docs sync committed directly to main SECOND `d2711ba`. 0 merge conflicts.

**Verified:** DS suite 4016 passed / 1 skipped / 1 xfailed / 1669 subtests (+25 over s150 3991 baseline). py_compile + ruff + ASCII clean. DS :8893 restarted via taskkill /F /PID 8212 + schtasks /Run /TN RC-DaemonSlayer; /health returns engine_version=1.45.0 patch=16.10.1 champions=172 items=705. RC :8888 unchanged. 1 worktree (Slice A) auto-removed post-merge + branch deleted.

**Don't-redo:** cc_conditional registry now 39 entries / 35 champions; the Meraki parse-strip is STILL a STANDING constraint for OTHER candidates - the 3 wave 8 entries were specifically the ones verifiable WITHOUT schema lift. The "16 consecutive saturation" verdict in item 150 was correct ONLY for schema-lift-blocked candidates. Future cc_conditional wave 9 attempts should similarly look for REJECT carries that DO NOT need the extractor schema lift. The orchestrator-merge pattern is now 17 consecutive runs (items 134-151).

**Carries forward:** (a) Item 150 carries (a)-(i) ALL unchanged - Meraki parse-strip is STILL standing constraint for SCHEMA-LIFT-BLOCKED candidates. (b) Meraki extractor schema lift operator-gated. (c) RC-PostmortemAnalyze first scheduled run 2026-05-24 04:15 (in <1 day) - verify LastTaskResult=0 next session. (d) DD Defy heal-on-takedown deferred. (e) Live ARAM/SR smoke pending. (f) All calibrations operator-gated. (g) BACKLOG L14 (a) kills -> takedowns flip operator-gated. (h) UI/UX live-game audit ritual owed. (i) Frozen-file grant NOT used. (j) Slice C MINOR PROPOSAL `/api/minimap-crop` to `_SUPPRESS_LOG_PATHS` operator-gated. (k) Wave 9+ should target REJECT carries that DO NOT need Meraki schema lift.

