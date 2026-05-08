# Riot Commander — Cross-Claude Bridge

_Living document. Covers RC↔Peer bridge wire format + Bridge Watcher daemon architecture._

---

## Overview

Three Claude Code sessions coordinate via a shared HTTPS bridge:
- **Legion** (`legion-rc`) — RC runtime + primary bridge host
- **Game-PC** (`gamepc-rc`) — Game agent; sends notes/results to Legion
- **Peer** (`peer-host`) — Separate Claude Code project; bidirectional lessons/tasks

Bridge is **opt-in**. Both sides must share a secret in `ops/local_paths.json` (gitignored). Nothing happens if unconfigured.

---

## Wire format

POST body to `/api/bridge/inbox` (both directions):

```json
{
  "source":      "rc-claude",
  "summary":     "shipped tier-3 #14",
  "kind":        "note",
  "id":          "rc-msg-2026-05-02-001",
  "target":      "peer",
  "body":        { "...": "..." },
  "in_reply_to": "peer-msg-2026-05-02-009"
}
```

| Field | Required | Notes |
|---|---|---|
| `source` | yes | Who sent it (≤40 chars) |
| `summary` | yes | Human-readable line (≤2000 chars) |
| `kind` | no | `note` \| `result` \| `ask` \| `task` \| `ack` (≤20 chars) |
| `id` | no | Caller-assigned ID (≤80 chars) |
| `target` | no | Addressed recipient — `rc` \| `gamepc` \| `peer` |
| `body` | no | Structured payload |
| `in_reply_to` | no | Prior message ID |

Response: `{"ok": true, "entry": {...}}` or `{"ok": false, "error": "<reason>"}`.

---

## Endpoints (Legion `:8888`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/bridge/inbox` | Bearer token | Receive from peer |
| `GET` | `/api/bridge` | none (local) | Read messages: `?source=&kind=&hours=N&limit=N` |
| `GET` | `/api/bridge/messages` | none (local) | Alias (Peer-compatible path) |
| `GET` | `/api/bridge/pending` | none | Escalation queue (operator triage) |
| `POST` | `/api/bridge/pending/<id>/{accept,defer,dismiss}` | none | Triage an escalation |
| `GET` | `/api/bridge/cadence` | none | Watcher poll mode |
| `POST` | `/api/bridge/cadence` | none | Toggle active/sleep |
| `GET` | `/api/health/all` | none | Fleet health including peer watcher state |

**Path-name asymmetry:** RC reads at `/api/bridge`; Peer reads at `/api/bridge/messages`.

---

## Bridge Watcher daemon

Each node runs a silent Python daemon (`tools/bridge_watcher.py`) that replaces the old `/loop /process-bridge-tasks` terminal pattern.

```
peer machines → POST /api/bridge/inbox
                         ↓
            bridge_watcher.py (daemon)
            • poll every 15s (active) / 300s (sleep)
            • classify each task
            • write heartbeat to bridge_watcher_health.json
                   ↙                      ↘
         auto-action lane           escalation lane
                ↓                          ↓
     claude --print (headless)    bridge_inbox_pending.json
     • restricted tool allowlist   + /api/bridge/pending
     • frozen-file gate            + push notification
     • 120s timeout
                ↓
     bridge_post_result.py
```

**Auto-action lanes** (Legion, opt-in via `--enable-auto-action-lanes read`):
- `read` — safe read-only ops (file reads, curl health checks)
- `ops` — restricted write ops (restart trigger, cert regen, git pull)

`Edit`, `Write`, `NotebookEdit` are always blocked from the auto-action runner.

**Node load restraint:** auto-lanes suppress when RC is dead / booting / stale heartbeat / grace restart. Counters: `auto_ok_since_boot`, `auto_err_since_boot`, `auto_suppressed_since_boot`.

---

## Scheduled tasks (per node)

| Node | Task | What it does |
|---|---|---|
| Legion | `RC-BridgeWatcher` | Silent bridge poll daemon |
| Game-PC | `RC-BridgeDaemon` | `gamepc_bridge_daemon.py` — polls Legion, invokes `claude --print` only when inbox > 0 |
| Game-PC | `RC-BridgeWatcher-GamePC` | Watcher health publisher |
| Game-PC | `RC-WatcherHealthPublisher-GamePC` | Pushes peer health to Legion |

---

## Sending to Peer (from Legion Claude session)

```python
from core.bridge import send
ok, detail = send(source="rc", summary="...", kind="note", target="peer")
```

Do **not** POST directly to `/api/bridge` — that only stores locally. Use `core.bridge.send()` which POSTs to Peer's `/api/bridge/inbox` with bearer auth.

---

## Lessons sync (Phase 1–3 shipped 2026-05-06)

- `tools/lessons_send.py` — operator-driven send; wraps `core/lessons_sender.py`
- `core/lessons_receiver.py` — triage on receive
- `.claude/commands/process-incoming-lessons.md` — `/process-incoming-lessons` skill
- Phase 4 (confidence scoring, symmetry check, auto-revert) deferred

---

## Config files

| File | Location | What it stores |
|---|---|---|
| `ops/local_paths.json` | Legion only (gitignored) | `bridge_shared_secret`, `bridge_remote_url` |
| `tools/bridge_watcher_config.json` | Each node | Per-node allowlists, thresholds, auto-action verbs |

Full architecture plan: `tools/BRIDGE_WATCHER_PLAN.md` (served via `https://legion-rc:8888/agent/BRIDGE_WATCHER_PLAN.md`).
Bridge wire format v0: `docs io RC peer/RC_BRIDGE_CONTRACT.md`.
