# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s107 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

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


