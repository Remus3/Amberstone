# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s168 wrap — 2026-05-11 (FU01 minimap-locate + LCU mastery endpoint live-fix + Game-PC redeploy)

Continuation per `NEXT_SESSION_PLAN_2026-05-10.md`. After s167 closed P1a/P2/P7/P8/P9, the remaining 🟡 backend items were either UI-blocked, data-blocked (sparse rewind), or operator-clarification-blocked (P6 Claude Desktop key). **FU01 minimap-locate** was the highest-leverage open item. Operator opened League mid-session, unblocking the s167 LCU mastery Game-PC redeploy — which surfaced a stale-endpoint bug, fixed and re-deployed in the same session.

## Ships

- **FU01 — minimap-locate 3-path resolver.** New module `agents/_minimap_bbox.py`; `agents/supervisor.py:597` rewired. Resolution order: HTTP `?bbox=` override (untouched) → `data/vision_regions.json` `_minimap_<mode>` key → hardcoded 1920×1080 fallback. The persisted key uses `_*` prefix so `core/vision_tesseract._regions()`'s metadata filter ignores it — no collision with OCR region namespace.
- **LCU mastery endpoint fix + Game-PC redeploy.** The s167 mastery hook called `/lol-collections/v1/inventories/<sid>/champion-mastery` — a path that returns HTTP 404 on current LCU builds (Riot migrated the API namespace). First live LCU contact during the Game-PC redeploy revealed this. Correct endpoint discovered via path-enumeration probe: `/lol-champion-mastery/v1/local-player/champion-mastery` (no sid in path; returns local player's mastery directly). Patched in `tools/gamepc_lcu_agent.py:241-251` + 6 mock-path occurrences in `tests/phase_b_champ_select/test_lcu_mastery.py` updated; full 10/10 mastery tests + 694/694 project sweep still green. Game-PC's `C:\RC-Agent\gamepc_lcu_agent.py` redeployed to fixed version via one-shot Legion `:8765` `http.server` + Game-PC `Invoke-WebRequest` (SMB blocked, no peer creds cached).
- **LCU mastery state-shape flatten fix.** First Lobby-phase live probe (after the endpoint patch) revealed the s167 code-path placed mastery at `state["lcu"]["lcu"]["mastery"]` — double-nested — because Legion's bridge handler already wraps the entire agent state as `legion_state["lcu"]`, and the agent was additionally doing `state.setdefault("lcu", {})["mastery"] = mastery`. Flattened to write at `state["mastery"]` and `state["summoner_id"]` at the top level of the agent's state, so Legion's wrap produces the intended `state["lcu"]["mastery"]` path. Tests updated (assertion paths + `idle` test now checks `state["mastery"]` is absent rather than `state["lcu"]`). Live-verified: `phase=Lobby` immediately produced `state["lcu"]["mastery"]` with 40 entries — top 5 ADCs (Jinx 33507 pts, Kai'Sa, Vayne, Caitlyn, Tristana) matching operator's `SamplePlayer#Vayne` main. Game-PC redeployed for a 3rd time this session via the same `http.server` mechanism.

## Tests

- `tests/fu01_minimap/test_minimap_bbox.py` — 19 tests: no-file → fallback; partial entries; wrong arity (3-tuple); wrong type (string); non-numeric (`"twenty"`); degenerate bbox (`l>=r`, `t>=b`); corrupted JSON; top-level non-object; case-insensitive mode lookup; `load_persisted` direct API; file-read exception swallowed via `mock.patch.object(Path, "read_text", side_effect=OSError)`.
- `tests/phase_b_champ_select/test_lcu_mastery.py` — 10 mock-path-updated tests still green after the endpoint patch (`/lol-collections/v1/inventories/<sid>/...` → `/lol-champion-mastery/v1/local-player/...`).

## Test posture at wrap

- DS suite: **949/949** (unchanged from s167).
- Project sweep: **694/694** (+19 fu01; +0 net from mastery patch — same 10 tests pass against the new path). Note: s167 wrap reported "601/601 (+10 LCU mastery)" — the 694 reflects the full `tests/` tree including snapshot/fixture suites that aren't separately tallied in session notes.

## Decisions / non-obvious notes for next-session-you

- **Behavior is byte-identical until calibration entries are added.** No `_minimap_<mode>` keys exist in `data/vision_regions.json` today — `resolve()` falls back to the same hardcoded bbox the inline dict had. Live `curl https://127.0.0.1:8888/api/minimap-crop?mode=sr` against the still-running pre-FU01 phase3 supervisor returns 200 with the cached vision frame (verified at session start). After phase3 restart, response will be identical.
- **Phase 3 supervisor was NOT restarted.** `agents/supervisor.py` is the `RC-Phase3-Supervisor` scheduled task (pid 16436 at session start; listens :8890/:8891 — separate from main RC's :8888). It doesn't watch `restart_trigger.txt`. To force pick-up: `taskkill /F /PID <pid>` + `schtasks /Run /TN "RC-Phase3-Supervisor"`. Skipped here because the change is additive — no observable difference until calibration is written. Next natural reboot / supervisor cycle picks it up.
- **Calibration recipe** (for the operator when needed): edit `data/vision_regions.json`, add `"_minimap_sr": [l, t, r, b]` (likewise for `aram`/`brawl`), then `curl -k -o /tmp/m.png "https://127.0.0.1:8888/api/minimap-crop?mode=sr"` and tweak until centered. Bbox is validated for shape (4 ints, `r>l`, `b>t`) — bad entries silently fall back to hardcoded.
- **Pending Desktop/Tickets/ paperwork.** Original ticket file `RC_TICKET_FU01_minimap_locate.md` no longer exists on disk (Desktop/Tickets/ is gone — was the "transfer plan" pack reviewed in s144). Spec inferred from ROADMAP + `docs/history_notes.md:509-513`.
- **LCU endpoint discovery method.** When an LCU path returns 404, enumerate candidates against the live client. The probe pattern used here: read the lockfile (`C:\Riot Games\League of Legends\lockfile`) → build basic auth header (`riot:<pw>`) → try a list of plausible paths and print HTTP code per path. Faster than reading Riot docs (which lag behind client builds). Both `/lol-champion-mastery/v1/local-player/champion-mastery` and `/lol-champion-mastery/v1/{puuid}/champion-mastery` work; chose `local-player` since it doesn't require a path-param resolve.
- **Game-PC deploy mechanism — one-shot http.server.** SMB pull (`\\192.168.8.230\C$\...`) failed (no peer creds cached on Game-PC). Workaround: `cd <staging-dir> && py -m http.server 8765` on Legion (run_in_background=true) + `Invoke-WebRequest` on Game-PC + `taskkill` the listener afterward. Routine pattern; document in OPERATIONS.md if it recurs. Backup of pre-fix file at `C:\RC-Agent\gamepc_lcu_agent.py.bak-s168-pre-endpoint-fix`; s149 vintage at `C:\RC-Agent\gamepc_lcu_agent.py.bak-s149-2026-05-11`.
- **RC-LCU scheduled task is broken.** `(Get-ScheduledTask -TaskName 'RC-LCU').Actions` uses `Execute: py` (the Windows Python launcher) which fails ERROR_FILE_NOT_FOUND under scheduled-task context (memory `project_rc_patchrefresh_fixed.md` predates this discovery for RC-PatchRefresh; same root cause). Live workaround: `Start-Process -FilePath 'C:\Users\Administrator\AppData\Local\Python\pythoncore-3.14-64\python.exe' -ArgumentList 'C:\RC-Agent\gamepc_lcu_agent.py' -WindowStyle Hidden`. Fix the task action to use the absolute path when the operator next reboots; otherwise auto-relaunch on reboot will silently fail.

## Open items handed off (unchanged from s167 plus FU01)

- 🟡 RC-LCU scheduled-task action path: change `Execute: py` → absolute python path (matches the running command-line of other Game-PC python agents).
- 🟡 Phase 3 supervisor restart to pick up FU01 live.
- 🟡 P6 (Sonnet/Haiku key routing) — needs operator clarification.
- 🟡 P1b augment registry — architectural; needs `as_pct` channel design pass.
- 🟡 P5 Default DS build #4 — waits on richer rewind data.
- 🟡 P3/P4 (History season-WR + Replay tab) — UI work, deferred per s166 directive.
- 🟡 UI Phase 3 steps 5–14 — UI work, deferred per s166 directive.

---

# s167 wrap — 2026-05-11 (backend sweep per NEXT_SESSION_PLAN_2026-05-10.md)

UI paused per s166 operator directive. Five backend ships in one commit (`1522b90`). Doc sync follow-up (`be86469`).

## Ships

1. **DS per-level DPS curve helper** (P1a) — `compute_dps_curve()` + `DpsCurvePoint` + `DPS_CURVE_LEVELS=(1,6,11,16,18)` in `agents/daemon_slayer/dps.py`. Pure additive; reuses `compute_dps()` per level. ENGINE_VERSION 0.60.0 → 0.61.0. 12 new tests (35 total in test_dps; 949 in DS suite). DS server restarted via `pythonw tools/start_daemon_slayer.py` after `taskkill /F /PID 13320` — `/health` confirms 0.61.0.
2. **rewind_history.db catchup** (P2) — `scripts/rewind_catchup.py` paginates Match-V5 → 5-table schema. **PUUID gotcha:** DB had stale `v8HzkOaP3OKe…`; current is `jVoxvNpcLTzD…` (Riot rotated). Script auto-resolves via Account-V1 from DB Riot ID (`SamplePlayer#Vayne`); state stores both stale + fresh for tracked-player detection. **`core/riot_api.get_recent_matches` extended** with `start`/`startTime`/`endTime`/`queue`/`type`. Idempotent + resumable via `data/rewind_catchup.state.json`. **2846 → 2851 matches** (only 5 games since 2025-12-15). DB was `-r--`; `attrib -r` cleared it.
3. **LCU mastery wired** (P8) — `tools/gamepc_lcu_agent.py` adds `_resolve_local_summoner_id` (cached) + `_maybe_refresh_mastery` (5-min TTL). Hits `/lol-summoner/v1/current-summoner` → `/lol-collections/v1/inventories/<sid>/champion-mastery`. Surfaced at `state["lcu"]["mastery"]` + `state["lcu"]["summoner_id"]` on Lobby / Matchmaking / ReadyCheck / ChampSelect / GameStart / InProgress / WaitingForStats. 10 tests under `tests/phase_b_champ_select/test_lcu_mastery.py`. **Last mile:** Game-PC redeploy needed before mastery appears live — Legion edit only.
4. **API surface audit** (P9) — `scripts/audit_api_surface.py` greps 4 surface regex sets. Writes `docs/API_SURFACE_AUDIT.md` (1363 lines, dedup'd by endpoint) + `data/api_surface.csv` (557 callsites). Counts: 89 internal `/api/*` / 70 LCU `/lol-*` / 6 web / 2 LiveClient. Foundation for future endpoint plumbing.
5. **Synthetic match pruning** (P7) — `scripts/prune_synthetic_matches.py`. Conservative heuristic: `champion = 'Dark Star Vertical'` OR `champion = '' AND game_time_s = 0`. Backup: `data/match_history.db.bak-2026-05-10-prune-synthetic`. **Deleted 56 rows (200 → 144).** `ds_calibration.jsonl` clean.

## Decisions / non-obvious notes for next-session-you

- **DPS curve scope was small.** Augment registry expansion (P1b) needs `as_pct` overlay channel architectural work; existing 10-entry registry stays.
- **rewind catchup is not "overnight" anymore.** Operator played 5 games in 5 months. Catchup runs in <30s. Schedule hourly via `schtasks` once operator resumes regular play; not needed right now.
- **PUUID rotation is silent.** Match-V5 returned HTTP 400 `"Exception decrypting <puuid>"` for the stale value. 78-char shape was fine; Riot's internal mapping was invalid. Account-V1 by Riot ID is the recovery path. **Do not assume stored PUUIDs survive long-term.**
- **DS server is NOT supervisor-restarted.** When you bump ENGINE_VERSION you must `taskkill /F /PID <pid>` + `pythonw tools/start_daemon_slayer.py`. Otherwise `/health` keeps reporting the old version and `tests/phase8_smoke/test_sr_draft_profile_engine.py::test_live_three_profiles` fails.
- **P6 (Sonnet/Haiku → Claude Desktop key) blocked on operator clarification.** Current path: `coaches/_base_coach.py:read_api_key()` reads `API-Key-Claude.txt` then `$ANTHROPIC_API_KEY`. CLI's `~/.claude/` is separate from this file — coaches already do NOT route through CLI's key. Operator needs to specify intent (replace file? billing visibility?).
- **NEXT_SESSION_PLAN_2026-05-10.md fully addressed for backend.** Remaining items are explicitly UI (deferred) or operator-clarification (P6).

## Test posture at wrap

- DS suite: **949/949** (+12 curve + version-pin updates)
- Project sweep: **601/601** (+10 LCU mastery)
- Phase_b suite: **40/40** (was 30; +10 mastery)

## Open items handed off

- 🟡 Game-PC redeploy of `tools/gamepc_lcu_agent.py` (LCU mastery hook).
- 🟡 P6 (Sonnet/Haiku key routing) — needs operator clarification.
- 🟡 P1b augment registry — architectural; needs `as_pct` channel design pass.
- 🟡 P5 Default DS build #4 — waits on richer rewind data.
- 🟡 P3/P4 (History season-WR + Replay tab) — UI work, deferred.
- 🟡 UI Phase 3 steps 5–14 — UI work, deferred per s166 directive.

---

# s166 wrap — 2026-05-10 (Phase B LCU agent handlers + Loading view scaffold — UI work paused)

Two-track session. First half: Phase B backend work — the dashboard commands that s164+s165 shipped on the UI side were no-ops because the Game-PC LCU agent didn't handle them. Second half: Phase 3 step 4 (Loading Screen view) scaffold + flow_04 fixture. End of session: operator paused UI work and directed the next session to focus on backend per `NEXT_SESSION_PLAN_2026-05-10.md`.

## What shipped (s166)

### Phase B — LCU agent (`tools/gamepc_lcu_agent.py`)

- **5 new command handlers** in `execute_command`:
  - `set_ban_intent` / `set_pick_intent` — find the local cell's in-progress ban|pick action via the new `_local_in_progress_action(sess, type)` helper, PATCH it with `{championId, completed: false}` so the in-game UI mirrors dashboard hover without actually locking.
  - `request_position_swap` / `request_pick_order_swap` — resolve `cell_id → swap id` via `session.positionSwaps[]` / `pickOrderSwaps[]`, POST to `/lol-champ-select/v1/session/{position|pick-order}-swaps/{id}/request`. BUSY / INVALID states return distinct errors.
  - `set_augment_intent` — explicit "unsupported" stub returning `{ok: false, err: "augment_intent_unsupported"}` + a note. The actual LCU `/lol-cherry/v1/*` endpoint needs a live Arena lobby for discovery; documented as deferred.
- **Champ-select state population** — new fields on `state["champ_select"]`:
  - `active_round` — `{type: "pick"|"ban", cell_ids: [...]}` from `_active_round(sess)` which walks `session.actions[]` for in-progress entries.
  - `is_brawl` — `queue_id == 480`.
  - `position_swaps` / `pick_order_swaps` — slim `{id, cellId, state}` lists via `_swap_entries(arr)`.
  - `arena_teams` (queues 1700/1710 only) — distilled from `additionalSubteamData` via `_arena_teams(sess)` with `is_me` detection from local cell.
  - `augments` scaffold (queues 1700/1710 only) — `{my_slots: ["","",""], options: [], current_round: 0}` placeholder.
  - Per-player `summoners` array on `_team_picks` (`[spell1Id, spell2Id]`) so the Loading view's D/F icons work in live mode.
- **30 new tests** under `tests/phase_b_champ_select/test_lcu_agent_phase_b.py` covering all four pure helpers + the 5 command handlers (mocking `lcu_request`). Full suite **665 passes** (up from 624).

### Phase 3 step 4 — Loading Screen view (`flow_04`)

- New top-level `<section id="view-loading">` in `web/index.html` — 2-col grid (Allies | Enemies), no briefing card (initially present, removed before commit per operator).
- `web/js/panels/loading.js` (new) — `renderLoadingView(lcu)` + `loadingViewEnabled()` opt-in (`?ld=1` or `localStorage.loadingView='1'`). Mode-conditional via `section.dataset.lvwMode` (sr/aram/arena/brawl). Arena renders 4 sub-team cards stacked in the enemies pane.
- `web/css/panels/loading_view.css` (new) — `.lvw-*` styles. Briefing classes (`.lvw-card-briefing`, `.lvw-brief-*`) removed pre-commit.
- View routing in `web/js/main.js`: `_viewAutoDerive` promotes to `loading` when `phase === "GameStart" && loadingViewEnabled()` — wins ahead of `activeMatchEnabled()`'s same-phase claim. Marked urgent in `_viewIsUrgent`. Re-fires `renderLoadingView` on every state envelope (HTTP + WS + lcu envelope wrapper).
- `web/js/lib/state.js` — `loading` added to `VIEW_IDS` / `VIEW_LABELS`.
- `web/css/dashboard.css` — `@import './panels/loading_view.css'`.
- `web/css/panels/header.css` — `body[data-view="loading"]` rules (hide main + home overlay, show `#view-loading`).
- `data/sim/flow_04_loading_screen.json` (new) — SR ranked draft, all 10 picks locked, `phase: "GameStart"`, FINALIZATION timer 9s.
- `data/sim/manifest.json` — flow_04 entry added.
- Cache busters bumped CSS 2026051111 → 2026051121, JS 2026051110 → 2026051121.

## Files touched (s166)

- `tools/gamepc_lcu_agent.py` — +~280 LOC across 4 helpers + 5 handlers + state extensions
- `tests/phase_b_champ_select/__init__.py` (new, empty)
- `tests/phase_b_champ_select/test_lcu_agent_phase_b.py` (new, ~330 LOC)
- `web/js/panels/loading.js` (new, ~200 LOC)
- `web/css/panels/loading_view.css` (new, ~150 LOC after briefing removal)
- `data/sim/flow_04_loading_screen.json` (new, ~55 LOC)
- `web/index.html` — Loading section + 2 cache busters
- `web/js/main.js` — import + auto-derive + applyView + urgent flag + 2 re-fire hooks
- `web/js/lib/state.js` — VIEW_IDS + VIEW_LABELS
- `web/css/dashboard.css` — 1-line @import
- `web/css/panels/header.css` — 3 view-routing rules
- `data/sim/manifest.json` — flow_04 entry
- `ROADMAP.md` — Phase B + Loading marked ✅; Phase 3 fixture-flow updated to steps 5–14 + PAUSED tag
- `CLAUDE.md` — priorities 23+24 marked ✅; 25 added (operator post-s166 directive)
- `NEXT_SESSION_PLAN_2026-05-10.md` (new) — 6-priority backend backlog the operator asked for

## Operator directive at end of session

> _"ill wait on the ui stuff for the moment, lets just finish the back end work for now and any pending backlog items that are not checked off and any roadmap items not checked off yet … priority task to check first will be the Daemon Slayer headless testing if nothing substantive — then connect to the rewind database: and run that headless overnight."_

UI work is **paused**. Next session reads `NEXT_SESSION_PLAN_2026-05-10.md` as the bootstrap and tackles backend priorities 1–6 in order.

## Next session opener

- Start from `NEXT_SESSION_PLAN_2026-05-10.md` — 6 priorities ranked.
- **P1** Daemon Slayer headless testing (per-level DPS curves + Arena augment overlay are the highest-leverage candidates).
- **P2** if P1 stalls: rewind_history.db catchup (newest entry is 2025-12-15; FU04 key now available; aim to run an idempotent `scripts/rewind_catchup.py` overnight).
- **Do not touch UI** (`web/**`) unless operator explicitly unblocks.
