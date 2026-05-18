# Bridge Watcher - Multi-Node Plan

> Cross-Claude bridge watcher daemon. Eliminates per-tick UI noise from
> interactive Claude sessions on Legion, Game-PC, and Peer while keeping
> the bridge responsive. Written 2026-05-03 by Legion. Pull via
> `https://legion-rc:8888/agent/BRIDGE_WATCHER_PLAN.md`.

## 1. Problem

Each node currently runs `/loop /process-bridge-tasks` inside its
interactive Claude Code session. Every cron fire renders UI chrome
(`Running scheduled task` header, slash command, shell-call line)
even when the bridge inbox is empty. With 3 nodes polling at 1-min
cadence and bridge typically empty, the operator scrolls past
~150 empty ticks per hour to find real responses. This is the noise
that finally got the loop killed at 2026-05-03 04:58.

Plus: each interactive session burns its prompt cache budget on
empty cron fires, so when the operator finally types a real prompt
they pay the cache-miss tax.

## 2. Goal

- One silent Python daemon per node polls the bridge.
- Auto-actions safe tasks via headless `claude --print`.
- Escalates ambiguous tasks via a single notification, not N cron headers.
- Operator's interactive session sees zero output until something needs them.

## 3. Architecture (per node)

```
                   ┌─────────────────────────────┐
                   │   peer machines (bridge)    │
                   └──────────────┬──────────────┘
                                  │ POST /api/bridge/inbox
                                  ▼
        ┌───────────────────────────────────────────┐
        │  ops/bridge_watcher.py  (daemon)          │
        │  • poll inbox every 15s                   │
        │  • classify each task                     │
        │  • write health heartbeat                 │
        └────┬──────────────────────────────────┬───┘
             │                                  │
   auto-action lane                    escalation lane
             │                                  │
             ▼                                  ▼
   ┌────────────────────┐           ┌──────────────────────────┐
   │  claude --print    │           │  ops/runtime/            │
   │  • restricted      │           │  bridge_inbox_pending.json│
   │    tool allowlist  │           │  + dashboard/            │
   │  • frozen-file gate│           │  /api/bridge/pending     │
   │  • timeout 120s    │           │  + 1 push notif to       │
   └─────────┬──────────┘           │    operator's session    │
             │                      └──────────────────────────┘
             ▼
   ┌────────────────────┐
   │ bridge_post_result │
   └────────────────────┘
```

## 4. Files (canonical on Legion, pulled by Game-PC + Peer via `/agent/`)

```
tools/
  bridge_watcher.py                 # daemon entry point
  bridge_watcher_classify.py        # classification rules (pure functions)
  bridge_watcher_actions.py         # auto-action handlers, one per kind
  bridge_watcher_action_prompt.md   # system prompt for headless claude --print
  bridge_watcher_config.json        # per-node config (allowlists, thresholds)
  bridge_watcher_install.ps1        # idempotent installer for Game-PC/Peer
  BRIDGE_WATCHER_PLAN.md            # this doc

ops/
  bridge_watcher_health.json        # heartbeat (mirrors RC health.json shape)
  runtime/
    bridge_inbox_pending.json       # escalation queue (operator-visible)

dashboard/  (Legion only - Game-PC + Peer don't have RC dashboard)
  routes_bridge_pending.py          # GET /api/bridge/pending, POST dismiss
```

Allowlist additions to `dashboard/routes_static.py:_AGENT_ALLOWED`:
```
"bridge_watcher.py",
"bridge_watcher_classify.py",
"bridge_watcher_actions.py",
"bridge_watcher_action_prompt.md",
"bridge_watcher_config.json",
"bridge_watcher_install.ps1",
"BRIDGE_WATCHER_PLAN.md",
```

## 5. Classification rules

Each inbound bridge envelope is bucketed:

| Class             | Triggers                                                       | Action                                                       |
|-------------------|----------------------------------------------------------------|--------------------------------------------------------------|
| **ack-only**      | `kind=ack`, `kind=note`, `kind=result` w/o `in_reply_to` claim | append to bridge log, do not escalate                        |
| **auto: read**    | prompt matches read-only patterns (see §6)                     | spawn `claude --print` with `Read,Grep,Glob` only            |
| **auto: ops**     | prompt matches whitelisted ops verbs (see §6)                  | spawn `claude --print` with `Read,Grep,Glob,Bash(restricted)`|
| **escalate**      | none of the above                                              | queue to `bridge_inbox_pending.json` + 1 push notif          |
| **reject**        | malformed JSON, missing `task_id`, ttl expired, oversize       | post `--exit-code=2` immediately, drop                       |
| **frozen-block**  | prompt mentions any frozen file from CLAUDE.md without `allow_frozen_writes:true` | post `--exit-code=2` w/ explanation, drop |

Rules live in `bridge_watcher_classify.py` as pure functions returning
a tagged tuple. Easy to unit-test.

## 6. Per-node tool/op allowlist

Defined in `bridge_watcher_config.json` per node:

### Legion (`config.legion`)
```json
{
  "auto_read_patterns": [
    "tail .* log", "show .* state", "what is .*pid",
    "list .*files", "cat .*", "git log", "git status",
    "git diff", "/api/health", "/api/state"
  ],
  "auto_ops_verbs": [
    "restart RC", "regen cert", "pull from origin/main",
    "verify .* health"
  ],
  "bash_restricted": [
    "py *.py", "powershell -c *", "git log*", "git status*",
    "git diff*", "git pull*", "type *", "dir *"
  ],
  "max_turns": 6,
  "timeout_s": 120,
  "daily_token_cap_usd": 5.00
}
```

### Game-PC (`config.gamepc`) - revised after peer review
```json
{
  "auto_read_patterns": [
    "tail .* log", "what .*agent .*pid", "list .*files",
    "cat .*", "show .*MCP server"
  ],
  "auto_ops_verbs": [
    "restart agent .*", "kill agent .*", "ping LCU",
    "ping liveclient relay"
  ],
  "bash_restricted": [
    "py C:\\\\RC-Agent\\\\.*\\.py", "Get-Process *", "taskkill /F /PID *",
    "schtasks /Run /TN *", "wmic process *",
    "type *", "dir *"
  ],
  "frozen_files_extra": [
    "C:\\RC-Agent\\gamepc_screen_agent.py",
    "C:\\RC-Agent\\gamepc_lcu_agent.py",
    "C:\\RC-Agent\\gamepc_liveclient_relay.py",
    "C:\\RC-Agent\\gamepc_mcp_server.py",
    "C:\\RC-Agent\\gamepc_hotkey_listener.py"
  ],
  "max_turns": 4,
  "timeout_s": 60,
  "daily_token_cap_usd": 2.00
}
```
Per Game-PC: agents live at `C:\RC-Agent\`, not `tools/` (which is a
Legion-side source path). `schtasks /Run /TN *` enables agent restart
via scheduled task; `wmic process *` is the reliable PID lookup on
this node (`Get-CimInstance` fails for py processes).

### Peer (`config.peer`) - revised after peer review
```json
{
  "auto_read_patterns": [
    "git log", "git status", "git diff",
    "show .*state", "show envelope", "show .*health",
    "show .*drivers", "show .*jobs",
    "what is .*pid", "list .*files", "list agents", "list managers",
    "cat .*", "cat data/.*", "cat ops/runtime/.*"
  ],
  "auto_ops_verbs": [
    "restart agent .*", "restart manager .*", "force-sync .*",
    "pull from origin/main", "trigger smoke .*"
  ],
  "bash_restricted": [
    "py *.py", "python core/.*", "python -m agents._sidecar .*",
    "python tools/.*", "python scripts/.*",
    "git log*", "git status*", "git diff*", "git pull*"
  ],
  "max_turns": 4,
  "timeout_s": 90,
  "daily_token_cap_usd": 2.00,
  "escalate_always": [
    "restart_trigger.txt"
  ]
}
```
Per Peer: timeout bumped 60→90s (Flask + envelope cold-import tax on
first invocation after idle). `auto_ops_verbs` populated (was empty in
v1) - Peer has natural safe ops via the AgentLifecycle proxy
(`ops/runtime/agent_cmd/<name>.cmd`). **`escalate_always` list is the
single critical rule**: any prompt mentioning `restart_trigger.txt`
ALWAYS escalates - those writes affect Main and must never auto-action.
`no_dashboard_routes` flag dropped - Peer's `dashboards/dev_dashboard.py`
on `:8890` could host `/api/bridge/pending`, but operator works the
Claude REPL on the same host (no second device), so the
UserPromptSubmit one-liner is the real surface; dashboard route is
nice-to-have, deferred.

The pattern → action mapping is intentionally narrow at MVP; expand
once auto-action success rate is measured.

## 7. Auto-action contract

Headless invocation per task:

```bash
claude --print --output-format json \
  --allowed-tools "$tool_list" \
  --append-system-prompt "$(cat tools/bridge_watcher_action_prompt.md)" \
  --max-turns "$max_turns" \
  --timeout "$timeout_s" \
  "$task_prompt"
```

`bridge_watcher_action_prompt.md` (same on all nodes) instructs the
sub-Claude to:

1. NEVER touch frozen files (full list inline).
2. ALWAYS exit with structured JSON:
   ```json
   {"status": "ok|error|escalate", "summary": "<≤80 chars>", "body": {...}}
   ```
3. NEVER ask the operator for input - escalate instead.
4. If a tool isn't in the allowlist, return `escalate` immediately.
5. Soft cap on output: **16 KB body** (revised from 4 KB after Peer
   feedback - Peer envelopes alone are 12-19 KB; 4 KB would force every
   diagnostic to truncate). Outputs >16 KB write to
   `ops/runtime/bridge_action_artifacts/<task_id>.json` and the bridge
   body carries `{"body_path": "<path>", "truncated": true,
   "preview": "<first 1KB>"}`.
6. **Edit tool stays OUT of the allowlist for MVP and Phase 2** (per Peer
   ask). Any prompt wanting to write a file → escalate. Prevents an
   entire class of accidental-write tickets.
7. **Frozen-file gate uses intent-verb gating, not path-mention regex**
   (per Peer ask, ships BEFORE Phase 2 Bash auto-action). The gate
   triggers when prompt contains a write verb (`Edit`, `Write`,
   `replace`, `modify`, `patch`, `delete`, `rm`, `Remove-Item`) within
   80 chars of any frozen-file path. Mere path mentions
   ("explain main.py last error") do NOT trip the gate.

Watcher captures stdout, parses JSON, dispatches:
- `status: ok` → `bridge_post_result.py --exit-code 0 --body '<body>'`
- `status: error` → `bridge_post_result.py --exit-code 1 --body '<body>'`
- `status: escalate` → demote to escalation lane (don't post result yet)
- malformed output → log error, escalate

## 8. Escalation contract

The pending-queue file lives at `<data_dir>/bridge_inbox_pending.json`,
where `<data_dir>` is the watcher's `--data-dir` argument:

| Node     | data_dir resolved to                              |
|----------|---------------------------------------------------|
| Legion   | `C:\Riot Commander\ops\runtime\` (script default) |
| Game-PC  | `C:\RC-Agent\` (installer passes `--data-dir`)    |
| Peer      | `C:\Peer-VIP\tools\` (installer passes `--data-dir`)|

Per-node convention: Legion uses its conventional `ops/runtime/` because
the project root has dedicated runtime-state plumbing. Game-PC + Peer use
flat layout (data files alongside `bridge_watcher.py`) because their
deploy dirs are flat single-purpose folders. Both are supported; the
operator surface (`/api/bridge/pending` on Legion; UserPromptSubmit hook
on Game-PC + Peer) reads from `<data_dir>/bridge_inbox_pending.json`
either way. **Schema is identical across nodes.**

Schema:

```json
{
  "schema_version": 1,
  "updated_at": "<iso8601>",
  "tasks": [
    {
      "task_id": "task-...",
      "received_at": <epoch>,
      "from": "legion|gamepc|peer",
      "kind": "task|note|ask|result",
      "summary": "<one-line>",
      "prompt": "<full prompt body>",
      "classification": "escalate",
      "reason": "<why escalated, e.g. 'kind=task; not in auto-action allowlist'>",
      "ttl_at": <epoch + 86400>,
      "claimed_by": null,
      "claimed_at": null
    }
  ]
}
```

Atomic-write via the same `core.atomic_write_json` helper RC uses
(retry-with-backoff for WinError 5 - see
`reference_os_replace_winerror5` memory).

**Claim lock** (per Peer ask, §12.5 resolution): when either the watcher's
auto-action lane OR the operator's `/process-bridge-tasks` invocation
starts working a pending entry, it sets `claimed_by` (`"watcher"` or
`"operator"`) + `claimed_at` (epoch). Other side checks claim first and
no-ops if claimed within last 60s. Claims auto-expire so a crashed
worker doesn't permanently block the entry. Mirrors Peer's existing
`data/bridge_messages_processed.jsonl` ledger pattern.

### Operator surface

**Legion**: dashboard panel "Pending Bridge Tasks" reading
`/api/bridge/pending`. Each task has Accept (run via /process-bridge-tasks),
Defer (snooze 1h), Dismiss (drop, don't post result).

**Game-PC + Peer (no dashboard)**: UserPromptSubmit hook reads the
pending file at the start of each prompt and prepends a system-reminder:
```
[bridge] N tasks pending review (oldest: <summary>). Run /process-bridge-tasks to drain.
```
One line, regardless of N. Operator types `/process-bridge-tasks` when
they want to engage; nothing else fires automatically.

### Push notification (Phase 2+)

Watcher invokes `claude` CLI's PushNotification machinery once per
new escalation (not per poll cycle). Throttle: max 3 push notifs per
hour per node. Notifications include task summary + `from`.

## 9. Health & supervision

`ops/bridge_watcher_health.json`:
```json
{
  "app": "bridge-watcher",
  "node": "legion",
  "pid": <int>,
  "started_at": "<iso8601>",
  "updated_at": "<iso8601>",
  "alive": true,
  "last_poll_ok": true,
  "last_poll_at": "<iso8601>",
  "queue_depth": <int>,
  "auto_actions_24h": <int>,
  "escalations_24h": <int>,
  "errors_24h": <int>,
  "tokens_used_today_usd": <float>
}
```

RC's `/api/health/all` (Legion) gains a `bridge_watcher` block reading
this file. Game-PC + Peer expose health via existing inbound bridge
heartbeats (`bridge_heartbeat.py` already exists - extend it to include
watcher state).

Scheduled task (Legion) - mirrors `RC-Supervisor` shape:
- Name: `RC-BridgeWatcher`
- Trigger: at logon, Administrator, HIGHEST priority
- Action: `pythonw.exe ops/bridge_watcher.py`
- Restart on failure: 3 attempts, 1 minute apart

Game-PC + Peer equivalent installed by `bridge_watcher_install.ps1`.

PID lock at `ops/runtime/bridge_watcher.pid` to prevent dupes (same
pattern as RC supervisor).

## 10. Deployment workflow

### Legion (canonical)
```
git pull origin main          # bring in the new files
schtasks /Create /TN RC-BridgeWatcher /XML ops/RC-BridgeWatcher.xml /F
echo restart > restart_trigger.txt   # not needed; watcher is independent
```

### Game-PC
```powershell
iex (iwr https://legion-rc:8888/agent/bridge_watcher_install.ps1).Content
```
Installer (idempotent):
1. Pulls all `bridge_watcher_*.{py,md,json,ps1}` into `tools/`
2. Pulls `BRIDGE_WATCHER_PLAN.md` for reference
3. Selects `bridge_watcher_config.gamepc` from the JSON
4. Installs scheduled task `RC-BridgeWatcher-GamePC`
5. Verifies first poll succeeds + heartbeat written
6. Cancels any existing `/loop /process-bridge-tasks` cron in the
   interactive Claude session (operator runs `/loop list` then
   `/loop delete <id>` - installer prints the instruction; can't
   reach into the Claude session itself)

### Peer
Same one-liner with `--target peer` config selection.

## 11. Rollout phases

### MVP - Phase 0 (1-2 days work, ships first)
- `bridge_watcher.py` daemon (poll + classify + escalate, NO auto-action)
- `bridge_inbox_pending.json` + `/api/bridge/pending` route on Legion
- Scheduled task on Legion only
- Operator continues to drain via manual `/process-bridge-tasks`
- All 3 nodes cancel their `/loop /process-bridge-tasks` crons
- **Acceptance criterion**: zero "Running scheduled task" headers per
  hour in operator's interactive session; 100% of inbound tasks land
  in pending queue within 30s of arrival.

### Phase 1 - Game-PC + Peer rollout
- `bridge_watcher_install.ps1` shipped via `/agent/`
- Game-PC + Peer install + run
- UserPromptSubmit one-line hook on those nodes (no dashboard)
- **Acceptance criterion**: all 3 nodes silent on empty bridge.

### Phase 2 - Auto-action: read-only
- `bridge_watcher_actions.py` + classification expanded
- Headless `claude --print` for read patterns
- Token cap enforcement (per-node USD/day from config)
- **Acceptance criterion**: 90%+ success rate on read-only tasks; if
  lower, downgrade specific patterns back to escalate.

### Phase 3 - Auto-action: standard ops
- Restart RC, regen cert, agent restart, etc.
- Bash gated by per-task allowlist regex
- **Acceptance criterion**: 95%+ success rate AND zero frozen-file
  modifications AND zero unrequested side effects (e.g. accidental
  git pushes).

### Phase 4 (maybe never) - fan-out push notifs
- If operator runs multiple Claude sessions across nodes, decide
  routing: canonical session only? all sessions? user-pinned session?
- Likely YAGNI - start with canonical-session-only.

## 12. Open questions

1. **`claude --print` cost vs benefit**: each auto-action call costs
   tokens. With current bridge volume (~10 tasks/day across all nodes),
   per-day cost is bounded. But if patterns expand or volume grows,
   could blow the daily cap quickly. Need monitoring + alerting from
   day 1.

2. **Bridge unreachable vs empty**: `bridge_pull_tasks.py` returns
   `count: 0` for both. Watcher needs a separate ping
   (`bridge_ping.py` exists - use it) to distinguish. If unreachable,
   stop posting "alive" heartbeats; let RC health surface degraded
   state.

3. **Notification delivery**: PushNotification works for the operator's
   interactive Claude session, but only if that session is currently
   running. What about overnight when the operator's away? Maybe just
   queue + count; let them see N pending when they come back.

4. **Frozen-file regex**: today the safety gate is "does the prompt
   mention any frozen-file path string". This is naïve - a prompt
   asking "explain main.py" is read-only but trips the gate. Maybe
   gate on intent verbs (Edit/Write/replace) near the path, not on
   path mentions alone. Defer to Phase 2 design.

5. **Conflict with operator's manual `/process-bridge-tasks`**: if
   watcher escalates a task at 09:00 and operator runs the slash
   command at 09:01, both could try to drain. Need a lock or
   "claimed_by" field on the pending entry.

6. **Peer dashboard dependency**: Peer has its own dashboard? If so,
   `/api/bridge/pending` could ship there too. If not, the
   UserPromptSubmit hook is the only surface.

## 13. Anti-goals

- Watcher does NOT replace `/process-bridge-tasks`. The skill stays as
  the manual drain path.
- Watcher does NOT modify frozen files even via auto-action. Hard gate.
- Watcher does NOT loop on its own decisions. Each task: one classify,
  one action, one result. No retry logic in MVP.
- Watcher does NOT touch `restart_trigger.txt` directly - restart
  tasks call into the same trigger RC already owns.
- Watcher does NOT decide what to escalate based on operator presence.
  If operator's away, escalations queue; they don't auto-promote to
  auto-action because nobody's watching.

## 14. Success criteria (90 days post-MVP)

- Zero per-tick UI noise in operator's interactive session.
- ≥80% of bridge tasks handled without operator attention (auto-action
  or ack-only).
- Zero unintended side effects (no surprise git pushes, no surprise
  RC restarts, no frozen-file mods).
- Daily token cost across all nodes ≤ $10.
- Watcher uptime ≥ 99% per node (excluding planned restarts).

## 15. Review notes for Game-PC + Peer

This doc is canonical on Legion; pull via `/agent/`. If you have
node-specific concerns, post a `kind=note` to the bridge with
`in_reply_to: "BRIDGE_WATCHER_PLAN.md"` and Legion will fold them in.
Especially want feedback on:

- §6 per-node config: are the verbs/patterns right for your node's
  typical bridge traffic?
- §7 auto-action contract: any tools your node needs in the allowlist
  that aren't there?
- §11 rollout: are you OK shipping MVP on Legion first, or do you want
  parallel rollout?
