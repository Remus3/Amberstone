# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-05-28 (post-game ranked SR queue) - items 209a + 209b + 210 SHIPPED: cmd-window flash + game-end BSOD + runes-not-pushing (3 commits pushed origin/main `07f5e79..fcba9cd`)

3 distinct operator-reported bugs surfaced + closed in one session. RC pid 16768 alive throughout. DS :8893 untouched. No RC restart.

**209a `8d36960` fix(bridge): CREATE_NO_WINDOW on watcher claude.cmd spawns.** Operator: "a cmd window keeps opening on legion". Root cause = `tools/bridge_watcher.py:269` push_notif + `tools/bridge_watcher_actions.py:244` auto-action lane both spawned claude.cmd via subprocess.run WITHOUT creationflags. pythonw parent has no console -> .cmd shim got a new visible console each call. Throttled to 3/hr but 10 escalations / 24h = visible flashes. Fix: 1-line `creationflags=CREATE_NO_WINDOW` on both. `bridge_watcher_actions.py` is frozen - operator-granted. NEW `tests/test_bridge_watcher_create_no_window.py` 3 drift guards. RC-BridgeWatcher restarted pid 12000 -> 12228.

**209b `6f56cd6` fix(gamepc): phase watcher BSOD - drop WaitingForStats + InProgress edge delay.** OPERATOR DIAGNOSIS: the item 207 LCU phase watcher fires DXGI capture (both monitors via bettercam) on `WaitingForStats` gameflow phase = exactly when League swaps 1080p -> 1440p = same Duet/GPU/Vanguard chain as the disabled `gamepc_screen_agent.py` = 0x50 vgk.sys BSOD. Surgical fix: drop `WaitingForStats` from `_CAPTURED_GAMEFLOW_PHASES`; add `INPROGRESS_CAPTURE_DELAY_S = 15.0` so handle_event sleeps past the game-start swap before binding DXGI for the InProgress phase. Cherry augment_select stays (mid-game stable). 65/65 tests PASS. Game-PC binary patched via HTTP-pull dance + `RC-PhaseWatcher` restarted pid 5128 -> 14320. NEW memory `feedback_gamepc_lcu_phase_watcher_bsod.md`.

**210 `fcba9cd` fix(lcu): apply_runes - broaden RC page DELETE filter to 3 prefixes.** Operator: "i am also not seeing the runes being pushed in client during champ select for the selected champ". Root cause = `tools/gamepc_lcu_agent.py:1088` `apply_runes` handler DELETE filter only matched `"RC: "` prefix. Codebase ships 4 RC page-name templates (loadout_resolver "RC: " + agent default "RC: Auto" + experimental "RC Experimental - " + lcu_client "RC - "). Operator LCU had stuck `RC Experimental - Vayne` page (em-dash legacy pre-purge) consuming 1 of 3 owned slots; with 3/3 full + filter missing legacy prefixes, POST `/lol-perks/v1/pages` 4xx'd silently. Fix: `nm[:3] in ("RC ", "RC:", "RC-")`. NEW `tests/test_apply_runes_page_filter.py` 4 tests. End-to-end verified: stuck page deleted, new `RC: Caitlyn sr-collapsed (SR)` ps=8000 ss=8100 perks=[8005,9111,9104,8014,8143,8135,5005,5008,5001] landed as currentpage. Game-PC agent redeployed pid 6640 -> 2408 + flipped python.exe -> pythonw.exe (no visible console; sibling fix to item 209a class).

**Don't-redo (tomorrow-you):**
- (a) Both bridge_watcher spawn sites are CI-locked by drift guard. Do NOT remove creationflags.
- (b) `_CAPTURED_GAMEFLOW_PHASES` MUST NOT re-add `WaitingForStats` (test fails). PGR capture must come from a post-swap trigger, not the WAMP edge. The discrete-event mental model is wrong - trigger is resolution swap co-firing with bound DXGI surface, not duration.
- (c) `INPROGRESS_CAPTURE_DELAY_S = 15.0` is calibrated for typical Windows 1440p<->1080p swap.
- (d) The 3-char prefix tuple `("RC ", "RC:", "RC-")` is canonical; do NOT revert to `startswith("RC: ")` (drift guard fails).
- (e) `isDeletable` guard must stay; user-imported pages (Aggregator A/Overlay App E) have isDeletable=true but never RC prefix.
- (f) Game-PC redeploy used HTTP-pull dance per [[reference_gamepc_http_server_redeploy]]; also flipped agent from python.exe (visible console) to pythonw.exe - durable hygiene.

**Carries forward:**
- (a) 4 divergent RC page-name templates still ship; filter catches all so no functional impact, but a hygiene pass could unify to single `"RC: "` prefix. Operator-gated.
- (b) All item 208 carries unchanged (item-167 align scorer ranged-ADC penalty still owed in `core/build_order.py::_score_item_for_archetype` "carry" branch).
- (c) Item 207 phase watcher's WaitingForStats fire was the BSOD; item 209b corrects it. Live deployment now complete on Game-PC.
- (d) Frozen-file grant USED only for `tools/bridge_watcher_actions.py`; NOT used for other frozen files.
- (e) Operator queued for ranked SR at session end (lcu.phase=Matchmaking + mode_key=sr) - next champ select is the live verification of item 210.

---

# 2026-05-27 (mid-game ranked SR Caitlyn+Lux duo) - item 208 SHIPPED: item-167 ADC pollution hot-fix 7 SR champs (`a814020`, pushed origin/main `b8a82fe..a814020`; non-frozen; data + tools only; no RC/DS restart; ADR-008 asset-hash auto-serves)

Operator reported live mid-game: SR build chooser populating wrong items on Caitlyn (Trinity Force + Bastionbreaker + Umbral Glaive on ADC primary; same on Jinx). Root cause = item-167 `tools/champion_loadout_align.py` archetype scorer ranking bruiser/on-hit-hybrid components high for ranged ADCs in the `_score_item_for_archetype("carry", ...)` path. AskUserQuestion scope fork pinned per [[feedback_scope_decision_cadence]]: operator picked "All 10 SR ADCs now" -> swept all 10 item-167 coverage-gap champs, 4 came back CLEAN (Lux/MasterYi/Twitch/Vayne), 7 polluted -> hot-patched in-place.

**Shipped (2 files / +392 / -259):**
- `tools/hotfix_sr_adc_loadouts_item167.py` NEW (~140 LOC) - reusable atomic-write patch script with `path()` helper + per-champ 16.10.x meta build dict. Atomic tmp.write_text + os.replace; ensure_ascii=True.
- `data/champion_loadouts.json` - 7 sr-collapsed variant payloads rewritten:
  - Caitlyn: Crit PRIMARY Yun Tal/Berserker/IE/RFC/LDR/Runaan; Lethality Eclipse/Berserker/Opportunity/Serylda/EoN/LDR; Carry kept
  - Ezreal: Manamune PRIMARY Manamune/Berserker/Trinity/LDR/Serylda/EoN
  - Jinx: Crit PRIMARY Yun Tal/Berserker/IE/RFC/LDR/Runaan; On-Hit BorK/Berserker/Runaan/Wits End/LDR/PD; duplicate Bruiser dropped
  - Kai'Sa: On-Hit PRIMARY BorK/Berserker/Runaan/Nashor/Riftmaker/LDR (Hail of Blades)
  - Kayn: Rhaast(Red) PRIMARY Sundered Sky/Steelcaps/DD/Sterak/Shojin/GA; Shadow(Blue) Eclipse/Merc/EoN/Serylda/DD/Maw
  - Pantheon: Lethality PRIMARY Eclipse/Merc/Black Cleaver/Sundered/Sterak/Maw
  - Varus: Lethality PRIMARY Eclipse/Berserker/Opportunity/Serylda/EoN/LDR

**Verified:** Live API /api/loadout/list POST returns new builds correctly for all 7; ADR-008 auto-serves data/*.json on next dashboard Ctrl+Shift+R; RC pid 16768 alive=True reload_ok=True mode=game throughout (operator stayed in-game). DS :8893 untouched. No tests added (pure data patch + non-test tool).

**Don't-redo (tomorrow-you):**
- The 4 CLEAN champs (Lux/MasterYi/Twitch/Vayne) do NOT need patching; their sr-collapsed paths already render proper ADC/mage meta. Do NOT re-pitch.
- Pantheon Sup Roam path keeps Umbral Glaive INTENTIONALLY (ward-clear support tool, not bruiser pollution). The grep flagged it but it's legit.
- `tools/champion_loadout_align.py` is the ROOT regression - the archetype scorer for `carry` ranks TF + Bastionbreaker high for ranged ADCs. Next patch regen via `tools/champion_loadout_align.py` will REPRODUCE this pollution unless the scorer is fixed first. Fix is in `core/build_order.py::_score_item_for_archetype` "carry" branch - add a ranged-ADC penalty for melee/bruiser items (TF Sheen + Bastionbreaker + Heartsteel + Umbral on ranged classifier).
- Champion-specific meta builds are HAND-CURATED 16.10.x and will drift at next League patch. Re-audit at any DS engine bump that touches `data/champion_loadouts.json`.
- ADR-008 auto-serves data/* on next dashboard load - do NOT add a restart_trigger.txt for data-only patches.

**Carries forward:**
- Item 207 carries ALL unchanged (LCU Phase Watcher live deployment to Game-PC still OWED at next operator-driven Game-PC reboot/install).
- Item 206 carries ALL unchanged (DDragon 16.11.1 + DS 16.11.1 baseline).
- All operator-gated decision-owed lane carries from items 134-207 unchanged.
- **NEW carry:** `tools/champion_loadout_align.py` archetype scorer fix - add ranged-ADC penalty for TF/Bastionbreaker/Heartsteel/Umbral. Without this, next patch regen REPRODUCES the item-167 pollution and the 7 hand-fixes get clobbered.
- **NEW carry:** Sweep `data/champion_loadouts.json` for any non-coverage-gap champion still carrying TF + Bastionbreaker on `_archetype="carry"` paths. This session only touched the 10 item-167 coverage-gap names; the same scorer may have polluted other ADCs (Sivir / Tristana / Xayah / Ashe / Draven / Lucian / Miss Fortune / Senna / Samira / Kog'Maw / Aphelios / Nilah etc.).

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
