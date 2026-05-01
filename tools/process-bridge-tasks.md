---
description: Pull pending bridge tasks targeted at this machine, execute each one, and post results back via bridge_post_result.py. Never relay results through the user.
---

Run `py C:\RC-Agent\bridge_pull_tasks.py --target gamepc` and parse its JSON output.

If `tasks` is empty, exit silently — no chat output, no tool calls. The /loop will fire again on its next interval.

Otherwise, for **each** task in the array (process oldest-first, the script already sorts):

1. Read `body.prompt` — that's the instruction Legion Claude sent.
2. Execute it fully using your normal tools (Bash, PowerShell, Read, Write, etc.). Treat it like a request from the user, with the same care.
3. The instant execution finishes — success or failure — call:

   ```
   py C:\RC-Agent\bridge_post_result.py <task_id> \
       --source gamepc \
       --summary "<one-line summary of what you did>" \
       --body '<json with the actual data Legion needs>' \
       --exit-code <0 if success, non-zero if failed>
   ```

   **The `--body` argument MUST be valid JSON** — Legion parses it with `json.loads`. Don't pass a PowerShell hashtable string like `{hostname:foo,now:bar}` (no quotes, no escaping). If you built a PSObject in PowerShell, pipe it through `ConvertTo-Json -Compress` before handing to `--body`. Verify with a quick `python -c "import json; json.loads(open('tmp').read())"` if unsure.

   The body should contain whatever Legion explicitly asked for, plus any stdout/stderr or error text that helps diagnose.

4. Do **not** print the result to chat. Do **not** wait for the user to confirm or relay. The bridge is the canonical channel — Legion's UserPromptSubmit hook fetches new bridge messages on every prompt, so once you've posted via `bridge_post_result.py`, Legion sees it.

If the task itself errors out (Python crash, PowerShell exception, missing file, etc.), still post a result with `--exit-code 1` and a body explaining the failure. Silent failures are worse than visible ones.

If `bridge_pull_tasks.py` itself fails (Legion unreachable, JSON parse error), output one short line to chat — that's a real anomaly worth surfacing.
