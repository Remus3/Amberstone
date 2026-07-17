# Riot Commander - Phase 3 Agent Framework

Deep reference for the agent roster and supervisor stack. For operating rules see `CLAUDE.md`; for DS engine see `DAEMON_SLAYER.md`.

## Two-supervisor architecture

| Supervisor | File | Port(s) | Role |
|---|---|---|---|
| **RC Supervisor** | `ops/rc_supervisor.py` | - | Owns `main.py` process lifecycle; PID lock; restart trigger |
| **Phase 3 Supervisor** | `agents/supervisor.py` | `:8890` HTTP + `:8891` WS | Orchestrates Agent 0-7; proxied at `/api/analyze` |

Both coexist on Legion. Neither kills the other.

## Agent roster

| Agent | Name | Module | Role |
|---|---|---|---|
| **0** | Gatekeeper | `agent0_gatekeeper/evaluator.py` | Task policy gate, 6 criteria (built for the cross-machine era; still the queue gate on 1-PC, ADR-011). Rejection: reasons 1,2,3,6 -> dead_letter; 4,5 -> auto_retry_once. Not a user security boundary. |
| **1** | Lead Scheduler | `agent1_lead/scheduler.py` | Single writer of `agents/state/task_queue.jsonl`. Priority queue with JSONL persistence. Gate policy: hard gates (kinds 1,7,8) -> `needs_explicit_approval`; Agent 0 review for kind 5; ungated (2,3,4,6) -> `ready`. |
| **2** | Backend Ingest | `agent2_backend/game_ingest.py` | `game-summary` tasks -> mode DB rows. WebSocket server. Win/loss detection. (SMB push retired, ADR-011/012 - `smb_push.py` is a guarded stub.) |
| **3** | Testing | `agent3_testing/suite/` | Pytest suite covering all agents + core modules. |
| **4** | Coach Mentor | `agent4_coach_mentor/analyzer.py` | Replays matches -> per-champion `adaptation_buckets` + `matchup_modifiers`. Activates modifiers at `MATCHUP_ACTIVATE_THRESHOLD` samples. |
| **5** | UI Agent | `agent5_ui/champion_fallback.py` | Champion fallback when Live Client API is down. Three-signal: (1) LCU champ-select, (2) last match_history.db row, (3) last user-input task. Served at `/api/locked-champion`. |
| **6** | Auditor | `agent6_auditor/_audit_probes.py` | Security audit probes - path traversal, subdir substring, dotfiles. `source_quality.json` ratings. |
| **7** | Context / NL Parser | `agent7_context/input_parser.py` | User strings -> tasks via Agent 1 scheduler. Two-stage: rule-based fast path (~80%), Haiku LLM fallback. Never dispatches agents directly - only files tasks. Warm session during play windows. |

## `agents/state/` runtime files

| File | Contents |
|---|---|
| `lockfile` | PID lock - Phase 3 supervisor heartbeats every 5s; duplicate launches abort |
| `task_queue.jsonl` | Append-only log of every task status transition (grows unbounded); Agent 1 replays on startup |
| `resolved_decisions.json` | Locked topology decisions (phase3-1.1, Apr 22) |

## Architecture map

```
agents/
  supervisor.py           Phase 3 orchestrator - :8890 HTTP + :8891 WS
  agent0_gatekeeper/      Task policy gate
  agent1_lead/            Task queue (scheduler.py) - JSONL writer, priority queue
  agent2_backend/         Live-match DB ingest, file ingest, WS server
  agent3_testing/         Pytest suite
  agent4_coach_mentor/    Per-champion analyzer: adaptation_buckets, matchup_modifiers
  agent5_ui/              Champion fallback (/api/locked-champion)
  agent6_auditor/         Security audit probes
  agent7_context/         NL input parser -> Agent 1
  state/                  task_queue.jsonl, lockfile, resolved_decisions.json
```
