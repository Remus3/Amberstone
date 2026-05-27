# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-05-26 - item 204 SHIPPED: /insights 2026-05-26-185928 followup - CLAUDE.md +5 sections + 2 scoping docs + edit_lint_check hook + verify-before-declaring memory

Operator ran `/insights` after wrap. Drained the report's actionable suggestions across 2 commits + 1 memory write outside repo. 1 commit `adb2e96` on origin/main `0676407..adb2e96`; non-frozen; non-engine; no DS restart; no RC restart (no route/coach module edits this run). 3 worktree-agent dispatches NOT used this session (single Claude orchestrator + scoping work only).

**Shipped (4 files / +340 / -0):**
- `CLAUDE.md` +5 sections from report: `## Session-End Ritual` + `## Output Constraints` + `## Style Rules` + `## TDD First` + `## Subagent Code Quality` (lines 65-77 + 124-130).
- `docs/CI_WATCHDOG_PLAN.md` NEW (5.4 KB / 88 lines) - scoping ONLY for auto-fix red CI via headless `claude -p` on dedicated worktree at `C:\RC-CIWatchdog\`. 3 open questions block implementation (PR auto-merge policy / bridge escalation envelope / stale-fix cancellation).
- `docs/LCU_PHASE_CAPTURE_WATCHER_PLAN.md` NEW (10.4 KB / 127 lines) - scoping ONLY for replacing champ-select / augment / lobby polling with LCU WAMP push events on Game-PC. 5 open questions block implementation (monitor target by RESOLUTION not index / debounce window / frame format / Cherry urgency / bridge envelope).
- `tools/edit_lint_check.py` NEW (~75 LOC) - PostToolUse hook helper: reads `$CLAUDE_FILE_PATHS`, runs `py -m ruff check --fix` on .py files, byte-scans for U+2014 / U+2013 / U+201C / U+201D / U+2018 / U+2019. Advisory non-blocking exit 0. Uses `chr(0xNNNN)` form in `_BANNED` dict to avoid self-violating the rule (item 154 precedent).

**Local-only (NOT in commit, NOT in repo):**
- `.claude/settings.json` PostToolUse hook entry added at L22-26 calling `edit_lint_check.py`. File is gitignored (`.gitignore:65`); change is LEGION-LOCAL. Operator must replay this edit on Game-PC + Peer if they want the hook on those fleets.
- `C:\Users\Administrator\.claude\projects\C--Riot-Commander\memory\feedback_verify_before_declare_broken.md` NEW - feedback memory: "X is dead / missing / broken / not installed" verdicts need a second independent probe + named stale-doc risk before stating. Indexed in `MEMORY.md` line 34 between `[[feedback_verify_generated_reports]]` + `[[feedback_backlog_path_stale_check]]`. Memory files live outside the repo per `auto memory` system.

**Don't-redo (tomorrow-you):**
- `/wrap` skill drop SKIPPED. Existing `C:\Users\Administrator\.claude\commands\wrap.md` is 7-section superset of the pasted version (git status + push + Game-PC bridge probe + RC restart check + memory updates + session size guard + final summary). Do NOT drop `.claude/skills/wrap/SKILL.md` - would downgrade.
- Pasted parallel-agents prompt was just a copyable quote, no infra to ship.
- CI Watchdog + LCU Phase Capture Watcher IMPLEMENTATION is gated on operator answering the open questions at bottom of each PLAN.md. Do NOT start coding either before that. Both are TDD-first per new `## TDD First` rule.
- New hook helper `tools/edit_lint_check.py` is ADVISORY non-blocking (exit 0 always). Future edits will surface em-dash / smart-quote warnings to stderr but never abort the operator's flow. The drift guard is dual-layered: hook catches at edit-time + `tools/strip_em_dashes.py` + `tools/strip_smart_quotes.py` sweep at audit-time.
- The 5 CLAUDE.md sections are baseline now; do NOT re-pitch a "TDD First" or "Output Constraints" section.
- Smoke-tested the hook on a synthetic em-dash file: detected `em-dash x1` and exit 0. Smoke-tested on the helper itself (clean): exit 0 no output.

**Carries forward:** All item 203 carries unchanged. RC pid 15960 alive=True last_reload_ok=True mode_key=client throughout. No bridge tasks pending.

---

# 2026-05-26 - item 203 SHIPPED: headless-upgrade run - duo_synergy.json frontend mock orphan closure + ground-truth verification of subagent claims

Operator triggered `/headless-upgrade` second consecutive long autonomous run on the same UTC day (item 202 wrapped earlier; this run started immediately after). Same operator-grant scope (frozen-file authority unused; 24-parallel-agents/task authority). 52nd-streak orchestrator pattern (items 134-189 + slim variants 190-198 + items 199 + 200 + 201 + 202 + 203). Pre-flight: HEAD `a7b37d9` clean / CI 6/6 green / ENGINE 1.61.0 / DS 4872 / RC pid 15960 mode=client / 0 open PRs / 0 stale remote branches. Bridge gamepc+peer green; Legion daemon idle.

**4 parallel investigative agents dispatched at start to find genuine actionable work (saturation lane is thin - cc_conditional schema-blocked wave 24+ / L31 saturated rounds 1-6 / UI v2.1 all 16 pages closed at item 202 / cost/latency 30 CLEAN / dead-endpoint cleanup item 186 done / dedup duplicate-fetch item 184 done).**

Per [[feedback_verify_generated_reports]] every agent claim was ground-truth grep-checked before any commit:

- Agent A (cost/latency wave 31): claimed L1 18 markers (baseline 13) + L2 9 _CACHE constants (baseline 12-16). My ground-truth grep: L1 18 markers across 10 .py files (+5 from item 202 baseline = legitimate expansion via routes_dictionary.py 3 markers + replay_coach.py 1 marker; NOT a regression). L2 strict `^[A-Z_]*_CACHE\s*=` returns 0 (wrong regex; agent same error); wider `_CACHE\b` returns 15 routes (within 12-16 prior baseline). Both flagged proposals = measurement errors, NOT actionable.

- Agent B (dead-code sweep): claimed only 1 actionable item (xfail test in test_wireable_sims_p1l3.py for lifesteal sustain - intentional Phase 6 architectural deferral). VERIFIED. NO ACTION.

- Agent C (BACKLOG/ROADMAP stale-sweep wave 24): claimed 0 flips CLEAN saturation. VERIFIED.

- Agent D (web surface sweep): claimed 11 panel JS files orphaned + duo_synergy.json orphan. **PARTIAL MEASUREMENT ERROR**: 10/11 panel "orphans" are actually imported via panel-to-panel chains (champ_select.js imports ban_suggest_toggle / build_order / cc_blended_ehp_threat / cc_conditional_pressure; active_match.js imports cd_ledger / spike_curve / ward_heat / draft_elo; dev.js imports replay_events; last_match.js imports post_game_phases). Agent only grepped main.js imports + missed the chain. **One CORRECT finding**: `web/data/ui_mock/duo_synergy.json` is genuinely orphan at frontend layer.

**Phase 1 `00f96be` (2 files / +69 / -0) feat(ui+test) item 203 - wire duo_synergy.json mock dispatcher in _csvFetchDuoSynergy + drift guard:**

Closes the orphan that surfaced during ground-truth audit. Item 199 Slice CD `c33xxx` shipped:
- Backend `dashboard/routes_duo_synergy.py` (full GET /api/duo-synergy handler).
- Mock fixture `web/data/ui_mock/duo_synergy.json` (45-cell sample payload).
- Test `tests/test_routes_duo_synergy.py` with ASCII guard on the fixture (`AsciiHygieneTests::test_mock_fixture_is_ascii`).

But the FRONTEND wiring never happened: `_csvFetchDuoSynergy` at `web/js/panels/champ_select.js:3134` ONLY fetched the live `/api/duo-synergy` endpoint. When body.dataset.uiMock="1" (operator's dev UI mock toggle via `?ui_mock=1` URL flag + Settings checkbox per item 157), the duo-synergy panel would still hit the live backend - the mock fixture was never loaded.

Fix mirrors 5 prior mock-dispatcher patterns (`_csMockLoad` items 165+181 / `_lmMockLoad` item 183 / `_lobbyMockLoad` item 163 / `_amMockLoad` item 184 / `_csvFetchUserVariants` mock branch item 178 at L2105). Added `isMock` short-circuit at top of `_csvFetchDuoSynergy` (after cache+inflight checks):
```javascript
const isMock = !!(document && document.body && document.body.dataset.uiMock === "1");
if (isMock) {
  _CSV_DUOSYN_INFLIGHT[key] = true;
  fetch("/data/ui_mock/duo_synergy.json", { cache: "no-store" })
    .then((r) => (r && r.ok ? r.json() : null))
    .then((j) => {
      _CSV_DUOSYN_INFLIGHT[key] = false;
      if (j && j.ok) {
        _CSV_DUOSYN_CACHE[key] = { data: j, fetchedAt: Date.now() };
        if (typeof onLoad === "function") onLoad();
      }
    })
    .catch(() => { _CSV_DUOSYN_INFLIGHT[key] = false; });
  return cached ? cached.data : null;
}
```

NEW `tests/test_routes_duo_synergy.py::DuoSynergyMockWireDriftGuard` class (4 tests):
- `test_csvFetchDuoSynergy_has_mock_branch` - asserts `body.dataset.uiMock === "1"` check present in champ_select.js
- `test_csvFetchDuoSynergy_loads_fixture_when_mock` - asserts `"/data/ui_mock/duo_synergy.json"` URL present
- `test_mock_branch_short_circuits_before_live_fetch` - asserts mock URL idx < live `/api/duo-synergy` URL idx (mock must come BEFORE live in source order)
- `test_mock_branch_populates_same_cache` - asserts mock branch writes to the same `_CSV_DUOSYN_CACHE[key] = { data: j, fetchedAt: Date.now() }` shape the live path uses

**Verified:** `py -m pytest tests/test_routes_duo_synergy.py -q` = **24 passed in 0.16s** (+4 over 20 baseline = exactly the new drift guard class). `py -m pytest tests/phase8_smoke/ tests/test_csv_topleft_picks_layout.py tests/test_csv_rune_push_on_selection_change.py tests/test_routes_duo_synergy.py -q` = **127 passed** post-merge. `py -m ruff check .` ALL CHECKS PASSED. `node --check web/js/panels/champ_select.js` exit 0. 0 new non-ASCII bytes. 0 frozen-file touches.

Merge: rebased onto weekly health commit `d77ae4e` (RC-WeeklyHealth task pushed during the run) then pushed `a7b37d9..00f96be`. CI green expected on push.

**Don't-redo:**
- `_csvFetchDuoSynergy` mock dispatcher is the SIXTH consumer of the `body.dataset.uiMock === "1"` pattern. Future panels that wire mock fixtures should mirror this exact shape (cache+inflight gated; short-circuit BEFORE live fetch; populates the same in-memory cache; same onLoad firing semantics).
- The `tests/test_routes_duo_synergy.py::DuoSynergyMockWireDriftGuard` class is the canonical CI-locked drift guard for the wire. If a future maintainer reverts the mock branch (e.g. during a refactor that consolidates fetch helpers) the 4 tests fail before reaching production.
- Cost/latency lever sweep "FLAG" results from sub-agents continue to surface measurement errors per [[feedback_verify_generated_reports]]. The L1 cache_control marker count + L2 _CACHE constant count BOTH need careful grep-pattern verification against current source. The 30-CLEAN streak through item 202 + this run = 31 consecutive CLEAN (L1+L2 confirmed within prior baseline range; not regressions).
- Subagent panel-orphan grep was incomplete: main.js imports + dashboard.css imports together cover only ~60% of the panel surface; the remaining ~40% are imported via panel-to-panel chains. Future "orphan" grep agents MUST also grep `web/js/panels/*.js` for inter-panel imports. The 11 panels Agent D flagged (ban_suggest_toggle + build_order + cc_blended_ehp + cc_conditional_pressure + cd_ledger + spike_curve + ward_heat + draft_elo + replay_events + post_game_phases) are all chain-imported; only duo_synergy.json was a genuine orphan (because the panel itself doesn't exist - the live fetcher is inlined in champ_select.js).
- The orchestrator-merge pattern this run was the SLIM variant (no parallel-slice worktree merge; 1 commit-bearing phase; 4 sequential investigative agents up front to find work then 1 implementation phase). Pattern fits when the saturation lane has 0-1 actionable items.

**Carries forward:**
(a) All item 202 carries unchanged EXCEPT new closure: duo_synergy.json frontend mock is NO LONGER orphan.
(b) Live in-game chip verification owed at next coach tick (mode_key was client throughout this session).
(c) Game-PC HTTP-pull redeploy carry from items 188 (Cherry chain) + 200 (Slice B stale-RC wipe) STILL OWED.
(d) DD Defy heal-on-takedown STILL deferred.
(e) Live ARAM/SR smoke STILL pending.
(f) Calibrations STILL operator-gated.
(g) Legion 1-PC consolidation STILL operator-gated.
(h) cc_conditional wave 24+ schema-blocked.
(i) Frozen-file grant authorized but NOT used this run.
(j) DS test count 4872 / cumulative subtests 1781 (unchanged - non-engine).
(k) item_build.js TODO at L108 (subtract owned sub-item values once items_recipes.json generated) STILL deferred - requires architectural decision on whether to generate items_recipes.json from DDragon `from` field at patch-refresh time + extend items_index.js to expose ITEM_RECIPES + ~200 LOC + test wire; operator-gated.
(l) Lifesteal/spellvamp xfail test in `agents/daemon_slayer/tests/test_wireable_sims_p1l3.py` (sustain modeling deferral, strict=True) STILL operator-gated - either delete on Phase 6 sustain-not-shipping confirmation OR flip to PASS on sustain-shipping implementation.

---

# 2026-05-26 - item 202 SHIPPED: headless-upgrade run - CI ruff F541 fix + champ_select.js 13 sub-floor typography migration + cc_conditional wave 23 Hecarim R distance-gated fear ENGINE 1.61.0 + housekeeping triple docs sync

Operator triggered `/headless-upgrade` long autonomous run with frozen-file grant + 24-parallel-agents-per-task authority. 51st-streak orchestrator pattern (items 134-189 + slim variants 190-198 + items 199 + 200 + 201 + 202). 4 phases sequential (no parallel-slice merge this session - slim variant). Pre-flight: CI RED on item 201 `64fc7cf` for 2x F541 in tests/test_coach_prompt_format_safe.py blocking main; fixed before any new work per skill discipline. 4 stale remote worktree branches deleted (a7763 + a8256 + ad041 + af19e all fully merged into 64fc7cf).

**Phase 0 `3b4eb2a` (4 files / +85 / -3) fix(ci+coach) item 201 polish:**
- tests/test_coach_prompt_format_safe.py: drop 2 extraneous f-prefixes (`py -m ruff check --fix` autofix; CI F541 fix; unblocks main since 64fc7cf 4 CI red runs).
- coach_integration/_coach.py:413-433: detect Anthropic permanent failures (credit balance / rate limit / auth / 400 invalid_request) + write short friendly status text to dashboard CALL pane instead of leaking raw API error JSON.
- web/js/main.js modePill flip stamps `document.title` baseline "RC . <MODE>" on every mode flip so browser tab doesn't persist prior game's champ/time after returning to lobby.
- web/js/main.js HTTP-fallback + SSE + LCU-poller paths stamp `state.latest.liveclient + summoner_cooldowns` BEFORE onState() so renderActiveMatch sees fresh data (was rendering "no live game" mid-game).
- WAKEUP_NOTES.md: item 201 entry already documented.

**Phase 1 `84a999a` (2 files / +193 / -16) chore(ui) champ_select_view.css v2.1 typography token migration + drift guard:**
Closes item 201 carry-forward "13 typography sub-floor sites on champ select Page #8". The carry-forward had STALE line numbers pointing to `web/js/panels/champ_select.js` (the audit subagent had misidentified the file); actual sub-floor sites live in `web/css/panels/champ_select_view.css`. 19 hardcoded sub-floor declarations surveyed; 12 flipped to `var(--fs-xs)` (16px v2.1 floor); 7 documented operator-exceptions preserved with inline rationale.

Flipped to `var(--fs-xs)`:
- `.csv-arch-btn .csv-arch-scorer` (11 -> 16)
- `.csv-pr-title` (13 -> 16)
- `.csv-pr-tag` (13 -> 16)
- `.csv-pb-role-label` (11 -> 16)
- `.csv-pb-role-chip` (15 -> 16)
- `.csv-pb-bans-header` (14 -> 16)
- `.csv-pb-pick-header` (14 -> 16)
- `.csv-sugg-ban-name` (12 -> 16)
- `.csv-sugg-pickorder-cell .csv-sugg-pickorder-idx` (15 -> 16)
- `.csv-build-label` (14 -> 16)
- `.csv-build-rune-name` (14 -> 16)
- `.csv-build-runes` (12 -> 16)

Operator-exception (sub-floor stays, documented rationale):
- `.csv-pr-chip` 14px (explicit operator-directed sub-floor per L1202)
- `.csv-pb-mood-label > span` 14px (parent display:none dead path)
- `.csv-bench-empty` 13px (item 178 audit)
- `.csv-build-spell.is-swapped::after` 10px ("!" indicator badge pseudoelement)
- `.csv-build-spell.empty` 11px (empty placeholder text)
- `.csv-duo-cell-tag` 11px (item 178 dense badge)
- `.csv-arena-cell-name` 13px (item 178 dense 15-cell column)

NEW `tests/test_csv_typography_v21_floor.py` 4 tests LOCK:
(a) the 12 flipped selectors all use var(--fs-xs) (no regression),
(b) the 7 operator-exception selectors stay at expected px with rationale comment present,
(c) any NEW sub-floor declaration without joining _OPERATOR_EXCEPTIONS fails CI,
(d) CSS doesn't gain a non-ASCII byte spike.

ADR-008 asset-hash auto-serves on next dashboard load; no RC restart.

**Phase 2 `084cc50` (43 files / +649 / -55) feat(ds) cc_conditional wave 23 ENGINE 1.61.0 - Hecarim R distance-gated fear:**
Audit subagent (Explore type) dispatched with explicit don't-redo list of 30+ already-shipped REJECT-verified candidates from waves 0-22. Subagent surveyed 115 candidates NOT in registry; surfaced Hecarim R as the canonical range-gated fear payload that prior waves had not matched against the COND_RANGE_GATED tag.

**SHIP Hecarim R Onslaught of Shadows distance-gated fear** primary registry COND_RANGE_GATED prob 0.4 durations_s=(1.5, 1.5, 1.5) flat per R rank `coexists_with_unconditional=True`. Per Meraki 16.10.1 effects_descriptions[1]: "Upon arrival, he fears nearby enemies for 0.75 : 1.5 (based on distance traveled) seconds and slows them by 0% : 99% (based on distance from Hecarim)." Coexists with unconditional Hecarim R 1.0s flat baseline in `_PER_SPELL_CC_DURATIONS["Hecarim"]["R"] = (1.0, 1.0, 1.0)`. **SECOND consumer of the wave 7 forward-marker COND_RANGE_GATED tag** after Maokai R wave 18. **FIRST Hecarim cc_conditional entry anywhere** (E knockback + R baseline fear already in unconditional registry). Hecarim is a NEW cc_conditional champion (was not in registry prior).

Registry growth: 71 entries / 56 champs / 1.60.0 -> **72 entries / 57 champs / 1.61.0** (62 primary + 8 sidecar -> 63 primary + 8 sidecar). COND_RANGE_GATED consumer count 1 -> 2. Tag count UNCHANGED at 13. ENGINE_VERSION 1.60.0 -> 1.61.0 + 32 stale ENGINE pin syncs across DS test files via bulk regex rewrite.

**+27 tests** in NEW `agents/daemon_slayer/tests/test_cc_conditional_wave23.py` (~340 LOC across 10 classes): per-entry shape pin + registry totals growth + COND_RANGE_GATED consumer count + multi-wave coexistence (Maokai + Hecarim) + unconditional coexistence preservation + default include_conditional=False byte-identical + MAX-rule consumer math + evidence from effects_descriptions snapshot + ENGINE pin + forward-marker allowlist + ASCII hygiene.

Consumer math: default `compute_cc_pressure(include_conditional=False)` BYTE-IDENTICAL to 1.60.0 for ALL champions (the wave 23 path skips when False). At include_conditional=True the MAX rule credits MAX(unconditional 1.0s, conditional 1.5 * 0.4 = 0.6s default) = 1.0s; default calibration keeps unconditional winning. Operator override Hecarim:R above 0.667 flips conditional above unconditional.

REJECT verdicts wave 23 (audit subagent full report):
- Jhin W Deadly Flourish "roots them for a duration" - duration lacks explicit numeric value
- Anivia Q recast shatter stun "stun them for a duration" - duration lacks explicit numeric value
- Heimerdinger E center-of-impact 1.5s stun - center-of-impact is spatial NOT tactical condition
- Lillia R Dream Mist 1.5s drowsy - COND_DREAM_STACK forward-marker tag still empty-registry; multi-mark mechanics parse-stripped
- Lissandra W root + R stun / Jinx E knockdown - all UNCONDITIONAL, belong in `_PER_SPELL_CC_DURATIONS` not cc_conditional
- Leona R epicenter stun - epicenter is spatial NOT tactical

Test relaxations: 6 prior-wave assertions relaxed for the 2nd COND_RANGE_GATED consumer. wave 18 `assertEqual(consumers, [(Maokai, R)])` -> `assertIn(("Maokai", "R"), consumers)` + count assertEqual(1) -> assertGreaterEqual(1); wave 12-13 `assertLessEqual(1)` -> `assertLessEqual(2)`; waves 14-17 same. DS suite 4845 -> 4872 (+27 = exactly wave 23 test file).

DS :8893 restarted via `Stop-Process -Id 3876 -Force` (PowerShell - Bash taskkill blocked in Git-Bash env) + `schtasks /Run /TN RC-DaemonSlayer` per [[reference_ds_server_not_supervisor_watched]] -> `/health` engine_version=1.61.0 / patch=16.10.1 / 172 champs / 705 items. RC :8888 unchanged pid 15960 alive=True last_reload_ok=True mode_key=None (client) throughout - non-coach + non-route module edits this session.

**Phase 3 `741e891` (6 files / +8 / -8) docs: sync living docs to wave 23 ENGINE 1.61.0 + 4872 tests + 72/57:**
- ROADMAP.md L165 Fleet status row: ENGINE 1.60.0 -> 1.61.0 + 4845 -> 4872 tests + appended wave 23 narrative.
- docs/DAEMON_SLAYER.md L5 + L32 + cc_conditional summary: ENGINE bump + 71/56 -> 72/57 + wave 23 closure note.
- docs/ARCHITECTURE.md L161: ENGINE bump + waves 0-22 -> 0-23.
- BACKLOG.md L13 cc_conditional ecosystem subsection: waves 1-22 -> waves 1-23 + wave 23 lineage append.
- README.md L46: 4,845 -> 4,872 tests.
- BRIEF.md L20 + L26: ENGINE_VERSION 1.60.0 -> 1.61.0 + 4,845 -> 4,872 passing tests.
- Skipped per [[feedback_no_history_rewrite]]: BRIEF.md historical milestone narrative + WAKEUP_NOTES.md prior sessions.

Parallel investigative agents (Phase 3 read-only):
- BACKLOG/ROADMAP stale-sweep subagent: 2 flips needed (ROADMAP L165 Fleet status ENGINE + cc_conditional 71/56 -> 72/57 - both applied this session); all other code-line anchors verified within +/- 5 tolerance.
- 30th-consecutive cost/latency 7-lever sweep subagent: 5/7 CLEAN + 2 MINOR PROPOSAL operator-gated (cache_control test-file noise + low _CACHE constant count). Per [[feedback_verify_generated_reports]] both flags are likely measurement errors (test files declare cache_control as DATA not RUNTIME use; _CACHE grep target may differ across audits with count fluctuating 12-16) - NOT auto-applied.

**Verified:** DS suite **4872 passed / 1 skipped / 1 xfailed / 1781 subtests in 67.12s** (+27 over 4845 baseline = exactly wave 23 test file). RC suite tests/phase8_smoke 70/70 PASS post-DS-restart. `py -m ruff check .` ALL CHECKS PASSED. py_compile + JS Function-constructor parse OK on all touched files. CI green on 3/4 prior pushes (Phase 0 ruff + Phase 1 typography + Phase 2 wave 23); Phase 3 docs sync in-progress at session-end.

**Don't-redo:**
- The 12 flipped sub-floor selectors in `champ_select_view.css` are CI-locked via `tests/test_csv_typography_v21_floor.py`. Any future maintainer that bumps these back to hardcoded px fails CI. The 7 operator-exception selectors carry inline rationale comments; do NOT bump without operator approval.
- Hecarim R coexists_with_unconditional=True is the canonical pattern for SECOND COND_RANGE_GATED consumer. Future wave 24+ candidates can reuse the COND_RANGE_GATED tag + coexists flag without re-pitching either schema.
- The 6 wave 23 REJECT-verified candidates (Jhin W vague / Anivia Q vague / Heimerdinger E spatial / Lillia R dream_stack-empty / Lissandra W+R unconditional / Jinx E unconditional) are NEGATIVES - do NOT re-pitch.
- The `champ_select_view.css` was the actual file for item 201's "13 typography sub-floor sites" carry-forward (not `champ_select.js` as the audit subagent claimed). Future audit agents flagging typography sub-floors should grep ACROSS both .js + .css files since `font-size:` lives in CSS rules only.
- The orchestrator-merge-with-parallel-slices pattern was NOT used this session (4 sequential phases, no worktree branches created); the simpler sequential-commit pattern is the slim variant for headless runs with NO scope-fork mid-flight.
- The cost/latency lever sweep "FLAG: MINOR" results from sub-agents are operator-gated proposals NOT auto-applied per [[feedback_verify_generated_reports]] - test-file cache_control + `_CACHE` constant counts are both likely measurement artifacts at sub-agent visibility.
- `Stop-Process -Id <pid> -Force` (PowerShell) is canonical for DS restarts; Bash `taskkill /F /PID` blocked in Git-Bash env per recent ledger pattern.
- Orchestrator-merge pattern now 51 consecutive runs (items 134-202; slim variants 190-198 + 200 + 201 + 202).

**Carries forward:**
(a) All item 201 carries CLOSED EXCEPT (a)-relaxed: 13 typography sub-floor sites NO LONGER carry (12 flipped + 7 operator-exception preserved this session).
(b) Live in-game chip verification owed at next coach tick (mode_key was client/None throughout this session).
(c) All item 200 carries unchanged: LCU agent redeploy via HTTP-pull dance for `delete_stale_rc_item_sets` + apply_item_sets_batch + champ select PICK section / DS top-picks UI changes - operator-gated.
(d) DD Defy heal-on-takedown STILL deferred (operator-gated).
(e) Live ARAM/SR smoke STILL pending.
(f) Calibrations STILL operator-gated.
(g) Legion 1-PC consolidation STILL operator-gated.
(h) cc_conditional wave 24+ candidates: COND_DREAM_STACK forward-marker tag (wave 7) STILL empty-registry; Lillia passive multi-mark mechanics parse-stripped in damage_blocks-only format - operator-gated schema lift needed beyond cast_time/effects_descriptions/notes/parent_resource to unblock.
(i) Frozen-file grant NOT used this session despite authorization.
(j) DS test count 4872 / cumulative subtests 1781.
(k) Stale local worktrees (24+ from prior orchestrator runs) STILL harness-locked - parent owns lifecycle per established pattern; left in place.
