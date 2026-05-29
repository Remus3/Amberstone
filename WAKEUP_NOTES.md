# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-05-28 (dev UI: user builds page) - user-curated builds now surface in live champ-select chooser (ALL modes) (1 commit `a887c2b` pushed origin/main `50543b7..a887c2b`; non-frozen; RC restarted pid 11272 -> 9312)

Operator: "starting on user builds page. user build for locked Caitlyn was not displayed in live champ select." Root cause: user builds (`coaches/sr_user_builds` -> `data/daemon_slayer/user_builds.json`) were orphaned from EVERY live chooser - `/api/loadout/list` -> `loadout_resolver.list_variants()` reads `champion_loadouts.json` only; `format_for_display()` was test-only; the old merge route `/api/sr-draft/profile` was deleted item 186.

**Shipped `a887c2b`:** `dashboard/routes_loadout.py` `_serve_loadout_list_post` appends user builds as `userbuild_<id>` rows for ALL modes (operator: "available in other modes as well"); new `_resolve_user_build()` builds the rune+item+summoner trio; `_serve_loadout_apply_post` routes `userbuild_*` before the resolver (colon-free key dodges the item-178 `<variant>:<path>` savedChoice split). `champ_select.js` + `champ_select_view.css` get a sky-blue `.csv-build-badge-user` - no other JS change, existing render/click/apply wiring flows the row key. NEW `tests/test_loadout_user_builds_merge.py` 16 tests. Drive-by: `tests/test_csv_rune_push_on_selection_change.py` stale Jinx `sr-bruiser` path (dropped item 208) -> `auto-sr-primary-carry` (Press the Attack vs adc-crit Lethal Tempo; keystone still differs).

**Verified:** 16/16 + 15/15 green; ruff + py_compile + node --check clean; RC pid 9312 alive reload_ok; live `/api/loadout/list` Caitlyn -> `userbuild_723d445b` "crit max" present sr/aram/arena, 6 item_ids resolved.

**Carries forward (tomorrow-you):** (a) Minor runes (`minor_primary`/`minor_secondary`) are SAVED on the user-builds page but NOT pushed to LCU - `format_for_display` + `build_perk_ids` ignore them so the LCU page gets default minors. This is the natural NEXT user-builds-page item. (b) Visual capture of the rendered chooser row OWED - operator was mode=client (no live champ select). (c) `_csvMaybePushBuildsToLCU` caps the in-game item-shop dropdown at 4 sets; a user build can be crowded out (click-apply push is unaffected). Minor.

---

# 2026-05-28 (Home Recent-5 wrong-items bug) - item 211 SHIPPED: gameId-keyed ingest + backfill + Match-V5 recovery (3 commits pushed origin/main `4ff288f..1628a47`; non-frozen; RC restarted pid 16768 -> 11272; ADR-008 auto-served)

Operator: "when on the home page, the recent 5 is always missing an item row for one of the cards - and eventually when the matches update : the items are on the wrong matches". Root cause = `dashboard/routes_last_match.py:122-125` `_serve_last_match_ingest` SELECTed `ORDER BY timestamp DESC LIMIT 1`. Race: Game-PC LCU agent POSTs ingest on EndOfGame BEFORE local performance_tracker.save_match writes the new row -> ingest stamped the PREVIOUS row's raw_data with the new game's lcu_match_detail (and items). New row then never received ingest -> items=[]. Visible live: row 1690 (Jinx 22:54:03) carried Caitlyn's gid 5569828374; row 1691 (Caitlyn 23:57:12) carried items=[].

**Shipped:**
- **`b7bd74a` fix(ingest):** matches schema gains `game_id INTEGER DEFAULT 0` + `idx_matches_game_id` + in-place ALTER TABLE migration. Route rewritten: gameId-primary -> gameCreation+gameDuration vs row.timestamp +/- 180s for legacy rows -> 202+queue+60s retry/10s drain. Matched rows stamp game_id so re-ingest is keyed. `performance_tracker.save_match` persists game_id when Live Client exposes it. +11 TDD tests in `tests/test_last_match_ingest_gameid.py` (schema migration / gameId match + idempotence / ts-window fallback / queue drain + age-out / item 211 regression pin). 3758 pass / 2 pre-existing failed (Pantheon lifeline + Jinx sr-bruiser, items 168/178 carries; NOT regressions).
- **`4e043a8` chore(backfill):** `tools/backfill_match_ingest_misattribution.py` walks every non-TFT row carrying lcu_match_detail, extracts participantId via tracked_puuid, maps championId via DDragon, compares vs db.champion. If mismatch: finds target row by champ + ts window; MOVEs detail with stamps `item211_backfill_moved_to/received_from` for forensics. Atomic backup. --dry-run + --window flags. Applied 180s + 600s passes -> 26 stamped + 15 moved + 15 true orphans.
- **`1628a47` feat(recovery):** `tools/recover_match_via_match_v5.py` for orphans where ingest NEVER landed (Game-PC agent offline / RC down / POST failed). Account-V1 -> Match-V5 by-puuid -> synth LCU-shaped blob with participantIdentities + participants[].stats.itemN -> POST /api/last-match/ingest. Row 1690 recovered via NA1_5569790114 (Jinx items [1055, 3032, 2523, 3031, 3086, 3144]). Home Recent-5 now 5/5 clean.

**Don't-redo (tomorrow-you):**
- (a) `_serve_last_match_ingest` row-match contract is gameId-primary then ts-window then queue+retry. Do NOT revert to "latest row" - the regression pin in test_last_match_ingest_gameid.py fails.
- (b) game_id INTEGER + idx_matches_game_id is the schema chokepoint; ALTER TABLE handles legacy DBs in place. The fresh-vs-legacy CREATE/ALTER branch in `core/match_db.py:84-110` is required because the full _SCHEMA's CREATE INDEX statements explode against narrow legacy tables.
- (c) matches.tracked_puuid IS STALE for older rows (per [[reference_riot_puuid_rotation]] - operator's puuid rotated). For Match-V5 recovery ALWAYS re-resolve via Account-V1 by Riot ID (SamplePlayer#Trist post-2026-05-20).
- (d) The Match-V5 gameDuration unit varies: seconds when gameEndTimestamp is present, milliseconds in older payloads. `_normalize_unit(n)` in recovery tool divides by 1000 when n > 100_000. Test before changing.
- (e) Backfill ran twice with different window sizes (180s strict, 600s for slow-grader cases); both backups kept at `data/match_history.db.bak-item211-20260528-{201639,201739}`.

**Carries forward:**
- (a) 15 orphan rows from backfill have no clean target row (target was never written - RC down / agent offline at the time). Operator-decision: run `tools/recover_match_via_match_v5.py --row-id <orphan>` per row to recover, OR add a `--clear-orphans` flag to backfill tool to clear wrong detail blobs (better empty than wrong on deeper History pages).
- (b) Live Client `/allgamedata` rarely exposes gameId reliably so performance_tracker writes game_id=0 most games. The timestamp-window fallback covers that. If a future Live Client patch surfaces gameId, the forward path tightens automatically.
- (c) All items 209/210 carries unchanged. Frozen-file grant NOT used.
- (d) Operator hard-refreshed dashboard after each phase; final state has 5/5 cards correct (Caitlyn/Caitlyn/Jinx/MF/Samira all show their own items).

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
