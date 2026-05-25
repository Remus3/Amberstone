# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-05-25 - items 182 + 183 SHIPPED: page #14 PGR SR v2.1 typography + pages #15+#16 PGR ARAM+Arena mock fixtures + ?mode URL flag wiring + housekeeping wave 24 CLEAN + Active Match read-only composition audit (2 merges `efc9cfd` + `b1c8e90` pushed origin/main `8cb5686..b1c8e90`; non-frozen; no DS engine change; no DS restart; no RC restart - ADR-008 asset-hash auto-serves CSS+JS+JSON on next dashboard load)

Operator: "continue other open items -> operator is in ranked SR" (x2 consecutive prompts). 34th + 35th consecutive runs using orchestrator-merge pattern (items 134-181 + 182 + 183). 4 worktree/investigative agents across two prompts. Pre-flight: 0 open PRs; 2 stale remote branches from item 181 deleted (`worktree-agent-a7b1d4045eb667440` + `worktree-agent-ae7fcc75d84601b9e` fully merged into `6ba6b4d`). RC mode_key=sr stable through both drains; mode dropped to client (Offline) by end of session (operator's ranked SR game ended between Slice A merge + /done).

**Item 182 Slice A `b72ec9f` (merge `efc9cfd` ort 0 conflicts 1 file +82 / -55) chore(ui) page #14 PGR SR v2.1 typography token migration:**
- `web/css/panels/last_match.css` 55 token swaps on `.lm-*` selectors covering all PGR mode-shared rendering. Hero tier: `.lm-hero-grade` 48 -> --fs-display (46); `.lm-hero-champ` + `.lm-hero-score-value` 32-36 -> --fs-xl (37). Statistical tier: `.lm-hero-role-grade-value` + `.lm-kda-text` 30 -> --fs-lg (29); `.lm-hero-stat-value` + `.lm-rank-cell-value` + `.lm-stat-value` + `.lm-tc-mvp-score-value` 26-27 -> --fs-stat (26). Body tier: `.lm-qr-list li` + `.lm-tl-chart-final` + `.lm-hero-result` 19-20 -> --fs-md (22); `.lm-tab` + `.lm-section-head` + `.lm-tc-row` 18-19 -> --fs-sm (18). Compact tier: floor bumps 13-15 -> --fs-xs (16) including `.lm-hero-score-tier`.
- 5 operator-exception sub-floor cells preserved with inline rationale comments (mirrors item 181 `.csv-bench-empty` + `.csv-duo-cell-tag` + `.csv-arena-cell-name` precedent): `.lm-hero-role-grade-role` 11px (3-char role badge density ADC/SUP/JG/MID/TOP); `.lm-wpa-foot` 13px (italic caption attribution); `.lm-tc-score-badge` 14px (per-row MVP/SVP/#N badge density 44px column); `.lm-tc-mvp-badge` 14px (MVP/SVP card badge text); `.lm-tc-mvp-score-tier` 11px (EXCELLENT/GOOD/OK/BAD micro-label).
- 3 hit-target floors added (`min-height: var(--hit-min)` 42px): `.lm-tab:467` + `.lm-rank-select:333` + `.lm-section-head-btn:1252`. Participant rows `.lm-tc-row` left sub-floor per item 181 dense-table precedent (tooltip cells, not click actions).
- 5-phase audit per `feedback_phase3_fixture_ritual`: STRUCTURE PASS (hero / tabs / per-side rosters / chart / WPA + 3-col Quick Review; no `.lm-arena-*` or `.lm-aram-*` selectors exist - all `.lm-*` font-sizes SR-shared = de-facto covers pages #15/16); TYPOGRAPHY PASS; HIT-TARGETS PASS; ASCII PASS 0 new non-ASCII bytes (pre-existing 972 bytes box-drawing/arrows operator-gated retro-sweep carry); HIERARCHY PASS (4 distinct tiers display/statistical/body/compact at 1080px baseline).

**Item 182 Slice B CLEAN no-commit (housekeeping triple wave 24):**
- BACKLOG/ROADMAP stale-sweep wave 24 = **0 flips**. Live anchors verified: `dev.js:361` verdict.team_won + `gamepc_lcu_agent.py:1192` augment_intent_unsupported within +/- 3 tolerance. **Sweep cycle decay:** 17=0 / 18=1 / 19=0 / 20=0 / 21=0 / 22=0 / 23=0 / **24=0** = 7 consecutive zero-flip waves = saturation deepening continues.
- 28th consecutive cost/latency CLEAN since item 134. 7 levers all green: prompt-cache 8 sites + route TTL 12 routes + polling tightest 2000ms + log spam top non-suppressed `POST /api/loadout/list` **0.631/s** (NEW top non-suppressed surfacing above prior `ds-preview` + `ward-heat` + `bridge`; below 1/s hard threshold; minor proposal operator-gated for future log-suppress) + ward-heat 0.148/s + bridge 0.132/s + 9-entry `_SUPPRESS_LOG_PATHS` unchanged + model tier all haiku-4-5 (Sonnet POST-call telemetry only; agent7_warm_session=haiku per item 177 correction) + 14 RC-* scheduled tasks + bundle parity 27=27 PASS.
- Living docs VERIFY CLEAN: ENGINE 1.56.0 + 4671 tests + 67/54 waves 0-19 + 13 condition tags - all current. Last DS bump item 177; items 178-181 no engine touch. No commit needed.

**Item 183 Slice A `b0ac2a6` (merge `b1c8e90` ort 0 conflicts 3 files +275) chore(ui) pages #15+#16 PGR ARAM+Arena mock fixtures + ?mode URL flag wiring:**
- NEW `web/data/ui_mock/last_match_aram.json` (108 lines): queue 450 mapId 12 (ARAM); 10-player; teams 100/200; augments all-zero -> `data-aug="0"`; operator champ Jinx (id 222); grade A; KDA 12/4/22.
- NEW `web/data/ui_mock/last_match_arena.json` (114 lines): queue 1750 CHERRY mapId 30 (canonical post-item-180); 12-player **6x2 shape** per item 180 `_arena_teams()` distil at `tools/gamepc_lcu_agent.py:536` (NOT 8x2 as brief initially asserted; agent caught + corrected against live LCU shape); subteam teamIds 100-600 (one per subteam, MY TEAM=300 -> renderer's `roster.filter(r.team_id === myTeamId)` -> 2 allies + 10 enemies); 4 augments/player + 2 trailing zeros -> `data-aug="1"`; operator champ Jinx grade S placement 2.
- `web/js/panels/last_match.js` +53 lines (L324-376): NEW `_lmIsMock()` / `_lmMockUrl()` / `_lmMockLoad(url)` helpers + `_liveFetch(_b)` live-path extraction. `fetchAndRenderLastMatch()` short-circuits to mock fixture when `body.dataset.uiMock === "1"` AND URL param `mode=aram|arena` present. Mirrors `web/js/main.js _csMockLoad` L3263 precedent (items 165 + 181).
- 5-phase audit ritual: STRUCTURE PASS (10p ARAM / 12p 6x2 Arena / mode-conditional augment grid via `#lm-tc-table[data-aug="1"]` 9-col track); TYPOGRAPHY DE-FACTO PASS (item 182 last_match.css mode-shared `.lm-*` + `.lm-tc-aug*` selectors already cover ARAM/Arena via 9-col augment grid); HIT-TARGETS PASS via item 182 floors (no new floors needed); ASCII PASS 0 new non-ASCII bytes; HIERARCHY PASS.

**Item 183 Slice B read-only no-commit (Active Match view composition audit):**
- 7 CSS files compose `#view-active-match`: 5 EXCLUSIVE (active_match.css 137 LOC / 2 font-size hits + draft_elo.css 191 / 11 + spike_curve.css 60 / 2 + ward_heat.css 97 / 5 + cd_ledger.css 205 / 6) + 2 SHARED (right_now.css 173 / 8 + next.css 58 / 1 - both also render in main grid; touches ripple to ALL views during in-game baseline).
- 0 mode-conditional CSS branching (no sr-only / aram-only / arena-only selectors; rendering identical SR/ARAM/Arena via JS logic).
- 19 sub-floor (< 16px) declarations pre-mapped for pages #11/12/13 v2.1 typography migration when operator out-of-game: active_match 2x14 / draft_elo 9-13 x5 / spike_curve 9-10 x2 / ward_heat 8-9 x5 (likely operator-exceptions for hover-tooltip micro-legends) / cd_ledger 9-12 x5.
- Bundle parity 27=27 PASS (test_dashboard_css_panel_imports_parity.py 4/4).

**Verified post-merges:**
- DS suite untouched (no engine change; DS :8893 serves 1.56.0 from item 177; not restarted).
- `py -m pytest tests/phase8_smoke/ tests/test_dashboard_css_panel_imports_parity.py -q` = **79 passed in 2.40s** post both merges.
- `py -m ruff check .` ALL CHECKS PASSED both times.
- JSON validity both new fixtures PASS via `json.load`.
- RC :8888 mode_key transitioned sr -> client (Offline) by end of session; pid 5800 alive=True last_reload_ok=True throughout; never restarted (ADR-008 auto-served CSS+JS+JSON).

**Don't-redo:**
- (a) Page #14 PGR SR v2.1 typography CLOSED; do NOT re-pitch font-size bumps on `.lm-*` without operator approval. The 5 operator-exception sub-floor cells (`.lm-hero-role-grade-role` 11 / `.lm-wpa-foot` 13 / `.lm-tc-score-badge` 14 / `.lm-tc-mvp-badge` 14 / `.lm-tc-mvp-score-tier` 11) carry rationale in CSS comments.
- (b) `last_match.css` is mode-SHARED - no ARAM-only / Arena-only selectors; pages #15/16 typography is DE-FACTO closed via item 182. Future PGR ARAM/Arena slices should focus on STRUCTURAL or content-layout deltas, not typography.
- (c) Arena PGR fixture shape is 6x2 = 12 players (NOT 8x2 / 16 players); honor live LCU `_arena_teams()` at `tools/gamepc_lcu_agent.py:536`.
- (d) `_lmMockLoad` mirrors `_csMockLoad` (items 165+181); future PGR mode-mock dispatchers extend the `?mode=<mode>` URL flag pattern.
- (e) Active Match composition allowlist locked: 5 EXCLUSIVE CSS files SAFE TO TOUCH only when operator out-of-game; 2 SHARED CSS files (right_now + next) ripple to all views.
- (f) 7 consecutive zero-flip BACKLOG sweep waves (17-24) = sweep cycle saturation deepening.
- (g) `/api/loadout/list` 0.631/s is the new top non-suppressed log entry; still below 1/s hard threshold; operator-gated minor proposal for future log-suppress needle.
- (h) Orchestrator-merge pattern now 35 consecutive runs (items 134-181 + 182 + 183).

**Carries forward:**
- (a) Live UI capture OWED for pages #14 + #15 + #16 PGR (SR + ARAM + Arena) at next non-game window (mid-ranked-SR forbids capture per [[feedback_screen_capture_default]] + brief).
- (b) Pages #11/12/13 Active Match SR/ARAM/Arena v2.1 typography STILL deferred (operator-out-of-game requirement). SAFE TARGETS LIST locked: 5 exclusive CSS files + 19 sub-floor declarations pre-mapped.
- (c) `/api/loadout/list` 0.631/s log-suppress minor proposal operator-gated.
- (d) All item 181 carries (a)-(l) otherwise unchanged: 542 residual U+2500 box-drawing chars operator-gated separate sweep; DD Defy deferred; calibrations operator-gated; Legion 1-PC consolidation operator-gated; cc_conditional wave 20+ schema-blocked; frozen-file grant NOT used; RC-PostmortemAnalyze first scheduled run was 2026-05-25 04:15 (operator can verify LastTaskResult=0).
- (e) `web/js/panels/last_match.js` still has 5 pre-existing non-ASCII codepoints (operator-gated retro-sweep separate pass; NOT introduced by this session).

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
