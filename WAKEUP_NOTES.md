# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-05-25 (early) - item 181 SHIPPED: UI scale v2.1 pages #9 ARAM + #10 Arena parallel slices + housekeeping triple wave 23 CLEAN (2 merges `2a4fa7b` + `6ba6b4d` pushed origin/main `c94881f..6ba6b4d`; non-frozen; no DS engine change; no DS restart; no RC restart - ADR-008 asset-hash auto-serves CSS+JS+JSON on next dashboard load)

Operator: "in parallel, work on the next items that are open -> operator is queuing ranked SR". Next-in-audit-order pages #9 + #10 from item 13 (16-page UI scale v2.1 refactor; 8 pages remaining post-item-178). 3 parallel agents dispatched concurrent per orchestrator-merge pattern (33rd consecutive run extending items 134-179; item 180 was direct-commit live-ops not orchestrator). Pre-flight: 0 open PRs, item 179's Slice A remote branch (`worktree-agent-abea64c3e46bbdd24`) deleted via `git push origin --delete` (already merged via `c55fd00`). 25 local worktrees harness-locked (parent owns lifecycle; left in place per pattern). Operator queueing ranked SR throughout drain - RC :8888 mode_key=sr stable, no restart.

**Slice A `14ee30d` (merge `2a4fa7b` ort 0 conflicts 1 file +5 / -1) chore(ui) page #9 Champ Select ARAM v2.1 token migration:**
- `web/css/panels/champ_select_view.css` 2 surgical edits: `.csv-bench-title` font-size `14px` -> `var(--fs-xs)` (16px floor); `.csv-bench-empty` 13px PRESERVED with inline documentation comment marking it as operator exception per item 178 audit ("waiting for reroll" empty-state copy; sub-floor intentional; do NOT bump without operator approval).
- Audit verdict per `feedback_phase3_fixture_ritual`: STRUCTURE PASS (bench[10] swap row + summoner-spell strip + DS Build Archetype + Pick & Ban + Assessment all render via existing ARAM path); TYPOGRAPHY PASS (only 1 stale sub-floor surfaced post-item-165 bench expansion); HIT-TARGETS PASS (bench cells + spell slots meet `--hit-min 42px` floor); ASCII PASS (0 new non-ASCII bytes); HIERARCHY PASS (4 distinct visual tiers at 1080px baseline).
- Mock fixture `web/data/ui_mock/champ_select_aram.json` (item 165) preserved byte-equivalent; render path `_csIsMock + _csvDetectMode` at `web/js/main.js:3252` + `web/js/panels/champ_select.js:339` UNCHANGED.

**Slice B `a8bf743` (merge `6ba6b4d` ort 0 conflicts 3 files +160 / -11) chore(ui) page #10 Champ Select Arena v2.1 mock + token migration:**
- NEW `web/data/ui_mock/champ_select_arena.json` (115 lines): queue_id 1750 (CHERRY mapId 30 canonical post-item-180) + gameMode CHERRY + 6 sub-teams x 2 players (12 total; matches live LCU shape exposed by `tools/gamepc_lcu_agent.py:536` `_arena_teams()` distil - NOT 6x3 as the c3a1e23 commit message implied; agent verified the brief's "6x3" against live code and shipped the actual 6x2 shape). MY TEAM at subteamIdx 3; 5 enemy trio cards. Augment scaffolds empty (CS phase pre-augment). Jinx `arena-collapsed` variant with 2 build paths (Crit primary + Carry secondary) sourced from item 179 ARAM/Arena collapse.
- `web/js/main.js` `_csMockLoad` extended at L3263 to branch `?mode=arena` -> `champ_select_arena.json` (mirrors L3263 ARAM branch from item 165).
- `web/css/panels/champ_select_view.css` 9 v2.1 token swaps on `csv-arena-*` / `csv-duo-*` / `csv-augment-*` namespaces + `--hit-min 42px` added to `.csv-augment-option`. 2 documented operator exceptions preserved (`.csv-duo-cell-tag` 11px ALLY/ME badge + `.csv-arena-cell-name` 13px dense enemy column).
- Audit verdict per ritual: STRUCTURE PASS (6 sub-teams + MY TEAM at subteam 3 + 5 enemy trio cards stacked + augment scaffold); TYPOGRAPHY PASS (2 documented exceptions); HIT-TARGETS PASS (`.csv-augment-option` meets 42px floor; `.csv-arena-cell` 38px preserved per `.csv-pb168-cell` density precedent); ASCII PASS (0 new non-ASCII bytes); HIERARCHY PASS.

**Slice C CLEAN no-commit (housekeeping triple wave 23):**
- BACKLOG/ROADMAP stale-sweep wave 23 = **0 flips**. Live anchors verified: `dev.js:361` verdict.team_won GREEN; `gamepc_lcu_agent.py:1192` augment_intent_unsupported (ROADMAP L82 cites :1194 = `"augment_id"` continuation line; actual return at :1192 within +/- 3 tolerance, NOT a flip). BACKLOG.md OPEN entries narrative-only no file:line refs. SHIPPED entries L23/L24/L82 historical paths untouched per [[feedback_no_history_rewrite]]. **Sweep cycle decay:** 17=0 / 18=1 / 19=0 / 20=0 / 21=0 / 22=0 / **23=0** = 6 consecutive zero-flip waves = saturation deepening.
- 27th consecutive cost/latency CLEAN since item 134. 7 levers all green: prompt-cache 8 sites + route TTL 12 routes (within 12-16 fluctuation) + polling tightest network 2000ms + log spam top non-suppressed `/api/bridge` 0.183/s + `/api/ward-heat` 0.128/s (both well below 1/s; close to item 179 baselines 0.194/0.132) + `/api/minimap-crop` + `/api/activity` 0/s (item 171 trailing-space fix holds) + 9-entry `_SUPPRESS_LOG_PATHS` unchanged + model tier all haiku-4-5 + 14 RC-* scheduled tasks matching item 180 catalog + bundle parity 27=27 (test 4/4 PASS).
- Living docs sync VERIFY CLEAN: ENGINE 1.56.0 + 4671 tests + cc_conditional 67/54 waves 0-19 + 13 condition tags - all current. Last DS bump = item 177 ENGINE 1.55.0 -> 1.56.0; items 178-180 had no engine touch. No commit needed.

**Verified post-merge:**
- DS suite untouched (no engine change; DS :8893 serves 1.56.0 from item 177).
- `py -m pytest tests/phase8_smoke/ -q` = **75 passed in 2.38s** post-Slice-B merge (unchanged from item 180 baseline).
- `py -m ruff check .` ALL CHECKS PASSED.
- RC :8888 unchanged pid 5800 mode_key=sr alive=True last_reload_ok=True throughout (operator queueing ranked SR; ADR-008 auto-serves CSS+JS+JSON on next dashboard load).

**Don't-redo:**
- Page #9 + #10 v2.1 token migrations are CLOSED; do NOT re-pitch font-size bumps or padding changes without operator approval. The 3 operator exceptions documented inline (`.csv-bench-empty` 13px + `.csv-duo-cell-tag` 11px + `.csv-arena-cell-name` 13px) are intentional sub-floor sites with rationale in CSS comments.
- Arena mock shape is 6x2 (12 total players) NOT 6x3 - the c3a1e23 commit message implied 6x3 but `_arena_teams()` at `tools/gamepc_lcu_agent.py:536` distils as 6x2; the mock honors live shape, agent caught + corrected the brief premise mid-flight. Do NOT re-pitch a 6x3 schema lift without first verifying live LCU returns it.
- Arena queue 1750 canonical (item 180); 1700/1710 stay as legacy classifier aliases for rewind_history.db only.
- Cost/latency lane saturated at item 179 baselines; the `_SUPPRESS_LOG_PATHS` 9-entry tuple is calibrated.
- BACKLOG/ROADMAP sweep cycle in 6-wave saturation; future sweeps should expect 0 flips unless file:line citation drift recurs from a NEW engine bump or NEW open item with anchors.
- Orchestrator-merge pattern now 33 consecutive runs (items 134-179 + 181; item 180 was direct-commit live-ops outside the pattern).

**Carry-forward (operator-gated):**
- Live UI capture OWED for page #9 ARAM at next ARAM/Mayhem champ-select session (operator was queueing SR ranked this session).
- Live UI capture OWED for page #10 Arena at next Arena champ-select session.
- 6 remaining v2.1 audit pages: #11/12/13 Active Match SR/ARAM/Arena + #14/15/16 PGR SR/ARAM/Arena.
- All item 180 carries unchanged: Arena 6x3 visual capture (per c3a1e23 _csvArenaPaneHtml refactor; now 6x2 verified from `_arena_teams()` so the "6x3" claim was wrong - the carry-forward becomes "verify live shape vs mock honors live"), 542 residual U+2500 box-drawing chars operator-gated separate sweep, RC-PostmortemAnalyze first scheduled run today 2026-05-25 04:15 (operator can verify LastTaskResult=0), DD Defy deferred, calibrations operator-gated, Legion 1-PC consolidation operator-gated, cc_conditional wave 20+ schema-blocked, frozen-file grant NOT used this session.
- 25 local worktrees still harness-locked (carry-forward; parent owns lifecycle).

---

# 2026-05-24 (late evening) - #89 LIVE VERIFICATION SHIPPED: Arena 1700 -> 1750 + Practice Tool queueId:3140 + drop is_brawl 480 (1 commit `55b67db` pushed origin/main `7cffcfb..55b67db`; non-frozen; no DS engine change; no DS restart; no RC restart; Game-PC agent redeployed via HTTP-pull to sha 0261d7d3aa251ca4 size 93730B pid 13188)

Operator: "start #89 live verification (ROADMAP L24): Practice Tool + ARAM Mayhem + Arena lobby create from BOTH pickers; Arena 6x3 render; agent name-map redeploy". Item #89 had been live-gated since 2026-05-17 commit `c3a1e23` shipped repo-side fixes. This session ran the live verification end-to-end with operator in front of the League client + dashboard, surfacing 3 stale queue assumptions that the offline test suite could never catch.

**Findings vs /lol-game-queues/v1/queues live LCU catalog (16.10.x):**
- **Arena live queue = 1750** (Arena 3x6 CHERRY mapId 30), NOT 1700/1710. Both retired from live catalog. Direct LCU POST {queueId:1700} returns 500 INVALID_LOBBY; {queueId:1750} returns 200 OK.
- **Practice Tool needs explicit queueId:3140** (Multiplayer Practice Tool Custom). The agent was omitting queueId entirely; newer LCU builds reject customGameLobby body with 500 INVALID_LOBBY when queueId is absent. Captured via in-client PT create -> GET /lol-lobby/v2/lobby showing gameConfig.queueId=3140 + gameMode:PRACTICETOOL + mapId:11. Test matrix proved adding queueId:3140 to the agent's existing teamSize:1 body fixes the 500.
- **`is_brawl: queue_id == 480` was dead** (Brawl retired s214; 480 is now Swiftplay per live catalog). Removed from agent champ-select state.

**Fixes (commit `55b67db`):** 12 files / +66 / -46. Updated 1700/1710 -> 1750 in: web/index.html (3 picker buttons + lobby `<option>`), web/js/main.js (SR_QUEUE_IDS comments + LV_QUEUE_TIPS map), web/js/panels/champ_select.js (modeMap + _csvDetectMode + _CSV_QUEUE_NAMES + cc-blended-ehp/cc-conditional-pressure mode resolvers + _csvResolveRole + P&B gate comment), web/js/panels/dev.js + last_match.js (queue_name + isArenaSubteamMode), coaches/loadout_resolver.py + core/augment_recommender.py + dashboard/builders_last_match.py + _cs_retention.py (classifier maps), core/queue_modes.py (1750 added + comment), tools/gamepc_lcu_agent.py (name-map 1700 -> 1750 + arena_teams classifier accepts 1750 + Practice Tool body gains explicit `queueId: 3140` + is_brawl line dropped). Updated tests/phase_b_champ_select/test_lcu_lobby_members.py (queue_name_map asserts + test_arena_queue_name uses 1750).

**Live end-to-end via /api/lcu-cmd dashboard chain (POST /api/lcu-cmd -> dashboard -> :8889 -> Game-PC agent -> LCU):**
- Arena change_queue_type queue_id:1750 -> ok:true; live LCU shows qid 1750 + gameMode CHERRY
- ARAM Mayhem change_queue_type queue_id:2400 -> ok:true; live LCU shows qid 2400 + gameMode KIWI
- lobby.create_practice_tool -> ok:true; live LCU shows qid 3140 + gameMode PRACTICETOOL + mapId 11
- Dashboard Pre-Game Lobby render in Arena state: footer pill "ARENA", mode label "ARENA", YOUR MAINS + MY TOP 8 populated (queue 1750 -> arena mode_key chain proven through state-builder + view-router + JS render)

**Verified:** RC suite excl phase8_smoke **3367 passed / 67 subtests passed** (same as item 179 baseline; behavior-equivalent). py_compile + node --check + ruff clean on all touched files. RC :8888 pid 5800 mode=client alive=True last_reload_ok=True throughout (no restart needed - non-frozen + non-coach-prompt edits; ADR-008 auto-served the CSS/JS edits).

**Game-PC agent redeploy via HTTP-pull pattern (per reference_gamepc_http_server_redeploy.md):** legion `py -m http.server 8765` from tools/ + Game-PC Invoke-WebRequest + taskkill old pid + atomic Move-Item + pythonw relaunch. End state: pid 13188, sha 0261d7d3aa251ca4, size 93730 bytes - matches Legion source exactly. Earlier in session there was a moment where 2 agent pids ran simultaneously (5368 + 1040) due to my failed taskkill - cleaned to single pid 1040 via explicit taskkill of older pid, then again for the PT-fix redeploy to pid 13188.

**Don't-redo:**
- Arena queue 1700/1710 -> 1750 is the canonical flip. 1700/1710 stay as LEGACY ALIASES in classifier maps (rewind_history.db has historic match data carrying those IDs); lobby CREATE POSTs use 1750 exclusively. Do NOT re-pitch dropping the 1700/1710 aliases - they earn their keep on replay/history.
- Practice Tool create body MUST carry explicit `queueId: 3140`. The `customGameLobby` config alone is insufficient. teamSize:1 is fine (live LCU expands to teamSize:5 + numPlayersPerTeam:5 post-create). Do NOT re-litigate teamSize:5 in the create body.
- `is_brawl: queue_id == 480` is permanently dropped. Brawl retired s214 + 480 reassigned to Swiftplay in 16.10. Do NOT reintroduce.
- Live LCU catalog at /lol-game-queues/v1/queues is the authoritative source-of-truth for queue IDs. When in doubt about a queue ID, GET that endpoint first; don't trust the agent's `_LOBBY_QUEUE_NAMES` map alone (it can lag behind Riot's catalog).
- The orchestrator-merge pattern was NOT used this session (single direct commit on main; live ops with operator-in-the-loop rather than parallel worktree agents).
- 22 local worktrees still harness-locked (carry-forward from item 179 + earlier; not this session's responsibility).

**Carry-forward (operator-gated):**
- Arena 6x3 champ-select VISUAL capture STILL OWED - needs operator to commit a real Arena queue + accept + CS entry. Lobby-side ARENA mode proven via monitor 1 capture; only the actual 3-ally-cell + central-me+2 + 5-enemy-trio-cards layout (per c3a1e23 _csvArenaPaneHtml + _csvRenderEnemiesArena 8x2 -> 6x3 refactor) remains unverified live.
- 542 residual U+2500 box-drawing chars (rc_supervisor 58 + rc_self_monitor 484) - operator-gated separate sweep per item 176 carries.
- All item 179 carries unchanged: RC-PostmortemAnalyze first scheduled run today 2026-05-25 04:15, DD Defy deferred, live ARAM/SR smoke pending, calibrations operator-gated, UI/UX live-game audit owed, Legion 1-PC consolidation operator-gated, cc_conditional wave 20+ schema-blocked, v2.1 audit pages 9/10/11/12/13/14/15/16 owed, frozen-file grant NOT used this session.

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
