# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s107 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s118 wrap — 2026-05-08 (Bridge Watcher node-load restraint)

## What shipped
- **Bridge Watcher node-load restraint** (`bridge_watcher.py`, commit f3ae4cb): `_check_rc_health(health, now)` pure function checks RC alive/last_reload_ok/booting/heartbeat age/restart grace. When RC is degraded, auto-action lanes downgrade to escalate for that poll cycle. Push notifications suppressed during RC-degraded cycles. New heartbeat fields: `auto_suppressed_since_boot` + `auto_suppressed_24h`. 9 new selftests at boundary inputs; 30/30 pass. Watcher restarted at pid=15004.
- **DDragon "16.9.1" is correct** — Riot uses year-based marketing versions (26.9) but DDragon API version string stays "16.9.1". Data pipeline is current, not stale.

## Do NOT redo
- Bridge watcher node-load restraint is preventive hardening, not a fix for observed harm. The feature is intentionally conservative (120s grace, 60s staleness threshold).
- DDragon version issue was a false alarm — no pipeline change needed.

## Open work (priority order)
1. **rewind_history.db staleness** — blocked on live SR game.
2. **Vision regions calibration** — blocked on live game.
3. **TFT 17.3** — next patch due ~2026-05-12. Same update process as 17.2.
4. **Bridge Watcher acceptance-criteria** — watch `auto_ok_since_boot` vs `auto_err_since_boot`; target ≥90% read / ≥95% ops.
5. **Auto-ops verb expansion** — needs 95% success rate first; check heartbeat before enabling.

---

# s117 wrap — 2026-05-08 (TFT patch 17.2 — Encounters + God Blessings)

## What shipped
- **TFT patch 17.2 update** (commit be3d168): Current League patch is 26.9 (year-based numbering) = TFT patch 17.2 (April 28, 2026).
  - `tft_pbe_engine.py` system prompt: Encounters section (16 returning + 5 new), God Blessings section (24 choices across 6 gods), trait balance changes (Timebreaker rework, Meeple nerf, Stargazer Fountain disabled, Anima buff).
  - `tft_pbe_data.py`: new `ENCOUNTERS` dict (21 entries), new `GOD_BLESSINGS` dict (24 choices), Timebreaker breakpoints corrected [2,3,4], trait notes updated.
  - `data/meta/tft_set17_meta.json`: `_patch` bumped to `17.2`, `_patch_notes_17.2` key added.
- RC restarted clean (pid=11716).

## Do NOT redo
- DDragon still reports version "16.9.1" (stale cache). Actual current League patch is 26.9 (year-based numbering). TFT patch follows TFT set versioning (17.2), not League patch numbers.
- `tft_data.py` (legacy Set 14 file) is fine as-is — only used for TIER_ODDS/XP tables by the old coach engine; active TFT coaching runs through `tft_pbe_engine.py`.

## Open work (priority order)
1. **rewind_history.db staleness** — blocked on live SR game.
2. **Vision regions calibration** — blocked on live game.
3. **DDragon version cache** — `data/meta/ddragon_version.json` shows 16.9.1; actual patch is 26.9. `data_pipeline.py ddragon` won't re-download since it thinks it's current. Low urgency — coaching data is functional.
4. **TFT 17.3** — next patch due ~2026-05-12; repeat this process when it drops.
5. **Bridge Watcher acceptance-criteria** — accumulates naturally.

---

# s116 wrap — 2026-05-08 (Game-PC boot fix + Smite jungler detection)

## What shipped
- **`gamepc_boot.ps1`** (commit 1ef54e3 + 2229d89): now calls `start_gamepc_claude.ps1` at end of boot sequence so Claude window actually appears. `start_gamepc_claude.ps1` updated to open a plain interactive session (no `/loop` — RC-BridgeDaemon handles automated task processing). Scheduled task installs now use absolute python.exe path (fixes `py` ERROR_FILE_NOT_FOUND in task-scheduler context).
- **Smite-based jungler detection** (`game_reader.py`, commit 6bec3ce): `_has_smite(player)` static method checks `summonerSpells` dict. `_gank_threat` now uses 3-tier cascade: zone-based → Smite → `_JUNGLE_CHAMPS` name heuristic. Same order for ally jungler. Any champion playing jungle (including off-meta picks and new releases) now correctly detected without manual list updates. 8 new tests, 237 pass.

## Do NOT redo
- `_JUNGLE_CHAMPS` is intentionally kept as tier-3 fallback for relay warm-up frames where summoner spell data may be absent.
- The `/loop 1m /process-bridge-tasks` removal from `start_gamepc_claude.ps1` was requested by Game-PC Claude via bridge task.

## Open work (priority order)
1. **rewind_history.db staleness** — blocked on live SR game; fresh match data needed for DS calibration correlation.
2. **Vision regions calibration** — blocked on live game.
3. **TFT Set data** — `tft/tft_data.py` seeded for Set 14/patch 15.x; current is 16.9.1. Requires web research for current set champions/traits/items. Scope is significant.
4. **Bridge Watcher acceptance-criteria** — accumulates naturally with real traffic.
5. **Cross-Claude Phase 4** — low urgency.

---

# s115 wrap — 2026-05-07 (DS calibration — game_id wiring)

## What shipped
- **`gamepc_lcu_agent.py`** (commit d66d14b): when `phase=InProgress` or `GameStart`, fetches `/lol-gameflow/v1/session` → `gameData.gameId` and adds top-level `state["game_id"]` to the upload-lcu payload.
- **`game_reader.py`** (commit d66d14b): new `_try_lcu_game_id()` reads `/latest-lcu` relay (20s freshness gate) and injects `"game_id"` into `_process_game()` SR return dict.
- **`coach_integration.py`** (commit d66d14b): `log_ds_run()` call now passes `game_id=str(game_state.get("game_id") or "")`. Future SR calibration records will carry the Riot game_id.
- RC restarted clean (pid=19064). Bridge task dispatched to Game-PC (`task-c80582dc5c45`) to re-pull `gamepc_lcu_agent.py` and restart `RC-LCU` scheduled task.

## Do NOT redo
- LCU lockfile is on Game-PC's local filesystem — `GameReader._ensure_lcu()` always returns False from Legion. The relay path (Game-PC → `:8889/upload-lcu` → `/latest-lcu`) is the correct source.
- The 120 existing calibration records already have `game_id=""` — the fix only helps future records.
- Pre-existing test failure in `tests/snapshot_regressions/test_app_authority.py` (frozen `app/__init__.py` missing `state` attr) — unrelated to this change, 229 other tests pass.

## Open work (priority order)
1. **DS calibration source side** — confirm Game-PC bridge task processed: `gamepc_lcu_agent.py` re-pulled + `RC-LCU` restarted. Verify `game_id` appears in `/latest-lcu` response during next live SR game.
2. **rewind_history.db staleness** — last entry Dec 2025; need a live game to populate fresh rows and unlock correlation analysis.
3. **Vision regions calibration** — needs in-game session.
4. **Bridge Watcher acceptance-criteria** — watch `auto_ok_since_boot` vs `auto_err_since_boot`; target ≥90% read / ≥95% ops before expanding `auto_ops_verbs`.
5. **Cross-Claude Phase 4** — low urgency.

---

# s114 wrap — 2026-05-07 (Bridge Watcher hardening Phase 3 — dry-run + artifact rotation + self-healing)

## What shipped
- **Dry-run mode** (`--dry-run` flag, commit 6dd91ff): classifies all envelopes but never writes to pending queue, spawns auto-actions, or sends push notifications. Heartbeat emits `dry_run=true`. Use `py tools/bridge_watcher.py --node legion --dry-run` to tune classifier patterns against real traffic at zero cost.
- **Artifact rotation** (`_rotate_artifacts()`, commit 6dd91ff): runs once per day (gated by `last_rotate_at` in state); deletes files in `ops/runtime/bridge_action_artifacts/` that are older than 7 days OR whose `task_id` is in `processed_ids`. Defensive per-file error handling.
- **Self-healing watchdog** (daemon thread, commit 6dd91ff): wakes every 30s; calls `os._exit(1)` if main loop has stalled > `max(120s, eff_poll*3)`. Threshold scales with cadence mode so sleep-mode (300s polls) doesn't false-fire. Lets scheduled-task `restart-on-failure` handle recovery rather than a hung-but-alive process.
- **21/21 selftests pass** (8 new: watchdog threshold ×3, rotation predicate ×5).
- Watcher restarted at pid=11656, `cadence_mode=active dry_run=False`.

## Do NOT redo
- `.claude/commands/` is gitignored — slash commands live there locally.
- Cross-node cadence control (`bridge_task.py --target <node>`) is deferred — `bridge_watcher_classify.py` is frozen.
- The three remaining Bridge Watcher hardening items are now ALL shipped (see ROADMAP for the ✅ markers).

## Open work (priority order)
1. **DS calibration** — 120 records, blocked on rewind_history.db (last entry Dec 2025). game_id not captured in `coach_integration.py` (not frozen — fixable).
2. **Vision regions calibration** — needs in-game session.
3. **Bridge Watcher acceptance-criteria** — watch `auto_ok_since_boot` vs `auto_err_since_boot` as real traffic accumulates; target ≥90% read / ≥95% ops before expanding `auto_ops_verbs`.
4. **Cross-Claude Phase 4** — low urgency.

---

# s113 wrap — 2026-05-07 (Bridge Watcher hardening Phase 2 — adaptive cadence)

## What shipped
- **Adaptive polling cadence** (`bridge_watcher.py` + `dashboard/routes_bridge_cadence.py`, commit 05983a4):
  - `_read_mode()` reads `ops/runtime/bridge_watcher_mode.json` once per poll cycle
  - Modes: `active`=15s (default), `sleep`=300s, `auto`=self-managing (15s while tasks arrive, 300s after 15 min without `kind=task`)
  - `last_task_ts` persisted in state; cold-boot defaults to `started_at` so restart always begins active
  - Heartbeat now includes `cadence_mode` + `effective_poll_s`
  - `GET/POST /api/bridge/cadence` endpoint wired into `_dispatch.py`
  - `/sleep` + `/wake` slash commands in `.claude/commands/` (gitignored, local only)
  - 13 selftests pass (`--selftest`)
- Watcher live at pid=14040, `cadence_mode=active effective_poll_s=15.0`

## Do NOT redo
- `.claude/commands/` is gitignored — slash commands live there locally; don't re-create if they already exist.
- Cross-node cadence control (`bridge_task.py --target <node>`) is deferred — `bridge_watcher_classify.py` is frozen.

## Open work (priority order)
1. **Bridge Watcher remaining** — artifact rotation (daily cleanup of `ops/runtime/bridge_action_artifacts/`), dry-run mode, watcher self-healing. All still need bridge_watcher.py (unfrozen).
2. **DS calibration** — 120 records, blocked on rewind_history.db (last entry Dec 2025). game_id not captured in `coach_integration.py` (not frozen — fixable).
3. **Vision regions calibration** — needs in-game session.
4. **Cross-Claude Phase 4** — low urgency.

---

# s112 wrap — 2026-05-07 (Bridge Watcher hardening Phase 1)

## What shipped
- **Sliding 24h event ring** (`tools/bridge_watcher.py`, commit f6095a0) — `event_ring_24h` persisted in `bridge_watcher_state.json`; `_ring_add` / `_ring_age` / `_ring_count` helpers. `*_24h` heartbeat fields now reflect true 24h windows, not aliases for `*_since_boot`. Ring survives watcher restarts.
- **Push notifications** — `_send_push_notification()` spawns headless `claude --print --allowed-tools PushNotification` when a new escalation lands; throttled to 3/hr via `push_notif_times` list in state. Silently no-ops if no active Claude session.
- **9-test inline selftest** (`py tools/bridge_watcher.py --selftest`) — covers ring aging, size cap, and throttle logic. All 9 pass.
- **RC-DaemonSlayer result=1 fix** (`start_daemon_slayer.py`) — pre-bind port check exits 0 when 8893 already bound, clearing the scheduled-task anomaly.
- **`bridge_watcher.py` removed from frozen list** in CLAUDE.md. Remaining hardening items (adaptive polling, artifact rotation, dry-run) still need it unfrozen.
- Watcher restarted at pid=12300, alive, last_poll_ok=True. Heartbeat now shows real `*_24h` fields.

## Do NOT redo
- Sliding ring is in `_STATE_PATH` (bridge_watcher_state.json). Do not add a separate SQLite or file — ring lives alongside processed_ids.
- Push notifications use `claude --print --allowed-tools PushNotification`. Do not use `subprocess.run(["notify-send"])` or Windows Toast — bridge_watcher_actions.py already uses this pattern.

## Open work (priority order)
1. **Bridge Watcher hardening (remaining)** — adaptive idle/active polling cadence + `/sleep` `/wake` slash commands (ROADMAP "Future" §1). Needs bridge_watcher.py (already unfrozen). Ask before starting.
2. **DS calibration** — 120 records in `data/ds_calibration.jsonl` (SR, 3 champs, no game_ids). **Blocked**: rewind_history.db last entry Dec 2025. game_id not captured in `coach_integration.py`. Fix would need `coach_integration.py` edit (not frozen).
3. **Vision regions calibration** — needs in-game session for a calibration frame.
4. **Cross-Claude Phase 4** — confidence scoring, symmetry check, auto-revert. Low urgency.

---

# s111 wrap — 2026-05-06 (Infrastructure fixes + roadmap audit)

## What shipped
- **RC-BridgeWatcher restarted** — was dead since 2026-05-05 14:15 (4 days after boot). All 3 RestartOnFailure retries also failed (root cause: unknown; watcher started fine when manually triggered via `schtasks /Run`). Now at pid=4652, alive, last_poll_ok=True.
- **RC-Phase3-Supervisor restarted** — was down (connection refused on :8890). State=Running after `schtasks /Run`.
- **`tools/claude-rc.ps1`** — removed `/loop 1m /process-bridge-tasks` from Legion terminal helper. Bridge watcher auto-action lanes now handle this; the /loop was redundant and costly.
- **ROADMAP/CLAUDE.md doc cleanup**: fleet health aggregation marked ✅ done; Peer bridge daemon + RC-VisionServer anomalies explained and marked done; DS calibration status updated with DB-staleness note.

## Key findings (no code change needed)
- **Fleet health aggregation** (`routes_health_peer.py` + `bridge_watcher_health_publisher.py`) was already fully deployed and live on both gamepc and peer. The ROADMAP item was done before this session; just not marked.
- **Peer bridge daemon**: confirmed alive via `/api/health/all` peers block (watcher_alive=True, fresh heartbeat). task-d0905eaf7636 was processed/dismissed; pending queue is empty.
- **RC-VisionServer last_result=267014** = `SCHED_S_TASK_TERMINATED` (shutdown-terminated), not a crash. Vision server runs via RC supervisor's in-process popen (vision=True on :8889). Scheduled task is redundant; no fix needed.

## Do NOT redo
- Fleet health aggregation — already done, both peers reporting.
- Peer bridge daemon investigation — confirmed working; task-d0905eaf7636 is gone.

## Open work (priority order)
1. **Bridge Watcher hardening** — sliding 24h counters + push notifications require unfreezing `tools/bridge_watcher.py`. Ask operator before starting. Watcher restart root cause is TBD — suspect a transient RC unavailability caused code-1 exit, then retry window expired before RC recovered.
2. **DS calibration analysis** — 120 records in `data/ds_calibration.jsonl` (SR, 3 champs, no game_ids). **Blocked**: `rewind_history.db` last entry is Dec 2025; can't correlate. Need DB refresh or a live-game game_id to unlatch (game_id not currently captured in `coach_integration.py:905` call to `log_ds_run`).
3. **Vision regions calibration** — needs in-game session for a calibration frame.
4. **Cross-Claude Phase 4** — low urgency.


