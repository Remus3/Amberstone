---
description: Poll the cross-Claude bridge for tasks targeted at this peer node and execute each one. Always runs the fetch - only chat output is suppressed on empty result.
---

**Step 1 - ALWAYS RUN THIS FIRST.** Do not skip; it is the ONLY way to know if there is new work:

```
py C:\RC-Agent\bridge_pull_tasks.py --target peer
```

**Step 2 - Parse the JSON output.** Shape is `{now, target, count, tasks: [...]}`. The `count` field is the source of truth.

**Step 3 - Branch on `count`:**

- **`count == 0`**: emit zero chat output and stop. Do not announce "no tasks", do not summarize, do not say "empty" - just stop.

- **`count > 0`**: process EACH task in the array (oldest-first; script already sorts). For each task:
  1. Read `body.prompt` - that is the instruction Legion sent.
  2. Execute it fully using your normal tools (Bash, PowerShell, Read, Write, etc.). Treat it like a user request - same care, same scrutiny.
  3. As soon as execution completes (success OR failure), post the result back:
     ```
     py C:\RC-Agent\bridge_post_result.py <task_id> \
         --source peer \
         --reply-to <the task's source field, e.g. legion> \
         --summary "<one-line description of what you did>" \
         --body '<valid JSON Legion can parse with json.loads>' \
         --exit-code <0 if success, non-zero if failed>
     ```
     **`--body` MUST be valid JSON.** Don't pass PowerShell hashtable strings (`{hostname:foo}`) - they fail `json.loads`. If you built a PSObject, pipe through `ConvertTo-Json -Compress` first.
     **On error/escalate (`--exit-code != 0`)**: also pass `--suggestions '<actionable next-step>'` (repeat for multiple) so the recipient Claude gets concrete next-steps inline. Example: `--suggestions 'install rtk via curl ... | sh' --suggestions 'verify Bash/WSL available'`. Backward compatible - omit on success.

**Step 4 - Channel discipline.** Do NOT print task results to chat. Do NOT wait for user confirmation. The bridge is the canonical channel - Legion's UserPromptSubmit hook fetches new bridge messages on every prompt, so once you've posted via `bridge_post_result.py`, Legion sees it.

**Failure handling:**
- If a task itself errors (Python crash, PowerShell exception, missing file): still post a result with `--exit-code 1` + body explaining the failure. Silent failures are worse than visible ones.
- If `bridge_pull_tasks.py` itself fails (Legion unreachable, JSON parse error): output ONE short line to chat - that's a real anomaly worth surfacing, not a silent task.

**Common confusion to avoid:**
- "Exit silently on empty" applies to chat output AFTER the fetch confirmed empty - NOT before. You must still run the fetch every time.
- The /loop firing in the background does NOT replace this skill's manual invocation. When the operator types `/process-bridge-tasks`, they want a fetch RIGHT NOW.
