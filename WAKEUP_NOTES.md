# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s107 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

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

---

# s108 wrap — 2026-05-06 (WT flash fixes — Legion + Game-PC)

## What shipped
- **`dashboard/server.py`** — added `creationflags=0x08000000` to vision server auto-start `Popen` (commit `cab0ce4`). Companion to `fb1b984` (DS auto-start fix from s107).
- **`C:\RC-Agent\gamepc_bridge_daemon.py`** (Game-PC only, not in Legion git) — two fixes:
  1. `--dangerouslySkipPermissions` (camelCase, not a real flag) → `--dangerously-skip-permissions`. This had caused 807+ crash-loop invocations today, each spawning a visible WT window every ~10s.
  2. Added `creationflags=0x08000000` + `stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL` to `subprocess.run` claude invocation.
- Game-PC daemon queue cleared; daemon idle at boot (0 invocations).

## Do NOT redo
- Legion `dashboard/server.py` flash fix: committed `cab0ce4`, pushed.
- Game-PC daemon fix: already live at `C:\RC-Agent\gamepc_bridge_daemon.py` on Game-PC.
- Do NOT revert `--dangerously-skip-permissions` — camelCase is wrong for claude 2.1.129+.

## Open work (priority order)
1. **Peer config audit** — `task-d0905eaf7636` from Peer sitting in bridge queue; process next session
2. **RC-VisionServer failing** (last_result=267014) — investigate pythonw path in scheduled task XML
3. **Peer bridge daemon** — confirm `~/peer_bridge_daemon_health.json` exists on Peer
4. **DS calibration** — accumulate 50+ games in `data/ds_calibration.jsonl`
5. **Vision regions calibration** — tune `data/vision_regions.json` bboxes

