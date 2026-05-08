# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s107 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

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

---

# s110 wrap — 2026-05-06 (Cross-Claude sync Phase 3 + DS/roadmap doc cleanup)

## What shipped
- **Cross-Claude Phase 3 — SessionStart lessons summary** (`4c4ce1a`) — `tools/rc_facts.py` gains `_lessons_summary()` which reads `ops/runtime/lessons_received.jsonl` and emits a markdown block in the SessionStart hook when lessons were synced in the last 24h ("from peer: N — M applied, K queued…"). No output when ledger empty.
- **`core/lessons_sender.py` stale comment fixed** — header was "skeleton-only / DOES NOT call bridge.send()" but send_now() has called bridge.send() since implementation.
- **README/ROADMAP/CLAUDE.md doc cleanup** (`b6d02ae`, `4c4ce1a`):
  - DS SR stale ❌ removed (coach_integration.py at root is already wired, core/coach_integration.py never existed)
  - Roadmap reprioritized: Cross-Claude learning sync first → Bridge Watcher hardening second
  - ROADMAP status table coaches row: was "Arena/Brawl needs pre-Haiku move; SR DS not wired" → "all 4 DS-before-Haiku ✅"
  - CLAUDE.md: memory frontmatter section added (cross_project / applies_when / does_not_apply_when docs); active priorities updated
  - README Cross-Claude sync: Phases 1–3 marked ✅; Phase 4 polish remains
- **`continue the roadmap` workflow established** — advisor-guided plan→parallel edits→verify→docs→wrap pattern.

## Do NOT redo
- `_lessons_summary()` correctly emits nothing when `lessons_received.jsonl` is empty — do not add fake/test entries.
- DS SR wire-in is confirmed done (commit b4609b4). Do not reinvestigate `core/coach_integration.py` — that path was never created.
- Phase 2 sender/receiver code (lessons_sender.py, lessons_receiver.py, tools/lessons_*.py) was already complete before this session; do not re-implement.

## Open work (priority order)
1. **Peer bridge daemon** — confirm `~/peer_bridge_daemon_health.json` exists on Peer; `task-d0905eaf7636` still in queue
2. **RC-VisionServer failing** (last_result=267014) — pythonw path in scheduled task XML
3. **Bridge Watcher hardening** — acceptance-criteria (≥90%/≥95%), sliding 24h counters, push notifications, `/api/bridge/pending` dashboard panel
4. **Cross-Claude Phase 4** — confidence scoring, symmetry check, auto-revert on test failure; low urgency
5. **DS calibration** — 50+ games into `data/ds_calibration.jsonl`
6. **Vision regions calibration** — tune `data/vision_regions.json` bboxes

---

# s109 wrap — 2026-05-06 (Memory library — agent patterns + workflow rules)

## What shipped
- **6 new memory entries** saved to `C:\Users\Administrator\.claude\projects\C--Riot-Commander\memory\`:
  1. `feedback_preflight_cron_loop.md` — read WAKEUP_NOTES + session_summaries before any cron/loop scheduling
  2. `feedback_investigate_command.md` — Task agent + 2 conditions + table + "don't propose fixes yet" pattern
  3. `feedback_parallel_dispatch.md` — reads in parallel, edits in one batch; applies to engine+tests+docs
  4. `feedback_parallel_batch_agents.md` — 4–6 worktree subagents + supervisor merge; one version bump after all green
  5. `reference_cost_watchdog_agent.md` — hourly cron cost-regression agent; mcp__anthropic-usage__query_usage → bisect → draft PR; 15% gate; never auto-merge
  6. `reference_tdd_ui_agent.md` — spec-to-green Playwright loop; tests commit first; 10-iteration cap; live smoke run
- **MEMORY.md** indexed all 6.
- No code changes to RC repo this session.

## Do NOT redo
- These memory entries are already indexed. Do not re-save on next session start.

## Open work (priority order — unchanged from s108)
1. **Peer config audit** — `task-d0905eaf7636` from Peer sitting in bridge queue; process next session
2. **RC-VisionServer failing** (last_result=267014) — investigate pythonw path in scheduled task XML
3. **Peer bridge daemon** — confirm `~/peer_bridge_daemon_health.json` exists on Peer
4. **Game-PC bridge auto-flow loop** — dead at /done (last result >8300s ago); re-run `/loop /process-bridge-tasks` on Game-PC at next session start
5. **DS calibration** — accumulate 50+ games in `data/ds_calibration.jsonl`
6. **Vision regions calibration** — tune `data/vision_regions.json` bboxes


