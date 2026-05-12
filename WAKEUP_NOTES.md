# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s169 wrap — 2026-05-11 (ADR-007 event-coach pivot — phase 1 ship, decision_detector expansion + heartbeat pill)

Operator-initiated discussion → architectural pivot doc + phase-1 ship in one session. Goal: shift coaching from continuous narration ("you're low HP — back!") to event-driven decision forks ("enemy JG missing 25s — safe/punish?"). Discovered mid-session that `core/decision_detector.py` (Tier 3 #15, 2026-05-01) ALREADY implements the architecture — `DECISION_REGISTRY`, `Decision` dataclass with A/B options, daemon loop, atomic store, JSONL log, dashboard banner + record_choice. Only 4 detectors shipped though, and the log showed only smoke-test entries (matches operator's "5 games in 5 months"). Pivot is therefore extension, not new build.

## Ships

- **ADR-007 (docs/adr/ADR-007-event-coach-pivot.md)** — formal pivot doc. Documents `decision_detector` as the foundation; lays out the 3 concurrent workstreams (detector library expansion, glanceable heartbeat surface, postmortem-from-rewind_history.db). Phase-1 scope explicitly = this session's ships. Phase-2 (postmortem pipeline) + phase-3 (prose-coach deprecation) deferred.
- **Tightened `detect_low_hp_backable`** (s169 reaction to "tell me 3× I'm low HP" complaint): HP threshold 40%→25% (you're committed to back, not deciding) + alive_for 45s→90s (post-respawn pre-fight has stable framing). Same 60s bucket id stays — re-fire was already prevented; the tightening reduces false-positive *rate* per game.
- **2 new detectors** in `core/decision_detector.py`:
  - `detect_jungler_gank_likely` — enemy JG (Smite-identified) missing ≥20s AND last seen OUTSIDE their own jungle quadrant. SR-only; defers to `objective_contest` when drake/baron is imminent. Bucketed to 90s windows. Options: `safe / punish`.
  - `detect_throwing_lead` — 2+ self-deaths in last 90s, clustered ≤45s apart, past 8min mark. Stateless (event-driven). Options: `reset / force`.
- **Heartbeat counter** on `DecisionLoop`:
  - `_eval_count` bumps after each successful eval cycle; resets on new-match game_time reversal (already-existing reset path).
  - `heartbeat()` method + module-level `read_heartbeat()` helper.
  - File-backed at `data/decisions_heartbeat.json` so the dashboard (RC main process) can read what the Phase 3 supervisor's loop wrote. `read_heartbeat()` recomputes `age_s` + `alive` at read time so a stuck supervisor flips `alive=False` on its own.
- **New API routes** (registered in `dashboard/routes_diag.py`):
  - `GET /api/decisions/heartbeat` — pill data source.
  - `POST /api/decisions/respond_active` — body `{choice_index: 0|1, dismiss?: bool, note?: str}` — resolves first pending decision by mapping to `options[choice_index]`. Single endpoint for the Game-PC keybind listener (Numpad 1/2/0 stay constant across detector types).
  - **POST validation loosened** — was hardcoded `choice ∈ {contest, give, skip}`; now validates against the actual pending decision's `options` list + `"skip"`. New detectors use options like `safe/punish`, `reset/force` so the old check rejected them.
- **Dashboard `#trigger-pill`** (header row 2, next to `#ds-pill`):
  - `web/index.html` adds the `<span class="trigger-pill" id="trigger-pill">● 0</span>`.
  - `web/css/panels/map_state.css` adds `.trigger-pill` styles with `.alive` (green) / `.stale` (amber) / `.dead` (grey) / `.pending` (blue outline) variants. Hidden on client/tft modes.
  - `web/js/panels/trigger_pill.js` polls both `/api/decisions/heartbeat` and `/api/decisions` at 2 Hz; displays `● N` counter (asterisked when pending). Tooltip carries diagnostic: counter / last-eval age / game_time / detector count / pending count.
  - `web/js/main.js` adds the side-effect import (panel self-starts on import).
  - Cache buster 2026051121 → 2026051122.
- **Game-PC keybind listener** (`tools/gamepc_keybind_listener.py`) — install-only; not auto-deployed. Hooks Numpad 1/2/0 via `keyboard` lib, POSTs to `/api/decisions/respond_active`. 250ms debounce. ENV overrides for keybinds (`RC_KEY_A` / `_B` / `_DISMISS`). Self-contained — own ssl context + urllib post, no RC imports. Documented schtasks install pattern in the docstring.
- **25 new tests** under `tests/test_decision_detector_adr007.py` — pure-function tests for all 3 detector changes + DecisionLoop heartbeat + file-backed read roundtrip. Full suite **719 passes** (was 694).

## Live verification

- RC restarted via `restart_trigger.txt` → endpoint live; `curl -ks https://127.0.0.1:8888/api/decisions/heartbeat` returns the no-file sentinel + `detectors: 6` confirming both new detectors registered.
- Phase 3 supervisor restarted via `taskkill /F /PID 16436` + `schtasks /Run /TN "RC-Phase3-Supervisor"` — new PID 11712 picked up the new code (per-tick the supervisor will run the 6 detectors + write heartbeat once a game starts).
- Dashboard screenshot from Game-PC monitor 1 confirmed no broken UI (pill correctly hidden in client mode). Polling logs show /api/decisions + /api/decisions/heartbeat at 2 Hz cadence — trigger_pill.js loaded and running.
- POST validation tested: `respond_active` with no pending returns 404 cleanly.

## Decisions / non-obvious notes for next-session-you

- **Detector signature stays pure**: `(snapshot, vision_state) → Optional[Decision]`. New "needs prev_snapshot" data (HP delta, gold delta) belongs in a separate loop-owned context dict — DO NOT extend the signature for one-off needs.
- **Cross-process heartbeat is file-backed**, same pattern as `DecisionStore`. The DecisionLoop singleton lives in the Phase 3 supervisor process; the dashboard reads via `read_heartbeat()` from `data/decisions_heartbeat.json`. No IPC, no socket — keeps it simple.
- **Rate-cap math**: `_MAX_PER_GAME = 5`, `_MIN_GAP_S = 30`. Now 6 detectors compete for those 5 slots. Watch the first 3 real games' logs — if any of the new detectors gets starved (always after low_hp_back / objective_contest in the gap), bump the cap.
- **Dispatch order matters**: POST_ROUTES registers `equals("/api/decisions/respond_active")` BEFORE `prefix("/api/decisions/")` so the equals match wins. Reversing the order would route `/respond_active` to `_serve_decision_choice_post` with id="respond_active" → 404.
- **`/api/decisions/respond_active` is keybind-shaped**, not banner-shaped. Banner buttons keep using `POST /api/decisions/<id>` with explicit choice string. Different audiences: keybind doesn't know the id, banner does.
- **Keybind listener needs `pip install keyboard`** on Game-PC. Schtasks docstring includes the install steps. Not yet deployed — operator should deploy when ready to live-test keybind flow. Without it, the dashboard banner buttons are the only A/B input.
- **The pill is hidden in client/tft modes** (CSS rule mirrors ds-pill). Operator won't see it on the home overlay or in TFT; intended.
- **`detect_low_hp_backable` tightening reduces fire rate**. Bucket is still 60s — re-fire was already prevented by the bucket id stability. The threshold tightening cuts the absolute rate (`<25%` is rare unless committed to back).

## Files touched

- `docs/adr/ADR-007-event-coach-pivot.md` (new, ~120 LOC)
- `core/decision_detector.py` (+~285 LOC: 2 detectors + heartbeat + write/read pair)
- `dashboard/routes_diag.py` (+118 LOC: 2 new handlers + relaxed POST validator + route table)
- `web/index.html` (+10 LOC: trigger-pill span + cache buster bump)
- `web/css/panels/map_state.css` (+42 LOC: .trigger-pill block)
- `web/js/main.js` (+2 LOC: side-effect import)
- `web/js/panels/trigger_pill.js` (new, ~85 LOC)
- `tools/gamepc_keybind_listener.py` (new, ~150 LOC)
- `tests/test_decision_detector_adr007.py` (new, ~330 LOC, 25 tests)
- `WAKEUP_NOTES.md` / `docs/history_notes.md` (this wrap + s166 archive)

## Open items handed off

- 🟡 **Game-PC keybind listener deployment** — `tools/gamepc_keybind_listener.py` not yet copied to Game-PC. Operator decides whether to install + run for live test. Banner buttons work without it.
- 🟡 **Live game observation** — first real-game test of the new detectors. Watch `data/decisions_log.jsonl` for fires; tune thresholds if any detector skip-rate exceeds 70%.
- 🟡 **ADR-007 phase 2 (postmortem pipeline)** — `scripts/postmortem_analyze.py` mining rewind_history.db for per-player death patterns. Deferred to s170+.
- 🟡 **ADR-007 phase 3 (prose-coach deprecation)** — mode coaches still narrate in parallel with decision_detector. Detector-by-detector deprecation pass deferred until phase-1 detectors prove out in real games.
- 🟡 (Unchanged from s168) RC-LCU scheduled-task `Execute: py` → absolute python path on Game-PC.
- 🟡 (Unchanged from s168) P1b augment registry, P5 default DS build #4, P3/P4 history+replay UI.

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

- 🟡 **Triage uncommitted working tree** (operator-flagged at end of s168). After `git commit 0c876ef + 5715004` shipped this session, the working tree still carries pre-session changes I deliberately did NOT bundle. Next-session-you: ask the operator whether each set is **commit / retire / in-progress** so the tree doesn't accumulate orphans.
  - **Audit-5 source code** (uncommitted modifications): `agents/supervisor.py` (h01 `_warm_agent7_alive` init at line 1540 + h02 null-guard in `_warm_agent7_handle` at line 1809) + `agents/agent7_context/warm_session.py` (m01 `stats()` lock-guard). Small, additive, thread-safety + warm-session-init fixes. Apparently applied by an audit sub-agent at some point; never landed.
  - **Audit-5 proposal artifacts** (untracked): `agents/agent6_auditor/proposals/20260506-070234-fifth-audit/P-audit5-h01-warm-agent7-alive-init.result.md` + `…-h02-warm-agent7-actually-warm.result.md` + `…-m01-warm-stats-lock.result.md`. These document the audit's findings; likely belong with the source-code changes above.
  - **Runtime state churn** (uncommitted, normal): `data/ds_calibration.jsonl`, `data/placement_heatmap.json`, `data/ratings/last_{arena,sr,tft}.json`, `data/tft_live_data.json`. These mutate every game; not session-authored. Probably should be `.gitignore`'d if not already (verify).
  - **DB backups + script state** (untracked): `data/match_history.db.bak-2026-05-09-pre-darkstar-purge`, `data/match_history.db.bak-2026-05-10-prune-synthetic`, `data/rewind_history.db.bak-pre-catchup-2026-05-10`, `data/rewind_catchup.state.json`. The `.bak`s are insurance for s167's DB ops; `rewind_catchup.state.json` is the resumable sentinel for the catchup script. Almost certainly should be `.gitignore`'d.
  - **Screenshots** (untracked): `dashboard-full.jpeg`, `ds-pill-{after,live}.jpeg`, `item-build-full.jpeg`, `last-match-arena-ds.jpeg`. Ad-hoc UI captures. Move to `docs/_archive/screenshots/` or delete?
  - **Exploration doc** (untracked): `rc-tutor-decision-matrix.md` — looks like operator's design notes. Operator should decide whether to commit, move to `docs/`, or retire.
  - **MCP cache** (untracked): `.playwright-mcp/` — ephemeral; `.gitignore` it.
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

