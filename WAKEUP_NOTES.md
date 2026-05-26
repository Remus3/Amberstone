# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 archived to docs/history_notes.md. Only the last 3 sessions kept here.

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

---

# 2026-05-26 - item 201 SHIPPED: LIVE BUG fix SR coach KeyError + Choices-first refactor w/ Alt+1/2/3 hotkeys + game-monitor skill gate `{game}` -> `{sr}`

Operator triggered "starting ranked sr - monitor UI and game, fix as needed -> smoke tests and checks and error corrections". Active ranked SoloDuo queue 420 mid-session. **LIVE PRODUCTION BUG SURFACED + ROOT-CAUSED + FIXED + 2 RC RESTARTS during the operator's first ranked SR game in 5 days.**

**Root cause:** `coach_integration/_sr_prompt.py:131` SR_SYSTEM_PROMPT had a JSON schema literal `[{"key":"A","label":"<3-5 word option>",...}]` inside the Choices field doc. Python's `str.format(profile=..., sr_rune_rec=..., sr_build_note=..., adaptation_hint=...)` at `coach_integration/_coach.py:262` parses `{"key":"A",...}` as a format field with field-name `"key"` (5-char literal with quotes) and raises `KeyError('"key"')` every coach tick. ARAM + Arena + Brawl 3x prompts had the SAME bug. Bug landed 2026-05-21 commits `58b7d20` (Brawl + SR native choices emit) + `b3cd60b` (ARAM/Arena phase 2). The 5-day window before today's ranked SR game was the first time the SR `.format()` path was exercised live. Symptom in `logs/2026-05-25.log`: `ERROR coach [_coach.py:196] Coach error: '"key"'` repeating every ~30s in-game with `coach.action / immediate / next` all empty.

**Fix `64fc7cf` (12 files / +554 / -68; pushed origin/main `2f703eb..64fc7cf`):**
1. **Brace-escape on 6 schema lines** (1 SR + 1 ARAM + 1 Arena + 3 Brawl URF/OFA/NB): `[{"key":"A",...},...]` -> `[{{"key":"A",...}},...]` so `str.format()` sees literal `{{...}}` and renders single-brace `{...}` back. Tools `tools/strip_em_dashes.py` + `tools/strip_smart_quotes.py` precedent.
2. **Dropped LLM `Immediate:` + `Next:` emit** from all 4 in-game system prompts. Operator scope expansion: "drop the coach prompt firing for the immediate/next, use the A+B choice surfacing, and make sure that the hotkey selections (ALT+1, ALT+2, ALT+3) are wired and the feedback can be received and acted upon. surface those choices within the immediate panel."
3. **Choices is now REQUIRED** (was OPTIONAL) in all 4 prompts. Token spend reduction + the JSON array is the primary actionable surface, not a sidecar.
4. **`coaches/brawl_coach.py::_NB_OUTPUT_KEYS / _URF_OUTPUT_KEYS / _OFA_OUTPUT_KEYS`** dropped `"immediate"` so `parse_fields(raw, output_keys)` doesn't silently look for a field the LLM no longer emits.
5. **`web/js/panels/coach_choices.js`**: window-level keydown handler for Alt+1/Alt+2/Alt+3 funnels into a shared `_activateChip` helper (same path as click); each chip carries an `Alt+N` pill so the digit binding is visible without hover; `_latestState` module-stash so the keyboard handler can snapshot game_context outside `renderCoachChoices`'s closure; `.rc-ack-bubble` toast renders after a successful POST so hotkey picks have visible ACK feedback.
6. **`web/js/panels/right_now.js`**: `hasChoices` guard hides `#rn-immediate` when `state.coach.choices.length > 0`, so the chips visually occupy the slot directly under `#rn-action` (per operator: "surface those choices within the immediate panel").
7. **`web/css/panels/coach_choices.css`**: chips column-stack (was horizontal flex-wrap), label at `--fs-md` (18px), chip meets `--hit-min` (42px), plus `.rc-hotkey` Alt+N pill + `.rc-ack-bubble` toast rules.
8. **`.claude/commands/game-monitor.md`** (user-level, not in repo): gate `{game, arena, aram, tft, brawl}` -> `{sr, arena, aram, tft, brawl}`. The prior set had a phantom `"game"` mode_key that `core/queue_modes.py` never emits (SR is `"sr"`). The skill never fired for SR games before this fix.

**Tests (+31 new tests across 2 new files):**
- NEW `tests/test_coach_prompt_format_safe.py` 7 tests: pin `.format()` works on each in-game prompt + repro the exact `KeyError('"key"')` shape so future JSON-in-prompt regressions fail CI before a live tick. Anchor includes `assertEqual(ei.value.args, ('"key"',))` so future Python parsing-rule changes are caught.
- NEW `tests/test_coach_choices_alt_hotkey.py` 24 tests: pin Immediate/Next drop in all 4 prompts + brawl output_keys drop + Alt+1/2/3 keydown bind + `ev.altKey` + Digit1/2/3 recognition + `_activateChip` shared path + ACK toast CSS + `right_now.js hasChoices` suppression order.
- 5 existing tests updated: `Choices: <OPTIONAL` -> `<REQUIRED` + `Return [] if` -> `Return []` across sr/aram/brawl `_choices_emit.py`.
- Smoke: `223 passed in 2.79s` across coach + phase8_smoke surfaces.

**RC restart sequence:** pid 7500 -> 2504 (SR brace fix) -> 2372 (full sweep ARAM/Arena/Brawl) -> 10464 (this commit's full prompts). `last_reload_ok=True` throughout. Each restart was 5-10s coach blackout but coach was already broken so no regression. Asset hash `5c6b5a4247 -> 8099493d46` across the 3 frontend edits; ADR-008 auto-served on Game-PC Chrome.

**Champ select audit subagent (Explore) launched in parallel during coach refactor:** 5-phase verdict for page #8 SR. STRUCTURE / HIT-TARGETS / ASCII / HIERARCHY = PASS. TYPOGRAPHY = FAIL: 13 sub-floor sites (12-15px hardcoded under `.csv-*` scope) at `web/js/panels/champ_select.js:769, 787, 1179, 1264, 1386, 1413, 1456, 1483, 1500, 1708, 1717, 1745, 2456`. All must upgrade to `var(--fs-xs)` (16px v2.1 floor). NO ALT-hotkey collision. Operator-gated for next pass.

**Don't-redo:**
- The `{{...}}` brace-escape on JSON literals inside `.format()`'d prompts is the canonical fix. NEW `tests/test_coach_prompt_format_safe.py` LOCKS the invariant - any new JSON literal in a system prompt that forgets to escape fails CI before reaching production.
- `coach.choices` is the primary actionable surface NOT a sidecar. Future coach surfaces (e.g. a new mode coach) should follow the same pattern: drop prose Immediate/Next, REQUIRED Choices, render in `#rn-immediate` slot via `hasChoices` guard.
- Alt+1/2/3 binding is in `web/js/panels/coach_choices.js` `_onAltDigitKeydown` (capture-phase, preventDefault on match). The handler is bound ONCE at module load via `window.__rcCoachChoicesAltBound` sentinel. The `_chipByKey` cache is rebuilt on every `renderCoachChoices` call; outside-of-render keypresses (no chips visible) are NO-OPs.
- The game-monitor skill gate fix (`{game}` -> `{sr}`) is in the user-level `.claude/commands/` directory - it survives `git clean` but won't be tracked in the repo. The 5-mode gate set is now correct against `core/queue_modes.py::QUEUE_ID_TO_MODE_KEY` values.
- Operator's commit-message numbering ("item 189" in `64fc7cf` subject) is a stale-snapshot artifact - the actual sequence number after item 200 is item 201 per WAKEUP_NOTES; the SHA is canonical regardless of textual label.
- Game-PC LCU agent redeploy from item 200 Slice B (`delete_stale_rc_item_sets`) STILL OWED at next Arena/SR window via HTTP-pull dance per [[reference_gamepc_http_server_redeploy]].

**Carries forward:**
- 13 typography sub-floor sites on champ select Page #8 (lines 769, 787, 1179, 1264, 1386, 1413, 1456, 1483, 1500, 1708, 1717, 1745, 2456) - bump to `var(--fs-xs)`. Operator-gated.
- Live in-game chip verification owed at next coach tick (mode_key was `client` throughout end of session).
- All item 200 carries unchanged (LCU agent redeploy / etc).

# 2026-05-26 - item 200 SHIPPED: parallel 4-slice UI audit drain - SR/ARAM/Arena item-build meta conformance (19 ARAM boots fixes) + LCU stale-RC item-set wipe pre-push (condense dropdown 20+ to <=4) + rune-push end-to-end drift guard (verdict EXISTS) + Champ Select PICK section moved to top-left card + DS top-picks carry removed

Operator triggered "NEXT SESSION: quick UI audit in parallel" with 4 explicit task threads. 50th-streak orchestrator pattern (items 134-189 + slim variants 190-198 + items 199 + 200). 4 worktree-isolated agents dispatched concurrent on disjoint surfaces (Slice A data/champion_loadouts.json + Slice B LCU agent / dashboard / JS push wire + Slice C tests-only / verdict EXISTS + Slice D UI HTML/CSS/JS restructure). No AskUserQuestion (operator scope explicit). Pre-flight: 0 open PRs; HEAD = `e8d3afa` clean; RC pid 8436 mode=client.

**Slice A `9efaa6f` (merge `432831a` ort 0 conflicts 4 files +532 / -20) feat(loadouts) SR/ARAM/Arena item-build meta conformance + 19-champ ARAM boots fix + drift guard:**
- Pre-state: SR=0 drift / Arena=0 drift (already CLEAN per item 167 align), ARAM=20 drift across 19 champs.
- Top patterns: 17x ARAM ap-tank Rod-of-Ages-rush boots-at-index-2 anti-pattern (Ahri / Anivia / Annie / AurelionSol / Fiddlesticks / Galio / Hwei / Karthus / Lillia / Mordekaiser / Morgana / Neeko / Nunu / Rammus / Swain / Syndra / Viktor) flipped to canonical items[1]=boots.
- 2x bootsless violations (Cassiopeia + Yuumi ARAM had Sorcerer's Shoes) dropped per `core/build_order.py::_BOOTSLESS_CHAMPS`.
- 1x Lulu on-hit ARAM boots position fix.
- NEW `tools/champion_loadout_validate_meta.py` ~270 LOC argparse + `--dry-run` + `--no-backup` flags + atomic backup to gitignored `data/champion_loadouts.json.bak-slice-a-<UTC-stamp>` (.gitignore entry added mirroring `data/*.db.bak-*` precedent).
- NEW `tests/test_champion_loadouts_meta_conformance.py` ~190 LOC / 7 tests (4 invariant + 2 lock-step + 1 ASCII).
- Coverage gaps from item 167 (SR 10 / ARAM 3) verified ALL CLOSED by items 178/179 multi-path collapse.

**Slice B `0b81310` (merge `bb951e1` ort 0 conflicts 4 files +430 / -0) feat(lcu+dashboard+ui) LCU stale-RC item-set wipe pre-push (condense dropdown from 20+ to <=4 per active scope):**
- Root cause confirmed: per item 165 `apply_item_set` is replace-by-uid (not wipe-all-RC); 4 paths * 3 modes = 12 sets per champion accumulate across session; 2-3 champions/session = 24-36 stale RC- entries matching operator's "20+".
- NEW handler `delete_stale_rc_item_sets(active_champion, active_mode)` at `tools/gamepc_lcu_agent.py:1010-1071`: GET current item-sets list -> DELETE every uid starting with `RC-` that does NOT match `RC-<active_champion>-<active_mode>-*` prefix (trailing-hyphen anchor guards substring false-keeps like Jinx vs JinxJunior or sr vs srtest). Operator non-RC- sets preserved unconditionally. Current-scope RC- sets preserved for apply-batch idempotence. Short-circuit PUT when nothing to wipe.
- Wired into `_LCU_ALLOWED_CMDS` at `dashboard/routes_loadout.py:46`.
- JS wire at `web/js/panels/champ_select.js::_csvMaybePushBuildsToLCU` L1801-1815 as PRE-PUSH best-effort try/catch (apply_item_sets_batch fires regardless on rune-push parity per Slice C).
- NEW `tests/test_lcu_item_sets_wipe_stale.py` ~340 LOC / 14 tests across 5 classes (HandlerShape 4 + WipeScope 6 + AllowlistDriftGuard 1 + JsWireDriftGuard 2 + AsciiHygiene 1).
- **Game-PC redeploy OWED:** live agent at `C:\RC-Agent\gamepc_lcu_agent.py` still runs pre-wipe code; redeploy via HTTP-pull dance per [[reference_gamepc_http_server_redeploy]] before operator can verify live dropdown condense.

**Slice C `b73799c` (merge `9679f12` ort 0 conflicts 1 new file +281) test(runes) rune push end-to-end drift guard - verdict EXISTS (no code fix needed):**
- Audit verdict: rune push works end-to-end on variant selection change for BOTH item-178 collapsed-path clicks AND legacy ARAM/Arena/experimental row clicks. Existing wire is correct.
- Flow verified: `_csvWireBuildVariants` L2549 wires both `.csv-build-path-row` clicks L2566 + `.csv-build-row` clicks L2588 -> `_csvApplyLoadout` L2509 POSTs `/api/loadout/apply` with `push_runes: true` default -> `dashboard/routes_loadout.py::_serve_loadout_apply_post` L144 -> `_enqueue(resolved.get("rune_cmd"))` L226 -> vision server `/lcu-cmd` -> `tools/gamepc_lcu_agent.py::apply_runes` handler L1010 -> PATCH/POST `/lol-perks/v1/pages` + PUT `/lol-perks/v1/currentpage` chain.
- Live verification: `coaches/loadout_resolver.py::resolve()` colon-form `<variant>:<path-key>` overlays per-path runes; Jinx `sr-collapsed:adc-crit` -> Lethal Tempo / Precision; Jinx `sr-collapsed:sr-bruiser` -> Conqueror / Precision = distinct LCU pages.
- NEW `tests/test_csv_rune_push_on_selection_change.py` 15 tests across 5 classes (JsVariantClickFiresApplyLoadoutTests 6 + DashboardAllowlistRuneCmdTests 3 + GamepcAgentRuneHandlerTests 3 + ResolverRuneCmdSmokeTests 2 + AsciiHygiene 1). Zero edits to production code.

**Slice D `70509b6` (merge `ed0902f` auto-merge clean 4 files +308 / -46) feat(ui) Champ Select PICK section moved to top-left card + DS top-picks carry section removed (frees space for 101 info area):**
- Identification: "DS top picks carry" = the `.csv-arch-preview` block inside `_csvArchetypePickerHtml` at `champ_select.js:1914-1951` (3 horizontal cells under the 6-archetype-buttons grid showing "DS top picks - <archetype>" with item icons; introduced item 168 commit `81925a6`). The 6-archetype-selectables picker itself UNCHANGED (item 168/178 operator-protected).
- Move scope: only the PICK 4-pick TOP sub-panel of Pick & Ban (item 168 `.csv-pb168-section[data-section="picks"]`) moves to top-left `.csv-card-allies` mount via NEW `#csv-picks-target`. MIDDLE bans + BOTTOM duo-synergy (101.qq.com, item 199 Slice CD) stay in row-2 `#csv-pickban-body`.
- `_csvRenderPickBan` split into picks + bans subroutines; picks wiring scope restricted to new top-left mount.
- NEW `.csv-card-allies-body` flex column rule + `#csv-picks-target` grow rule in `web/css/panels/champ_select_view.css`.
- 5-phase audit PASS per [[feedback_phase3_fixture_ritual]]: STRUCTURE + TYPOGRAPHY (0 new sub-floor declarations) + HIT-TARGETS (`.csv-pb168-cell` 38px icon density preserved) + ASCII (0 new non-ASCII bytes) + HIERARCHY (4 distinct visual tiers).
- NEW `tests/test_csv_topleft_picks_layout.py` ~247 LOC / 18 tests across 5 classes (grep-based pin tests for PICK in top-left + carry removed + Pick & Ban structure preserved).
- Live UI capture deferred to next operator session (ADR-008 asset-hash auto-serves; no RC restart needed for UI alone).

**Merge order:** A `432831a` -> B `bb951e1` -> C `9679f12` -> D `ed0902f`. Slice B + D both touched `web/js/panels/champ_select.js` at DISJOINT regions (B at L1801-1815 pre-push wire / D at L1914-1951 `.csv-arch-preview` removal + `_csvRenderPickBan` split) -> ort auto-merged clean with 0 conflicts. Pushed origin/main `e8d3afa..ed0902f`.

**Verified:** `py -m pytest tests/test_champion_loadouts_meta_conformance.py tests/test_lcu_item_sets_wipe_stale.py tests/test_csv_rune_push_on_selection_change.py tests/test_csv_topleft_picks_layout.py tests/test_champion_loadouts_no_unique_clash.py tests/test_champion_loadout_autogen.py tests/test_champion_loadout_collapse_to_paths.py tests/test_champion_loadout_collapse_aram_arena.py tests/phase8_smoke/ -q` = **231 passed in 2.39s** (+54 over baseline = exactly 7 + 14 + 15 + 18 new tests across the 4 slices). `py -m ruff check .` ALL CHECKS PASSED. `node --check web/js/panels/champ_select.js` exit 0. `py -m py_compile tools/gamepc_lcu_agent.py dashboard/routes_loadout.py tools/champion_loadout_validate_meta.py` clean. DS :8893 untouched (non-engine; serves 1.60.0 from item 199; not restarted). RC :8888 restarted via `restart_trigger.txt` -> pid 7500 alive=True last_reload_ok=True mode=client (picks up new `delete_stale_rc_item_sets` allowlist; Slice D UI auto-served via ADR-008).

**Don't-redo:**
- `tools/champion_loadout_validate_meta.py` is the canonical drift detector + fixer for SR/ARAM/Arena boots-position + bootsless-champ + first-item-archetype invariants. Future patch upgrades that regenerate autogen seeds should run this tool to flatten drift before committing.
- The ARAM ap-tank Rod-of-Ages-rush anti-pattern was a SEED-LEVEL drift: the auto-aram-primary scorer placed the Mythic/Rod-of-Ages first item correctly but `tools/champion_loadout_align.py` (item 167) was BYPASSED for ARAM in item 166's hand-curate merge. Drift was localized to the 17 ap-tank ARAM variants because `_DEFAULT_BOOTS_BY_ARCHETYPE` maps ap-tank to Sorcerer's Shoes and the hand-curate cloned the auto seed without boots-injection on item 166's merge path. Future ARAM hand-curate passes MUST also run `champion_loadout_validate_meta.py --fix` after merge.
- `delete_stale_rc_item_sets` LCU handler is the canonical chokepoint for RC- set hygiene. The trailing-hyphen anchor in the prefix match (`RC-<champ>-<mode>-` NOT `RC-<champ>-<mode>`) is essential to avoid substring false-keeps (Jinx vs JinxJunior; sr vs srtest). Future RC- set UID schema changes MUST preserve the `RC-<champion>-<mode>-<path>` trailing-hyphen separator discipline.
- The rune-push wire is END-TO-END CORRECT as-is (verdict EXISTS); future audit waves should NOT re-pitch a "missing rune push" fix without first running `tests/test_csv_rune_push_on_selection_change.py` (15-test drift guard locks the wire integrity).
- The PICK-to-top-left layout is the canonical Champ Select top-left composition going forward. `.csv-arch-preview` is DEAD; do NOT re-introduce a duplicate DS top-picks render block - the 6-archetype-selectables picker carries top-3 DS items per archetype natively (item 168 `.csv-arch-preview` block was the duplicate that was operator-flagged this session).
- The orchestrator-merge pattern is now 50th-streak (items 134-189 + slim variants 190-198 + items 199 + 200). Disjoint file surfaces (data + LCU/dashboard/JS + tests-only + UI) land 0 merge conflicts.
- The 4-slice parallel dispatch with one truly disjoint surface per agent is durable for "audit + fix-as-needed" sessions.

**Carries forward:**
(a) Items 197 + 198 + 199 carries unchanged EXCEPT: (n)-item-199 UI audit work DONE this session = item 200.
(b) NEW carry: Game-PC HTTP-pull redeploy of `gamepc_lcu_agent.py` to `C:\RC-Agent\gamepc_lcu_agent.py` HARD-OWED at next non-game window (operator does HTTP-pull dance per [[reference_gamepc_http_server_redeploy]]: Legion `py -m http.server 8765 --bind 0.0.0.0 --directory tools` -> Game-PC `Invoke-WebRequest` -> sha256-verify -> taskkill old pid -> atomic Move-Item -> pythonw relaunch). Compounds with item 188 Slice C 4-PATCH Cherry chain redeploy carry - operator can redeploy ONCE carrying BOTH (NEW Slice B stale-RC wipe + Cherry).
(c) Cherry augment live verification STILL OWED at next Arena 1750 window after carry (b) redeploy lands.
(d) Live UI capture of new PICK-to-top-left layout OWED at next operator-driven Champ Select session (mock fixture at `?ui_mock=1&mode=sr#champ-select`).
(e) Live ARAM/SR smoke STILL pending.
(f) Calibrations STILL operator-gated.
(g) Legion 1-PC consolidation STILL operator-gated.
(h) Active Match #11/12/13 real in-game capture STILL OWED.
(i) v2.1 visual captures pages #9/10/11/12/13/14/15/16 STILL OWED at next operator-driven Chrome session.
(j) Rell W form 1 + cc_conditional wave 24+ candidates per item 199 STILL operator-decision-gated / require schema lift.
(k) Phase 3 95% N=50+ gate STILL UNREACHABLE (zero-cadence inbound bridge traffic per item 199 carry).
(l) Duo-synergy panel live UI capture + other lane combos (top+jng, jng+mid, mid+sup) STILL operator-gated separately (item 199 carries (l) + (m)).
(m) Frozen-file grant NOT used this session.

