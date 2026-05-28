# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-05-27 (late evening) - item 207 SHIPPED: LCU Phase Capture Watcher implementation - tools/gamepc_phase_watcher.py + 64 TDD tests + /upload-frame event_meta extension + Game-PC installer

Operator: "continue WAKEUP_NOTES.md -> Resume a specific carry-forward -> LCU Phase Capture Watcher". Resumed item 204's deferred scoping doc `docs/LCU_PHASE_CAPTURE_WATCHER_PLAN.md`. AskUserQuestion 4-question scope fork pinned per [[feedback_scope_decision_cadence]]: (Q1) Capture target = **BOTH monitors per event** (game 1920x1080 + dashboard 1920x1280; classified by RESOLUTION not index per [[reference_gamepc_monitor_index_volatility]]); (Q2) Debounce = per (topic, sub_phase, queue_id) per gameflow cycle (recommended default); (Q3) Frame format = JPEG q75 inherit (recommended default; matches gamepc_screen_agent.py contract); (Q4) Cherry urgency = standard debounce (recommended default; CHERRY_NO_DEBOUNCE flag stays False initially); Q5 bridge envelope = YES emit kind=ui_capture (defaulted; low-cost UI-audit hook).

**Shipped (6 files / +1010 / -3):**
- `tools/gamepc_phase_watcher.py` NEW (~480 LOC) - WAMP-JSON v2 client + 5 topic classifiers (gameflow_phase / champ_select_session / cherry_augments / cherry_augment_select / lobby) + `Debouncer` class + per-monitor DXGI capture orchestrator + JPEG q75 encoder + bridge envelope builder + sidecar JSON writer + reconnect loop with exponential backoff capped at 30s. Lockfile auth mirrors `tools/gamepc_lcu_agent.py:146` shape. Capture lifts the bettercam path from `tools/gamepc_screen_agent.py:206` (NOT a continuous loop - on-demand only per [[feedback_gamepc_screen_capture_bsod]]). Both monitors per event Q1: `capture_both_monitors()` iterates idx 0/1, each result classified by height (1080 -> "game" / 1280 -> "dashboard" / else "unknown"). Live deployment requires `py -m pip install bettercam websocket-client` on Game-PC.
- `tests/test_gamepc_phase_watcher.py` NEW (~520 LOC / **64 tests across 13 classes**) - TDD-first stub-driven: ClassifyGameflowPhase 9 (incl. drift guard for unknown phase strings like "RiotBlitz") + ClassifyChampSelectSession 6 + ClassifyCherryAugments 4 + ClassifyLobby 6 + Debouncer 5 (incl. reset_cycle invariant) + WampMessage 5 (subscribe frame slash->underscore + parse_wamp_event type-8 only + garbage->None) + TopicDispatch 2 (SUBSCRIBED_TOPICS constant locked + unknown topic returns None) + SidecarWrite 2 (filename shape + JSON disk write) + BridgeEnvelope 3 (kind=ui_capture + id field + summary) + UploadFramePayloadShape 1 (event_meta carried) + BothMonitorsCapture 2 (resolution-based labels) + JpegQualityDefault 2 (drift guard for JPEG q75) + AsciiHygiene 2 + WiredSitesGrep 11 (pins all 9 helpers + 2 constants) + DispatchIntegration 4. 64/64 PASS.
- `tests/test_vision_frame_event_meta.py` NEW (~110 LOC / **3 tests**) - drift guard for `vision_server/_frame.py` event_meta extension: polling upload without event_meta still works (event_tagged=False) + dict event_meta is persisted in cache + non-dict event_meta is coerced to None. 3/3 PASS.
- `vision_server/_frame.py` EXTENDED (+9 / -2) - `handle_upload_frame()` reads optional `event_meta` field; type-checks dict (else None); persists in `_latest_frame` + `_frames_by_source[src]` slots; response carries `event_tagged: bool`. Backward-compatible: polling agent uploads continue to work unchanged.
- `tools/gamepc_phase_watcher_install.ps1` NEW (~140 LOC) - Game-PC scheduled-task installer with at-logon trigger. Pulls watcher source from Legion's `/agent/`, kills any existing watcher pid via taskkill (PowerShell Get-CimInstance probe), registers `RC-PhaseWatcher` task running pythonw.exe with sidecar dir flag, starts + verifies pid alive. `-DryRun` flag for safe preview. Mirrors `tools/bridge_watcher_install.ps1` install discipline.
- `data/event_captures/` NEW directory + `.gitkeep` - sidecar JSON destination; **distinct from `data/coaching_data/`** so event-capture content does NOT leak into coach-prompt context per the plan's "Don't-redo" rules.

**Scoping doc updated:**
- `docs/LCU_PHASE_CAPTURE_WATCHER_PLAN.md` prepended with `**SHIPPED 2026-05-27 (item 207).**` header listing implementation files + the 5 locked Q answers. Plan body preserved verbatim below for design-record purposes per [[feedback_no_history_rewrite]].

**Verified:** `py -m ruff check ...` ALL CHECKS PASSED on all 5 touched/new code files. `py -m pytest tests/test_gamepc_phase_watcher.py tests/test_vision_frame_event_meta.py tests/phase8_smoke/ -q` = **137 passed in 2.55s** (64 + 3 + 70 = 137). Full RC suite `py -m pytest tests/ -q --ignore=tests/python-embed` = **3811 passed / 1 skipped / 71 subtests in 61.47s** (item 206 baseline 3674 + 67 new + diff). DS suite untouched (no engine bump; DS :8893 serves 1.61.0 / 16.11.1 from item 206 unchanged; not restarted). RC :8888 unchanged (no route module edits; vision_server changes pick up on next vision-server bounce which operator can defer to next reboot).

**Don't-redo (tomorrow-you):**
- The 4 operator scope-fork answers are LOCKED in the watcher source as module-level constants: `USE_JPEG = True` + `JPEG_QUALITY = 75` + `GAME_MONITOR_HEIGHT = 1080` + `DASH_MONITOR_HEIGHT = 1280` + `CHERRY_NO_DEBOUNCE = False`. Drift-guard tests pin these values. Operator can flip CHERRY_NO_DEBOUNCE later for item 187 Slice C live verification if they want every available[] transition captured per Arena game.
- `Debouncer` class shape: 1 set keyed by `(topic, sub_phase, queue_id)` tuples + `reset_cycle()` on EndOfGame transition. Do NOT add time-bound debounce (Q2 explicitly rejected the 10s window option).
- Both-monitor capture via `capture_both_monitors()` iterates idx 0/1 and classifies by RESOLUTION; the index swap across reboots noted in [[reference_gamepc_monitor_index_volatility]] is handled by `_classify_monitor(width, height)` mapping height->label. If operator changes monitor resolutions in the future, update `GAME_MONITOR_HEIGHT` + `DASH_MONITOR_HEIGHT` constants (both pinned by tests).
- `vision_server/_frame.py` event_meta extension is BACKWARD-COMPATIBLE - polling agent uploads without the field continue to work + log to event_tagged=False. Do NOT add a required event_meta field to the upload schema.
- Bridge envelope `kind=ui_capture` is the canonical home for event-driven UI-capture notifications. Future UI-audit-ritual subagent on Legion can subscribe to that envelope kind specifically.
- The watcher's WAMP loop is GUARDED on `websocket-client` import; if the package is missing on Game-PC, watcher degrades gracefully (logs critical + exits) rather than crashing. Polling agent stays alive independently per the plan's failure-isolation goal.
- The 5 SUBSCRIBED_TOPICS are: `/lol-gameflow/v1/gameflow-phase` + `/lol-champ-select/v1/session` + `/lol-cherry-game-intra-event/v1/augments` + `/lol-cherry-game-intra-event/v1/augment-select` + `/lol-lobby/v2/lobby`. TFT and Replay phases intentionally OUT-OF-SCOPE per plan. Future TFT-specific watcher could be a sibling module.
- DXGI on-demand single-frame capture only. NEVER reintroduce the continuous screen-agent loop in this watcher - the polling agent's bettercam camera-release discipline is the BSOD-clean pattern; this watcher creates + releases per event.
- Capture failure per monitor (one of 2 raises) does NOT block the other monitor's upload + the cycle still emits the bridge envelope with whatever frames landed. Both monitors failing -> skip sidecar + bridge entirely (no orphan capture event).
- The mid-implementation test failure was: `BothMonitorsCaptureTests.test_capture_both_monitors_returns_two_entries` initially used a `MagicMock` returning same resolution for both calls -> both labels classified as "game". Fixed the test to use `side_effect` with distinct per-index resolutions (1080 + 1280) which reflects the operator's actual setup. The second test `test_capture_classifies_monitors_by_resolution` was already correct. Mirroring: when a test sets up multiple per-call returns, use `side_effect` not `return_value`.

**Carries forward:** 
- Item 206 carries ALL unchanged (DDragon 16.11.1 + DS 16.11.1 baseline + 16.10.1 frozen historical anchor; do NOT re-flip).
- Item 205 carries ALL unchanged (UNIVERSAL_FILES portable bootstrap kit at desktop folder; out-of-tree).
- Item 204 carries ALL unchanged EXCEPT: LCU Phase Capture Watcher implementation NO LONGER deferred (DONE this session). CI Watchdog implementation STILL deferred pending 3 open questions in `docs/CI_WATCHDOG_PLAN.md`.
- **NEW carry: Live deployment of watcher to Game-PC OWED.** Operator runs `tools/gamepc_phase_watcher_install.ps1` once. Prereqs: `py -m pip install bettercam websocket-client` on Game-PC. First live cycle should land event-tagged frames in vision server `/latest-frame?source=game-pc-event-game` (or `-dashboard`) and JSON sidecars under `data/event_captures/`. Bridge envelope `kind=ui_capture` lands on Legion's `:8888/api/bridge`.
- **NEW carry: Item 187 Slice C Cherry augment live verification can now consume event-driven captures.** When operator enters Arena 1750 augment-phase, watcher fires on first non-empty `available[]` and captures both monitors. The 4-endpoint PATCH chain at `tools/gamepc_lcu_agent.py:1179-1194` priority order can be empirically verified by inspecting the watcher's `cherry_augment_select` capture (response confirms which endpoint accepted the PATCH).
- DD Defy still deferred / calibrations still operator-gated / Legion 1-PC consolidation still operator-gated / live UI captures for pages #11/12/13 still gated on in-game window (but now event-driven once the watcher deploys). Frozen-file grant NOT used this session.

---

# 2026-05-27 (evening) - item 206 SHIPPED: DDragon + DS patch 16.10.1 -> 16.11.1 + 9 patch-drift test fixes

Operator: "new patch  // check everywhere for updates and commit + push". Live DDragon dropped 16.11.1; RC was pinned at 16.10.1 (cached 2026-05-13). Full refresh chain executed end-to-end. 1 commit `ac83a4b` pushed origin/main `9af3c1a..ac83a4b`; ENGINE_VERSION unchanged at 1.61.0 (data refresh only). DS :8893 restarted via `schtasks /Run /TN RC-DaemonSlayer` -> serves patch=16.11.1 / 172 champs / 705 items. RC :8888 unchanged pid 16064 alive=True mode_key=client throughout.

**Refresh chain:**
- `py scripts/data_pipeline.py all` -> DDragon meta refresh (703 items / 172 champs / 35 spells / 16.11.1)
- `py tools/daemon_slayer_extract.py` -> data/daemon_slayer/16.11.1/{champions,items,scenarios,arena_augments,items_meraki,manifest}.json + current.txt flip
- `py tools/daemon_slayer_abilities_extract.py` -> data/daemon_slayer/16.11.1/champion_abilities.json (171 champs / 927 forms / 99.0% ok_rate)
- `py tools/ddragon_mirror_refresh.py` -> web/data/ddragon/16.11.1/ (577 MB; gitignored) + data/meta_build/ddragon/16.11.1/{champion,item,profileicon,runesReforged,summoner}.json
- Hand-curated artifacts copied 16.10.1 -> 16.11.1: `enchanter_items.json` + `cherry_augments.json` + `mayhem_augment_stats.json` (not auto-generated; cross-patch stable)

**Patch-drift fixes (9 tests):**
- 4 Yunara tests pinned to `DataSnapshot.load(patch="16.10.1")`: Riot lifted Yunara's ARAM disable (aramDamageDealt 0 -> 1.0) in 16.11.1; no champion is currently ARAM-disabled, so engine-invariant zero-multiplier tests pin to the prior snapshot.
- 2 IE-divergence tests pinned to 16.10.1: Riot unified SR / Arena-mirror Infinity Edge AD to 75 in 16.11.1 (was SR 75 vs Arena 55).
- 1 IE-divergence test swapped to Bloodthirster (3072 SR 80 AD vs 223072 Arena 70 AD - still divergent at 16.11.1).
- 1 Phase B Cherry test updated for item 188 Slice C handler (was asserting deleted no-op stub behavior; now covers 4-endpoint PATCH chain + no-augment-id reject).
- 1 smart-quote hygiene allowlist extended: DDragon-delivered `ddragon_items.json` (Riot ships an en-dash) + `agents/agent6_auditor/reports/` (dated artifacts).

**Living docs synced (live patch header only - historical wave anchors at 16.10.1 preserved per `feedback_no_history_rewrite`):**
- BRIEF.md L20: `ENGINE_VERSION 1.61.0 (16.10.1)` -> `(16.11.1)`
- docs/DAEMON_SLAYER.md L5: `patch 16.10.1` -> `16.11.1`
- docs/ARCHITECTURE.md L161: `patch 16.10.1` -> `16.11.1`
- dashboard/routes_dictionary.py docstring: `currently 16.10.1` -> `currently 16.11.1`
- web/js/main.js 5 hardcoded `/data/ddragon/16.10.1/` paths + CHAMPS.version fallback strings -> `16.11.1`

**Verified:** DS suite 4872 passed / 1 skipped / 1 xfailed / 1781 subtests in 67s. RC suite 3674 passed / 1 skipped in 60s. Phase 8 smoke 70/70. `py -m ruff check .` ALL CHECKS PASSED. DS `/health` returns engine_version=1.61.0 / patch=16.11.1 / 172 champs / 705 items.

**Don't-redo (tomorrow-you):**
- The 16.10.1 DS snapshot dir STAYS in `data/daemon_slayer/` indefinitely - 11 DS test files reference it as a frozen historical anchor (CC entries pinned to specific Meraki data state). The 4 Yunara tests + 2 IE tests added this session join that pattern.
- DS `/health` items=705 is the canonical catalog count (incl. Arena mirrors + mode-specific copies); DDragon purchasable subset is 547 + total entries 703 - 3 separate counts, all legitimate. Do NOT flip the README's 547 to 703 / 705.
- Yunara + Zaahen missing from Meraki bulk is HISTORICAL PATTERN for new champs (they were missing at 16.10.1 release too); Meraki catches up within 1-2 patches. Do NOT re-pitch as a bug.
- Hand-curated artifacts (`enchanter_items.json` + `cherry_augments.json` + `mayhem_augment_stats.json`) must be COPIED FORWARD on every patch refresh until either (a) operator decides to update them with patch-specific value drift or (b) they're auto-generated. Their schema_version=1 + patch field tracks the original authoring patch.
- The smart-quote hygiene allowlist for `data/meta/ddragon_items.json` + `ddragon_runes.json` + `ddragon_summoner_spells.json` is now durable; Riot-delivered punctuation in catalog data is NOT authored-source drift.
- `agents/agent6_auditor/reports/` is now in the hygiene allowlist as dated immutable artifacts.

**Carries forward:** All item 205 + item 204 carries unchanged. Mid-game capture for any UI v2.1 page-#11/12/13 still operator-gated (game state mode_key=client at /done time = safe to /clear). 7 prior-session items still in WAKEUP_NOTES (205 + 204 + 203 from item-201 chain) - eligible for archive via `wakeup_prune.py --keep 3` post-this-session.

---

# 2026-05-27 - item 205 SHIPPED: UNIVERSAL_FILES portable bootstrap kit updated 2026-05-19 -> 2026-05-27

Operator: "update the desktop folder UNIVERSAL_FILES, with all the new changes that would apply forward to a project. all tools and methods and watchers". Target = `C:\Users\Administrator\Desktop\UNIVERSAL_FILES\` (6 .md files / NOT a git repo / portable bootstrap kit for fresh Claude Code projects on Windows). Lifted forward all durable patterns proven on RC items 134-204 (40+ orchestrator-merge runs).

**Files updated (out-of-tree, no git commit):**
- `1_ENV_CHECK.md`: 426 -> 621 lines (+195). Checks 15-24 added: drift guards, ADR-008 asset-hash, cost-trace shim, v2.1 tokens, phase8_smoke, bridge watcher cadence, memory state, in-repo skills + mirror drift, scheduled tasks catalog, Phase 3 supervisor stale-code probe. Extended SYSTEM SUMMARY template.
- `2_BOOTSTRAP.md`: 1134 -> 1715 (+581). 14 new slash command here-strings: /verify /run /review /code-review /security-review /loop /schedule /insights /headless-upgrade /process-incoming-lessons /init /update-config /fewer-permission-prompts /keybindings-help. NEW Step 10.5 (mirror tracked commands loop for full 26-cmd set), Step 11.5 (phase8_smoke scaffold), Step 12.6 (ADR-008 asset-hash skeleton).
- `3_MASTER.md`: 1404 -> 2245 (+841). Parts 21-32 appended: orchestrator-merge pattern, AskUserQuestion scope-fork cadence, 7-lever CLEAN wave audit, BACKLOG stale-sweep, v2.1 tokens + 5-phase UI audit ritual, ADR-008 asset-hash, slice-based commits, drift-guard tests, record_anthropic_response shim, HTTP-pull redeploy dance, mojibake byte-repair, updated quick-ref card.
- `4_PROJECT_MIGRATION.md`: 472 -> 598 (+126). 16 gap-analysis items added (drift guards, cost-trace, tokens, mock fixtures, asset-hash, .claude/skills, etc), NEW Steps 4i (drift-guard tests) + 4j (ADR-008) + 4k (cost-trace shim), 4 new pitfalls (verify_generated_reports / no_history_rewrite / backlog_path_stale_check / verify_before_declare_broken).
- `5_NEW_PROJECT.md`: 369 -> 451 (+82). Scaffold items 30-43 (tokens.css verbatim / ui_mock dir / cost-tracker + shim / phase8_smoke / 4 hygiene tests / repair tools / .claude/skills / asset-hash route / 5 feedback memories / docs/cost_trace.md). NEW Q7.4-7.6 (mojibake check / cost-trace audit cadence / drift guard patterns).
- `6_USAGE_GUIDE.md`: 333 -> 461 (+128). Part H (14 new slash commands quick-ref) + Part I (8 new troubleshooting items for caveman ULTRA / subagent verify / Phase3 stale / Git-Bash taskkill / v2.1 tokens / cost-trace / bridge watcher cadence / scope cadence).

Total: +1953 lines across 6 files. All bumped 2026-05-19 -> 2026-05-27. ASCII clean (no em-dashes / smart quotes added).

**Method:** 4 parallel general-purpose agents drafted surgical additions (one per file pairing). Orchestrator applied via Edit/Write to existing files. 6 TaskCreate/TaskUpdate items tracked end-to-end (all completed).

**Don't-redo (tomorrow-you):**
- UNIVERSAL_FILES is NOT a git repo - desktop folder lives at `C:\Users\Administrator\Desktop\UNIVERSAL_FILES\`. Edits there do NOT need git commit. If operator wants version control later, `git init` it as its own repo.
- All 26 slash commands now documented across the 3 files where they belong (2_BOOTSTRAP installs them, 3_MASTER references them in quick-ref, 6_USAGE_GUIDE explains them to humans). Do NOT add new commands without updating all 3.
- The v2.1 token scale (--fs-xs=16 through --fs-display=46 / --hit-min=42) is documented verbatim in 3_MASTER Part 25 + 5_NEW_PROJECT item 30. Future projects scaffolded via /init pick this up automatically.
- ADR-008 unified asset-hash pattern (compute_asset_hash MD5 over web/{js,css,data/ui_mock}/ mtime+size; ?v=<hash> query) is now scaffold item 41. Future dashboards get it by default.
- record_anthropic_response + tracked_anthropic shim pattern documented in 3_MASTER Part 29 + scaffold items 32-33 + drift-guard test item 37. Future Claude API projects auto-cost-trace once they wire the shim.
- 5 new feedback memory files scaffolded as item 42 (verify_generated_reports / no_history_rewrite / backlog_path_stale_check / verify_before_declare_broken / scope_decision_cadence). Future projects get the memory pattern at scaffold time.

**Carries forward:** All item 204 carries unchanged (CI Watchdog + LCU Phase Capture Watcher PLAN.md still gated on operator answering open questions). RC pid=16064 alive=True last_reload_ok=True mode_key=client throughout. No bridge tasks pending. No RC repo edits this session.

