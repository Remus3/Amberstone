---
description: Poll the cross-Claude bridge for tasks targeted at Peer and execute each one. Always runs the fetch - only chat output is suppressed on empty result.
---

> **Peer OPERATOR**: Before installing this as `~/.claude/commands/process-bridge-tasks.md`,
> replace `<ATX_HELPERS_DIR>` below with the directory where your
> `bridge_pull_tasks.py` + `bridge_post_result.py` live. **This may be `core/`
> not `tools/`** - Peer has historically kept these helpers in `core/`. Examples:
> `C:\Peer-VIP\core`, `D:\peer-vip\core`, `<your-repo>\tools`. The placeholder
> intentionally doesn't say `_TOOLS_DIR` to avoid biasing toward Legion's layout.
>
> Also adjust the CLI flags + JSON parsing lines if your local helpers differ
> from Legion's contract:
> - Peer `bridge_pull_tasks.py` may emit bare `{tasks: [...]}` (no `count`/`now`/`target`)
> - Peer `bridge_post_result.py` uses `--target` not `--reply-to` (Legion-specific)
> Check your local script signatures + adjust the `Otherwise` branch below to match.

**Step 1 - ALWAYS RUN THIS FIRST.** Do not skip; it is the ONLY way to know if there is new work:

```
py <ATX_HELPERS_DIR>\bridge_pull_tasks.py --target peer
```

**Step 2 - Parse the JSON output.** Shape is `{now, target, count, tasks: [...]}`. The `count` field is the source of truth.

**Step 3 - Branch on `count`:**

- **`count == 0`**: emit zero chat output and stop. Do not announce "no tasks", do not summarize, do not say "empty" - just stop.

- **`count > 0`**: process EACH task in the array (oldest-first; script already sorts). For each task:
  1. Read `body.prompt` - that is the instruction the peer sent.
  2. **SAFETY GATE** - if the task touches any frozen file from Peer's CLAUDE.md hard-rule list AND `body.allow_frozen_writes != true`, post `--exit-code 2` with a body explaining which file was off-limits. Then move on.
  3. Otherwise execute the prompt fully using your normal tools. Treat it like a user request.
  4. As soon as execution completes (success OR failure), post the result back:
     ```
     py <ATX_HELPERS_DIR>\bridge_post_result.py <task_id> \
         --source peer \
         --reply-to <the task's source field, e.g. legion> \
         --summary "<one-line description of what you did>" \
         --body '<valid JSON the peer can parse with json.loads>' \
         --exit-code <0 if success, non-zero if failed>
     ```
     **`--body` MUST be valid JSON.** Don't pass PowerShell hashtable strings - they fail `json.loads`. Pipe PSObjects through `ConvertTo-Json -Compress` first.

**Step 4 - Channel discipline.** Do NOT print task results to chat. Do NOT wait for user confirmation. The bridge is the canonical channel.

**Failure handling:**
- If a task itself errors (Python crash, exception, missing file): still post a result with `--exit-code 1` + body explaining the failure. Silent failures are worse than visible ones.
- If `bridge_pull_tasks.py` itself fails (peer unreachable, JSON parse error): output ONE short line to chat - that's a real anomaly worth surfacing.

**Common confusion to avoid:**
- "Exit silently on empty" applies to chat output AFTER the fetch confirmed empty - NOT before. You must still run the fetch every time.
- The bridge_watcher daemon polls in the background and writes escalations to `bridge_inbox_pending.json`, but the operator typing `/process-bridge-tasks` wants a fresh fetch + drain RIGHT NOW. Don't shortcut by reading the pending file alone.

**Peer-specific note** (per Peer feedback on BRIDGE_WATCHER_PLAN sec12.5): if the watcher's auto-action lane (Phase 2+) has `claimed_by` set on a pending entry, you should respect it - but for `kind=task` envelopes that arrive directly via `bridge_pull_tasks.py`, the claim concept doesn't apply. Just process them.
